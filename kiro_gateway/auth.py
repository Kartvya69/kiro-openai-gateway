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
Менеджер аутентификации для Kiro API.

Управляет жизненным циклом токенов доступа:
- Загрузка credentials из .env или JSON файла
- Автоматическое обновление токена при истечении
- Потокобезопасное обновление с использованием asyncio.Lock
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from kiro_gateway.config import (
    TOKEN_REFRESH_THRESHOLD,
    get_kiro_refresh_url,
    get_kiro_api_host,
    get_kiro_q_host,
)
from kiro_gateway.utils import get_machine_fingerprint


class KiroAuthManager:
    """
    Управляет жизненным циклом токена для доступа к Kiro API.
    
    Поддерживает:
    - Загрузку credentials из .env или JSON файла
    - Автоматическое обновление токена при истечении
    - Проверку времени истечения (expiresAt)
    - Сохранение обновлённых токенов в файл
    
    Attributes:
        profile_arn: ARN профиля AWS CodeWhisperer
        region: Регион AWS
        api_host: Хост API для текущего региона
        q_host: Хост Q API для текущего региона
        fingerprint: Уникальный fingerprint машины
    
    Example:
        >>> auth_manager = KiroAuthManager(
        ...     refresh_token="your_refresh_token",
        ...     region="us-east-1"
        ... )
        >>> token = await auth_manager.get_access_token()
    """
    
    def __init__(
        self,
        refresh_token: Optional[str] = None,
        profile_arn: Optional[str] = None,
        region: str = "us-east-1",
        creds_file: Optional[str] = None
    ):
        """
        Инициализирует менеджер аутентификации.
        
        Args:
            refresh_token: Refresh token для обновления access token
            profile_arn: ARN профиля AWS CodeWhisperer
            region: Регион AWS (по умолчанию us-east-1)
            creds_file: Путь к JSON файлу с credentials (опционально)
        """
        self._refresh_token = refresh_token
        self._profile_arn = profile_arn
        self._region = region
        self._creds_file = creds_file
        
        self._access_token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
        
        # Динамические URL на основе региона
        self._refresh_url = get_kiro_refresh_url(region)
        self._api_host = get_kiro_api_host(region)
        self._q_host = get_kiro_q_host(region)
        
        # Fingerprint для User-Agent
        self._fingerprint = get_machine_fingerprint()
        
        # Загружаем credentials из файла если указан
        if creds_file:
            self._load_credentials_from_file(creds_file)
    
    def _load_credentials_from_file(self, file_path: str) -> None:
        """
        Загружает credentials из JSON файла.
        
        Поддерживаемые поля в JSON:
        - refreshToken: Refresh token
        - accessToken: Access token (если уже есть)
        - profileArn: ARN профиля
        - region: Регион AWS
        - expiresAt: Время истечения токена (ISO 8601)
        
        Args:
            file_path: Путь к JSON файлу
        """
        try:
            path = Path(file_path).expanduser()
            if not path.exists():
                logger.warning(f"Credentials file not found: {file_path}")
                return
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Загружаем данные из файла
            if 'refreshToken' in data:
                self._refresh_token = data['refreshToken']
            if 'accessToken' in data:
                self._access_token = data['accessToken']
            if 'profileArn' in data:
                self._profile_arn = data['profileArn']
            if 'region' in data:
                self._region = data['region']
                # Обновляем URL для нового региона
                self._refresh_url = get_kiro_refresh_url(self._region)
                self._api_host = get_kiro_api_host(self._region)
                self._q_host = get_kiro_q_host(self._region)
            
            # Парсим expiresAt
            if 'expiresAt' in data:
                try:
                    expires_str = data['expiresAt']
                    # Поддержка разных форматов даты
                    if expires_str.endswith('Z'):
                        self._expires_at = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                    else:
                        self._expires_at = datetime.fromisoformat(expires_str)
                except Exception as e:
                    logger.warning(f"Failed to parse expiresAt: {e}")
            
            logger.info(f"Credentials loaded from {file_path}")
            
        except Exception as e:
            logger.error(f"Error loading credentials from file: {e}")
    
    def _save_credentials_to_file(self) -> None:
        """
        Сохраняет обновлённые credentials в JSON файл.
        
        Обновляет существующий файл, сохраняя другие поля.
        """
        if not self._creds_file:
            return
        
        try:
            path = Path(self._creds_file).expanduser()
            
            # Читаем существующие данные
            existing_data = {}
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            
            # Обновляем данные
            existing_data['accessToken'] = self._access_token
            existing_data['refreshToken'] = self._refresh_token
            if self._expires_at:
                existing_data['expiresAt'] = self._expires_at.isoformat()
            if self._profile_arn:
                existing_data['profileArn'] = self._profile_arn
            
            # Сохраняем
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Credentials saved to {self._creds_file}")
            
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")
    
    def is_token_expiring_soon(self) -> bool:
        """
        Проверяет, истекает ли токен в ближайшее время.
        
        Returns:
            True если токен истекает в течение TOKEN_REFRESH_THRESHOLD секунд
            или если информация о времени истечения отсутствует
        """
        if not self._expires_at:
            return True  # Если нет информации о времени истечения, считаем что нужно обновить
        
        now = datetime.now(timezone.utc)
        threshold = now.timestamp() + TOKEN_REFRESH_THRESHOLD
        
        return self._expires_at.timestamp() <= threshold
    
    async def _refresh_token_request(self) -> None:
        """
        Выполняет запрос на обновление токена.
        
        Отправляет POST запрос к Kiro API для получения нового access token.
        Обновляет внутреннее состояние и сохраняет credentials в файл.
        
        Raises:
            ValueError: Если refresh token не установлен или ответ не содержит accessToken
            httpx.HTTPError: При ошибке HTTP запроса
        """
        if not self._refresh_token:
            raise ValueError("Refresh token не установлен")
        
        logger.info("Refreshing Kiro token...")
        
        payload = {'refreshToken': self._refresh_token}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"KiroGateway-{self._fingerprint[:16]}",
        }
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._refresh_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        
        new_access_token = data.get("accessToken")
        new_refresh_token = data.get("refreshToken")
        expires_in = data.get("expiresIn", 3600)
        new_profile_arn = data.get("profileArn")
        
        if not new_access_token:
            raise ValueError(f"Ответ не содержит accessToken: {data}")
        
        # Обновляем данные
        self._access_token = new_access_token
        if new_refresh_token:
            self._refresh_token = new_refresh_token
        if new_profile_arn:
            self._profile_arn = new_profile_arn
        
        # Вычисляем время истечения с запасом (минус 60 секунд)
        self._expires_at = datetime.now(timezone.utc).replace(microsecond=0)
        self._expires_at = datetime.fromtimestamp(
            self._expires_at.timestamp() + expires_in - 60,
            tz=timezone.utc
        )
        
        logger.info(f"Token refreshed, expires: {self._expires_at.isoformat()}")
        
        # Сохраняем в файл
        self._save_credentials_to_file()
    
    async def get_access_token(self) -> str:
        """
        Возвращает действительный access_token, обновляя его при необходимости.
        
        Потокобезопасный метод с использованием asyncio.Lock.
        Автоматически обновляет токен если он истёк или скоро истечёт.
        
        Returns:
            Действительный access token
        
        Raises:
            ValueError: Если не удалось получить access token
        """
        async with self._lock:
            if not self._access_token or self.is_token_expiring_soon():
                await self._refresh_token_request()
            
            if not self._access_token:
                raise ValueError("Не удалось получить access token")
            
            return self._access_token
    
    async def force_refresh(self) -> str:
        """
        Принудительно обновляет токен.
        
        Используется при получении 403 ошибки от API.
        
        Returns:
            Новый access token
        """
        async with self._lock:
            await self._refresh_token_request()
            return self._access_token
    
    @property
    def profile_arn(self) -> Optional[str]:
        """ARN профиля AWS CodeWhisperer."""
        return self._profile_arn
    
    @property
    def region(self) -> str:
        """Регион AWS."""
        return self._region
    
    @property
    def api_host(self) -> str:
        """Хост API для текущего региона."""
        return self._api_host
    
    @property
    def q_host(self) -> str:
        """Хост Q API для текущего региона."""
        return self._q_host
    
    @property
    def fingerprint(self) -> str:
        """Уникальный fingerprint машины."""
        return self._fingerprint