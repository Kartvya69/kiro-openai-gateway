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
Конвертеры для преобразования форматов OpenAI <-> Kiro.

Содержит функции для:
- Извлечения текстового контента из различных форматов
- Объединения соседних сообщений
- Построения истории разговора для Kiro API
- Сборки полного payload для запроса
"""

import json
from typing import Any, Dict, List

from loguru import logger

from kiro_gateway.config import get_internal_model_id
from kiro_gateway.models import ChatMessage, ChatCompletionRequest


def extract_text_content(content: Any) -> str:
    """
    Извлекает текстовый контент из различных форматов.
    
    OpenAI API поддерживает несколько форматов content:
    - Строка: "Hello, world!"
    - Список: [{"type": "text", "text": "Hello"}]
    - None: пустое сообщение
    
    Args:
        content: Контент в любом поддерживаемом формате
    
    Returns:
        Извлечённый текст или пустая строка
    
    Example:
        >>> extract_text_content("Hello")
        'Hello'
        >>> extract_text_content([{"type": "text", "text": "World"}])
        'World'
        >>> extract_text_content(None)
        ''
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif "text" in item:
                    text_parts.append(item["text"])
            elif isinstance(item, str):
                text_parts.append(item)
        return "".join(text_parts)
    return str(content)


def merge_adjacent_messages(messages: List[ChatMessage]) -> List[ChatMessage]:
    """
    Объединяет соседние сообщения с одинаковой ролью.
    
    Kiro API не принимает несколько сообщений подряд от одного role.
    Эта функция объединяет такие сообщения в одно.
    
    Args:
        messages: Список сообщений
    
    Returns:
        Список сообщений с объединёнными соседними сообщениями
    
    Example:
        >>> msgs = [
        ...     ChatMessage(role="user", content="Hello"),
        ...     ChatMessage(role="user", content="World")
        ... ]
        >>> merged = merge_adjacent_messages(msgs)
        >>> len(merged)
        1
        >>> merged[0].content
        'Hello\\nWorld'
    """
    if not messages:
        return []
    
    merged = []
    for msg in messages:
        if not merged:
            merged.append(msg)
            continue
        
        last = merged[-1]
        if msg.role == last.role:
            # Объединяем контент
            last_text = extract_text_content(last.content)
            current_text = extract_text_content(msg.content)
            last.content = f"{last_text}\n{current_text}"
            logger.debug(f"Merged adjacent messages with role {msg.role}")
        else:
            merged.append(msg)
    
    return merged


def build_kiro_history(messages: List[ChatMessage], model_id: str) -> List[Dict[str, Any]]:
    """
    Строит массив history для Kiro API из OpenAI messages.
    
    Kiro API ожидает чередование userInputMessage и assistantResponseMessage.
    Эта функция преобразует OpenAI формат в Kiro формат.
    
    Args:
        messages: Список сообщений в формате OpenAI
        model_id: Внутренний ID модели Kiro
    
    Returns:
        Список словарей для поля history в Kiro API
    
    Example:
        >>> msgs = [ChatMessage(role="user", content="Hello")]
        >>> history = build_kiro_history(msgs, "claude-sonnet-4")
        >>> history[0]["userInputMessage"]["content"]
        'Hello'
    """
    history = []
    
    for msg in messages:
        if msg.role == "user":
            content = extract_text_content(msg.content)
            
            user_input = {
                "content": content,
                "modelId": model_id,
                "origin": "AI_EDITOR",
            }
            
            # Обработка tool_results (ответы на tool calls)
            tool_results = _extract_tool_results(msg.content)
            if tool_results:
                user_input["userInputMessageContext"] = {"toolResults": tool_results}
            
            history.append({"userInputMessage": user_input})
            
        elif msg.role == "assistant":
            content = extract_text_content(msg.content)
            
            assistant_response = {"content": content}
            
            # Обработка tool_calls
            tool_uses = _extract_tool_uses(msg)
            if tool_uses:
                assistant_response["toolUses"] = tool_uses
            
            history.append({"assistantResponseMessage": assistant_response})
            
        elif msg.role == "system":
            # System prompt обрабатывается отдельно в build_kiro_payload
            pass
    
    return history


def _extract_tool_results(content: Any) -> List[Dict[str, Any]]:
    """
    Извлекает tool results из контента сообщения.
    
    Args:
        content: Контент сообщения (может быть списком)
    
    Returns:
        Список tool results в формате Kiro
    """
    tool_results = []
    
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                tool_results.append({
                    "content": [{"text": extract_text_content(item.get("content", ""))}],
                    "status": "success",
                    "toolUseId": item.get("tool_use_id", "")
                })
    
    return tool_results


def _extract_tool_uses(msg: ChatMessage) -> List[Dict[str, Any]]:
    """
    Извлекает tool uses из сообщения assistant.
    
    Args:
        msg: Сообщение assistant
    
    Returns:
        Список tool uses в формате Kiro
    """
    tool_uses = []
    
    # Из поля tool_calls
    if msg.tool_calls:
        for tc in msg.tool_calls:
            if isinstance(tc, dict):
                tool_uses.append({
                    "name": tc.get("function", {}).get("name", ""),
                    "input": json.loads(tc.get("function", {}).get("arguments", "{}")),
                    "toolUseId": tc.get("id", "")
                })
    
    # Из content (если там есть tool_use)
    if isinstance(msg.content, list):
        for item in msg.content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_uses.append({
                    "name": item.get("name", ""),
                    "input": item.get("input", {}),
                    "toolUseId": item.get("id", "")
                })
    
    return tool_uses


def build_kiro_payload(
    request_data: ChatCompletionRequest,
    conversation_id: str,
    profile_arn: str
) -> dict:
    """
    Строит полный payload для Kiro API.
    
    Включает:
    - Полную историю сообщений
    - System prompt (добавляется к первому user сообщению)
    - Tools definitions
    - Текущее сообщение
    
    Args:
        request_data: Запрос в формате OpenAI
        conversation_id: Уникальный ID разговора
        profile_arn: ARN профиля AWS CodeWhisperer
    
    Returns:
        Словарь payload для POST запроса к Kiro API
    
    Raises:
        ValueError: Если нет сообщений для отправки
    """
    messages = list(request_data.messages)
    
    # Извлекаем system prompt
    system_prompt = ""
    non_system_messages = []
    for msg in messages:
        if msg.role == "system":
            system_prompt += extract_text_content(msg.content) + "\n"
        else:
            non_system_messages.append(msg)
    system_prompt = system_prompt.strip()
    
    # Объединяем соседние сообщения с одинаковой ролью
    merged_messages = merge_adjacent_messages(non_system_messages)
    
    if not merged_messages:
        raise ValueError("Нет сообщений для отправки")
    
    # Получаем внутренний ID модели
    model_id = get_internal_model_id(request_data.model)
    
    # Строим историю (все сообщения кроме последнего)
    history_messages = merged_messages[:-1] if len(merged_messages) > 1 else []
    
    # Если есть system prompt, добавляем его к первому user сообщению в истории
    if system_prompt and history_messages:
        first_msg = history_messages[0]
        if first_msg.role == "user":
            original_content = extract_text_content(first_msg.content)
            first_msg.content = f"{system_prompt}\n\n{original_content}"
    
    history = build_kiro_history(history_messages, model_id)
    
    # Текущее сообщение (последнее)
    current_message = merged_messages[-1]
    current_content = extract_text_content(current_message.content)
    
    # Если system prompt есть, но история пуста - добавляем к текущему сообщению
    if system_prompt and not history:
        current_content = f"{system_prompt}\n\n{current_content}"
    
    # Если текущее сообщение - assistant, нужно добавить его в историю
    # и создать user сообщение "Continue"
    if current_message.role == "assistant":
        history.append({
            "assistantResponseMessage": {
                "content": current_content
            }
        })
        current_content = "Continue"
    
    # Если контент пустой
    if not current_content:
        current_content = "Continue"
    
    # Строим userInputMessage
    user_input_message = {
        "content": current_content,
        "modelId": model_id,
        "origin": "AI_EDITOR",
    }
    
    # Добавляем tools и tool_results если есть
    user_input_context = _build_user_input_context(request_data, current_message)
    if user_input_context:
        user_input_message["userInputMessageContext"] = user_input_context
    
    # Собираем финальный payload
    payload = {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": conversation_id,
            "currentMessage": {
                "userInputMessage": user_input_message
            }
        }
    }
    
    # Добавляем историю только если она не пуста
    if history:
        payload["conversationState"]["history"] = history
    
    # Добавляем profileArn
    if profile_arn:
        payload["profileArn"] = profile_arn
    
    return payload


def _build_user_input_context(
    request_data: ChatCompletionRequest,
    current_message: ChatMessage
) -> Dict[str, Any]:
    """
    Строит userInputMessageContext для текущего сообщения.
    
    Включает tools definitions и tool_results.
    
    Args:
        request_data: Запрос с tools
        current_message: Текущее сообщение
    
    Returns:
        Словарь с контекстом или пустой словарь
    """
    context = {}
    
    # Добавляем tools если есть
    if request_data.tools:
        tools_list = []
        for tool in request_data.tools:
            if tool.type == "function":
                tools_list.append({
                    "toolSpecification": {
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "inputSchema": {"json": tool.function.parameters or {}}
                    }
                })
        if tools_list:
            context["tools"] = tools_list
    
    # Обработка tool_results в текущем сообщении
    tool_results = _extract_tool_results(current_message.content)
    if tool_results:
        context["toolResults"] = tool_results
    
    return context