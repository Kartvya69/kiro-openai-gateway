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
Кэш метаданных моделей для Kiro Gateway.

Потокобезопасное хранилище информации о доступных моделях
с поддержкой TTL и lazy loading.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from kiro_gateway.config import MODEL_CACHE_TTL, DEFAULT_MAX_INPUT_TOKENS


class ModelInfoCache:
    """
    Потокобезопасный кэш для хранения метаданных о моделях.
    
    Использует Lazy Loading для заполнения - данные загружаются
    только при первом обращении или когда кэш устарел.
    
    Attributes:
        cache_ttl: Время жизни кэша в секундах
    
    Example:
        >>> cache = ModelInfoCache()
        >>> await cache.update([{"modelId": "claude-sonnet-4", "tokenLimits": {...}}])
        >>> info = cache.get("claude-sonnet-4")
        >>> max_tokens = cache.get_max_input_tokens("claude-sonnet-4")
    """
    
    def __init__(self, cache_ttl: int = MODEL_CACHE_TTL):
        """
        Инициализирует кэш моделей.
        
        Args:
            cache_ttl: Время жизни кэша в секундах (по умолчанию из конфига)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._last_update: Optional[float] = None
        self._cache_ttl = cache_ttl
    
    async def update(self, models_data: List[Dict[str, Any]]) -> None:
        """
        Обновляет кэш моделей.
        
        Потокобезопасно заменяет содержимое кэша новыми данными.
        
        Args:
            models_data: Список словарей с информацией о моделях.
                        Каждый словарь должен содержать ключ "modelId".
        """
        async with self._lock:
            logger.info(f"Updating model cache. Found {len(models_data)} models.")
            self._cache = {model["modelId"]: model for model in models_data}
            self._last_update = time.time()
    
    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает информацию о модели.
        
        Args:
            model_id: ID модели
        
        Returns:
            Словарь с информацией о модели или None если модель не найдена
        """
        return self._cache.get(model_id)
    
    def get_max_input_tokens(self, model_id: str) -> int:
        """
        Возвращает maxInputTokens для модели.
        
        Args:
            model_id: ID модели
        
        Returns:
            Максимальное количество input токенов или DEFAULT_MAX_INPUT_TOKENS
        """
        model = self._cache.get(model_id)
        if model and model.get("tokenLimits"):
            return model["tokenLimits"].get("maxInputTokens") or DEFAULT_MAX_INPUT_TOKENS
        return DEFAULT_MAX_INPUT_TOKENS
    
    def is_empty(self) -> bool:
        """
        Проверяет, пуст ли кэш.
        
        Returns:
            True если кэш пуст
        """
        return not self._cache
    
    def is_stale(self) -> bool:
        """
        Проверяет, устарел ли кэш.
        
        Returns:
            True если кэш устарел (прошло больше cache_ttl секунд)
            или если кэш никогда не обновлялся
        """
        if not self._last_update:
            return True
        return time.time() - self._last_update > self._cache_ttl
    
    def get_all_model_ids(self) -> List[str]:
        """
        Возвращает список всех ID моделей в кэше.
        
        Returns:
            Список ID моделей
        """
        return list(self._cache.keys())
    
    @property
    def size(self) -> int:
        """Количество моделей в кэше."""
        return len(self._cache)
    
    @property
    def last_update_time(self) -> Optional[float]:
        """Время последнего обновления (timestamp) или None."""
        return self._last_update