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
Вспомогательные утилиты для Kiro Gateway.

Содержит функции для генерации fingerprint, формирования заголовков
и другие общие утилиты.
"""

import hashlib
import uuid
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from kiro_gateway.auth import KiroAuthManager


def get_machine_fingerprint() -> str:
    """
    Генерирует уникальный fingerprint машины на основе hostname и username.
    
    Используется для формирования User-Agent, чтобы идентифицировать
    конкретную установку gateway.
    
    Returns:
        SHA256 хеш строки "{hostname}-{username}-kiro-gateway"
    """
    try:
        import socket
        import getpass
        
        hostname = socket.gethostname()
        username = getpass.getuser()
        unique_string = f"{hostname}-{username}-kiro-gateway"
        
        return hashlib.sha256(unique_string.encode()).hexdigest()
    except Exception as e:
        logger.warning(f"Failed to get machine fingerprint: {e}")
        return hashlib.sha256(b"default-kiro-gateway").hexdigest()


def get_kiro_headers(auth_manager: "KiroAuthManager", token: str) -> dict:
    """
    Формирует заголовки для запросов к Kiro API.
    
    Включает все необходимые заголовки для аутентификации и идентификации:
    - Authorization с Bearer токеном
    - User-Agent с fingerprint
    - Специфичные для AWS CodeWhisperer заголовки
    
    Args:
        auth_manager: Менеджер аутентификации для получения fingerprint
        token: Access token для авторизации
    
    Returns:
        Словарь с заголовками для HTTP запроса
    """
    fingerprint = auth_manager.fingerprint
    
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"aws-sdk-js/1.0.27 ua/2.1 os/win32#10.0.19044 lang/js md/nodejs#22.21.1 api/codewhispererstreaming#1.0.27 m/E KiroGateway-{fingerprint[:32]}",
        "x-amz-user-agent": f"aws-sdk-js/1.0.27 KiroGateway-{fingerprint[:32]}",
        "x-amzn-codewhisperer-optout": "true",
        "x-amzn-kiro-agent-mode": "vibe",
        "amz-sdk-invocation-id": str(uuid.uuid4()),
        "amz-sdk-request": "attempt=1; max=3",
    }


def generate_completion_id() -> str:
    """
    Генерирует уникальный ID для chat completion.
    
    Returns:
        ID в формате "chatcmpl-{uuid_hex}"
    """
    return f"chatcmpl-{uuid.uuid4().hex}"


def generate_conversation_id() -> str:
    """
    Генерирует уникальный ID для разговора.
    
    Returns:
        UUID в строковом формате
    """
    return str(uuid.uuid4())


def generate_tool_call_id() -> str:
    """
    Генерирует уникальный ID для tool call.
    
    Returns:
        ID в формате "call_{uuid_hex[:8]}"
    """
    return f"call_{uuid.uuid4().hex[:8]}"