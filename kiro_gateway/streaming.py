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
Streaming логика для преобразования потока Kiro в OpenAI формат.

Содержит генераторы для:
- Преобразования AWS SSE в OpenAI SSE
- Формирования streaming chunks
- Обработки tool calls в потоке
"""

import json
import time
from typing import TYPE_CHECKING, AsyncGenerator

import httpx
from loguru import logger

from kiro_gateway.parsers import AwsEventStreamParser, parse_bracket_tool_calls, deduplicate_tool_calls
from kiro_gateway.utils import generate_completion_id

if TYPE_CHECKING:
    from kiro_gateway.auth import KiroAuthManager
    from kiro_gateway.cache import ModelInfoCache

# Импортируем debug_logger для логирования
try:
    from kiro_gateway.debug_logger import debug_logger
except ImportError:
    debug_logger = None


async def stream_kiro_to_openai(
    client: httpx.AsyncClient,
    response: httpx.Response,
    model: str,
    model_cache: "ModelInfoCache",
    auth_manager: "KiroAuthManager"
) -> AsyncGenerator[str, None]:
    """
    Генератор для преобразования потока Kiro в OpenAI формат.
    
    Парсит AWS SSE stream и конвертирует события в OpenAI chat.completion.chunk.
    Поддерживает tool calls и вычисление usage.
    
    Args:
        client: HTTP клиент (для управления соединением)
        response: HTTP ответ с потоком данных
        model: Имя модели для включения в ответ
        model_cache: Кэш моделей для получения лимитов токенов
        auth_manager: Менеджер аутентификации
    
    Yields:
        Строки в формате SSE: "data: {...}\\n\\n" или "data: [DONE]\\n\\n"
    
    Example:
        >>> async for chunk in stream_kiro_to_openai(client, response, "claude-sonnet-4", cache, auth):
        ...     print(chunk)
        data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...}
        
        data: [DONE]
    """
    completion_id = generate_completion_id()
    created_time = int(time.time())
    first_chunk = True
    
    parser = AwsEventStreamParser()
    metering_data = None
    context_usage_percentage = None
    full_content = ""
    
    try:
        async for chunk in response.aiter_bytes():
            # Логируем сырой chunk
            if debug_logger:
                debug_logger.log_raw_chunk(chunk)
            
            events = parser.feed(chunk)
            
            for event in events:
                if event["type"] == "content":
                    content = event["data"]
                    full_content += content
                    
                    # Формируем delta
                    delta = {"content": content}
                    if first_chunk:
                        delta["role"] = "assistant"
                        first_chunk = False
                    
                    # Формируем OpenAI chunk
                    openai_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
                    }
                    
                    chunk_text = f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                    
                    # Логируем модифицированный chunk
                    if debug_logger:
                        debug_logger.log_modified_chunk(chunk_text.encode('utf-8'))
                    
                    yield chunk_text
                
                elif event["type"] == "usage":
                    metering_data = event["data"]
                
                elif event["type"] == "context_usage":
                    context_usage_percentage = event["data"]
        
        # Проверяем bracket-style tool calls в полном контенте
        bracket_tool_calls = parse_bracket_tool_calls(full_content)
        all_tool_calls = parser.get_tool_calls() + bracket_tool_calls
        all_tool_calls = deduplicate_tool_calls(all_tool_calls)
        
        # Определяем finish_reason
        finish_reason = "tool_calls" if all_tool_calls else "stop"
        
        # Вычисляем total_tokens на основе context_usage_percentage
        total_tokens = 0
        if context_usage_percentage is not None:
            max_input_tokens = model_cache.get_max_input_tokens(model)
            total_tokens = int((context_usage_percentage / 100) * max_input_tokens)
        
        # Отправляем tool calls если есть
        if all_tool_calls:
            tool_calls_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"tool_calls": all_tool_calls},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(tool_calls_chunk, ensure_ascii=False)}\n\n"
        
        # Финальный чанк с usage
        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": total_tokens,
                "completion_tokens": 0,
                "total_tokens": total_tokens,
            }
        }
        
        if metering_data:
            final_chunk["usage"]["credits_used"] = metering_data
        
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error(f"Error during streaming: {e}", exc_info=True)
    finally:
        await response.aclose()
        logger.debug("Streaming completed")


async def collect_stream_response(
    client: httpx.AsyncClient,
    response: httpx.Response,
    model: str,
    model_cache: "ModelInfoCache",
    auth_manager: "KiroAuthManager"
) -> dict:
    """
    Собирает полный ответ из streaming потока.
    
    Используется для non-streaming режима - собирает все chunks
    и формирует единый ответ.
    
    Args:
        client: HTTP клиент
        response: HTTP ответ с потоком
        model: Имя модели
        model_cache: Кэш моделей
        auth_manager: Менеджер аутентификации
    
    Returns:
        Словарь с полным ответом в формате OpenAI chat.completion
    """
    full_content = ""
    final_usage = None
    tool_calls = []
    completion_id = generate_completion_id()
    
    async for chunk_str in stream_kiro_to_openai(
        client,
        response,
        model,
        model_cache,
        auth_manager
    ):
        if not chunk_str.startswith("data:"):
            continue
        
        data_str = chunk_str[len("data:"):].strip()
        if not data_str or data_str == "[DONE]":
            continue
        
        try:
            chunk_data = json.loads(data_str)
            
            # Извлекаем данные из chunk
            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
            if "content" in delta:
                full_content += delta["content"]
            if "tool_calls" in delta:
                tool_calls.extend(delta["tool_calls"])
            
            # Сохраняем usage из последнего chunk
            if "usage" in chunk_data:
                final_usage = chunk_data["usage"]
                
        except (json.JSONDecodeError, IndexError):
            continue
    
    # Формируем финальный ответ
    message = {"role": "assistant", "content": full_content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    
    finish_reason = "tool_calls" if tool_calls else "stop"
    
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason
        }],
        "usage": final_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }