# -*- coding: utf-8 -*-

# Kiro OpenAI Gateway
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
Конфигурация Kiro Gateway.

Централизованное хранение всех настроек, констант и маппингов.
Загружает переменные окружения и предоставляет типизированный доступ к ним.
"""

import os
from typing import Dict, List
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# ==================================================================================================
# Настройки прокси-сервера
# ==================================================================================================

# API ключ для доступа к прокси (клиенты должны передавать его в Authorization header)
PROXY_API_KEY: str = os.getenv("PROXY_API_KEY", "changeme_proxy_secret")

# ==================================================================================================
# Kiro API Credentials
# ==================================================================================================

# Refresh token для обновления access token
REFRESH_TOKEN: str = os.getenv("REFRESH_TOKEN", "")

# Profile ARN для AWS CodeWhisperer
PROFILE_ARN: str = os.getenv("PROFILE_ARN", "")

# Регион AWS (по умолчанию us-east-1)
REGION: str = os.getenv("KIRO_REGION", "us-east-1")

# Путь к файлу с credentials (опционально, альтернатива .env)
KIRO_CREDS_FILE: str = os.getenv("KIRO_CREDS_FILE", "")

# ==================================================================================================
# Kiro API URL Templates
# ==================================================================================================

# URL для обновления токена
KIRO_REFRESH_URL_TEMPLATE: str = "https://prod.{region}.auth.desktop.kiro.dev/refreshToken"

# Хост для основного API (generateAssistantResponse)
KIRO_API_HOST_TEMPLATE: str = "https://codewhisperer.{region}.amazonaws.com"

# Хост для Q API (ListAvailableModels)
KIRO_Q_HOST_TEMPLATE: str = "https://q.{region}.amazonaws.com"

# ==================================================================================================
# Настройки токенов
# ==================================================================================================

# Время до истечения токена, когда нужно обновить (в секундах)
# По умолчанию 10 минут - обновляем токен заранее, чтобы избежать ошибок
TOKEN_REFRESH_THRESHOLD: int = 600

# ==================================================================================================
# Retry конфигурация
# ==================================================================================================

# Максимальное количество попыток при ошибках
MAX_RETRIES: int = 3

# Базовая задержка между попытками (секунды)
# Используется exponential backoff: delay * (2 ** attempt)
BASE_RETRY_DELAY: float = 1.0

# ==================================================================================================
# Маппинг моделей
# ==================================================================================================

# Внешние имена моделей (OpenAI-совместимые) -> внутренние ID Kiro
# Клиенты используют внешние имена, а мы конвертируем их во внутренние
MODEL_MAPPING: Dict[str, str] = {
    # Claude Opus 4.5 - топовая модель
    "claude-opus-4-5": "claude-opus-4.5",
    "claude-opus-4-5-20251101": "claude-opus-4.5",
    
    # Claude Haiku 4.5 - быстрая модель
    "claude-haiku-4-5": "claude-haiku-4.5",
    "claude-haiku-4.5": "claude-haiku-4.5",  # Прямой проброс
    
    # Claude Sonnet 4.5 - улучшенная модель
    "claude-sonnet-4-5": "CLAUDE_SONNET_4_5_20250929_V1_0",
    "claude-sonnet-4-5-20250929": "CLAUDE_SONNET_4_5_20250929_V1_0",
    
    # Claude Sonnet 4 - сбалансированная модель
    "claude-sonnet-4": "CLAUDE_SONNET_4_20250514_V1_0",
    "claude-sonnet-4-20250514": "CLAUDE_SONNET_4_20250514_V1_0",
    
    # Claude 3.7 Sonnet - legacy модель
    "claude-3-7-sonnet-20250219": "CLAUDE_3_7_SONNET_20250219_V1_0",
    
    # Алиасы для удобства
    "auto": "claude-sonnet-4.5",
}

# Список доступных моделей для эндпоинта /v1/models
# Эти модели будут отображаться клиентам как доступные
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
# Настройки кэша моделей
# ==================================================================================================

# TTL кэша моделей в секундах (1 час)
MODEL_CACHE_TTL: int = 3600

# Максимальное количество input токенов по умолчанию
DEFAULT_MAX_INPUT_TOKENS: int = 200000

# ==================================================================================================
# Debug Settings
# ==================================================================================================

# If True, the last request will be logged in detail to DEBUG_DIR
# Enable via .env: DEBUG_LAST_REQUEST=true
DEBUG_LAST_REQUEST: bool = os.getenv("DEBUG_LAST_REQUEST", "false").lower() in ("true", "1", "yes")

# Directory for debug log files
DEBUG_DIR: str = os.getenv("DEBUG_DIR", "debug_logs")

# ==================================================================================================
# Версия приложения
# ==================================================================================================

APP_VERSION: str = "2.0.0"
APP_TITLE: str = "Kiro API Gateway"
APP_DESCRIPTION: str = "OpenAI-совместимый интерфейс для Kiro API (AWS CodeWhisperer)."


def get_kiro_refresh_url(region: str) -> str:
    """Возвращает URL для обновления токена для указанного региона."""
    return KIRO_REFRESH_URL_TEMPLATE.format(region=region)


def get_kiro_api_host(region: str) -> str:
    """Возвращает хост API для указанного региона."""
    return KIRO_API_HOST_TEMPLATE.format(region=region)


def get_kiro_q_host(region: str) -> str:
    """Возвращает хост Q API для указанного региона."""
    return KIRO_Q_HOST_TEMPLATE.format(region=region)


def get_internal_model_id(external_model: str) -> str:
    """
    Конвертирует внешнее имя модели во внутренний ID Kiro.
    
    Args:
        external_model: Внешнее имя модели (например, "claude-sonnet-4-5")
    
    Returns:
        Внутренний ID модели для Kiro API
    """
    return MODEL_MAPPING.get(external_model, external_model)