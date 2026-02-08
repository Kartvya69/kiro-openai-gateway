# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
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
Per-request authentication for Kiro Gateway.

This module handles authentication when AUTH_MODE="per_request".
In this mode, clients send their Kiro refresh token directly in the
Authorization: Bearer header, and a temporary auth manager is created
for each request.
"""

import time
from typing import Optional, Dict
from dataclasses import dataclass
from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader
from loguru import logger

from kiro.auth import KiroAuthManager
from kiro.config import AUTH_MODE, PROXY_API_KEY


# Security scheme for extracting Authorization header
auth_header = APIKeyHeader(name="Authorization", auto_error=False)


@dataclass
class CachedAuthManager:
    """Cached auth manager with expiration time."""
    auth_manager: KiroAuthManager
    refresh_token: str
    created_at: float
    last_used: float


# Simple in-memory cache for auth managers
# Key: refresh_token_hash, Value: CachedAuthManager
_auth_manager_cache: Dict[str, CachedAuthManager] = {}
_cache_ttl_seconds: float = 300  # 5 minutes
_cache_cleanup_interval: float = 600  # 10 minutes
_last_cache_cleanup: float = 0.0


def _hash_token(token: str) -> str:
    """
    Create a hash of the token for cache key.
    
    Uses a simple hash to avoid storing actual tokens in cache keys.
    
    Args:
        token: The refresh token to hash
        
    Returns:
        Hash string for cache key
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _cleanup_cache() -> None:
    """
    Remove expired entries from the auth manager cache.
    
    Called periodically to prevent memory leaks.
    """
    global _last_cache_cleanup
    
    now = time.time()
    if now - _last_cache_cleanup < _cache_cleanup_interval:
        return
    
    expired_keys = []
    for key, cached in _auth_manager_cache.items():
        if now - cached.last_used > _cache_ttl_seconds:
            expired_keys.append(key)
    
    for key in expired_keys:
        del _auth_manager_cache[key]
    
    if expired_keys:
        logger.debug(f"Cleaned up {len(expired_keys)} expired auth manager cache entries")
    
    _last_cache_cleanup = now


def extract_bearer_token(auth_header_value: Optional[str]) -> Optional[str]:
    """
    Extract the bearer token from Authorization header.
    
    Args:
        auth_header_value: The Authorization header value
        
    Returns:
        The token if present and properly formatted, None otherwise
    """
    if not auth_header_value:
        return None
    
    if not auth_header_value.startswith("Bearer "):
        return None
    
    token = auth_header_value[7:].strip()  # Remove "Bearer " prefix
    if not token:
        return None
    
    return token


def get_cached_auth_manager(refresh_token: str) -> Optional[KiroAuthManager]:
    """
    Get a cached auth manager for the given refresh token.
    
    Args:
        refresh_token: The Kiro refresh token
        
    Returns:
        Cached auth manager if found and not expired, None otherwise
    """
    _cleanup_cache()
    
    token_hash = _hash_token(refresh_token)
    cached = _auth_manager_cache.get(token_hash)
    
    if cached is None:
        return None
    
    # Check if cache entry has expired
    now = time.time()
    if now - cached.last_used > _cache_ttl_seconds:
        del _auth_manager_cache[token_hash]
        return None
    
    # Update last used time
    cached.last_used = now
    return cached.auth_manager


def cache_auth_manager(refresh_token: str, auth_manager: KiroAuthManager) -> None:
    """
    Cache an auth manager for the given refresh token.
    
    Args:
        refresh_token: The Kiro refresh token
        auth_manager: The auth manager to cache
    """
    token_hash = _hash_token(refresh_token)
    now = time.time()
    
    _auth_manager_cache[token_hash] = CachedAuthManager(
        auth_manager=auth_manager,
        refresh_token=refresh_token,
        created_at=now,
        last_used=now
    )


def create_auth_manager_from_token(refresh_token: str) -> KiroAuthManager:
    """
    Create a new auth manager from a refresh token.
    
    Args:
        refresh_token: The Kiro refresh token
        
    Returns:
        Configured KiroAuthManager
    """
    return KiroAuthManager(
        refresh_token=refresh_token,
        region="us-east-1"  # Default region, can be made configurable per-request if needed
    )


async def get_request_auth_manager(request: Request) -> KiroAuthManager:
    """
    Get the auth manager for the current request.
    
    This function handles both authentication modes:
    - AUTH_MODE="proxy_key": Returns the global auth manager from app.state
    - AUTH_MODE="per_request": Extracts token from header and creates per-request auth manager
    
    Args:
        request: FastAPI Request object
        
    Returns:
        KiroAuthManager for the request
        
    Raises:
        HTTPException: 401 if authentication fails
    """
    # Mode 1: Proxy key mode - use global auth manager
    if AUTH_MODE != "per_request":
        if not hasattr(request.app.state, 'auth_manager'):
            logger.error("Global auth manager not initialized")
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: auth manager not initialized"
            )
        return request.app.state.auth_manager
    
    # Mode 2: Per-request mode - extract token from header
    auth_header_value = request.headers.get("Authorization")
    refresh_token = extract_bearer_token(auth_header_value)
    
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "type": "authentication_error",
                    "message": "Missing or invalid Authorization header. Expected: 'Bearer <kiro_refresh_token>'"
                }
            }
        )
    
    # Try to get cached auth manager
    auth_manager = get_cached_auth_manager(refresh_token)
    
    if auth_manager is None:
        # Create new auth manager
        try:
            auth_manager = create_auth_manager_from_token(refresh_token)
            cache_auth_manager(refresh_token, auth_manager)
            logger.debug("Created new per-request auth manager")
        except Exception as e:
            logger.error(f"Failed to create auth manager: {e}")
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "type": "authentication_error",
                        "message": f"Invalid refresh token or configuration error: {str(e)}"
                    }
                }
            )
    
    return auth_manager


async def verify_api_key_or_token(request: Request) -> bool:
    """
    Verify authentication for the request.
    
    In proxy_key mode: validates PROXY_API_KEY
    In per_request mode: validates that a Kiro refresh token is valid by attempting token refresh
    
    Args:
        request: FastAPI Request object
        
    Returns:
        True if authentication is valid
        
    Raises:
        HTTPException: 401 if authentication fails
    """
    # Per-request mode: validate the Kiro refresh token by attempting to get an access token
    if AUTH_MODE == "per_request":
        auth_header_value = request.headers.get("Authorization")
        refresh_token = extract_bearer_token(auth_header_value)
        
        if not refresh_token:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "type": "authentication_error",
                        "message": "Missing or invalid Authorization header. Expected: 'Bearer <kiro_refresh_token>'"
                    }
                }
            )
        
        # Try to get cached auth manager first
        auth_manager = get_cached_auth_manager(refresh_token)
        
        if auth_manager is None:
            # Create new auth manager and validate the token by attempting refresh
            try:
                auth_manager = create_auth_manager_from_token(refresh_token)
                # Actually validate the token by attempting to get an access token
                await auth_manager.get_access_token()
                cache_auth_manager(refresh_token, auth_manager)
                logger.debug("Validated and cached per-request auth manager")
            except Exception as e:
                logger.warning(f"Invalid Kiro refresh token: {e}")
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": {
                            "type": "authentication_error",
                            "message": f"Invalid Kiro refresh token: {str(e)}"
                        }
                    }
                )
        else:
            # Cached manager exists, verify token is still valid
            try:
                await auth_manager.get_access_token()
            except Exception as e:
                logger.warning(f"Cached token validation failed: {e}")
                # Remove from cache and try again
                token_hash = _hash_token(refresh_token)
                _auth_manager_cache.pop(token_hash, None)
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": {
                            "type": "authentication_error",
                            "message": f"Invalid or expired Kiro refresh token: {str(e)}"
                        }
                    }
                )
        
        return True
    
    # Proxy key mode: validate PROXY_API_KEY
    auth_header_value = request.headers.get("Authorization")
    if auth_header_value and auth_header_value == f"Bearer {PROXY_API_KEY}":
        return True
    
    # Also support x-api-key header for Anthropic compatibility
    x_api_key = request.headers.get("x-api-key")
    if x_api_key and x_api_key == PROXY_API_KEY:
        return True
    
    logger.warning("Access attempt with invalid API key")
    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "type": "authentication_error",
                "message": "Invalid or missing API key"
            }
        }
    )
