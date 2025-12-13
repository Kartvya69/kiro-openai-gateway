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
Обработчики исключений для Kiro Gateway.

Содержит функции для обработки ошибок валидации и других исключений
в формате, совместимом с JSON-сериализацией.
"""

from typing import Any, List, Dict

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger


def sanitize_validation_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Преобразует ошибки валидации в JSON-сериализуемый формат.
    
    Pydantic может включать bytes объекты в поле 'input', которые
    не сериализуются в JSON. Эта функция конвертирует их в строки.
    
    Args:
        errors: Список ошибок валидации от Pydantic
    
    Returns:
        Список ошибок с bytes преобразованными в строки
    """
    sanitized = []
    for error in errors:
        sanitized_error = {}
        for key, value in error.items():
            if isinstance(value, bytes):
                # Конвертируем bytes в строку
                sanitized_error[key] = value.decode("utf-8", errors="replace")
            elif isinstance(value, (list, tuple)):
                # Рекурсивно обрабатываем списки
                sanitized_error[key] = [
                    v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v
                    for v in value
                ]
            else:
                sanitized_error[key] = value
        sanitized.append(sanitized_error)
    return sanitized


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Обработчик ошибок валидации Pydantic.
    
    Логирует детали ошибки и возвращает информативный ответ.
    Корректно обрабатывает bytes объекты в ошибках, преобразуя их в строки.
    
    Args:
        request: FastAPI Request объект
        exc: Исключение валидации от Pydantic
    
    Returns:
        JSONResponse с деталями ошибки и статусом 422
    """
    body = await request.body()
    body_str = body.decode("utf-8", errors="replace")
    
    # Санитизируем ошибки для JSON-сериализации
    sanitized_errors = sanitize_validation_errors(exc.errors())
    
    logger.error(f"Validation error (422): {sanitized_errors}")
    logger.error(f"Request body: {body_str[:500]}...")
    
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors, "body": body_str[:500]},
    )