# -*- coding: utf-8 -*-

"""
Token Refresh Module for IdC (AWS SSO OIDC) Authentication.

Implements automatic token refresh for BuilderId/Enterprise providers
based on kiro-batch-login's refresh system.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


class IdCTokenRefresher:
    """
    Handles token refresh for IdC (AWS SSO OIDC) authentication.
    
    Uses AWS SSO OIDC's createToken API with grant_type=refresh_token.
    Requires stored client credentials (_clientId, _clientSecret) from original login.
    """
    
    def __init__(self, creds_file: str, refresh_interval: int = 1800):
        """
        Initialize the token refresher.
        
        Args:
            creds_file: Path to auth.json credentials file
            refresh_interval: Refresh interval in seconds (default: 1800 = 30 minutes)
        """
        self._creds_file = Path(creds_file).expanduser()
        self._refresh_interval = refresh_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def _get_oidc_token_url(self, region: str) -> str:
        """Get AWS SSO OIDC token endpoint URL."""
        return f"https://oidc.{region}.amazonaws.com/token"
    
    def _load_credentials(self) -> dict:
        """Load credentials from JSON file."""
        if not self._creds_file.exists():
            raise FileNotFoundError(f"Credentials file not found: {self._creds_file}")
        
        with open(self._creds_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_credentials(self, data: dict) -> None:
        """Save credentials to JSON file."""
        with open(self._creds_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    async def refresh_token(self) -> dict:
        """
        Refresh the access token using AWS SSO OIDC API.
        
        Returns:
            Updated credentials dict
            
        Raises:
            ValueError: If required fields are missing
            httpx.HTTPError: On HTTP request error
        """
        creds = self._load_credentials()
        
        # Validate auth method
        auth_method = creds.get('authMethod')
        if auth_method != 'IdC':
            raise ValueError(f"Unsupported auth method: {auth_method}. Only 'IdC' is supported.")
        
        # Validate required fields
        refresh_token = creds.get('refreshToken')
        client_id = creds.get('_clientId')
        client_secret = creds.get('_clientSecret')
        region = creds.get('region', 'us-east-1')
        
        if not refresh_token:
            raise ValueError("refreshToken is required")
        if not client_id:
            raise ValueError("_clientId is required for IdC token refresh")
        if not client_secret:
            raise ValueError("_clientSecret is required for IdC token refresh")
        
        logger.info(f"Refreshing IdC token for provider: {creds.get('provider', 'unknown')}")
        
        # Build request payload
        payload = {
            'clientId': client_id,
            'clientSecret': client_secret,
            'grantType': 'refresh_token',
            'refreshToken': refresh_token
        }
        
        token_url = self._get_oidc_token_url(region)
        
        async with httpx.AsyncClient(timeout=30) as http_client:
            response = await http_client.post(
                token_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            response_data = response.json()
        
        # Extract new tokens
        new_access_token = response_data.get('accessToken')
        new_refresh_token = response_data.get('refreshToken')
        expires_in = response_data.get('expiresIn', 3600)
        
        if not new_access_token:
            raise ValueError(f"Response does not contain accessToken: {response_data}")
        
        # Calculate new expiration time
        expires_at = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = datetime.fromtimestamp(
            expires_at.timestamp() + expires_in,
            tz=timezone.utc
        )
        
        # Update credentials
        creds['accessToken'] = new_access_token
        if new_refresh_token:
            creds['refreshToken'] = new_refresh_token
        creds['expiresAt'] = expires_at.isoformat().replace('+00:00', 'Z')
        creds['expiresIn'] = expires_in
        creds['refreshedAt'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        creds['savedAt'] = creds['refreshedAt']
        
        # Preserve id token if present
        if 'idToken' in response_data:
            creds['idToken'] = response_data['idToken']
        
        # Save updated credentials
        self._save_credentials(creds)
        
        logger.info(f"Token refreshed successfully, expires: {creds['expiresAt']}")
        
        return creds
    
    async def _refresh_loop(self) -> None:
        """Background task that refreshes token periodically."""
        while self._running:
            # Wait for next refresh interval first
            await asyncio.sleep(self._refresh_interval)
            
            if not self._running:
                break
            
            try:
                await self.refresh_token()
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")
    
    def start(self) -> None:
        """Start the automatic refresh background task."""
        if self._running:
            logger.warning("Token refresher is already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info(f"Token refresh scheduler started (interval: {self._refresh_interval}s)")
    
    def stop(self) -> None:
        """Stop the automatic refresh background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Token refresh scheduler stopped")


async def refresh_once(creds_file: str) -> dict:
    """
    Perform a single token refresh.
    
    Args:
        creds_file: Path to auth.json credentials file
        
    Returns:
        Updated credentials dict
    """
    refresher = IdCTokenRefresher(creds_file)
    return await refresher.refresh_token()


async def start_auto_refresh(creds_file: str, interval: int = 1800) -> IdCTokenRefresher:
    """
    Start automatic token refresh.
    
    Args:
        creds_file: Path to auth.json credentials file
        interval: Refresh interval in seconds (default: 1800 = 30 minutes)
        
    Returns:
        IdCTokenRefresher instance (call .stop() to stop)
    """
    refresher = IdCTokenRefresher(creds_file, interval)
    refresher.start()
    return refresher
