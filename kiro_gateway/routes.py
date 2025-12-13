# -*- coding: utf-8 -*-

# Kiro OpenAI Gateway
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
FastAPI роуты для Kiro Gateway.

Содержит все эндпоинты API:
- / и /health: Health check
- /v1/models: Список моделей
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
    PROXY_API_KEY,
    AVAILABLE_MODELS,
    APP_VERSION,
)
from kiro_gateway.models import (
    OpenAIModel,
    ModelList,
    ChatCompletionRequest,
)
from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.cache import ModelInfoCache
from kiro_gateway.converters import build_kiro_payload
from kiro_gateway.streaming import stream_kiro_to_openai, collect_stream_response
from kiro_gateway.http_client import KiroHttpClient
from kiro_gateway.utils import get_kiro_headers, generate_conversation_id

# Импортируем debug_logger
try:
    from kiro_gateway.debug_logger import debug_logger
except ImportError:
    debug_logger = None


# --- Схема безопасности ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_api_key(auth_header: str = Security(api_key_header)) -> bool:
    """
    Проверяет API ключ в заголовке Authorization.
    
    Ожидает формат: "Bearer {PROXY_API_KEY}"
    
    Args:
        auth_header: Значение заголовка Authorization
    
    Returns:
        True если ключ валиден
    
    Raises:
        HTTPException: 401 если ключ невалиден или отсутствует
    """
    if not auth_header or auth_header != f"Bearer {PROXY_API_KEY}":
        logger.warning("Access attempt with invalid API key.")
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    return True


# --- Роутер ---
router = APIRouter()


@router.get("/")
async def root():
    """
    Health check endpoint.
    
    Returns:
        Статус и версия приложения
    """
    return {
        "status": "ok",
        "message": "Kiro API Gateway is running",
        "version": APP_VERSION
    }


@router.get("/health")
async def health():
    """
    Детальный health check.
    
    Returns:
        Статус, timestamp и версия
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": APP_VERSION
    }


@router.get("/v1/models", response_model=ModelList, dependencies=[Depends(verify_api_key)])
async def get_models(request: Request):
    """
    Возвращает список доступных моделей.
    
    Использует статический список моделей с возможностью обновления из API.
    Кэширует результаты для уменьшения нагрузки на API.
    
    Args:
        request: FastAPI Request для доступа к app.state
    
    Returns:
        ModelList с доступными моделями
    """
    logger.info("Request to /v1/models")
    
    auth_manager: KiroAuthManager = request.app.state.auth_manager
    model_cache: ModelInfoCache = request.app.state.model_cache
    
    # Пытаемся получить модели из API если кэш пуст или устарел
    if model_cache.is_empty() or model_cache.is_stale():
        try:
            token = await auth_manager.get_access_token()
            headers = get_kiro_headers(auth_manager, token)
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{auth_manager.q_host}/ListAvailableModels",
                    headers=headers,
                    params={
                        "origin": "AI_EDITOR",
                        "profileArn": auth_manager.profile_arn or ""
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models_list = data.get("models", [])
                    await model_cache.update(models_list)
                    logger.info(f"Received {len(models_list)} models from API")
        except Exception as e:
            logger.warning(f"Failed to fetch models from API: {e}")
    
    # Возвращаем статический список моделей
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
    Chat completions endpoint - совместим с OpenAI API.
    
    Принимает запросы в формате OpenAI и транслирует их в Kiro API.
    Поддерживает streaming и non-streaming режимы.
    
    Args:
        request: FastAPI Request для доступа к app.state
        request_data: Запрос в формате OpenAI ChatCompletionRequest
    
    Returns:
        StreamingResponse для streaming режима
        JSONResponse для non-streaming режима
    
    Raises:
        HTTPException: При ошибках валидации или API
    """
    logger.info(f"Request to /v1/chat/completions (model={request_data.model}, stream={request_data.stream})")
    
    auth_manager: KiroAuthManager = request.app.state.auth_manager
    model_cache: ModelInfoCache = request.app.state.model_cache
    
    # Подготовка отладочных логов
    if debug_logger:
        debug_logger.prepare_new_request()
    
    # Логируем входящий запрос
    try:
        request_body = json.dumps(request_data.model_dump(), ensure_ascii=False, indent=2).encode('utf-8')
        if debug_logger:
            debug_logger.log_request_body(request_body)
    except Exception as e:
        logger.warning(f"Failed to log request body: {e}")
    
    # Ленивое заполнение кэша моделей
    if model_cache.is_empty():
        logger.debug("Model cache is empty, skipping forced population")
    
    # Генерируем ID для разговора
    conversation_id = generate_conversation_id()
    
    # Строим payload для Kiro
    try:
        kiro_payload = build_kiro_payload(
            request_data,
            conversation_id,
            auth_manager.profile_arn or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Логируем payload для Kiro
    try:
        kiro_request_body = json.dumps(kiro_payload, ensure_ascii=False, indent=2).encode('utf-8')
        if debug_logger:
            debug_logger.log_kiro_request_body(kiro_request_body)
    except Exception as e:
        logger.warning(f"Failed to log Kiro request: {e}")
    
    # Создаём HTTP клиент с retry логикой
    http_client = KiroHttpClient(auth_manager)
    
    try:
        url = f"{auth_manager.api_host}/generateAssistantResponse"
        
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
            return Response(status_code=response.status_code, content=error_content)
        
        if request_data.stream:
            # Streaming режим
            async def stream_wrapper():
                try:
                    async for chunk in stream_kiro_to_openai(
                        http_client.client,
                        response,
                        request_data.model,
                        model_cache,
                        auth_manager
                    ):
                        yield chunk
                finally:
                    await http_client.close()
            
            return StreamingResponse(stream_wrapper(), media_type="text/event-stream")
        
        else:
            # Non-streaming режим - собираем весь ответ
            openai_response = await collect_stream_response(
                http_client.client,
                response,
                request_data.model,
                model_cache,
                auth_manager
            )
            
            await http_client.close()
            return JSONResponse(content=openai_response)
    
    except HTTPException:
        await http_client.close()
        raise
    except Exception as e:
        await http_client.close()
        logger.error(f"Internal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")