# -*- coding: utf-8 -*-

"""
Local Storage module for Kiro Gateway.

Provides JSON file-based storage as fallback when DATABASE_URL is not set.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger

from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.config import TOKEN_REFRESH_THRESHOLD


DEFAULT_ACCOUNTS_FILE = "accounts.json"


class LocalAccount:
    """
    Local account model (mirrors KiroAccount from database.py).
    """
    
    def __init__(
        self,
        id: int,
        name: str,
        auth_method: Optional[str] = None,
        provider: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
        expires_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_used_at: Optional[datetime] = None,
        is_active: bool = True,
        request_count: int = 0,
        extra_data: Optional[dict] = None,
    ):
        self.id = id
        self.name = name
        self.auth_method = auth_method
        self.provider = provider
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.profile_arn = profile_arn
        self.region = region
        self.expires_at = expires_at
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at
        self.last_used_at = last_used_at
        self.is_active = is_active
        self.request_count = request_count
        self.extra_data = extra_data or {}
    
    def to_dict(self) -> dict:
        """Convert account to dictionary (without sensitive data)."""
        return {
            "id": self.id,
            "name": self.name,
            "auth_method": self.auth_method,
            "provider": self.provider,
            "region": self.region,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_active": self.is_active,
            "request_count": self.request_count,
        }
    
    def to_storage_dict(self) -> dict:
        """Convert account to dictionary for storage (includes sensitive data)."""
        return {
            "id": self.id,
            "name": self.name,
            "auth_method": self.auth_method,
            "provider": self.provider,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "profile_arn": self.profile_arn,
            "region": self.region,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_active": self.is_active,
            "request_count": self.request_count,
            "extra_data": self.extra_data,
        }
    
    @classmethod
    def from_storage_dict(cls, data: dict) -> "LocalAccount":
        """Create account from storage dictionary."""
        def parse_datetime(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val
            try:
                if val.endswith('Z'):
                    return datetime.fromisoformat(val.replace('Z', '+00:00'))
                return datetime.fromisoformat(val)
            except:
                return None
        
        return cls(
            id=data.get("id", 0),
            name=data.get("name", "Unknown"),
            auth_method=data.get("auth_method"),
            provider=data.get("provider"),
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            profile_arn=data.get("profile_arn"),
            region=data.get("region", "us-east-1"),
            expires_at=parse_datetime(data.get("expires_at")),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
            last_used_at=parse_datetime(data.get("last_used_at")),
            is_active=data.get("is_active", True),
            request_count=data.get("request_count", 0),
            extra_data=data.get("extra_data", {}),
        )
    
    def is_token_valid(self) -> bool:
        """Check if the token is still valid."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) < self.expires_at
    
    def is_token_expiring_soon(self, threshold_seconds: int = 600) -> bool:
        """Check if the token is expiring within threshold."""
        if not self.expires_at:
            return True
        now = datetime.now(timezone.utc)
        return (self.expires_at.timestamp() - now.timestamp()) <= threshold_seconds
    
    @property
    def client_id(self) -> Optional[str]:
        """Get client_id from extra_data."""
        if not self.extra_data:
            return None
        return self.extra_data.get("clientId") or self.extra_data.get("client_id")
    
    @property
    def client_secret(self) -> Optional[str]:
        """Get client_secret from extra_data."""
        if not self.extra_data:
            return None
        return self.extra_data.get("clientSecret") or self.extra_data.get("client_secret")


class LocalAccountManager:
    """
    Manages Kiro accounts with local JSON file storage.
    
    Drop-in replacement for AccountManager when DATABASE_URL is not set.
    """
    
    REFRESH_INTERVAL = 300
    
    def __init__(self, storage_file: str = DEFAULT_ACCOUNTS_FILE):
        """
        Initialize LocalAccountManager.
        
        Args:
            storage_file: Path to JSON file for storing accounts
        """
        self.storage_file = Path(storage_file)
        self._accounts: Dict[int, LocalAccount] = {}
        self._auth_managers: Dict[int, KiroAuthManager] = {}
        self._account_ids: List[int] = []
        self._current_index = 0
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
    
    def _save_to_file(self) -> None:
        """Save accounts to JSON file."""
        try:
            data = {
                "next_id": self._next_id,
                "accounts": [acc.to_storage_dict() for acc in self._accounts.values()]
            }
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._accounts)} accounts to {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to save accounts to file: {e}")
    
    def _load_from_file(self) -> None:
        """Load accounts from JSON file."""
        if not self.storage_file.exists():
            logger.info(f"No accounts file found at {self.storage_file}, starting fresh")
            return
        
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._next_id = data.get("next_id", 1)
            accounts_data = data.get("accounts", [])
            
            for acc_data in accounts_data:
                account = LocalAccount.from_storage_dict(acc_data)
                self._accounts[account.id] = account
                if account.is_active:
                    self._account_ids.append(account.id)
                    auth_manager = self._create_auth_manager(account)
                    self._auth_managers[account.id] = auth_manager
                if account.id >= self._next_id:
                    self._next_id = account.id + 1
            
            logger.info(f"Loaded {len(self._accounts)} accounts from {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to load accounts from file: {e}")
    
    async def load_accounts(self) -> int:
        """Load all active accounts from file."""
        async with self._lock:
            self._accounts.clear()
            self._auth_managers.clear()
            self._account_ids.clear()
            self._load_from_file()
        
        logger.info(f"Loaded {len(self._account_ids)} active accounts from local storage")
        return len(self._account_ids)
    
    def _create_auth_manager(self, account: LocalAccount) -> KiroAuthManager:
        """Create a KiroAuthManager from account data."""
        auth_manager = KiroAuthManager(
            refresh_token=account.refresh_token,
            profile_arn=account.profile_arn,
            region=account.region or "us-east-1",
        )
        if account.access_token:
            auth_manager._access_token = account.access_token
        if account.expires_at:
            auth_manager._expires_at = account.expires_at
        return auth_manager
    
    async def add_account(
        self,
        name: str,
        auth_method: str,
        provider: Optional[str],
        access_token: str,
        refresh_token: str,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
        expires_at: Optional[datetime] = None,
        extra_data: Optional[dict] = None,
    ) -> LocalAccount:
        """Add a new account."""
        async with self._lock:
            account = LocalAccount(
                id=self._next_id,
                name=name,
                auth_method=auth_method,
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                profile_arn=profile_arn,
                region=region,
                expires_at=expires_at,
                extra_data=extra_data or {},
            )
            self._next_id += 1
            
            self._accounts[account.id] = account
            self._account_ids.append(account.id)
            
            auth_manager = self._create_auth_manager(account)
            self._auth_managers[account.id] = auth_manager
            
            self._save_to_file()
        
        logger.info(f"Added account: {name} (id={account.id}, method={auth_method})")
        return account
    
    async def remove_account(self, account_id: int) -> bool:
        """Remove an account."""
        async with self._lock:
            if account_id not in self._accounts:
                return False
            
            del self._accounts[account_id]
            if account_id in self._auth_managers:
                del self._auth_managers[account_id]
            if account_id in self._account_ids:
                self._account_ids.remove(account_id)
                if self._current_index >= len(self._account_ids):
                    self._current_index = 0
            
            self._save_to_file()
        
        logger.info(f"Removed account id={account_id}")
        return True
    
    async def get_next_account(self) -> Optional[KiroAuthManager]:
        """Get next healthy account using round-robin."""
        async with self._lock:
            if not self._account_ids:
                return None
            
            attempts = len(self._account_ids)
            for _ in range(attempts):
                account_id = self._account_ids[self._current_index]
                self._current_index = (self._current_index + 1) % len(self._account_ids)
                
                auth_manager = self._auth_managers.get(account_id)
                if auth_manager:
                    asyncio.create_task(self._update_account_usage(account_id))
                    return auth_manager
            
            return None
    
    async def _update_account_usage(self, account_id: int) -> None:
        """Update account usage statistics."""
        async with self._lock:
            if account_id in self._accounts:
                account = self._accounts[account_id]
                account.last_used_at = datetime.now(timezone.utc)
                account.request_count += 1
                self._save_to_file()
    
    async def list_accounts(self) -> List[dict]:
        """List all accounts with status."""
        async with self._lock:
            return [
                {
                    **account.to_dict(),
                    "status": self._get_account_status(account),
                }
                for account in self._accounts.values()
            ]
    
    def _get_account_status(self, account: LocalAccount) -> str:
        """Get human-readable account status."""
        if not account.is_active:
            return "inactive"
        if not account.access_token:
            return "no_token"
        if not account.is_token_valid():
            return "expired"
        if account.is_token_expiring_soon():
            return "expiring_soon"
        return "healthy"
    
    async def get_account(self, account_id: int) -> Optional[dict]:
        """Get a single account by ID."""
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return None
            return {
                **account.to_dict(),
                "status": self._get_account_status(account),
            }
    
    async def update_account(
        self,
        account_id: int,
        name: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update account properties."""
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return False
            
            if name is not None:
                account.name = name
            if is_active is not None:
                account.is_active = is_active
                if is_active:
                    if account_id not in self._account_ids:
                        self._account_ids.append(account_id)
                        self._auth_managers[account_id] = self._create_auth_manager(account)
                else:
                    if account_id in self._account_ids:
                        self._account_ids.remove(account_id)
                    if account_id in self._auth_managers:
                        del self._auth_managers[account_id]
                    if self._current_index >= len(self._account_ids):
                        self._current_index = 0
            
            account.updated_at = datetime.now(timezone.utc)
            self._save_to_file()
        
        logger.info(f"Updated account id={account_id}")
        return True
    
    async def update_account_tokens(
        self,
        account_id: int,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        profile_arn: Optional[str] = None,
    ) -> bool:
        """Update account tokens after refresh."""
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return False
            
            account.access_token = access_token
            if refresh_token:
                account.refresh_token = refresh_token
            if expires_at:
                account.expires_at = expires_at
            if profile_arn:
                account.profile_arn = profile_arn
            account.updated_at = datetime.now(timezone.utc)
            
            # Update auth manager
            if account_id in self._auth_managers:
                auth_manager = self._auth_managers[account_id]
                auth_manager._access_token = access_token
                if refresh_token:
                    auth_manager._refresh_token = refresh_token
                if expires_at:
                    auth_manager._expires_at = expires_at
                if profile_arn:
                    auth_manager._profile_arn = profile_arn
            
            self._save_to_file()
        
        return True
    
    async def refresh_account_token(self, account_id: int) -> tuple[bool, str]:
        """Refresh token for a specific account."""
        import httpx
        
        async with self._lock:
            account = self._accounts.get(account_id)
        
        if not account:
            return False, "Account not found"
        
        if account.client_id and account.client_secret:
            return await self._refresh_idc_token(account)
        
        if account.auth_method == "social":
            return await self._refresh_social_token(account)
        
        return False, "Missing client credentials. Please re-authenticate."
    
    async def _refresh_social_token(self, account: LocalAccount) -> tuple[bool, str]:
        """Refresh token using Kiro's refresh endpoint."""
        import httpx
        
        if not account.refresh_token:
            return False, "No refresh token available"
        
        region = account.region or "us-east-1"
        refresh_url = f"https://prod.{region}.auth.desktop.kiro.dev/refreshToken"
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    refresh_url,
                    json={"refreshToken": account.refresh_token},
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                data = response.json()
            
            new_access_token = data.get("accessToken")
            new_refresh_token = data.get("refreshToken")
            new_profile_arn = data.get("profileArn")
            expires_in = data.get("expiresIn", 3600)
            
            if not new_access_token:
                return False, "No access token in response"
            
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + expires_in,
                tz=timezone.utc
            )
            
            await self.update_account_tokens(
                account.id,
                new_access_token,
                new_refresh_token or account.refresh_token,
                expires_at,
                new_profile_arn or account.profile_arn,
            )
            
            logger.info(f"Social token refreshed for account id={account.id}")
            return True, "Token refreshed successfully"
            
        except Exception as e:
            logger.error(f"Social token refresh failed: {e}")
            return False, f"Refresh failed: {str(e)}"
    
    async def _refresh_idc_token(self, account: LocalAccount) -> tuple[bool, str]:
        """Refresh token using AWS SSO OIDC API."""
        import httpx
        
        if not account.refresh_token:
            return False, "No refresh token available"
        
        if not account.client_id or not account.client_secret:
            return False, "Missing client credentials"
        
        region = account.region or "us-east-1"
        token_url = f"https://oidc.{region}.amazonaws.com/token"
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    token_url,
                    json={
                        "clientId": account.client_id,
                        "clientSecret": account.client_secret,
                        "grantType": "refresh_token",
                        "refreshToken": account.refresh_token,
                    },
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                data = response.json()
            
            new_access_token = data.get("accessToken")
            new_refresh_token = data.get("refreshToken")
            expires_in = data.get("expiresIn", 3600)
            
            if not new_access_token:
                return False, "No access token in response"
            
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + expires_in,
                tz=timezone.utc
            )
            
            await self.update_account_tokens(
                account.id,
                new_access_token,
                new_refresh_token or account.refresh_token,
                expires_at,
                account.profile_arn,
            )
            
            logger.info(f"IdC token refreshed for account id={account.id}")
            return True, "Token refreshed successfully"
            
        except Exception as e:
            logger.error(f"IdC token refresh failed: {e}")
            return False, f"Refresh failed: {str(e)}"
    
    async def refresh_all_tokens(self, force: bool = False) -> int:
        """Refresh tokens for all accounts."""
        refreshed = 0
        
        async with self._lock:
            accounts = list(self._accounts.values())
        
        for account in accounts:
            if account.is_active and (force or account.is_token_expiring_soon(TOKEN_REFRESH_THRESHOLD)):
                try:
                    success, _ = await self.refresh_account_token(account.id)
                    if success:
                        refreshed += 1
                except Exception as e:
                    logger.error(f"Failed to refresh token for account id={account.id}: {e}")
        
        return refreshed
    
    async def _auto_refresh_loop(self) -> None:
        """Background task to auto-refresh tokens."""
        try:
            refreshed = await self.refresh_all_tokens()
            if refreshed > 0:
                logger.info(f"Initial auto-refresh: refreshed {refreshed} tokens")
        except Exception as e:
            logger.error(f"Error in initial auto-refresh: {e}")
        
        while True:
            try:
                await asyncio.sleep(self.REFRESH_INTERVAL)
                refreshed = await self.refresh_all_tokens()
                if refreshed > 0:
                    logger.info(f"Auto-refreshed {refreshed} tokens")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-refresh loop: {e}")
    
    def start_auto_refresh(self) -> None:
        """Start background task to auto-refresh tokens."""
        if self._refresh_task is None:
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
            logger.info("Started auto-refresh background task (local storage)")
    
    def stop_auto_refresh(self) -> None:
        """Stop background refresh task."""
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None
            logger.info("Stopped auto-refresh background task")
    
    @property
    def account_count(self) -> int:
        """Get number of loaded accounts."""
        return len(self._account_ids)
    
    async def get_total_requests(self) -> int:
        """Get total request count across all accounts."""
        async with self._lock:
            return sum(acc.request_count for acc in self._accounts.values())
