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
Kiro Gateway - OpenAI-совместимый прокси для Kiro API.

Этот пакет предоставляет модульную архитектуру для проксирования
запросов OpenAI API к Kiro (AWS CodeWhisperer).

Модули:
    - config: Конфигурация и константы
    - models: Pydantic модели для OpenAI API
    - auth: Менеджер аутентификации Kiro
    - cache: Кэш метаданных моделей
    - utils: Вспомогательные утилиты
    - converters: Конвертация OpenAI <-> Kiro форматов
    - parsers: Парсеры AWS SSE потоков
    - streaming: Логика стриминга ответов
    - http_client: HTTP клиент с retry логикой
    - routes: FastAPI роуты
    - exceptions: Обработчики исключений
"""

__version__ = "2.0.0"
__author__ = "Kiro Gateway Team"

# Основные компоненты для удобного импорта
from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.cache import ModelInfoCache
from kiro_gateway.http_client import KiroHttpClient
from kiro_gateway.routes import router

# Конфигурация
from kiro_gateway.config import (
    PROXY_API_KEY,
    REGION,
    MODEL_MAPPING,
    AVAILABLE_MODELS,
    APP_VERSION,
)

# Модели
from kiro_gateway.models import (
    ChatCompletionRequest,
    ChatMessage,
    OpenAIModel,
    ModelList,
)

# Конвертеры
from kiro_gateway.converters import (
    build_kiro_payload,
    extract_text_content,
    merge_adjacent_messages,
)

# Парсеры
from kiro_gateway.parsers import (
    AwsEventStreamParser,
    parse_bracket_tool_calls,
)

# Streaming
from kiro_gateway.streaming import (
    stream_kiro_to_openai,
    collect_stream_response,
)

# Exceptions
from kiro_gateway.exceptions import (
    validation_exception_handler,
    sanitize_validation_errors,
)

__all__ = [
    # Версия
    "__version__",
    
    # Основные классы
    "KiroAuthManager",
    "ModelInfoCache",
    "KiroHttpClient",
    "router",
    
    # Конфигурация
    "PROXY_API_KEY",
    "REGION",
    "MODEL_MAPPING",
    "AVAILABLE_MODELS",
    "APP_VERSION",
    
    # Модели
    "ChatCompletionRequest",
    "ChatMessage",
    "OpenAIModel",
    "ModelList",
    
    # Конвертеры
    "build_kiro_payload",
    "extract_text_content",
    "merge_adjacent_messages",
    
    # Парсеры
    "AwsEventStreamParser",
    "parse_bracket_tool_calls",
    
    # Streaming
    "stream_kiro_to_openai",
    "collect_stream_response",
    
    # Exceptions
    "validation_exception_handler",
    "sanitize_validation_errors",
]