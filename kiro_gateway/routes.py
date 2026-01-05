# -*- coding: utf-8 -*-

# Kiro OpenAI Gateway
# https://github.com/jwadow/kiro-openai-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
FastAPI routes for Kiro Gateway.

Contains all API endpoints:
- / and /health: Health check
- /v1/models: Models list
- /v1/chat/completions: Chat completions
"""

import json
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from loguru import logger

from kiro_gateway.config import (
    AVAILABLE_MODELS,
    APP_VERSION,
)
from kiro_gateway.api_keys import validate_api_key
from kiro_gateway.models import (
    OpenAIModel,
    ModelList,
    ChatCompletionRequest,
    OAuthStartRequest,
    OAuthStartResponse,
    OAuthStatusResponse,
)
from kiro_gateway.auth import KiroAuthManager, AuthType
from kiro_gateway.cache import ModelInfoCache
from kiro_gateway.converters import build_kiro_payload
from kiro_gateway.streaming import stream_kiro_to_openai, collect_stream_response, stream_with_first_token_retry
from kiro_gateway.http_client import KiroHttpClient
from kiro_gateway.utils import get_kiro_headers, generate_conversation_id

# Import debug_logger
try:
    from kiro_gateway.debug_logger import debug_logger
except ImportError:
    debug_logger = None


# --- Security scheme ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_api_key(auth_header: str = Security(api_key_header)) -> bool:
    """
    Verify API key in Authorization header.
    
    Expects format: "Bearer {API_KEY}"
    Supports multiple API keys managed via WebUI.
    
    Args:
        auth_header: Authorization header value
    
    Returns:
        True if key is valid
    
    Raises:
        HTTPException: 401 if key is invalid or missing
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("Access attempt with missing or malformed API key.")
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    
    key = auth_header[7:]  # Remove "Bearer " prefix
    if not validate_api_key(key):
        logger.warning("Access attempt with invalid API key.")
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    
    return True


# --- Router ---
router = APIRouter()


@router.get("/")
async def root():
    """
    Health check endpoint.
    
    Returns:
        Status and application version
    """
    return {
        "status": "ok",
        "message": "Kiro API Gateway is running",
        "version": APP_VERSION
    }


@router.get("/health")
async def health():
    """
    Detailed health check.
    
    Returns:
        Status, timestamp and version
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": APP_VERSION
    }


@router.get("/v1/models", response_model=ModelList, dependencies=[Depends(verify_api_key)])
async def get_models(request: Request):
    """
    Return list of available models.
    
    Uses static model list with ability to update from API.
    Caches results to reduce API load.
    
    Args:
        request: FastAPI Request for accessing app.state
    
    Returns:
        ModelList with available models
    """
    logger.info("Request to /v1/models")
    
    auth_manager: KiroAuthManager = request.app.state.auth_manager
    model_cache: ModelInfoCache = request.app.state.model_cache
    
    # Try to get models from API if cache is empty or stale
    if model_cache.is_empty() or model_cache.is_stale():
        try:
            token = await auth_manager.get_access_token()
            headers = get_kiro_headers(auth_manager, token)
            
            # Build params - profileArn is only needed for Kiro Desktop auth
            # AWS SSO OIDC (Builder ID) users don't need profileArn and it causes 403 if sent
            params = {"origin": "AI_EDITOR"}
            if auth_manager.auth_type == AuthType.KIRO_DESKTOP and auth_manager.profile_arn:
                params["profileArn"] = auth_manager.profile_arn
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{auth_manager.q_host}/ListAvailableModels",
                    headers=headers,
                    params=params
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models_list = data.get("models", [])
                    await model_cache.update(models_list)
                    logger.info(f"Received {len(models_list)} models from API")
        except Exception as e:
            logger.warning(f"Failed to fetch models from API: {e}")
    
    # Return static model list
    openai_models = [
        OpenAIModel(
            id=model_id,
            owned_by="anthropic",
            description="Claude model via Kiro API"
        )
        for model_id in AVAILABLE_MODELS
    ]
    
    return ModelList(data=openai_models)


@router.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request, request_data: ChatCompletionRequest):
    """
    Chat completions endpoint - compatible with OpenAI API.
    
    Accepts requests in OpenAI format and translates them to Kiro API.
    Supports streaming and non-streaming modes.
    
    Args:
        request: FastAPI Request for accessing app.state
        request_data: Request in OpenAI ChatCompletionRequest format
    
    Returns:
        StreamingResponse for streaming mode
        JSONResponse for non-streaming mode
    
    Raises:
        HTTPException: On validation or API errors
    """
    logger.info(f"Request to /v1/chat/completions (model={request_data.model}, stream={request_data.stream})")
    
    # Try to get auth_manager from AccountManager (multi-account mode)
    # Fall back to single auth_manager if AccountManager not available
    account_manager = getattr(request.app.state, 'account_manager', None)
    if account_manager and account_manager.account_count > 0:
        auth_manager = await account_manager.get_next_account()
        if not auth_manager:
            logger.warning("No healthy accounts available, falling back to default auth_manager")
            auth_manager = request.app.state.auth_manager
    else:
        auth_manager: KiroAuthManager = request.app.state.auth_manager
    
    model_cache: ModelInfoCache = request.app.state.model_cache
    
    # Prepare debug logs
    if debug_logger:
        debug_logger.prepare_new_request()
    
    # Log incoming request
    try:
        request_body = json.dumps(request_data.model_dump(), ensure_ascii=False, indent=2).encode('utf-8')
        if debug_logger:
            debug_logger.log_request_body(request_body)
    except Exception as e:
        logger.warning(f"Failed to log request body: {e}")
    
    # Lazy model cache population
    if model_cache.is_empty():
        logger.debug("Model cache is empty, skipping forced population")
    
    # Generate conversation ID
    conversation_id = generate_conversation_id()
    
    # Build payload for Kiro
    # profileArn is only needed for Kiro Desktop auth
    # AWS SSO OIDC (Builder ID) users don't need profileArn and it causes 403 if sent
    profile_arn_for_payload = ""
    if auth_manager.auth_type == AuthType.KIRO_DESKTOP and auth_manager.profile_arn:
        profile_arn_for_payload = auth_manager.profile_arn
    
    try:
        kiro_payload = build_kiro_payload(
            request_data,
            conversation_id,
            profile_arn_for_payload
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Log Kiro payload
    try:
        kiro_request_body = json.dumps(kiro_payload, ensure_ascii=False, indent=2).encode('utf-8')
        if debug_logger:
            debug_logger.log_kiro_request_body(kiro_request_body)
    except Exception as e:
        logger.warning(f"Failed to log Kiro request: {e}")
    
    # Create HTTP client with retry logic
    http_client = KiroHttpClient(auth_manager)
    url = f"{auth_manager.api_host}/generateAssistantResponse"
    try:
        # Make request to Kiro API (for both streaming and non-streaming modes)
        # Important: we wait for Kiro response BEFORE returning StreamingResponse,
        # so that 200 OK means Kiro accepted the request and started responding
        response = await http_client.request_with_retry(
            "POST",
            url,
            kiro_payload,
            stream=True
        )
        
        if response.status_code != 200:
            try:
                error_content = await response.aread()
            except Exception:
                error_content = b"Unknown error"
            
            await http_client.close()
            error_text = error_content.decode('utf-8', errors='replace')
            logger.error(f"Error from Kiro API: {response.status_code} - {error_text}")
            
            # Try to parse JSON response from Kiro to extract error message
            error_message = error_text
            try:
                error_json = json.loads(error_text)
                if "message" in error_json:
                    error_message = error_json["message"]
                    if "reason" in error_json:
                        error_message = f"{error_message} (reason: {error_json['reason']})"
            except (json.JSONDecodeError, KeyError):
                pass
            
            # Log access log for error (before flush, so it gets into app_logs)
            logger.warning(
                f"HTTP {response.status_code} - POST /v1/chat/completions - {error_message[:100]}"
            )
            
            # Flush debug logs on error ("errors" mode)
            if debug_logger:
                debug_logger.flush_on_error(response.status_code, error_message)
            
            # Return error in OpenAI API format
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "error": {
                        "message": error_message,
                        "type": "kiro_api_error",
                        "code": response.status_code
                    }
                }
            )
        
        # Prepare data for fallback token counting
        # Convert Pydantic models to dicts for tokenizer
        messages_for_tokenizer = [msg.model_dump() for msg in request_data.messages]
        tools_for_tokenizer = [tool.model_dump() for tool in request_data.tools] if request_data.tools else None
        
        if request_data.stream:
            # Streaming mode
            async def stream_wrapper():
                streaming_error = None
                client_disconnected = False
                try:
                    async for chunk in stream_kiro_to_openai(
                        http_client.client,
                        response,
                        request_data.model,
                        model_cache,
                        auth_manager,
                        request_messages=messages_for_tokenizer,
                        request_tools=tools_for_tokenizer
                    ):
                        yield chunk
                except GeneratorExit:
                    # Client disconnected - this is normal
                    client_disconnected = True
                    logger.debug("Client disconnected during streaming (GeneratorExit in routes)")
                except Exception as e:
                    streaming_error = e
                    # Try to send [DONE] to client before finishing
                    # so client doesn't "hang" waiting for data
                    try:
                        yield "data: [DONE]\n\n"
                    except Exception:
                        pass  # Client already disconnected
                    raise
                finally:
                    await http_client.close()
                    # Log access log for streaming (success or error)
                    if streaming_error:
                        error_type = type(streaming_error).__name__
                        error_msg = str(streaming_error) if str(streaming_error) else "(empty message)"
                        logger.error(f"HTTP 500 - POST /v1/chat/completions (streaming) - [{error_type}] {error_msg[:100]}")
                    elif client_disconnected:
                        logger.info(f"HTTP 200 - POST /v1/chat/completions (streaming) - client disconnected")
                    else:
                        logger.info(f"HTTP 200 - POST /v1/chat/completions (streaming) - completed")
                    # Write debug logs AFTER streaming completes
                    if debug_logger:
                        if streaming_error:
                            debug_logger.flush_on_error(500, str(streaming_error))
                        else:
                            debug_logger.discard_buffers()
            
            return StreamingResponse(stream_wrapper(), media_type="text/event-stream")
        
        else:
            
            # Non-streaming mode - collect entire response
            openai_response = await collect_stream_response(
                http_client.client,
                response,
                request_data.model,
                model_cache,
                auth_manager,
                request_messages=messages_for_tokenizer,
                request_tools=tools_for_tokenizer
            )
            
            await http_client.close()
            
            # Log access log for non-streaming success
            logger.info(f"HTTP 200 - POST /v1/chat/completions (non-streaming) - completed")
            
            # Write debug logs after non-streaming request completes
            if debug_logger:
                debug_logger.discard_buffers()
            
            return JSONResponse(content=openai_response)
    
    except HTTPException as e:
        await http_client.close()
        # Log access log for HTTP error
        logger.warning(f"HTTP {e.status_code} - POST /v1/chat/completions - {e.detail}")
        # Flush debug logs on HTTP error ("errors" mode)
        if debug_logger:
            debug_logger.flush_on_error(e.status_code, str(e.detail))
        raise
    except Exception as e:
        await http_client.close()
        logger.error(f"Internal error: {e}", exc_info=True)
        # Log access log for internal error
        logger.error(f"HTTP 500 - POST /v1/chat/completions - {str(e)[:100]}")
        # Flush debug logs on internal error ("errors" mode)
        if debug_logger:
            debug_logger.flush_on_error(500, str(e))
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


# ==================================================================================================
# OAuth Endpoints
# ==================================================================================================

@router.post("/auth/kiro/start", response_model=OAuthStartResponse)
async def start_kiro_auth(request: Request, auth_request: OAuthStartRequest):
    """
    Start Kiro OAuth authentication flow.
    
    Supports:
    - "google": Google social auth
    - "github": GitHub social auth
    - "builder-id": AWS Builder ID (device code flow)
    
    Args:
        request: FastAPI Request for accessing app.state
        auth_request: OAuth start request with method
    
    Returns:
        OAuthStartResponse with auth URL and details
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    method = auth_request.method.lower()
    
    logger.info(f"Starting Kiro OAuth authentication (method={method})")
    
    try:
        if method in ("google", "github"):
            provider = "Google" if method == "google" else "Github"
            result = await oauth_manager.start_social_auth(
                provider=provider,
                port=auth_request.port,
            )
        elif method == "builder-id":
            result = await oauth_manager.start_builder_id_auth()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid auth method: {method}. Use 'google', 'github', or 'builder-id'"
            )
        
        return OAuthStartResponse(**result)
    
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/kiro/status", response_model=OAuthStatusResponse)
async def get_kiro_auth_status(request: Request):
    """
    Get current Kiro OAuth authentication status.
    
    Returns:
        OAuthStatusResponse with current auth status
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    status = oauth_manager.get_auth_status()
    
    if status is None:
        return OAuthStatusResponse(in_progress=False)
    
    return OAuthStatusResponse(**status)


@router.post("/auth/kiro/cancel")
async def cancel_kiro_auth(request: Request):
    """
    Cancel ongoing Kiro OAuth authentication.
    
    Returns:
        Success message
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    await oauth_manager.cancel_auth()
    
    logger.info("Kiro OAuth authentication cancelled")
    
    return {"status": "ok", "message": "Authentication cancelled"}


@router.post("/auth/kiro/wait")
async def wait_for_kiro_auth(request: Request):
    """
    Wait for ongoing Kiro OAuth authentication to complete.
    
    This is a blocking endpoint that waits until auth completes or times out.
    
    Returns:
        Token data on success
    
    Raises:
        HTTPException: On timeout, error, or no auth in progress
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    
    try:
        result = await oauth_manager.wait_for_auth()
        logger.info("Kiro OAuth authentication completed successfully")
        return {
            "status": "ok",
            "message": "Authentication successful",
            "credentials_file": str(oauth_manager.credentials_file),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))