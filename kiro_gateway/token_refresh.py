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
    
    # Refresh token when it has less than this many seconds until expiration
    REFRESH_THRESHOLD_SECONDS = 300  # 5 minutes before expiration
    # Minimum interval between refresh attempts (to avoid hammering the API)
    MIN_REFRESH_INTERVAL = 60  # 1 minute
    # Maximum interval to wait before checking again
    MAX_CHECK_INTERVAL = 300  # 5 minutes
    
    def __init__(self, creds_file: str, refresh_interval: int = 1800):
        """
        Initialize the token refresher.
        
        Args:
            creds_file: Path to auth.json credentials file
            refresh_interval: Refresh interval in seconds (default: 1800 = 30 minutes)
                             Note: This is now used as a fallback; the refresher
                             primarily uses expiration-aware scheduling.
        """
        self._creds_file = Path(creds_file).expanduser()
        self._refresh_interval = refresh_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._auth_manager = None  # Reference to KiroAuthManager for sync
    
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
    
    def _get_seconds_until_expiry(self) -> Optional[float]:
        """
        Get seconds until token expiration.
        
        Returns:
            Seconds until expiry, or None if expiration time is unknown
        """
        try:
            creds = self._load_credentials()
            expires_at_str = creds.get('expiresAt')
            if not expires_at_str:
                return None
            
            if expires_at_str.endswith('Z'):
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            else:
                expires_at = datetime.fromisoformat(expires_at_str)
            
            now = datetime.now(timezone.utc)
            return (expires_at - now).total_seconds()
        except Exception as e:
            logger.warning(f"Could not determine token expiry: {e}")
            return None
    
    def _should_refresh(self) -> bool:
        """
        Check if token should be refreshed now.
        
        Returns:
            True if token is expired or will expire within threshold
        """
        seconds_until_expiry = self._get_seconds_until_expiry()
        if seconds_until_expiry is None:
            return True  # Unknown expiry, refresh to be safe
        return seconds_until_expiry <= self.REFRESH_THRESHOLD_SECONDS
    
    def set_auth_manager(self, auth_manager) -> None:
        """
        Set reference to KiroAuthManager for synchronization.
        
        Args:
            auth_manager: KiroAuthManager instance to sync tokens with
        """
        self._auth_manager = auth_manager
    
    def _sync_to_auth_manager(self, creds: dict) -> None:
        """
        Sync refreshed credentials to KiroAuthManager.
        
        Args:
            creds: Updated credentials dict
        """
        if self._auth_manager is None:
            return
        
        try:
            self._auth_manager._access_token = creds.get('accessToken')
            self._auth_manager._refresh_token = creds.get('refreshToken')
            
            expires_at_str = creds.get('expiresAt')
            if expires_at_str:
                if expires_at_str.endswith('Z'):
                    self._auth_manager._expires_at = datetime.fromisoformat(
                        expires_at_str.replace('Z', '+00:00')
                    )
                else:
                    self._auth_manager._expires_at = datetime.fromisoformat(expires_at_str)
            
            logger.debug("Synced refreshed token to auth manager")
        except Exception as e:
            logger.warning(f"Failed to sync token to auth manager: {e}")
    
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
        
        # Sync to auth manager if available
        self._sync_to_auth_manager(creds)
        
        logger.info(f"Token refreshed successfully, expires: {creds['expiresAt']}")
        
        return creds
    
    def _calculate_next_refresh_delay(self) -> float:
        """
        Calculate optimal delay until next refresh check.
        
        Returns:
            Seconds to wait before next refresh attempt
        """
        seconds_until_expiry = self._get_seconds_until_expiry()
        
        if seconds_until_expiry is None:
            # Unknown expiry, use fallback interval
            return self._refresh_interval
        
        if seconds_until_expiry <= 0:
            # Already expired, refresh immediately
            return 0
        
        if seconds_until_expiry <= self.REFRESH_THRESHOLD_SECONDS:
            # Within threshold, refresh soon
            return self.MIN_REFRESH_INTERVAL
        
        # Schedule refresh to happen at threshold time
        # (with some buffer to account for processing time)
        delay = seconds_until_expiry - self.REFRESH_THRESHOLD_SECONDS - 30
        
        # Clamp to reasonable bounds
        return max(self.MIN_REFRESH_INTERVAL, min(delay, self.MAX_CHECK_INTERVAL))
    
    async def _refresh_loop(self) -> None:
        """Background task that refreshes token based on expiration time."""
        # Check immediately on startup if refresh is needed
        if self._should_refresh():
            try:
                logger.info("Token needs refresh on startup, refreshing now...")
                await self.refresh_token()
            except Exception as e:
                logger.error(f"Initial token refresh failed: {e}")
        
        while self._running:
            # Calculate optimal delay based on token expiration
            delay = self._calculate_next_refresh_delay()
            logger.debug(f"Next token refresh check in {delay:.0f} seconds")
            
            await asyncio.sleep(delay)
            
            if not self._running:
                break
            
            # Check if refresh is actually needed
            if self._should_refresh():
                try:
                    await self.refresh_token()
                except Exception as e:
                    logger.error(f"Token refresh failed: {e}")
                    # On failure, retry after minimum interval
                    await asyncio.sleep(self.MIN_REFRESH_INTERVAL)
    
    def start(self) -> None:
        """Start the automatic refresh background task."""
        if self._running:
            logger.warning("Token refresher is already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        
        seconds_until_expiry = self._get_seconds_until_expiry()
        if seconds_until_expiry is not None:
            logger.info(f"Token refresh scheduler started (token expires in {seconds_until_expiry:.0f}s)")
        else:
            logger.info("Token refresh scheduler started")
    
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
