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
Парсеры для AWS Event Stream формата.

Содержит классы и функции для:
- Парсинга бинарного AWS SSE потока
- Извлечения JSON событий
- Обработки tool calls
- Дедупликации контента
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from kiro_gateway.utils import generate_tool_call_id


def find_matching_brace(text: str, start_pos: int) -> int:
    """
    Находит позицию закрывающей скобки с учётом вложенности и строк.
    
    Использует bracket counting для корректного парсинга вложенных JSON.
    Учитывает строки в кавычках и escape-последовательности.
    
    Args:
        text: Текст для поиска
        start_pos: Позиция открывающей скобки '{'
    
    Returns:
        Позиция закрывающей скобки или -1 если не найдена
    
    Example:
        >>> find_matching_brace('{"a": {"b": 1}}', 0)
        14
        >>> find_matching_brace('{"a": "{}"}', 0)
        10
    """
    if start_pos >= len(text) or text[start_pos] != '{':
        return -1
    
    brace_count = 0
    in_string = False
    escape_next = False
    
    for i in range(start_pos, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\' and in_string:
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i
    
    return -1


def parse_bracket_tool_calls(response_text: str) -> List[Dict[str, Any]]:
    """
    Парсит tool calls в формате [Called func_name with args: {...}].
    
    Некоторые модели возвращают tool calls в текстовом формате вместо
    структурированного JSON. Эта функция извлекает их.
    
    Args:
        response_text: Текст ответа модели
    
    Returns:
        Список tool calls в формате OpenAI
    
    Example:
        >>> text = "[Called get_weather with args: {\"city\": \"London\"}]"
        >>> calls = parse_bracket_tool_calls(text)
        >>> calls[0]["function"]["name"]
        'get_weather'
    """
    if not response_text or "[Called" not in response_text:
        return []
    
    tool_calls = []
    pattern = r'\[Called\s+(\w+)\s+with\s+args:\s*'
    
    for match in re.finditer(pattern, response_text, re.IGNORECASE):
        func_name = match.group(1)
        args_start = match.end()
        
        # Ищем начало JSON
        json_start = response_text.find('{', args_start)
        if json_start == -1:
            continue
        
        # Ищем конец JSON с учётом вложенности
        json_end = find_matching_brace(response_text, json_start)
        if json_end == -1:
            continue
        
        json_str = response_text[json_start:json_end + 1]
        
        try:
            args = json.loads(json_str)
            tool_call_id = generate_tool_call_id()
            tool_calls.append({
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps(args)
                }
            })
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse tool call arguments: {json_str[:100]}")
    
    return tool_calls


def deduplicate_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Удаляет дубликаты tool calls по имени и аргументам.
    
    Args:
        tool_calls: Список tool calls
    
    Returns:
        Список уникальных tool calls
    """
    seen = set()
    unique = []
    
    for tc in tool_calls:
        key = f"{tc['function']['name']}-{tc['function']['arguments']}"
        if key not in seen:
            seen.add(key)
            unique.append(tc)
    
    return unique


class AwsEventStreamParser:
    """
    Парсер для AWS Event Stream формата.
    
    AWS возвращает события в бинарном формате с разделителями :message-type...event.
    Этот класс извлекает JSON события из потока и преобразует их в удобный формат.
    
    Поддерживаемые типы событий:
    - content: Текстовый контент ответа
    - tool_start: Начало tool call (name, toolUseId)
    - tool_input: Продолжение input для tool call
    - tool_stop: Завершение tool call
    - usage: Информация о потреблении кредитов
    - context_usage: Процент использования контекста
    
    Attributes:
        buffer: Буфер для накопления данных
        last_content: Последний обработанный контент (для дедупликации)
        current_tool_call: Текущий незавершённый tool call
        tool_calls: Список завершённых tool calls
    
    Example:
        >>> parser = AwsEventStreamParser()
        >>> events = parser.feed(chunk)
        >>> for event in events:
        ...     if event["type"] == "content":
        ...         print(event["data"])
    """
    
    # Паттерны для поиска JSON событий
    EVENT_PATTERNS = [
        ('{"content":', 'content'),
        ('{"name":', 'tool_start'),
        ('{"input":', 'tool_input'),
        ('{"stop":', 'tool_stop'),
        ('{"followupPrompt":', 'followup'),
        ('{"usage":', 'usage'),
        ('{"contextUsagePercentage":', 'context_usage'),
    ]
    
    def __init__(self):
        """Инициализирует парсер."""
        self.buffer = ""
        self.last_content: Optional[str] = None  # Для дедупликации повторяющегося контента
        self.current_tool_call: Optional[Dict[str, Any]] = None
        self.tool_calls: List[Dict[str, Any]] = []
    
    def feed(self, chunk: bytes) -> List[Dict[str, Any]]:
        """
        Добавляет chunk в буфер и возвращает распарсенные события.
        
        Args:
            chunk: Байты данных из потока
        
        Returns:
            Список событий в формате {"type": str, "data": Any}
        """
        try:
            self.buffer += chunk.decode('utf-8', errors='ignore')
        except Exception:
            return []
        
        events = []
        
        while True:
            # Находим ближайший паттерн
            earliest_pos = -1
            earliest_type = None
            
            for pattern, event_type in self.EVENT_PATTERNS:
                pos = self.buffer.find(pattern)
                if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                    earliest_pos = pos
                    earliest_type = event_type
            
            if earliest_pos == -1:
                break
            
            # Ищем конец JSON
            json_end = find_matching_brace(self.buffer, earliest_pos)
            if json_end == -1:
                # JSON не полный, ждём больше данных
                break
            
            json_str = self.buffer[earliest_pos:json_end + 1]
            self.buffer = self.buffer[json_end + 1:]
            
            try:
                data = json.loads(json_str)
                event = self._process_event(data, earliest_type)
                if event:
                    events.append(event)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON: {json_str[:100]}")
        
        return events
    
    def _process_event(self, data: dict, event_type: str) -> Optional[Dict[str, Any]]:
        """
        Обрабатывает распарсенное событие.
        
        Args:
            data: Распарсенный JSON
            event_type: Тип события
        
        Returns:
            Обработанное событие или None
        """
        if event_type == 'content':
            return self._process_content_event(data)
        elif event_type == 'tool_start':
            return self._process_tool_start_event(data)
        elif event_type == 'tool_input':
            return self._process_tool_input_event(data)
        elif event_type == 'tool_stop':
            return self._process_tool_stop_event(data)
        elif event_type == 'usage':
            return {"type": "usage", "data": data.get('usage', 0)}
        elif event_type == 'context_usage':
            return {"type": "context_usage", "data": data.get('contextUsagePercentage', 0)}
        
        return None
    
    def _process_content_event(self, data: dict) -> Optional[Dict[str, Any]]:
        """Обрабатывает событие с контентом."""
        content = data.get('content', '')
        
        # Пропускаем followupPrompt
        if data.get('followupPrompt'):
            return None
        
        # Дедупликация повторяющегося контента
        if content == self.last_content:
            return None
        
        self.last_content = content
        
        return {"type": "content", "data": content}
    
    def _process_tool_start_event(self, data: dict) -> Optional[Dict[str, Any]]:
        """Обрабатывает начало tool call."""
        # Завершаем предыдущий tool call если есть
        if self.current_tool_call:
            self._finalize_tool_call()
        
        self.current_tool_call = {
            "id": data.get('toolUseId', generate_tool_call_id()),
            "type": "function",
            "function": {
                "name": data.get('name', ''),
                "arguments": data.get('input', '')
            }
        }
        
        if data.get('stop'):
            self._finalize_tool_call()
        
        return None
    
    def _process_tool_input_event(self, data: dict) -> Optional[Dict[str, Any]]:
        """Обрабатывает продолжение input для tool call."""
        if self.current_tool_call:
            self.current_tool_call['function']['arguments'] += data.get('input', '')
        return None
    
    def _process_tool_stop_event(self, data: dict) -> Optional[Dict[str, Any]]:
        """Обрабатывает завершение tool call."""
        if self.current_tool_call and data.get('stop'):
            self._finalize_tool_call()
        return None
    
    def _finalize_tool_call(self) -> None:
        """Завершает текущий tool call и добавляет в список."""
        if not self.current_tool_call:
            return
        
        # Пытаемся распарсить arguments как JSON
        args = self.current_tool_call['function']['arguments']
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                self.current_tool_call['function']['arguments'] = json.dumps(parsed)
            except json.JSONDecodeError:
                pass
        
        self.tool_calls.append(self.current_tool_call)
        self.current_tool_call = None
    
    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """
        Возвращает все собранные tool calls.
        
        Завершает текущий tool call если он не завершён.
        Удаляет дубликаты.
        
        Returns:
            Список уникальных tool calls
        """
        if self.current_tool_call:
            self._finalize_tool_call()
        return deduplicate_tool_calls(self.tool_calls)
    
    def reset(self) -> None:
        """Сбрасывает состояние парсера."""
        self.buffer = ""
        self.last_content = None
        self.current_tool_call = None
        self.tool_calls = []