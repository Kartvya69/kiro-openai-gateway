# -*- coding: utf-8 -*-

"""
API Keys management for Kiro Gateway.

Provides multi-key authentication system with local JSON storage.
"""

import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


DEFAULT_API_KEYS_FILE = "api_keys.json"


def generate_api_key(prefix: str = "sk-") -> str:
    """Generate an OpenAI-style API key."""
    chars = string.ascii_letters + string.digits
    random_part = ''.join(secrets.choice(chars) for _ in range(48))
    return f"{prefix}{random_part}"


class APIKey:
    """API Key model."""
    
    def __init__(
        self,
        key: str,
        name: str,
        created_at: Optional[datetime] = None,
        last_used_at: Optional[datetime] = None,
        is_active: bool = True,
        request_count: int = 0,
    ):
        self.key = key
        self.name = name
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_used_at = last_used_at
        self.is_active = is_active
        self.request_count = request_count
    
    def to_dict(self, mask_key: bool = True) -> dict:
        """Convert to dictionary."""
        key_display = self.key
        if mask_key and len(self.key) > 8:
            key_display = self.key[:7] + "..." + self.key[-4:]
        
        return {
            "key": key_display,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_active": self.is_active,
            "request_count": self.request_count,
        }
    
    def to_storage_dict(self) -> dict:
        """Convert to storage dictionary (includes full key)."""
        return {
            "key": self.key,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_active": self.is_active,
            "request_count": self.request_count,
        }
    
    @classmethod
    def from_storage_dict(cls, data: dict) -> "APIKey":
        """Create from storage dictionary."""
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
            key=data.get("key", ""),
            name=data.get("name", "Unnamed Key"),
            created_at=parse_datetime(data.get("created_at")),
            last_used_at=parse_datetime(data.get("last_used_at")),
            is_active=data.get("is_active", True),
            request_count=data.get("request_count", 0),
        )


class APIKeyManager:
    """
    Manages API keys with local JSON storage.
    """
    
    def __init__(self, storage_file: str = DEFAULT_API_KEYS_FILE):
        self.storage_file = Path(storage_file)
        self._keys: Dict[str, APIKey] = {}  # key -> APIKey
        self._load_from_file()
    
    def _save_to_file(self) -> None:
        """Save keys to JSON file."""
        try:
            data = {
                "keys": [key.to_storage_dict() for key in self._keys.values()]
            }
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._keys)} API keys to {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to save API keys: {e}")
    
    def _load_from_file(self) -> None:
        """Load keys from JSON file."""
        if not self.storage_file.exists():
            # Create default keys on first run
            self._create_default_keys()
            return
        
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            keys_data = data.get("keys", [])
            for key_data in keys_data:
                api_key = APIKey.from_storage_dict(key_data)
                self._keys[api_key.key] = api_key
            
            logger.info(f"Loaded {len(self._keys)} API keys from {self.storage_file}")
            
            # Create default keys if none exist
            if not self._keys:
                self._create_default_keys()
                
        except Exception as e:
            logger.error(f"Failed to load API keys: {e}")
            self._create_default_keys()
    
    def _create_default_keys(self) -> None:
        """Create default API keys on first run."""
        logger.info("Creating default API keys...")
        
        # Create 2 default keys
        key1 = self.create_key("Default Key 1")
        key2 = self.create_key("Default Key 2")
        
        logger.info("=" * 60)
        logger.info("  AUTO-GENERATED API KEYS")
        logger.info("=" * 60)
        logger.info(f"  Key 1: {key1.key}")
        logger.info(f"  Key 2: {key2.key}")
        logger.info("=" * 60)
        logger.info("  Use these keys as 'api_key' when connecting clients")
        logger.info("  You can manage keys in the WebUI at /ui -> API Keys")
        logger.info("=" * 60)
    
    def create_key(self, name: str) -> APIKey:
        """Create a new API key."""
        key_str = generate_api_key("sk-")
        api_key = APIKey(key=key_str, name=name)
        self._keys[key_str] = api_key
        self._save_to_file()
        logger.info(f"Created API key: {name}")
        return api_key
    
    def delete_key(self, key: str) -> bool:
        """Delete an API key."""
        if key in self._keys:
            del self._keys[key]
            self._save_to_file()
            logger.info(f"Deleted API key")
            return True
        return False
    
    def get_key(self, key: str) -> Optional[APIKey]:
        """Get an API key by its value."""
        return self._keys.get(key)
    
    def validate_key(self, key: str) -> bool:
        """Validate an API key and update usage stats."""
        api_key = self._keys.get(key)
        if not api_key:
            return False
        if not api_key.is_active:
            return False
        
        # Update usage stats
        api_key.last_used_at = datetime.now(timezone.utc)
        api_key.request_count += 1
        self._save_to_file()
        return True
    
    def list_keys(self, mask: bool = True) -> List[dict]:
        """List all API keys."""
        return [key.to_dict(mask_key=mask) for key in self._keys.values()]
    
    def update_key(self, key: str, name: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        """Update an API key."""
        api_key = self._keys.get(key)
        if not api_key:
            return False
        
        if name is not None:
            api_key.name = name
        if is_active is not None:
            api_key.is_active = is_active
        
        self._save_to_file()
        return True
    
    def get_key_by_prefix(self, prefix: str) -> Optional[APIKey]:
        """Find a key by its prefix (for display purposes)."""
        for key, api_key in self._keys.items():
            if key.startswith(prefix):
                return api_key
        return None
    
    @property
    def key_count(self) -> int:
        """Get number of keys."""
        return len(self._keys)
    
    @property
    def active_key_count(self) -> int:
        """Get number of active keys."""
        return sum(1 for k in self._keys.values() if k.is_active)


# Global instance
_api_key_manager: Optional[APIKeyManager] = None


def get_api_key_manager() -> APIKeyManager:
    """Get or create the global API key manager."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager


def validate_api_key(key: str) -> bool:
    """Validate an API key (convenience function)."""
    return get_api_key_manager().validate_key(key)
