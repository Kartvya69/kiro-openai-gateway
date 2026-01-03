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
Pydantic модели для OpenAI-совместимого API.

Определяет схемы данных для запросов и ответов,
обеспечивая валидацию и сериализацию.
"""

import time
from typing import Any, Dict, List, Optional, Union
from typing_extensions import Annotated
from pydantic import BaseModel, Field


# ==================================================================================================
# Модели для /v1/models endpoint
# ==================================================================================================

class OpenAIModel(BaseModel):
    """
    Модель данных для описания AI модели в формате OpenAI.
    
    Используется в ответе эндпоинта /v1/models.
    """
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "anthropic"
    description: Optional[str] = None


class ModelList(BaseModel):
    """
    Список моделей в формате OpenAI.
    
    Ответ эндпоинта GET /v1/models.
    """
    object: str = "list"
    data: List[OpenAIModel]


# ==================================================================================================
# Модели для /v1/chat/completions endpoint
# ==================================================================================================

class ChatMessage(BaseModel):
    """
    Сообщение в чате в формате OpenAI.
    
    Поддерживает различные роли (user, assistant, system, tool)
    и различные форматы контента (строка, список, объект).
    
    Attributes:
        role: Роль отправителя (user, assistant, system, tool)
        content: Содержимое сообщения (может быть строкой, списком или None)
        name: Опциональное имя отправителя
        tool_calls: Список вызовов инструментов (для assistant)
        tool_call_id: ID вызова инструмента (для tool)
    """
    role: str
    content: Optional[Union[str, List[Any], Any]] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    tool_call_id: Optional[str] = None
    
    model_config = {"extra": "allow"}


class ToolFunction(BaseModel):
    """
    Описание функции инструмента.
    
    Attributes:
        name: Имя функции
        description: Описание функции
        parameters: JSON Schema параметров функции
    """
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class Tool(BaseModel):
    """
    Инструмент (tool) в формате OpenAI.
    
    Attributes:
        type: Тип инструмента (обычно "function")
        function: Описание функции
    """
    type: str = "function"
    function: ToolFunction


class ChatCompletionRequest(BaseModel):
    """
    Запрос на генерацию ответа в формате OpenAI Chat Completions API.
    
    Поддерживает все стандартные поля OpenAI API, включая:
    - Базовые параметры (model, messages, stream)
    - Параметры генерации (temperature, top_p, max_tokens)
    - Tools (function calling)
    - Дополнительные параметры (игнорируются, но принимаются для совместимости)
    
    Attributes:
        model: ID модели для генерации
        messages: Список сообщений чата
        stream: Использовать streaming (по умолчанию False)
        temperature: Температура генерации (0-2)
        top_p: Top-p sampling
        n: Количество вариантов ответа
        max_tokens: Максимальное количество токенов в ответе
        max_completion_tokens: Альтернативное поле для max_tokens
        stop: Стоп-последовательности
        presence_penalty: Штраф за повторение тем
        frequency_penalty: Штраф за повторение слов
        tools: Список доступных инструментов
        tool_choice: Стратегия выбора инструмента
    """
    model: str
    messages: Annotated[List[ChatMessage], Field(min_length=1)]
    stream: bool = False
    
    # Параметры генерации
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = 1
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    
    # Tools (function calling)
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[str, Dict]] = None
    
    # Поля для совместимости (игнорируются)
    stream_options: Optional[Dict[str, Any]] = None
    logit_bias: Optional[Dict[str, float]] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    user: Optional[str] = None
    seed: Optional[int] = None
    parallel_tool_calls: Optional[bool] = None
    
    model_config = {"extra": "allow"}


# ==================================================================================================
# Модели для ответов
# ==================================================================================================

class ChatCompletionChoice(BaseModel):
    """
    Один вариант ответа в Chat Completion.
    
    Attributes:
        index: Индекс варианта
        message: Сообщение ответа
        finish_reason: Причина завершения (stop, tool_calls, length)
    """
    index: int = 0
    message: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
    """
    Информация об использовании токенов.
    
    Attributes:
        prompt_tokens: Количество токенов в запросе
        completion_tokens: Количество токенов в ответе
        total_tokens: Общее количество токенов
        credits_used: Использованные кредиты (специфично для Kiro)
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    credits_used: Optional[float] = None


class ChatCompletionResponse(BaseModel):
    """
    Полный ответ Chat Completion (non-streaming).
    
    Attributes:
        id: Уникальный ID ответа
        object: Тип объекта ("chat.completion")
        created: Timestamp создания
        model: Использованная модель
        choices: Список вариантов ответа
        usage: Информация об использовании токенов
    """
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage


class ChatCompletionChunkDelta(BaseModel):
    """
    Дельта изменений в streaming chunk.
    
    Attributes:
        role: Роль (только в первом chunk)
        content: Новый контент
        tool_calls: Новые tool calls
    """
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatCompletionChunkChoice(BaseModel):
    """
    Один вариант в streaming chunk.
    
    Attributes:
        index: Индекс варианта
        delta: Дельта изменений
        finish_reason: Причина завершения (только в последнем chunk)
    """
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """
    Streaming chunk в формате OpenAI.
    
    Attributes:
        id: Уникальный ID ответа
        object: Тип объекта ("chat.completion.chunk")
        created: Timestamp создания
        model: Использованная модель
        choices: Список вариантов
        usage: Информация об использовании (только в последнем chunk)
    """
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChunkChoice]
    usage: Optional[ChatCompletionUsage] = None


# ==================================================================================================
# OAuth Models
# ==================================================================================================

class OAuthStartRequest(BaseModel):
    """
    Request to start OAuth authentication.
    
    Attributes:
        method: Auth method - "google", "github", or "builder-id"
        port: Optional specific port for callback server
    """
    method: str = Field(
        ...,
        description="Auth method: 'google', 'github', or 'builder-id'"
    )
    port: Optional[int] = Field(
        None,
        description="Specific port for callback server (optional)"
    )


class OAuthStartResponse(BaseModel):
    """
    Response from starting OAuth authentication.
    
    Attributes:
        auth_url: URL to open in browser for authentication
        method: Auth method used
        provider: Provider name (for social auth)
        port: Callback server port (for social auth)
        redirect_uri: Full redirect URI (for social auth)
        user_code: User code to enter (for device code flow)
        verification_uri: Verification URL (for device code flow)
        expires_in: Seconds until auth expires
        interval: Polling interval (for device code flow)
    """
    auth_url: str
    method: str
    provider: Optional[str] = None
    port: Optional[int] = None
    redirect_uri: Optional[str] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: int = 600
    interval: Optional[int] = None


class OAuthStatusResponse(BaseModel):
    """
    Response for OAuth status check.
    
    Attributes:
        in_progress: Whether auth is in progress
        method: Auth method (if in progress)
        provider: Provider name (if social auth)
        started_at: ISO timestamp when auth started
    """
    in_progress: bool = False
    method: Optional[str] = None
    provider: Optional[str] = None
    started_at: Optional[str] = None