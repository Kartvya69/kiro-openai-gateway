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
Kiro API Gateway - OpenAI-compatible interface for Kiro API.

Application entry point. Creates FastAPI app and connects routes.

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
    or directly:
    python main.py
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from kiro_gateway.config import (
    APP_TITLE,
    APP_DESCRIPTION,
    APP_VERSION,
    REFRESH_TOKEN,
    PROFILE_ARN,
    REGION,
    KIRO_CREDS_FILE,
    KIRO_CLI_DB_FILE,
    PROXY_API_KEY,
    LOG_LEVEL,
    OAUTH_CALLBACK_PORT_START,
    OAUTH_CALLBACK_PORT_END,
    OAUTH_AUTH_TIMEOUT,
    OAUTH_POLL_INTERVAL,
    _warn_timeout_configuration,
)
from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.cache import ModelInfoCache
from kiro_gateway.routes import router
from kiro_gateway.exceptions import validation_exception_handler
from kiro_gateway.token_refresh import IdCTokenRefresher
from kiro_gateway.oauth import KiroOAuthManager
from kiro_gateway.webui import webui_router, start_session_cleanup, stop_session_cleanup
from kiro_gateway.database import init_database, close_database, is_database_configured
from kiro_gateway.accounts import AccountManager
from kiro_gateway.local_storage import LocalAccountManager


# --- Loguru Configuration ---
logger.remove()
logger.add(
    sys.stderr,
    level=LOG_LEVEL,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """
    Intercepts logs from standard logging and redirects them to loguru.
    
    This allows capturing logs from uvicorn, FastAPI and other libraries
    that use standard logging instead of loguru.
    """
    
    def emit(self, record: logging.LogRecord) -> None:
        # Get the corresponding loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        
        # Find the caller frame for correct source display
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging_intercept():
    """
    Configures log interception from standard logging to loguru.
    
    Intercepts logs from:
    - uvicorn (access logs, error logs)
    - uvicorn.error
    - uvicorn.access
    - fastapi
    """
    # List of loggers to intercept
    loggers_to_intercept = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
    ]
    
    for logger_name in loggers_to_intercept:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False


# Configure uvicorn/fastapi log interception
setup_logging_intercept()


# --- Configuration Validation ---
def generate_api_key(prefix: str = "sk-") -> str:
    """Generate an OpenAI-style API key."""
    import secrets
    import string
    chars = string.ascii_letters + string.digits
    random_part = ''.join(secrets.choice(chars) for _ in range(48))
    return f"{prefix}{random_part}"


def validate_configuration() -> None:
    """
    Validates and auto-creates configuration if needed.
    
    - Auto-creates config.yml from config.example.yml if not found
    - Auto-generates API keys if using defaults
    """
    import yaml
    
    config_file = Path("config.yml")
    config_example = Path("config.example.yml")
    
    # Auto-create config.yml if not found
    if not config_file.exists():
        if config_example.exists():
            import shutil
            shutil.copy(config_example, config_file)
            logger.info(f"Created {config_file} from {config_example}")
        else:
            # Create minimal config
            minimal_config = {
                "proxy_api_key": generate_api_key("sk-"),
                "secret_key": generate_api_key("sk-"),
                "kiro_region": "us-east-1",
                "log_level": "INFO",
            }
            with open(config_file, 'w') as f:
                yaml.dump(minimal_config, f, default_flow_style=False)
            logger.info(f"Created minimal {config_file}")
    
    # Load current config and check if we need to generate keys
    try:
        with open(config_file, 'r') as f:
            current_config = yaml.safe_load(f) or {}
    except:
        current_config = {}
    
    config_updated = False
    
    # Auto-generate proxy_api_key if using default or empty
    proxy_key = current_config.get("proxy_api_key", "")
    if not proxy_key or proxy_key in ("changeme_proxy_secret", "my-super-secret-password-123"):
        new_proxy_key = generate_api_key("sk-")
        current_config["proxy_api_key"] = new_proxy_key
        config_updated = True
        logger.info(f"Generated new proxy_api_key: {new_proxy_key}")
    
    # Auto-generate secret_key if using default or empty
    secret_key = current_config.get("secret_key", "")
    if not secret_key or secret_key in ("changeme_secret_key", "admin123", "my-webui-secret-key"):
        new_secret_key = generate_api_key("sk-")
        current_config["secret_key"] = new_secret_key
        config_updated = True
        logger.info(f"Generated new secret_key: {new_secret_key}")
    
    # Save updated config
    if config_updated:
        with open(config_file, 'w') as f:
            yaml.dump(current_config, f, default_flow_style=False)
        logger.info(f"Updated {config_file} with auto-generated keys")
        logger.info("You can view/change these keys in the config.yml file")
    
    # Log the keys for user reference (only on first run)
    if config_updated:
        logger.info("=" * 60)
        logger.info("  AUTO-GENERATED API KEYS")
        logger.info("=" * 60)
        logger.info(f"  Proxy API Key: {current_config.get('proxy_api_key')}")
        logger.info(f"  WebUI Secret:  {current_config.get('secret_key')}")
        logger.info("=" * 60)
        logger.info("  Use Proxy API Key as 'api_key' when connecting clients")
        logger.info("  Use WebUI Secret to login at http://localhost:8000/ui")
        logger.info("=" * 60)


# Run configuration validation on import
validate_configuration()

# Warn about suboptimal timeout configuration
_warn_timeout_configuration()


# --- Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application lifecycle.
    
    Creates and initializes:
    - Database connection and AccountManager (or LocalAccountManager if no DATABASE_URL)
    - KiroAuthManager for token management (fallback)
    - ModelInfoCache for model caching
    - IdCTokenRefresher for automatic token refresh (if using IdC auth)
    """
    logger.info("Starting application... Creating state managers.")
    
    # Initialize AccountManager (PostgreSQL or Local storage)
    app.state.account_manager = None
    app.state.using_local_storage = False
    
    if is_database_configured():
        # Use PostgreSQL database
        try:
            session_factory = await init_database()
            app.state.account_manager = AccountManager(session_factory)
            await app.state.account_manager.load_accounts()
            app.state.account_manager.start_auto_refresh()
            logger.info(f"AccountManager initialized with {app.state.account_manager.account_count} accounts (PostgreSQL)")
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")
            logger.warning("Falling back to local storage")
            app.state.account_manager = LocalAccountManager()
            await app.state.account_manager.load_accounts()
            app.state.account_manager.start_auto_refresh()
            app.state.using_local_storage = True
            logger.info(f"LocalAccountManager initialized with {app.state.account_manager.account_count} accounts (JSON file)")
    else:
        # Use local JSON file storage
        logger.info("DATABASE_URL not configured, using local storage")
        app.state.account_manager = LocalAccountManager()
        await app.state.account_manager.load_accounts()
        app.state.account_manager.start_auto_refresh()
        app.state.using_local_storage = True
        logger.info(f"LocalAccountManager initialized with {app.state.account_manager.account_count} accounts (JSON file)")
    
    # Create AuthManager
    # Priority: SQLite DB > JSON file > environment variables
    app.state.auth_manager = KiroAuthManager(
        refresh_token=REFRESH_TOKEN,
        profile_arn=PROFILE_ARN,
        region=REGION,
        creds_file=KIRO_CREDS_FILE if KIRO_CREDS_FILE else None,
        sqlite_db=KIRO_CLI_DB_FILE if KIRO_CLI_DB_FILE else None,
    )
    
    # Create model cache
    app.state.model_cache = ModelInfoCache()
    
    # Create OAuth manager
    creds_file = KIRO_CREDS_FILE if KIRO_CREDS_FILE else "auth.json"
    app.state.oauth_manager = KiroOAuthManager(
        credentials_file=creds_file,
        callback_port_start=OAUTH_CALLBACK_PORT_START,
        callback_port_end=OAUTH_CALLBACK_PORT_END,
        auth_timeout=OAUTH_AUTH_TIMEOUT,
        poll_interval=OAUTH_POLL_INTERVAL,
    )
    logger.info("OAuth manager initialized")
    
    # Start automatic token refresh for IdC auth
    app.state.token_refresher = None
    if KIRO_CREDS_FILE:
        try:
            from pathlib import Path
            import json
            creds_path = Path(KIRO_CREDS_FILE).expanduser()
            if creds_path.exists():
                with open(creds_path, 'r') as f:
                    creds = json.load(f)
                if creds.get('authMethod') == 'IdC':
                    app.state.token_refresher = IdCTokenRefresher(KIRO_CREDS_FILE)
                    # Link refresher to auth manager for token sync (bidirectional)
                    app.state.token_refresher.set_auth_manager(app.state.auth_manager)
                    app.state.auth_manager.set_idc_refresher(app.state.token_refresher)
                    app.state.token_refresher.start()
                    logger.info("IdC token auto-refresh enabled (expiration-aware)")
        except Exception as e:
            logger.warning(f"Could not start token auto-refresh: {e}")
    
    # Start session cleanup background task
    start_session_cleanup()
    logger.info("Session cleanup task started")
    
    yield
    
    # Stop session cleanup task
    stop_session_cleanup()
    
    # Stop token refresher on shutdown
    if app.state.token_refresher:
        app.state.token_refresher.stop()
    
    # Stop account manager auto-refresh
    if app.state.account_manager:
        app.state.account_manager.stop_auto_refresh()
    
    # Close database connection (only if using PostgreSQL)
    if not app.state.using_local_storage:
        await close_database()
    
    logger.info("Shutting down application.")


# --- FastAPI Application ---
app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan
)


# --- CORS Middleware ---
# Allow CORS for all origins to support browser clients
# and tools that send preflight OPTIONS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
)


# --- Validation Error Handler Registration ---
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# --- Static Files ---
static_dir = Path(__file__).parent / "kiro_gateway" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# --- Route Registration ---
app.include_router(router)
app.include_router(webui_router)


# --- Uvicorn log config ---
# Minimal configuration for redirecting uvicorn logs to loguru.
# Uses InterceptHandler which intercepts logs and passes them to loguru.
UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "default": {
            "class": "main.InterceptHandler",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


# --- Entry Point ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server...")
    
    # Use string reference to avoid double module import
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=UVICORN_LOG_CONFIG,
    )
