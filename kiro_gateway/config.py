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
Kiro Gateway Configuration.

Centralized storage for all settings, constants, and mappings.
Loads configuration from YAML file and provides typed access to them.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _load_yaml_config(config_file: str = "config.yml") -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Args:
        config_file: Path to YAML config file (default "config.yml")
    
    Returns:
        Dictionary with configuration values
    """
    config_path = Path(config_file)
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception:
        return {}


def _get_config_value(config: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Get configuration value from config dict.
    
    Args:
        config: Configuration dictionary
        key: Configuration key
        default: Default value if key not found
    
    Returns:
        Configuration value or default
    """
    return config.get(key, default)


# Load configuration from YAML
_config = _load_yaml_config()

# ==================================================================================================
# Proxy Server Settings
# ==================================================================================================

PROXY_API_KEY: str = _get_config_value(_config, "proxy_api_key", "changeme_proxy_secret")

# Secret key for Web UI login (separate from proxy_api_key)
SECRET_KEY: str = _get_config_value(_config, "secret_key", "changeme_secret_key")

# ==================================================================================================
# Kiro API Credentials
# ==================================================================================================

REFRESH_TOKEN: str = _get_config_value(_config, "refresh_token", "")

PROFILE_ARN: str = _get_config_value(_config, "profile_arn", "")

REGION: str = _get_config_value(_config, "kiro_region", "us-east-1")

_raw_creds_file = _get_config_value(_config, "kiro_creds_file", "")
KIRO_CREDS_FILE: str = str(Path(_raw_creds_file)) if _raw_creds_file else ""

# ==================================================================================================
# Kiro API URL Templates
# ==================================================================================================

KIRO_REFRESH_URL_TEMPLATE: str = "https://prod.{region}.auth.desktop.kiro.dev/refreshToken"

KIRO_API_HOST_TEMPLATE: str = "https://codewhisperer.{region}.amazonaws.com"

KIRO_Q_HOST_TEMPLATE: str = "https://q.{region}.amazonaws.com"

# ==================================================================================================
# Token Settings
# ==================================================================================================

TOKEN_REFRESH_THRESHOLD: int = 600

# ==================================================================================================
# Retry Configuration
# ==================================================================================================

MAX_RETRIES: int = 3

BASE_RETRY_DELAY: float = 1.0

# ==================================================================================================
# Model Mapping
# ==================================================================================================

MODEL_MAPPING: Dict[str, str] = {
    "claude-opus-4-5": "claude-opus-4.5",
    "claude-opus-4-5-20251101": "claude-opus-4.5",
    "claude-haiku-4-5": "claude-haiku-4.5",
    "claude-haiku-4.5": "claude-haiku-4.5",
    "claude-sonnet-4-5": "CLAUDE_SONNET_4_5_20250929_V1_0",
    "claude-sonnet-4-5-20250929": "CLAUDE_SONNET_4_5_20250929_V1_0",
    "claude-sonnet-4": "CLAUDE_SONNET_4_20250514_V1_0",
    "claude-sonnet-4-20250514": "CLAUDE_SONNET_4_20250514_V1_0",
    "claude-3-7-sonnet-20250219": "CLAUDE_3_7_SONNET_20250219_V1_0",
    "auto": "claude-sonnet-4.5",
}

AVAILABLE_MODELS: List[str] = [
    "claude-opus-4-5",
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-sonnet-4-5-20250929",
    "claude-sonnet-4",
    "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219",
]

# ==================================================================================================
# Model Cache Settings
# ==================================================================================================

MODEL_CACHE_TTL: int = 3600

DEFAULT_MAX_INPUT_TOKENS: int = 200000

# ==================================================================================================
# Tool Description Handling
# ==================================================================================================

TOOL_DESCRIPTION_MAX_LENGTH: int = int(_get_config_value(_config, "tool_description_max_length", 10000))

# ==================================================================================================
# Logging Settings
# ==================================================================================================

LOG_LEVEL: str = str(_get_config_value(_config, "log_level", "INFO")).upper()

# ==================================================================================================
# First Token Timeout Settings
# ==================================================================================================

FIRST_TOKEN_TIMEOUT: float = float(_get_config_value(_config, "first_token_timeout", 15))

STREAMING_READ_TIMEOUT: float = float(_get_config_value(_config, "streaming_read_timeout", 300))

FIRST_TOKEN_MAX_RETRIES: int = int(_get_config_value(_config, "first_token_max_retries", 3))

# ==================================================================================================
# Debug Settings
# ==================================================================================================

_DEBUG_MODE_RAW: str = str(_get_config_value(_config, "debug_mode", "off")).lower()

if _DEBUG_MODE_RAW in ("off", "errors", "all"):
    DEBUG_MODE: str = _DEBUG_MODE_RAW
else:
    DEBUG_MODE: str = "off"

DEBUG_DIR: str = _get_config_value(_config, "debug_dir", "debug_logs")

# ==================================================================================================
# OAuth Settings
# ==================================================================================================

_oauth_config = _get_config_value(_config, "oauth", {}) or {}

OAUTH_CALLBACK_PORT_START: int = int(_oauth_config.get("callback_port_start", 19876))
OAUTH_CALLBACK_PORT_END: int = int(_oauth_config.get("callback_port_end", 19880))
OAUTH_AUTH_TIMEOUT: int = int(_oauth_config.get("auth_timeout", 600))
OAUTH_POLL_INTERVAL: int = int(_oauth_config.get("poll_interval", 5))


def _warn_timeout_configuration():
    """
    Print warning if timeout configuration is suboptimal.
    """
    if FIRST_TOKEN_TIMEOUT >= STREAMING_READ_TIMEOUT:
        YELLOW = "\033[93m"
        RESET = "\033[0m"
        
        warning_text = f"""
{YELLOW}WARNING: Suboptimal timeout configuration detected.
    
    FIRST_TOKEN_TIMEOUT ({FIRST_TOKEN_TIMEOUT}s) >= STREAMING_READ_TIMEOUT ({STREAMING_READ_TIMEOUT}s)
    
    Recommendation: FIRST_TOKEN_TIMEOUT should be LESS than STREAMING_READ_TIMEOUT.{RESET}
"""
        print(warning_text, file=sys.stderr)

# ==================================================================================================
# Application Version
# ==================================================================================================

APP_VERSION: str = "1.0.7"
APP_TITLE: str = "Kiro API Gateway"
APP_DESCRIPTION: str = "OpenAI-compatible interface for Kiro API (AWS CodeWhisperer). Made by @jwadow"


def get_kiro_refresh_url(region: str) -> str:
    """Return token refresh URL for the specified region."""
    return KIRO_REFRESH_URL_TEMPLATE.format(region=region)


def get_kiro_api_host(region: str) -> str:
    """Return API host for the specified region."""
    return KIRO_API_HOST_TEMPLATE.format(region=region)


def get_kiro_q_host(region: str) -> str:
    """Return Q API host for the specified region."""
    return KIRO_Q_HOST_TEMPLATE.format(region=region)


def get_internal_model_id(external_model: str) -> str:
    """
    Convert external model name to internal Kiro ID.
    
    Args:
        external_model: External model name (e.g., "claude-sonnet-4-5")
    
    Returns:
        Internal model ID for Kiro API
    """
    return MODEL_MAPPING.get(external_model, external_model)
