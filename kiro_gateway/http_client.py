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
HTTP клиент для Kiro API с поддержкой retry логики.

Обрабатывает:
- 403: автоматический refresh токена и повтор
- 429: exponential backoff
- 5xx: exponential backoff
- Таймауты: exponential backoff
"""

import asyncio
from typing import Optional

import httpx
from fastapi import HTTPException
from loguru import logger

from kiro_gateway.config import MAX_RETRIES, BASE_RETRY_DELAY
from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.utils import get_kiro_headers


class KiroHttpClient:
    """
    HTTP клиент для Kiro API с поддержкой retry логики.
    
    Автоматически обрабатывает ошибки и повторяет запросы:
    - 403: обновляет токен и повторяет
    - 429: ждёт с exponential backoff
    - 5xx: ждёт с exponential backoff
    - Таймауты: ждёт с exponential backoff
    Attributes:
        auth_manager: Менеджер аутентификации для получения токенов
        client: HTTP клиент httpx
    
    Example:
        >>> client = KiroHttpClient(auth_manager)
        >>> response = await client.request_with_retry(
        ...     "POST",
        ...     "https://api.example.com/endpoint",
        ...     {"data": "value"},
        ...     stream=True
        ... )
    """
    
    def __init__(self, auth_manager: KiroAuthManager):
        """
        Инициализирует HTTP клиент.
        
        Args:
            auth_manager: Менеджер аутентификации
        """
        self.auth_manager = auth_manager
        self.client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """
        Возвращает или создаёт HTTP клиент.
        
        Returns:
            Активный HTTP клиент
        """
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(timeout=300, follow_redirects=True)
        return self.client
    
    async def close(self) -> None:
        """Закрывает HTTP клиент."""
        if self.client and not self.client.is_closed:
            await self.client.aclose()
    
    async def request_with_retry(
        self,
        method: str,
        url: str,
        json_data: dict,
        stream: bool = False
    ) -> httpx.Response:
        """
        Выполняет HTTP запрос с retry логикой.
        
        Автоматически обрабатывает различные типы ошибок:
        - 403: обновляет токен через auth_manager.force_refresh() и повторяет
        - 429: ждёт с exponential backoff (1s, 2s, 4s)
        - 5xx: ждёт с exponential backoff
        - Таймауты: ждёт с exponential backoff
        
        Args:
            method: HTTP метод (GET, POST, etc.)
            url: URL запроса
            json_data: Тело запроса (JSON)
            stream: Использовать streaming (по умолчанию False)
        
        Returns:
            httpx.Response с успешным ответом
        
        Raises:
            HTTPException: При неудаче после всех попыток (502)
        """
        client = await self._get_client()
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                # Получаем актуальный токен
                token = await self.auth_manager.get_access_token()
                headers = get_kiro_headers(self.auth_manager, token)
                
                if stream:
                    req = client.build_request(method, url, json=json_data, headers=headers)
                    response = await client.send(req, stream=True)
                else:
                    response = await client.request(method, url, json=json_data, headers=headers)
                
                # Проверяем статус
                if response.status_code == 200:
                    return response
                
                # 403 - токен истёк, обновляем и повторяем
                if response.status_code == 403:
                    logger.warning(f"Received 403, refreshing token (attempt {attempt + 1}/{MAX_RETRIES})")
                    await self.auth_manager.force_refresh()
                    continue
                
                # 429 - rate limit, ждём и повторяем
                if response.status_code == 429:
                    delay = BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Received 429, waiting {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(delay)
                    continue
                
                # 5xx - серверная ошибка, ждём и повторяем
                if 500 <= response.status_code < 600:
                    delay = BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Received {response.status_code}, waiting {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(delay)
                    continue
                
                # Другие ошибки - возвращаем как есть
                return response
                
            except httpx.TimeoutException as e:
                last_error = e
                delay = BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Timeout, waiting {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(delay)
                
            except httpx.RequestError as e:
                last_error = e
                delay = BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Request error: {e}, waiting {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(delay)
        
        # Все попытки исчерпаны
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось выполнить запрос после {MAX_RETRIES} попыток: {last_error}"
        )
    
    async def __aenter__(self) -> "KiroHttpClient":
        """Поддержка async context manager."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Закрывает клиент при выходе из контекста."""
        await self.close()