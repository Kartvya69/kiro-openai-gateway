# -*- coding: utf-8 -*-

"""
Account Manager for Kiro Gateway.

Manages multiple Kiro accounts with PostgreSQL storage and load balancing.
Provides round-robin account selection and automatic token refresh.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.database import KiroAccount
from kiro_gateway.config import TOKEN_REFRESH_THRESHOLD


class AccountManager:
    """
    Manages multiple Kiro accounts with PostgreSQL storage and load balancing.
    
    Features:
    - Load accounts from PostgreSQL database
    - Round-robin load balancing across accounts
    - Automatic token refresh for expiring tokens
    - Health-aware account selection (skip invalid tokens)
    """
    
    REFRESH_INTERVAL = 300  # Check for token refresh every 5 minutes
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        Initialize AccountManager.
        
        Args:
            session_factory: SQLAlchemy async session factory
        """
        self.session_factory = session_factory
        self._auth_managers: Dict[int, KiroAuthManager] = {}
        self._account_ids: List[int] = []
        self._current_index = 0
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
    
    async def load_accounts(self) -> int:
        """
        Load all active accounts from database.
        
        Returns:
            Number of accounts loaded
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount).where(KiroAccount.is_active == True)
            )
            accounts = result.scalars().all()
        
        async with self._lock:
            self._auth_managers.clear()
            self._account_ids.clear()
            
            for account in accounts:
                auth_manager = self._create_auth_manager(account)
                self._auth_managers[account.id] = auth_manager
                self._account_ids.append(account.id)
            
            self._current_index = 0
        
        logger.info(f"Loaded {len(accounts)} accounts from database")
        return len(accounts)
    
    def _create_auth_manager(self, account: KiroAccount) -> KiroAuthManager:
        """Create a KiroAuthManager from account data."""
        auth_manager = KiroAuthManager(
            refresh_token=account.refresh_token,
            profile_arn=account.profile_arn,
            region=account.region or "us-east-1",
        )
        # Set access token directly if available
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
    ) -> KiroAccount:
        """
        Add a new account to database.
        
        Args:
            name: User-friendly account name
            auth_method: Authentication method (social, builder-id, IdC)
            provider: OAuth provider (Google, Github, AWS)
            access_token: Access token
            refresh_token: Refresh token
            profile_arn: AWS profile ARN
            region: AWS region
            expires_at: Token expiration time
            extra_data: Additional data
        
        Returns:
            Created KiroAccount
        """
        account = KiroAccount(
            name=name,
            auth_method=auth_method,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            profile_arn=profile_arn,
            region=region,
            expires_at=expires_at,
            extra_data=extra_data or {},
            is_active=True,
            request_count=0,
        )
        
        async with self.session_factory() as session:
            session.add(account)
            await session.commit()
            await session.refresh(account)
        
        # Add to in-memory cache
        async with self._lock:
            auth_manager = self._create_auth_manager(account)
            self._auth_managers[account.id] = auth_manager
            self._account_ids.append(account.id)
        
        logger.info(f"Added account: {name} (id={account.id}, method={auth_method})")
        return account
    
    async def remove_account(self, account_id: int) -> bool:
        """
        Remove an account from database.
        
        Args:
            account_id: Account ID to remove
        
        Returns:
            True if account was removed
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount).where(KiroAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
            
            if not account:
                return False
            
            await session.delete(account)
            await session.commit()
        
        # Remove from in-memory cache
        async with self._lock:
            if account_id in self._auth_managers:
                del self._auth_managers[account_id]
            if account_id in self._account_ids:
                self._account_ids.remove(account_id)
                # Reset index if needed
                if self._current_index >= len(self._account_ids):
                    self._current_index = 0
        
        logger.info(f"Removed account id={account_id}")
        return True
    
    async def get_next_account(self) -> Optional[KiroAuthManager]:
        """
        Get next healthy account using round-robin.
        
        Returns:
            KiroAuthManager for the next account, or None if no accounts available
        """
        async with self._lock:
            if not self._account_ids:
                return None
            
            # Try each account once
            attempts = len(self._account_ids)
            for _ in range(attempts):
                account_id = self._account_ids[self._current_index]
                self._current_index = (self._current_index + 1) % len(self._account_ids)
                
                auth_manager = self._auth_managers.get(account_id)
                if auth_manager:
                    # Update last used and request count
                    asyncio.create_task(self._update_account_usage(account_id))
                    return auth_manager
            
            return None
    
    async def _update_account_usage(self, account_id: int) -> None:
        """Update account usage statistics."""
        try:
            async with self.session_factory() as session:
                await session.execute(
                    update(KiroAccount)
                    .where(KiroAccount.id == account_id)
                    .values(
                        last_used_at=datetime.now(timezone.utc),
                        request_count=KiroAccount.request_count + 1,
                    )
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to update account usage: {e}")
    
    async def list_accounts(self) -> List[dict]:
        """
        List all accounts with status.
        
        Returns:
            List of account dictionaries
        """
        async with self.session_factory() as session:
            result = await session.execute(select(KiroAccount))
            accounts = result.scalars().all()
        
        return [
            {
                **account.to_dict(),
                "status": self._get_account_status(account),
            }
            for account in accounts
        ]
    
    def _get_account_status(self, account: KiroAccount) -> str:
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
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount).where(KiroAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
        
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
        """
        Update account properties.
        
        Args:
            account_id: Account ID
            name: New account name (optional)
            is_active: New active status (optional)
        
        Returns:
            True if updated successfully
        """
        update_values = {"updated_at": datetime.now(timezone.utc)}
        
        if name is not None:
            update_values["name"] = name
        if is_active is not None:
            update_values["is_active"] = is_active
        
        async with self.session_factory() as session:
            await session.execute(
                update(KiroAccount)
                .where(KiroAccount.id == account_id)
                .values(**update_values)
            )
            await session.commit()
        
        # Update in-memory cache if is_active changed
        if is_active is not None:
            async with self._lock:
                if is_active:
                    # Re-add to account_ids if not present
                    if account_id not in self._account_ids and account_id in self._auth_managers:
                        self._account_ids.append(account_id)
                else:
                    # Remove from account_ids
                    if account_id in self._account_ids:
                        self._account_ids.remove(account_id)
                        if self._current_index >= len(self._account_ids):
                            self._current_index = 0
        
        logger.info(f"Updated account id={account_id}: {update_values}")
        return True
    
    async def update_account_tokens(
        self,
        account_id: int,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        profile_arn: Optional[str] = None,
    ) -> bool:
        """
        Update account tokens after refresh.
        
        Args:
            account_id: Account ID
            access_token: New access token
            refresh_token: New refresh token (optional)
            expires_at: New expiration time
            profile_arn: Profile ARN (optional)
        
        Returns:
            True if updated successfully
        """
        update_values = {
            "access_token": access_token,
            "updated_at": datetime.now(timezone.utc),
        }
        if refresh_token:
            update_values["refresh_token"] = refresh_token
        if expires_at:
            update_values["expires_at"] = expires_at
        if profile_arn:
            update_values["profile_arn"] = profile_arn
        
        async with self.session_factory() as session:
            await session.execute(
                update(KiroAccount)
                .where(KiroAccount.id == account_id)
                .values(**update_values)
            )
            await session.commit()
        
        # Update in-memory cache
        async with self._lock:
            if account_id in self._auth_managers:
                auth_manager = self._auth_managers[account_id]
                auth_manager._access_token = access_token
                if refresh_token:
                    auth_manager._refresh_token = refresh_token
                if expires_at:
                    auth_manager._expires_at = expires_at
                if profile_arn:
                    auth_manager._profile_arn = profile_arn
        
        return True
    
    async def refresh_account_token(self, account_id: int) -> tuple[bool, str]:
        """
        Refresh token for a specific account.
        
        For 'social' auth (Builder ID via social login): Uses Kiro's refresh endpoint
        For other auth methods (IdC, builder-id): Uses AWS SSO OIDC refresh
        
        Args:
            account_id: Account ID to refresh
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Get account info
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount).where(KiroAccount.id == account_id)
            )
            account = result.scalar_one_or_none()
        
        if not account:
            return False, "Account not found"
        
        # If client credentials are present, use AWS SSO OIDC refresh
        # This handles cases where auth_method is "social" but credentials were created via Builder ID
        if account.client_id and account.client_secret:
            logger.debug(f"Using IdC refresh for account id={account.id} (has client credentials)")
            return await self._refresh_idc_token(account)
        
        # 'social' auth without client credentials uses Kiro's refresh endpoint
        if account.auth_method == "social":
            return await self._refresh_social_token(account)
        
        # Other auth methods (IdC, builder-id) use AWS SSO OIDC refresh
        # but they require client credentials
        return False, "Missing client credentials. Please re-authenticate."
    
    async def _refresh_social_token(self, account: KiroAccount) -> tuple[bool, str]:
        """
        Refresh token using Kiro's refresh endpoint (for social auth accounts).
        
        Args:
            account: KiroAccount instance
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not account.refresh_token:
            return False, "No refresh token available"
        
        region = account.region or "us-east-1"
        refresh_url = f"https://prod.{region}.auth.desktop.kiro.dev/refreshToken"
        
        payload = {
            "refreshToken": account.refresh_token,
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    refresh_url,
                    json=payload,
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
            
            # Calculate expiration
            expires_at = datetime.now(timezone.utc)
            expires_at = datetime.fromtimestamp(
                expires_at.timestamp() + expires_in,
                tz=timezone.utc
            )
            
            # Update database
            await self.update_account_tokens(
                account.id,
                new_access_token,
                new_refresh_token or account.refresh_token,
                expires_at,
                new_profile_arn or account.profile_arn,
            )
            
            # Update auth manager if exists
            auth_manager = self._auth_managers.get(account.id)
            if auth_manager:
                auth_manager._access_token = new_access_token
                if new_refresh_token:
                    auth_manager._refresh_token = new_refresh_token
                auth_manager._expires_at = expires_at
                if new_profile_arn:
                    auth_manager._profile_arn = new_profile_arn
            
            logger.info(f"Social token refreshed for account id={account.id}, expires: {expires_at.isoformat()}")
            return True, "Token refreshed successfully"
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Social token refresh HTTP error for account id={account.id}: {e}")
            if e.response.status_code == 401:
                return False, "Refresh token expired. Please re-authenticate."
            return False, f"HTTP error: {e.response.status_code}"
        except Exception as e:
            logger.error(f"Social token refresh failed for account id={account.id}: {e}")
            return False, f"Refresh failed: {str(e)}"
    
    async def _refresh_idc_token(self, account: KiroAccount) -> tuple[bool, str]:
        """
        Refresh token using AWS SSO OIDC API (for Builder ID and IdC accounts).
        
        Args:
            account: KiroAccount instance
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not account.refresh_token:
            return False, "No refresh token available"
        
        if not account.client_id or not account.client_secret:
            return False, "Missing client credentials. Please re-authenticate."
        
        region = account.region or "us-east-1"
        token_url = f"https://oidc.{region}.amazonaws.com/token"
        
        payload = {
            "clientId": account.client_id,
            "clientSecret": account.client_secret,
            "grantType": "refresh_token",
            "refreshToken": account.refresh_token,
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    token_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                data = response.json()
            
            new_access_token = data.get("accessToken")
            new_refresh_token = data.get("refreshToken")
            expires_in = data.get("expiresIn", 3600)
            
            if not new_access_token:
                return False, "No access token in response"
            
            # Calculate expiration
            expires_at = datetime.now(timezone.utc)
            expires_at = datetime.fromtimestamp(
                expires_at.timestamp() + expires_in,
                tz=timezone.utc
            )
            
            # Update database
            await self.update_account_tokens(
                account.id,
                new_access_token,
                new_refresh_token or account.refresh_token,
                expires_at,
                account.profile_arn,
            )
            
            # Update auth manager if exists
            auth_manager = self._auth_managers.get(account.id)
            if auth_manager:
                auth_manager._access_token = new_access_token
                if new_refresh_token:
                    auth_manager._refresh_token = new_refresh_token
                auth_manager._expires_at = expires_at
            
            logger.info(f"IdC token refreshed for account id={account.id}, expires: {expires_at.isoformat()}")
            return True, "Token refreshed successfully"
            
        except httpx.HTTPStatusError as e:
            logger.error(f"IdC token refresh HTTP error for account id={account.id}: {e}")
            if e.response.status_code == 401:
                return False, "Refresh token expired. Please re-authenticate."
            return False, f"HTTP error: {e.response.status_code}"
        except Exception as e:
            logger.error(f"IdC token refresh failed for account id={account.id}: {e}")
            return False, f"Refresh failed: {str(e)}"
    
    async def refresh_all_tokens(self, force: bool = False) -> int:
        """
        Refresh tokens for all accounts.
        
        Args:
            force: If True, refresh all tokens regardless of expiration.
                   If False, only refresh tokens expiring soon.
        
        Returns:
            Number of tokens refreshed
        """
        refreshed = 0
        
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount).where(KiroAccount.is_active == True)
            )
            accounts = result.scalars().all()
        
        for account in accounts:
            if force or account.is_token_expiring_soon(TOKEN_REFRESH_THRESHOLD):
                try:
                    success, message = await self.refresh_account_token(account.id)
                    if success:
                        refreshed += 1
                        logger.info(f"Refreshed token for account id={account.id}")
                    else:
                        logger.warning(f"Failed to refresh token for account id={account.id}: {message}")
                except Exception as e:
                    logger.error(f"Failed to refresh token for account id={account.id}: {e}")
        
        return refreshed
    
    async def _auto_refresh_loop(self) -> None:
        """Background task to auto-refresh tokens."""
        # Refresh immediately on startup
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
            logger.info("Started auto-refresh background task")
    
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
        async with self.session_factory() as session:
            result = await session.execute(
                select(KiroAccount)
            )
            accounts = result.scalars().all()
        
        return sum(account.request_count for account in accounts)
