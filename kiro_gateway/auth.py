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
Authentication manager for Kiro API.

Manages the lifecycle of access tokens:
- Loading credentials from .env or JSON file
- Automatic token refresh on expiration
- Thread-safe refresh using asyncio.Lock
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from kiro_gateway.config import (
    TOKEN_REFRESH_THRESHOLD,
    get_kiro_refresh_url,
    get_kiro_api_host,
    get_kiro_q_host,
)
from kiro_gateway.utils import get_machine_fingerprint


class KiroAuthManager:
    """
    Manages the token lifecycle for accessing Kiro API.
    
    Supports:
    - Loading credentials from .env or JSON file
    - Automatic token refresh on expiration
    - Expiration time validation (expiresAt)
    - Saving updated tokens to file
    
    Attributes:
        profile_arn: AWS CodeWhisperer profile ARN
        region: AWS region
        api_host: API host for the current region
        q_host: Q API host for the current region
        fingerprint: Unique machine fingerprint
    
    Example:
        >>> auth_manager = KiroAuthManager(
        ...     refresh_token="your_refresh_token",
        ...     region="us-east-1"
        ... )
        >>> token = await auth_manager.get_access_token()
    """
    
    def __init__(
        self,
        refresh_token: Optional[str] = None,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
        creds_file: Optional[str] = None
    ):
        """
        Initializes the authentication manager.
        
        Args:
            refresh_token: Refresh token for obtaining access token
            profile_arn: AWS CodeWhisperer profile ARN
            region: AWS region (default: us-east-1)
            creds_file: Path to JSON file with credentials (optional)
        """
        self._refresh_token = refresh_token
        self._profile_arn = profile_arn
        self._region = region
        self._creds_file = creds_file
        
        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._idc_refresher = None  # Reference to IdCTokenRefresher for fallback
        self._auth_method: Optional[str] = None  # 'IdC' or other
        
        # Dynamic URLs based on region
        self._refresh_url = get_kiro_refresh_url(region)
        self._api_host = get_kiro_api_host(region)
        self._q_host = get_kiro_q_host(region)
        
        # Fingerprint for User-Agent
        self._fingerprint = get_machine_fingerprint()
        
        # Load credentials from file if specified
        if creds_file:
            self._load_credentials_from_file(creds_file)
    
    def _load_credentials_from_file(self, file_path: str) -> None:
        """
        Loads credentials from a JSON file.
        
        Supported JSON fields:
        - refreshToken: Refresh token
        - accessToken: Access token (if already available)
        - profileArn: Profile ARN
        - region: AWS region
        - expiresAt: Token expiration time (ISO 8601)
        
        Args:
            file_path: Path to JSON file
        """
        try:
            path = Path(file_path).expanduser()
            if not path.exists():
                logger.warning(f"Credentials file not found: {file_path}")
                return
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Load data from file
            if 'refreshToken' in data:
                self._refresh_token = data['refreshToken']
            if 'accessToken' in data:
                self._access_token = data['accessToken']
            if 'profileArn' in data:
                self._profile_arn = data['profileArn']
            if 'region' in data:
                self._region = data['region']
                # Update URLs for new region
                self._refresh_url = get_kiro_refresh_url(self._region)
                self._api_host = get_kiro_api_host(self._region)
                self._q_host = get_kiro_q_host(self._region)
            
            # Parse expiresAt
            if 'expiresAt' in data:
                try:
                    expires_str = data['expiresAt']
                    # Support for different date formats
                    if expires_str.endswith('Z'):
                        self._expires_at = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                    else:
                        self._expires_at = datetime.fromisoformat(expires_str)
                except Exception as e:
                    logger.warning(f"Failed to parse expiresAt: {e}")
            
            # Store auth method for fallback logic
            if 'authMethod' in data:
                self._auth_method = data['authMethod']
            
            logger.info(f"Credentials loaded from {file_path}")
            
        except Exception as e:
            logger.error(f"Error loading credentials from file: {e}")
    
    def _save_credentials_to_file(self) -> None:
        """
        Saves updated credentials to a JSON file.
        
        Updates the existing file while preserving other fields.
        """
        if not self._creds_file:
            return
        
        try:
            path = Path(self._creds_file).expanduser()
            
            # Read existing data
            existing_data = {}
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            
            # Update data
            existing_data['accessToken'] = self._access_token
            existing_data['refreshToken'] = self._refresh_token
            if self._expires_at:
                existing_data['expiresAt'] = self._expires_at.isoformat()
            if self._profile_arn:
                existing_data['profileArn'] = self._profile_arn
            
            # Save
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Credentials saved to {self._creds_file}")
            
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")
    
    def is_token_expiring_soon(self) -> bool:
        """
        Checks if the token is expiring soon.
        
        Returns:
            True if the token expires within TOKEN_REFRESH_THRESHOLD seconds
            or if expiration time information is not available
        """
        if not self._expires_at:
            return True  # If no expiration info available, assume refresh is needed
        
        now = datetime.now(timezone.utc)
        threshold = now.timestamp() + TOKEN_REFRESH_THRESHOLD
        
        return self._expires_at.timestamp() <= threshold
    
    async def _refresh_token_request(self) -> None:
        """
        Performs a token refresh request.
        
        Sends a POST request to Kiro API to obtain a new access token.
        Updates internal state and saves credentials to file.
        If 401 is received and IdC auth is used, falls back to IdC token refresh.
        
        Raises:
            ValueError: If refresh token is not set or response doesn't contain accessToken
            httpx.HTTPError: On HTTP request error
        """
        if not self._refresh_token:
            raise ValueError("Refresh token is not set")
        
        logger.info("Refreshing Kiro token...")
        
        payload = {'refreshToken': self._refresh_token}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"KiroIDE-0.7.45-{self._fingerprint}",
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._refresh_url, json=payload, headers=headers)
            
            # If 401 and using IdC auth, try IdC token refresh
            if response.status_code == 401 and self._auth_method == 'IdC' and self._idc_refresher:
                logger.warning("Kiro token refresh returned 401, attempting IdC token refresh...")
                try:
                    creds = await self._idc_refresher.refresh_token()
                    # IdC refresher already syncs to this auth manager via _sync_to_auth_manager
                    logger.info(f"IdC token refresh successful, expires: {creds.get('expiresAt', 'unknown')}")
                    return
                except Exception as e:
                    logger.error(f"IdC token refresh also failed: {e}")
                    raise httpx.HTTPStatusError(
                        f"Both Kiro and IdC token refresh failed: {e}",
                        request=response.request,
                        response=response
                    )
            
            response.raise_for_status()
            data = response.json()
        
        new_access_token = data.get("accessToken")
        new_refresh_token = data.get("refreshToken")
        expires_in = data.get("expiresIn", 3600)
        new_profile_arn = data.get("profileArn")
        
        if not new_access_token:
            raise ValueError(f"Response does not contain accessToken: {data}")
        
        # Update data
        self._access_token = new_access_token
        if new_refresh_token:
            self._refresh_token = new_refresh_token
        if new_profile_arn:
            self._profile_arn = new_profile_arn
        
        # Calculate expiration time with buffer (minus 60 seconds)
        self._expires_at = datetime.now(timezone.utc).replace(microsecond=0)
        self._expires_at = datetime.fromtimestamp(
            self._expires_at.timestamp() + expires_in - 60,
            tz=timezone.utc
        )
        
        logger.info(f"Token refreshed, expires: {self._expires_at.isoformat()}")
        
        # Save to file
        self._save_credentials_to_file()
    
    def set_idc_refresher(self, refresher) -> None:
        """
        Set reference to IdCTokenRefresher for fallback refresh.
        
        Args:
            refresher: IdCTokenRefresher instance
        """
        self._idc_refresher = refresher
    
    async def get_access_token(self) -> str:
        """
        Returns a valid access_token, refreshing it if necessary.
        
        Thread-safe method using asyncio.Lock.
        Automatically refreshes the token if it has expired or is about to expire.
        
        Returns:
            Valid access token
        
        Raises:
            ValueError: If unable to obtain access token
        """
        async with self._lock:
            if not self._access_token or self.is_token_expiring_soon():
                await self._refresh_token_request()
            
            if not self._access_token:
                raise ValueError("Failed to obtain access token")
            
            return self._access_token
    
    async def force_refresh(self) -> str:
        """
        Forces a token refresh.
        
        Used when receiving a 403 error from the API.
        
        Returns:
            New access token
        """
        async with self._lock:
            await self._refresh_token_request()
            return self._access_token
    
    @property
    def profile_arn(self) -> Optional[str]:
        """AWS CodeWhisperer profile ARN."""
        return self._profile_arn
    
    @property
    def region(self) -> str:
        """AWS region."""
        return self._region
    
    @property
    def api_host(self) -> str:
        """API host for the current region."""
        return self._api_host
    
    @property
    def q_host(self) -> str:
        """Q API host for the current region."""
        return self._q_host
    
    @property
    def fingerprint(self) -> str:
        """Unique machine fingerprint."""
        return self._fingerprint

    async def get_usage_limits(self) -> dict:
        """
        Fetch usage limits from Kiro Q API.
        
        Returns:
            Dictionary with usage data including:
            - daysUntilReset
            - nextDateReset
            - subscriptionInfo
            - userInfo
            - usageBreakdownList
        
        Raises:
            httpx.HTTPError: On HTTP request error
            ValueError: If unable to obtain access token
        """
        token = await self.get_access_token()
        
        url = f"{self._q_host}/getUsageLimits"
        params = {
            "isEmailRequired": "true",
            "origin": "AI_EDITOR",
            "resourceType": "AGENTIC_REQUEST",
        }
        if self._profile_arn:
            params["profileArn"] = self._profile_arn
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"aws-sdk-js/1.0.27 ua/2.1 os/linux lang/py api/codewhispererruntime#1.0.27 m/E KiroIDE-0.7.45-{self._fingerprint}",
            "x-amz-user-agent": f"aws-sdk-js/1.0.27 KiroIDE-0.7.45-{self._fingerprint}",
            "amz-sdk-request": "attempt=1; max=1",
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params, headers=headers)
            
            # If 403, try refreshing token and retry once
            if response.status_code == 403:
                logger.warning("Received 403 on getUsageLimits, refreshing token...")
                token = await self.force_refresh()
                headers["Authorization"] = f"Bearer {token}"
                response = await client.get(url, params=params, headers=headers)
            
            response.raise_for_status()
            return response.json()