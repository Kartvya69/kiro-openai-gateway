# -*- coding: utf-8 -*-

"""
Database module for Kiro Gateway.

Provides SQLAlchemy async engine, session factory, and ORM models
for storing Kiro accounts in PostgreSQL.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from loguru import logger

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""
    pass


class KiroAccount(Base):
    """
    Kiro account model for storing authentication credentials.
    
    Attributes:
        id: Primary key
        name: User-friendly account name
        auth_method: Authentication method (social, builder-id, IdC)
        provider: OAuth provider (Google, Github, AWS)
        access_token: Current access token
        refresh_token: Refresh token for obtaining new access tokens
        profile_arn: AWS CodeWhisperer profile ARN
        region: AWS region
        expires_at: Token expiration time
        created_at: Account creation time
        updated_at: Last update time
        last_used_at: Last time account was used for a request
        is_active: Whether account is active
        request_count: Total requests made with this account
        extra_data: Additional data (client_id, client_secret for IdC, etc.)
    """
    __tablename__ = "kiro_accounts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    auth_method = Column(String(50))  # "social", "builder-id", "IdC"
    provider = Column(String(50))  # "Google", "Github", "AWS"
    
    # Credentials
    access_token = Column(Text)
    refresh_token = Column(Text)
    profile_arn = Column(String(500))
    region = Column(String(50), default="us-east-1")
    
    # Token management
    expires_at = Column(DateTime(timezone=True))
    
    # Metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True))
    
    # Status
    is_active = Column(Boolean, default=True)
    request_count = Column(Integer, default=0)
    
    # Extra data (for IdC client_id, client_secret, etc.)
    extra_data = Column(JSON, default=dict)
    
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


# Global engine and session factory (initialized in init_database)
_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


async def init_database() -> async_sessionmaker[AsyncSession]:
    """
    Initialize database connection and create tables.
    
    Returns:
        Async session factory for creating database sessions
    """
    global _engine, _session_factory
    
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    logger.info("Initializing database connection...")
    
    _engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    
    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    logger.info("Database initialized successfully")
    return _session_factory


async def close_database() -> None:
    """Close database connection."""
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database connection closed")


def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    """Get the session factory (must call init_database first)."""
    return _session_factory
