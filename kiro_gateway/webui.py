# -*- coding: utf-8 -*-

"""
Web UI routes for Kiro Gateway.

Provides endpoints for:
- Login with secret_key
- Account management (list, add, remove)
- OAuth flow integration
- Config management (read/write)
- System info (uptime, memory, CPU)
- Real-time logs via SSE
- Usage statistics
"""

import asyncio
import hashlib
import os
import platform
import secrets
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import psutil
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from loguru import logger
from pydantic import BaseModel

from kiro_gateway.config import SECRET_KEY, APP_VERSION
import json as json_module
from kiro_gateway.accounts import AccountManager


# Session tokens with file persistence
_sessions: dict = {}
SESSION_EXPIRY_DAYS = 30  # Extended to 30 days for longer persistence
SESSION_FILE = Path(__file__).parent.parent / ".sessions.json"
_session_cleanup_task: Optional[asyncio.Task] = None

# Server start time for uptime calculation
_server_start_time = time.time()

# Log buffer for SSE streaming
_log_buffer: deque = deque(maxlen=500)
_log_subscribers: List[asyncio.Queue] = []

# System info cache
_system_info_cache: Optional[Dict[str, Any]] = None
_system_info_cache_time: float = 0
SYSTEM_INFO_CACHE_TTL = 5  # seconds


def _load_sessions_from_file():
    """Load sessions from persistent storage on startup."""
    global _sessions
    try:
        if SESSION_FILE.exists():
            with open(SESSION_FILE, 'r') as f:
                data = json_module.load(f)
            
            now = datetime.now(timezone.utc)
            loaded = 0
            for token, session in data.items():
                # Parse expires_at and filter out expired sessions
                expires_at = datetime.fromisoformat(session["expires_at"])
                if expires_at > now:
                    _sessions[token] = {
                        "created_at": datetime.fromisoformat(session["created_at"]),
                        "expires_at": expires_at,
                    }
                    loaded += 1
            
            if loaded > 0:
                logger.info(f"Loaded {loaded} persistent sessions from file")
    except Exception as e:
        logger.warning(f"Could not load sessions from file: {e}")


def _save_sessions_to_file():
    """Save sessions to persistent storage."""
    try:
        data = {}
        for token, session in _sessions.items():
            data[token] = {
                "created_at": session["created_at"].isoformat(),
                "expires_at": session["expires_at"].isoformat(),
            }
        
        with open(SESSION_FILE, 'w') as f:
            json_module.dump(data, f)
    except Exception as e:
        logger.warning(f"Could not save sessions to file: {e}")


async def cleanup_expired_sessions():
    """Background task to clean up expired sessions periodically."""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            now = datetime.now(timezone.utc)
            expired = [token for token, session in _sessions.items() 
                      if now > session["expires_at"]]
            for token in expired:
                del _sessions[token]
            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired sessions")
                _save_sessions_to_file()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")


def start_session_cleanup():
    """Start the session cleanup background task and load persistent sessions."""
    global _session_cleanup_task
    _load_sessions_from_file()
    if _session_cleanup_task is None or _session_cleanup_task.done():
        _session_cleanup_task = asyncio.create_task(cleanup_expired_sessions())


def stop_session_cleanup():
    """Stop the session cleanup background task and save sessions."""
    global _session_cleanup_task
    _save_sessions_to_file()
    if _session_cleanup_task and not _session_cleanup_task.done():
        _session_cleanup_task.cancel()


def add_log_entry(message: str, level: str = "INFO"):
    """Add a log entry to the buffer and notify subscribers."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    _log_buffer.append(entry)
    for queue in _log_subscribers:
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass


# Custom log handler to capture logs
class WebUILogHandler:
    def write(self, message):
        if message.strip():
            level = "INFO"
            if "ERROR" in message or "error" in message.lower():
                level = "ERROR"
            elif "WARNING" in message or "warning" in message.lower():
                level = "WARNING"
            elif "DEBUG" in message:
                level = "DEBUG"
            add_log_entry(message.strip(), level)


webui_router = APIRouter(prefix="/ui", tags=["webui"])

# Security
session_header = APIKeyHeader(name="X-Session-Token", auto_error=False)


def _generate_session_token() -> str:
    """Generate a secure session token."""
    return secrets.token_urlsafe(32)


def _hash_key(key: str) -> str:
    """Hash a key for comparison."""
    return hashlib.sha256(key.encode()).hexdigest()


async def verify_session(
    session_token: str = Depends(session_header),
    token: Optional[str] = None,
) -> bool:
    """Verify session token from header or query parameter."""
    # Try header first, then query param (for SSE)
    actual_token = session_token or token
    
    if not actual_token:
        raise HTTPException(status_code=401, detail="Session token required")
    
    session = _sessions.get(actual_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    if datetime.now(timezone.utc) > session["expires_at"]:
        del _sessions[actual_token]
        raise HTTPException(status_code=401, detail="Session expired")
    
    return True


# --- Request/Response Models ---

class LoginRequest(BaseModel):
    secret_key: str


class LoginResponse(BaseModel):
    success: bool
    session_token: Optional[str] = None
    expires_at: Optional[str] = None
    message: Optional[str] = None


class AddAccountRequest(BaseModel):
    name: str
    method: str  # "google", "github", "builder-id"


class AccountResponse(BaseModel):
    id: int
    name: str
    auth_method: Optional[str]
    provider: Optional[str]
    region: Optional[str]
    expires_at: Optional[str]
    created_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool
    request_count: int
    status: str


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]


# --- Routes ---

@webui_router.get("", response_class=HTMLResponse)
async def serve_ui(request: Request):
    """Serve the main UI page."""
    templates_dir = Path(__file__).parent / "templates"
    index_path = templates_dir / "index.html"
    
    if not index_path.exists():
        return HTMLResponse(
            content="<h1>UI not found</h1><p>templates/index.html is missing</p>",
            status_code=404
        )
    
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    return HTMLResponse(content=html_content)


@webui_router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login with secret_key.
    
    Returns a session token valid for 24 hours.
    """
    if request.secret_key != SECRET_KEY:
        logger.warning("Failed login attempt")
        return LoginResponse(success=False, message="Invalid secret key")
    
    # Generate session token
    session_token = _generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRY_DAYS)
    
    _sessions[session_token] = {
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    }
    
    # Persist sessions to file
    _save_sessions_to_file()
    
    logger.info("Successful login")
    return LoginResponse(
        success=True,
        session_token=session_token,
        expires_at=expires_at.isoformat(),
    )


@webui_router.post("/logout")
async def logout(session_token: str = Depends(session_header)):
    """Logout and invalidate session."""
    if session_token in _sessions:
        del _sessions[session_token]
        _save_sessions_to_file()
    return {"success": True, "message": "Logged out"}


# --- System Info ---

def _get_system_info_uncached() -> Dict[str, Any]:
    """Get system information without caching."""
    uptime_seconds = int(time.time() - _server_start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if hours > 24:
        days = hours // 24
        hours = hours % 24
        uptime_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        uptime_str = f"{hours}h {minutes}m {seconds}s"
    else:
        uptime_str = f"{minutes}m {seconds}s"
    
    # Memory info
    memory = psutil.virtual_memory()
    memory_used_mb = memory.used / (1024 * 1024)
    memory_total_mb = memory.total / (1024 * 1024)
    memory_percent = memory.percent
    
    # CPU info - use interval=None for non-blocking call (returns last measurement)
    cpu_percent = psutil.cpu_percent(interval=None)
    
    # Process info
    process = psutil.Process()
    process_memory_mb = process.memory_info().rss / (1024 * 1024)
    
    return {
        "version": APP_VERSION,
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "uptime": uptime_str,
        "uptime_seconds": uptime_seconds,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "memory": {
            "used_mb": round(memory_used_mb, 1),
            "total_mb": round(memory_total_mb, 1),
            "percent": memory_percent,
            "process_mb": round(process_memory_mb, 1),
        },
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(),
        },
        "pid": os.getpid(),
    }


@webui_router.get("/api/system")
async def get_system_info(_: bool = Depends(verify_session)):
    """Get system information with caching."""
    global _system_info_cache, _system_info_cache_time
    
    now = time.time()
    if _system_info_cache is None or (now - _system_info_cache_time) > SYSTEM_INFO_CACHE_TTL:
        _system_info_cache = _get_system_info_uncached()
        _system_info_cache_time = now
    
    return _system_info_cache


# --- Config Management ---

@webui_router.get("/api/config")
async def get_config(_: bool = Depends(verify_session)):
    """Get current configuration."""
    config_path = Path("config.yml")
    
    if not config_path.exists():
        return {"config": {}, "exists": False}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        
        # Mask sensitive values
        safe_config = config.copy()
        if "proxy_api_key" in safe_config:
            safe_config["proxy_api_key"] = "***" + safe_config["proxy_api_key"][-4:] if len(safe_config.get("proxy_api_key", "")) > 4 else "****"
        if "secret_key" in safe_config:
            safe_config["secret_key"] = "***" + safe_config["secret_key"][-4:] if len(safe_config.get("secret_key", "")) > 4 else "****"
        if "refresh_token" in safe_config and safe_config["refresh_token"]:
            safe_config["refresh_token"] = "***" + safe_config["refresh_token"][-8:] if len(safe_config.get("refresh_token", "")) > 8 else "****"
        
        return {"config": safe_config, "exists": True}
    except Exception as e:
        logger.error(f"Failed to read config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/api/config")
async def update_config(request: ConfigUpdateRequest, _: bool = Depends(verify_session)):
    """Update configuration values."""
    config_path = Path("config.yml")
    
    try:
        # Load existing config
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                current_config = yaml.safe_load(f) or {}
        else:
            current_config = {}
        
        # Update with new values (skip masked values)
        for key, value in request.config.items():
            if isinstance(value, str) and value.startswith("***"):
                continue  # Skip masked values
            current_config[key] = value
        
        # Write back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(current_config, f, default_flow_style=False, allow_unicode=True)
        
        logger.info("Configuration updated via Web UI")
        add_log_entry("Configuration updated via Web UI", "INFO")
        
        return {"success": True, "message": "Configuration saved. Some changes may require restart."}
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Accounts ---

@webui_router.get("/accounts")
async def list_accounts(
    request: Request,
    _: bool = Depends(verify_session),
):
    """List all accounts."""
    account_manager: AccountManager = request.app.state.account_manager
    accounts = await account_manager.list_accounts()
    total_requests = await account_manager.get_total_requests()
    
    return {
        "accounts": accounts,
        "total_count": len(accounts),
        "active_count": sum(1 for a in accounts if a["is_active"]),
        "total_requests": total_requests,
    }


@webui_router.get("/accounts/{account_id}")
async def get_account(
    request: Request,
    account_id: int,
    _: bool = Depends(verify_session),
):
    """Get a single account."""
    account_manager: AccountManager = request.app.state.account_manager
    account = await account_manager.get_account(account_id)
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return account


@webui_router.delete("/accounts/{account_id}")
async def delete_account(
    request: Request,
    account_id: int,
    _: bool = Depends(verify_session),
):
    """Delete an account."""
    account_manager: AccountManager = request.app.state.account_manager
    success = await account_manager.remove_account(account_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    
    add_log_entry(f"Account {account_id} deleted via Web UI", "INFO")
    return {"success": True, "message": f"Account {account_id} deleted"}


@webui_router.post("/accounts/{account_id}/refresh")
async def refresh_account_token(
    request: Request,
    account_id: int,
    _: bool = Depends(verify_session),
):
    """Manually refresh an account's token."""
    account_manager: AccountManager = request.app.state.account_manager
    
    try:
        success, message = await account_manager.refresh_account_token(account_id)
        if success:
            add_log_entry(f"Token refreshed for account {account_id}", "INFO")
            return {"success": True, "message": message}
        else:
            add_log_entry(f"Token refresh failed for account {account_id}: {message}", "WARNING")
            raise HTTPException(status_code=400, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/accounts/start-auth")
async def start_account_auth(
    request: Request,
    auth_request: AddAccountRequest,
    _: bool = Depends(verify_session),
):
    """
    Start OAuth flow for adding a new account.
    
    Returns auth URL and flow details.
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    method = auth_request.method.lower()
    
    logger.info(f"Starting OAuth for new account: {auth_request.name} (method={method})")
    add_log_entry(f"Starting OAuth for account: {auth_request.name}", "INFO")
    
    # Store account name for later
    oauth_manager._pending_account_name = auth_request.name
    
    try:
        if method in ("google", "github"):
            provider = "Google" if method == "google" else "Github"
            result = await oauth_manager.start_social_auth(provider=provider)
        elif method == "builder-id":
            result = await oauth_manager.start_builder_id_auth()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid auth method: {method}. Use 'google', 'github', or 'builder-id'"
            )
        
        return {
            "success": True,
            "auth_url": result["auth_url"],
            "method": result["method"],
            "provider": result.get("provider"),
            "port": result.get("port"),
            "user_code": result.get("user_code"),
            "verification_uri": result.get("verification_uri"),
            "expires_in": result.get("expires_in", 600),
        }
    
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/accounts/complete-auth")
async def complete_account_auth(
    request: Request,
    _: bool = Depends(verify_session),
):
    """
    Wait for OAuth to complete and save account to database.
    
    This is a blocking endpoint that waits for auth completion.
    """
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    account_manager: AccountManager = request.app.state.account_manager
    
    account_name = getattr(oauth_manager, '_pending_account_name', 'New Account')
    
    try:
        # Wait for OAuth to complete
        result = await oauth_manager.wait_for_auth()
        
        # Get auth details
        auth_status = oauth_manager._current_auth or {}
        auth_method = auth_status.get("method", "social")
        provider = auth_status.get("provider")
        
        # Parse expiration
        expires_at = None
        if "expiresAt" in result:
            expires_str = result["expiresAt"]
            if expires_str.endswith("Z"):
                expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            else:
                expires_at = datetime.fromisoformat(expires_str)
        
        # Save to database
        account = await account_manager.add_account(
            name=account_name,
            auth_method=auth_method,
            provider=provider,
            access_token=result.get("accessToken", ""),
            refresh_token=result.get("refreshToken", ""),
            profile_arn=result.get("profileArn"),
            region=result.get("region", "us-east-1"),
            expires_at=expires_at,
            extra_data={
                "clientId": result.get("_clientId"),
                "clientSecret": result.get("_clientSecret"),
            } if result.get("_clientId") else None,
        )
        
        logger.info(f"OAuth completed, saved account: {account_name} (id={account.id})")
        add_log_entry(f"Account added: {account_name} (id={account.id})", "INFO")
        
        return {
            "success": True,
            "message": "Account added successfully",
            "account": account.to_dict(),
        }
    
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth complete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/accounts/cancel-auth")
async def cancel_account_auth(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Cancel ongoing OAuth flow."""
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    await oauth_manager.cancel_auth()
    
    return {"success": True, "message": "Authentication cancelled"}


@webui_router.get("/auth-status")
async def get_auth_status(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Get current OAuth status."""
    from kiro_gateway.oauth import KiroOAuthManager
    
    oauth_manager: KiroOAuthManager = request.app.state.oauth_manager
    status = oauth_manager.get_auth_status()
    
    return {
        "in_progress": status is not None,
        "details": status,
    }


# --- Stats ---

@webui_router.get("/stats")
async def get_stats(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Get gateway statistics."""
    account_manager: AccountManager = request.app.state.account_manager
    accounts = await account_manager.list_accounts()
    
    healthy = sum(1 for a in accounts if a["status"] == "healthy")
    expiring = sum(1 for a in accounts if a["status"] == "expiring_soon")
    expired = sum(1 for a in accounts if a["status"] == "expired")
    
    return {
        "total_accounts": len(accounts),
        "healthy_accounts": healthy,
        "expiring_accounts": expiring,
        "expired_accounts": expired,
        "total_requests": await account_manager.get_total_requests(),
        "load_balancing": "round-robin",
    }


# --- Usage Statistics ---

@webui_router.get("/api/usage")
async def get_usage_stats(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Get usage statistics per account."""
    account_manager: AccountManager = request.app.state.account_manager
    accounts = await account_manager.list_accounts()
    
    usage_data = []
    for account in accounts:
        usage_data.append({
            "id": account["id"],
            "name": account["name"],
            "provider": account.get("provider") or account.get("auth_method", "Unknown"),
            "request_count": account["request_count"],
            "last_used_at": account.get("last_used_at"),
            "status": account["status"],
        })
    
    # Sort by request count descending
    usage_data.sort(key=lambda x: x["request_count"], reverse=True)
    
    total_requests = sum(a["request_count"] for a in usage_data)
    
    return {
        "accounts": usage_data,
        "total_requests": total_requests,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# --- Real-time Logs (SSE) ---

def _verify_session_token(token: Optional[str]) -> bool:
    """Verify session token without raising exceptions."""
    if not token:
        return False
    session = _sessions.get(token)
    if not session:
        return False
    if datetime.now(timezone.utc) > session["expires_at"]:
        del _sessions[token]
        return False
    return True


@webui_router.get("/api/logs/stream")
async def stream_logs(
    request: Request,
    token: Optional[str] = None,
    _: bool = Depends(verify_session),
):
    """Stream logs via Server-Sent Events.
    
    Supports authentication via:
    - X-Session-Token header (standard)
    - ?token= query parameter (for EventSource which doesn't support headers)
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _log_subscribers.append(queue)
    
    async def event_generator():
        try:
            # Send existing logs first
            for entry in list(_log_buffer):
                yield f"data: {entry}\n\n"
            
            # Stream new logs
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {entry}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield f": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _log_subscribers:
                _log_subscribers.remove(queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@webui_router.get("/api/logs")
async def get_logs(_: bool = Depends(verify_session)):
    """Get recent logs."""
    return {
        "logs": list(_log_buffer),
        "count": len(_log_buffer),
    }


@webui_router.delete("/api/logs")
async def clear_logs(_: bool = Depends(verify_session)):
    """Clear log buffer."""
    _log_buffer.clear()
    return {"success": True, "message": "Logs cleared"}


# --- Enhanced Config Management ---

class ConfigFieldUpdate(BaseModel):
    field: str
    value: Any


@webui_router.get("/api/config/raw")
async def get_raw_config(_: bool = Depends(verify_session)):
    """Get raw configuration with all fields (sensitive values masked)."""
    config_path = Path("config.yml")
    
    if not config_path.exists():
        return {"config": {}, "exists": False, "schema": get_config_schema()}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        
        # Create a full config with defaults
        full_config = {
            "proxy_api_key": config.get("proxy_api_key", ""),
            "secret_key": config.get("secret_key", ""),
            "kiro_creds_file": config.get("kiro_creds_file", ""),
            "refresh_token": config.get("refresh_token", ""),
            "profile_arn": config.get("profile_arn", ""),
            "kiro_region": config.get("kiro_region", "us-east-1"),
            "log_level": config.get("log_level", "INFO"),
            "first_token_timeout": config.get("first_token_timeout", 15),
            "first_token_max_retries": config.get("first_token_max_retries", 3),
            "streaming_read_timeout": config.get("streaming_read_timeout", 300),
            "tool_description_max_length": config.get("tool_description_max_length", 10000),
            "debug_mode": config.get("debug_mode", "off"),
            "debug_dir": config.get("debug_dir", "debug_logs"),
            "oauth": config.get("oauth", {
                "callback_port_start": 19876,
                "callback_port_end": 19880,
                "auth_timeout": 600,
                "poll_interval": 5,
            }),
        }
        
        # Mask sensitive values
        masked_config = full_config.copy()
        for key in ["proxy_api_key", "secret_key", "refresh_token"]:
            if masked_config.get(key):
                val = masked_config[key]
                if len(val) > 4:
                    masked_config[key] = "***" + val[-4:]
                else:
                    masked_config[key] = "****"
        
        return {
            "config": masked_config,
            "exists": True,
            "schema": get_config_schema(),
        }
    except Exception as e:
        logger.error(f"Failed to read config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def get_config_schema() -> Dict[str, Any]:
    """Return config field schema for UI rendering."""
    return {
        "sections": [
            {
                "id": "authentication",
                "title": "Authentication",
                "icon": "fa-key",
                "fields": [
                    {"key": "proxy_api_key", "label": "Proxy API Key", "type": "password", "description": "Password to protect your proxy server"},
                    {"key": "secret_key", "label": "Secret Key (Web UI)", "type": "password", "description": "Password for Web UI access"},
                ]
            },
            {
                "id": "kiro",
                "title": "Kiro Settings",
                "icon": "fa-cloud",
                "fields": [
                    {"key": "kiro_creds_file", "label": "Credentials File", "type": "text", "description": "Path to JSON credentials file"},
                    {"key": "refresh_token", "label": "Refresh Token", "type": "password", "description": "Kiro refresh token (alternative to creds file)"},
                    {"key": "profile_arn", "label": "Profile ARN", "type": "text", "description": "AWS CodeWhisperer profile ARN (usually auto-detected)"},
                    {"key": "kiro_region", "label": "Region", "type": "select", "options": ["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"], "description": "AWS region"},
                ]
            },
            {
                "id": "streaming",
                "title": "Streaming & Timeouts",
                "icon": "fa-clock",
                "fields": [
                    {"key": "first_token_timeout", "label": "First Token Timeout (s)", "type": "number", "min": 1, "max": 120, "description": "Timeout for first token from model"},
                    {"key": "first_token_max_retries", "label": "Max Retries", "type": "number", "min": 0, "max": 10, "description": "Maximum retry attempts"},
                    {"key": "streaming_read_timeout", "label": "Streaming Timeout (s)", "type": "number", "min": 30, "max": 600, "description": "Read timeout for streaming responses"},
                    {"key": "tool_description_max_length", "label": "Tool Desc Max Length", "type": "number", "min": 1000, "max": 50000, "description": "Maximum tool description length"},
                ]
            },
            {
                "id": "debug",
                "title": "Debug Settings",
                "icon": "fa-bug",
                "fields": [
                    {"key": "log_level", "label": "Log Level", "type": "select", "options": ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], "description": "Logging verbosity"},
                    {"key": "debug_mode", "label": "Debug Mode", "type": "select", "options": ["off", "errors", "all"], "description": "Debug logging mode"},
                    {"key": "debug_dir", "label": "Debug Directory", "type": "text", "description": "Directory for debug log files"},
                ]
            },
        ]
    }


@webui_router.post("/api/config/field")
async def update_config_field(update: ConfigFieldUpdate, _: bool = Depends(verify_session)):
    """Update a single configuration field."""
    config_path = Path("config.yml")
    
    # Validate field
    valid_fields = [
        "proxy_api_key", "secret_key", "kiro_creds_file", "refresh_token",
        "profile_arn", "kiro_region", "log_level", "first_token_timeout",
        "first_token_max_retries", "streaming_read_timeout", "tool_description_max_length",
        "debug_mode", "debug_dir"
    ]
    
    if update.field not in valid_fields:
        raise HTTPException(status_code=400, detail=f"Invalid field: {update.field}")
    
    # Skip masked values
    if isinstance(update.value, str) and update.value.startswith("***"):
        return {"success": True, "message": "Skipped masked value", "skipped": True}
    
    try:
        # Load existing config
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}
        
        # Update field
        config[update.field] = update.value
        
        # Write back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        
        logger.info(f"Config field '{update.field}' updated via Web UI")
        add_log_entry(f"Config field '{update.field}' updated", "INFO")
        
        return {"success": True, "message": f"Field '{update.field}' updated"}
    except Exception as e:
        logger.error(f"Failed to update config field: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Enhanced Account Management ---

class AccountUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


@webui_router.patch("/accounts/{account_id}")
async def update_account(
    request: Request,
    account_id: int,
    update: AccountUpdateRequest,
    _: bool = Depends(verify_session),
):
    """Update account properties (name, active status)."""
    account_manager: AccountManager = request.app.state.account_manager
    
    try:
        account = await account_manager.get_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        updates = {}
        if update.name is not None:
            updates["name"] = update.name
        if update.is_active is not None:
            updates["is_active"] = update.is_active
        
        if updates:
            await account_manager.update_account(account_id, **updates)
            add_log_entry(f"Account {account_id} updated: {updates}", "INFO")
        
        return {"success": True, "message": "Account updated", "updates": updates}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/accounts/{account_id}/toggle")
async def toggle_account(
    request: Request,
    account_id: int,
    _: bool = Depends(verify_session),
):
    """Toggle account active status."""
    account_manager: AccountManager = request.app.state.account_manager
    
    try:
        account = await account_manager.get_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        new_status = not account["is_active"]
        await account_manager.update_account(account_id, is_active=new_status)
        
        status_text = "activated" if new_status else "deactivated"
        add_log_entry(f"Account {account_id} {status_text}", "INFO")
        
        return {"success": True, "is_active": new_status, "message": f"Account {status_text}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@webui_router.post("/accounts/refresh-all")
async def refresh_all_tokens(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Refresh tokens for all accounts."""
    account_manager: AccountManager = request.app.state.account_manager
    
    try:
        refreshed = await account_manager.refresh_all_tokens(force=True)
        add_log_entry(f"Refreshed {refreshed} account tokens", "INFO")
        return {"success": True, "refreshed_count": refreshed, "message": f"Refreshed {refreshed} tokens"}
    except Exception as e:
        logger.error(f"Failed to refresh all tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Enhanced Usage Statistics ---

@webui_router.get("/api/usage/summary")
async def get_usage_summary(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Get detailed usage summary with percentages."""
    account_manager: AccountManager = request.app.state.account_manager
    accounts = await account_manager.list_accounts()
    
    total_requests = sum(a["request_count"] for a in accounts)
    
    usage_data = []
    for account in accounts:
        req_count = account["request_count"]
        percentage = (req_count / total_requests * 100) if total_requests > 0 else 0
        
        usage_data.append({
            "id": account["id"],
            "name": account["name"],
            "provider": account.get("provider") or account.get("auth_method", "Unknown"),
            "request_count": req_count,
            "percentage": round(percentage, 1),
            "last_used_at": account.get("last_used_at"),
            "status": account["status"],
            "is_active": account["is_active"],
            "expires_at": account.get("expires_at"),
        })
    
    # Sort by request count descending
    usage_data.sort(key=lambda x: x["request_count"], reverse=True)
    
    # Calculate status counts
    status_counts = {
        "healthy": sum(1 for a in accounts if a["status"] == "healthy"),
        "expiring_soon": sum(1 for a in accounts if a["status"] == "expiring_soon"),
        "expired": sum(1 for a in accounts if a["status"] == "expired"),
        "inactive": sum(1 for a in accounts if not a["is_active"]),
    }
    
    return {
        "accounts": usage_data,
        "total_requests": total_requests,
        "total_accounts": len(accounts),
        "active_accounts": sum(1 for a in accounts if a["is_active"]),
        "status_counts": status_counts,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# --- Kiro Credits/Usage Limits ---

@webui_router.get("/api/credits")
async def get_kiro_credits(
    request: Request,
    _: bool = Depends(verify_session),
):
    """Get Kiro credits/usage limits for all accounts."""
    account_manager: AccountManager = request.app.state.account_manager
    
    results = []
    errors = []
    
    # Get all active accounts
    async with account_manager._lock:
        account_ids = list(account_manager._account_ids)
        auth_managers = dict(account_manager._auth_managers)
    
    # Fetch accounts info for names
    accounts_info = await account_manager.list_accounts()
    account_names = {a["id"]: a["name"] for a in accounts_info}
    
    for account_id in account_ids:
        auth_manager = auth_managers.get(account_id)
        if not auth_manager:
            continue
        
        try:
            usage_data = await auth_manager.get_usage_limits()
            
            # Extract relevant data - look for CREDIT or AGENTIC_REQUEST
            usage_breakdown = usage_data.get("usageBreakdownList", [])
            credit_usage = None
            for item in usage_breakdown:
                resource_type = item.get("resourceType", "")
                if resource_type in ("CREDIT", "AGENTIC_REQUEST"):
                    credit_usage = item
                    break
            
            if credit_usage:
                # Check for free trial info first (has higher limits)
                free_trial = credit_usage.get("freeTrialInfo", {})
                if free_trial and free_trial.get("freeTrialStatus") == "ACTIVE":
                    current = free_trial.get("currentUsage", 0)
                    limit = free_trial.get("usageLimit", 0)
                else:
                    current = credit_usage.get("currentUsage", 0)
                    limit = credit_usage.get("usageLimit", 0)
                
                remaining = max(0, limit - current)
                percentage_used = (current / limit * 100) if limit > 0 else 0
                
                # Check for bonuses
                bonuses = credit_usage.get("bonuses", [])
                bonus_total = sum(b.get("usageLimit", 0) - b.get("currentUsage", 0) for b in bonuses)
                
                results.append({
                    "account_id": account_id,
                    "account_name": account_names.get(account_id, f"Account {account_id}"),
                    "current_usage": current,
                    "usage_limit": limit,
                    "remaining": remaining,
                    "percentage_used": round(percentage_used, 1),
                    "bonus_remaining": bonus_total,
                    "days_until_reset": usage_data.get("daysUntilReset"),
                    "next_reset_date": usage_data.get("nextDateReset"),
                    "subscription": usage_data.get("subscriptionInfo", {}).get("subscriptionTitle", "Unknown"),
                    "email": usage_data.get("userInfo", {}).get("email"),
                    "free_trial_status": free_trial.get("freeTrialStatus") if free_trial else None,
                    "free_trial_expiry": free_trial.get("freeTrialExpiry") if free_trial else None,
                })
            else:
                results.append({
                    "account_id": account_id,
                    "account_name": account_names.get(account_id, f"Account {account_id}"),
                    "error": "No credit usage data found",
                })
                
        except Exception as e:
            logger.warning(f"Failed to get credits for account {account_id}: {e}")
            errors.append({
                "account_id": account_id,
                "account_name": account_names.get(account_id, f"Account {account_id}"),
                "error": str(e),
            })
    
    # Calculate totals
    total_remaining = sum(r.get("remaining", 0) for r in results if "remaining" in r)
    total_limit = sum(r.get("usage_limit", 0) for r in results if "usage_limit" in r)
    total_used = sum(r.get("current_usage", 0) for r in results if "current_usage" in r)
    
    return {
        "accounts": results,
        "errors": errors,
        "totals": {
            "total_remaining": total_remaining,
            "total_limit": total_limit,
            "total_used": total_used,
            "percentage_used": round((total_used / total_limit * 100) if total_limit > 0 else 0, 1),
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
