# -*- coding: utf-8 -*-

"""
Unit-тесты для конвертеров OpenAI <-> Kiro.
Проверяет логику преобразования форматов сообщений и payload.
"""

import pytest

from kiro_gateway.converters import (
    extract_text_content,
    merge_adjacent_messages,
    build_kiro_history,
    build_kiro_payload,
    _extract_tool_results,
    _extract_tool_uses,
    _build_user_input_context
)
from kiro_gateway.models import ChatMessage, ChatCompletionRequest, Tool, ToolFunction


class TestExtractTextContent:
    """Тесты функции extract_text_content."""
    
    def test_extracts_from_string(self):
        """
        Что он делает: Проверяет извлечение текста из строки.
        Цель: Убедиться, что строка возвращается как есть.
        """
        print("Настройка: Простая строка...")
        content = "Hello, World!"
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось 'Hello, World!', Получено '{result}'")
        assert result == "Hello, World!"
    
    def test_extracts_from_none(self):
        """
        Что он делает: Проверяет обработку None.
        Цель: Убедиться, что None возвращает пустую строку.
        """
        print("Настройка: None...")
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(None)
        
        print(f"Сравниваем результат: Ожидалось '', Получено '{result}'")
        assert result == ""
    
    def test_extracts_from_list_with_text_type(self):
        """
        Что он делает: Проверяет извлечение из списка с type=text.
        Цель: Убедиться, что OpenAI multimodal формат обрабатывается.
        """
        print("Настройка: Список с type=text...")
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": " World"}
        ]
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось 'Hello World', Получено '{result}'")
        assert result == "Hello World"
    
    def test_extracts_from_list_with_text_key(self):
        """
        Что он делает: Проверяет извлечение из списка с ключом text.
        Цель: Убедиться, что альтернативный формат обрабатывается.
        """
        print("Настройка: Список с ключом text...")
        content = [{"text": "Hello"}, {"text": " World"}]
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось 'Hello World', Получено '{result}'")
        assert result == "Hello World"
    
    def test_extracts_from_list_with_strings(self):
        """
        Что он делает: Проверяет извлечение из списка строк.
        Цель: Убедиться, что список строк объединяется.
        """
        print("Настройка: Список строк...")
        content = ["Hello", " ", "World"]
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось 'Hello World', Получено '{result}'")
        assert result == "Hello World"
    
    def test_extracts_from_mixed_list(self):
        """
        Что он делает: Проверяет извлечение из смешанного списка.
        Цель: Убедиться, что разные форматы в одном списке обрабатываются.
        """
        print("Настройка: Смешанный список...")
        content = [
            {"type": "text", "text": "Part1"},
            "Part2",
            {"text": "Part3"}
        ]
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось 'Part1Part2Part3', Получено '{result}'")
        assert result == "Part1Part2Part3"
    
    def test_converts_other_types_to_string(self):
        """
        Что он делает: Проверяет конвертацию других типов в строку.
        Цель: Убедиться, что числа и другие типы преобразуются.
        """
        print("Настройка: Число...")
        content = 42
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось '42', Получено '{result}'")
        assert result == "42"
    
    def test_handles_empty_list(self):
        """
        Что он делает: Проверяет обработку пустого списка.
        Цель: Убедиться, что пустой список возвращает пустую строку.
        """
        print("Настройка: Пустой список...")
        content = []
        
        print("Действие: Извлечение текста...")
        result = extract_text_content(content)
        
        print(f"Сравниваем результат: Ожидалось '', Получено '{result}'")
        assert result == ""


class TestMergeAdjacentMessages:
    """Тесты функции merge_adjacent_messages."""
    
    def test_merges_adjacent_user_messages(self):
        """
        Что он делает: Проверяет объединение соседних user сообщений.
        Цель: Убедиться, что сообщения с одинаковой ролью объединяются.
        """
        print("Настройка: Два user сообщения подряд...")
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="user", content="World")
        ]
        
        print("Действие: Объединение сообщений...")
        result = merge_adjacent_messages(messages)
        
        print(f"Сравниваем длину: Ожидалось 1, Получено {len(result)}")
        assert len(result) == 1
        assert "Hello" in result[0].content
        assert "World" in result[0].content
    
    def test_preserves_alternating_messages(self):
        """
        Что он делает: Проверяет сохранение чередующихся сообщений.
        Цель: Убедиться, что разные роли не объединяются.
        """
        print("Настройка: Чередующиеся сообщения...")
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
            ChatMessage(role="user", content="How are you?")
        ]
        
        print("Действие: Объединение сообщений...")
        result = merge_adjacent_messages(messages)
        
        print(f"Сравниваем длину: Ожидалось 3, Получено {len(result)}")
        assert len(result) == 3
    
    def test_handles_empty_list(self):
        """
        Что он делает: Проверяет обработку пустого списка.
        Цель: Убедиться, что пустой список не вызывает ошибок.
        """
        print("Настройка: Пустой список...")
        
        print("Действие: Объединение сообщений...")
        result = merge_adjacent_messages([])
        
        print(f"Сравниваем результат: Ожидалось [], Получено {result}")
        assert result == []
    
    def test_handles_single_message(self):
        """
        Что он делает: Проверяет обработку одного сообщения.
        Цель: Убедиться, что одно сообщение возвращается как есть.
        """
        print("Настройка: Одно сообщение...")
        messages = [ChatMessage(role="user", content="Hello")]
        
        print("Действие: Объединение сообщений...")
        result = merge_adjacent_messages(messages)
        
        print(f"Сравниваем длину: Ожидалось 1, Получено {len(result)}")
        assert len(result) == 1
        assert result[0].content == "Hello"
    
    def test_merges_multiple_adjacent_groups(self):
        """
        Что он делает: Проверяет объединение нескольких групп.
        Цель: Убедиться, что несколько групп соседних сообщений объединяются.
        """
        print("Настройка: Несколько групп соседних сообщений...")
        messages = [
            ChatMessage(role="user", content="A"),
            ChatMessage(role="user", content="B"),
            ChatMessage(role="assistant", content="C"),
            ChatMessage(role="assistant", content="D"),
            ChatMessage(role="user", content="E")
        ]
        
        print("Действие: Объединение сообщений...")
        result = merge_adjacent_messages(messages)
        
        print(f"Сравниваем длину: Ожидалось 3, Получено {len(result)}")
        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "user"


class TestBuildKiroHistory:
    """Тесты функции build_kiro_history."""
    
    def test_builds_user_message(self):
        """
        Что он делает: Проверяет построение user сообщения.
        Цель: Убедиться, что user сообщение преобразуется в userInputMessage.
        """
        print("Настройка: User сообщение...")
        messages = [ChatMessage(role="user", content="Hello")]
        
        print("Действие: Построение истории...")
        result = build_kiro_history(messages, "claude-sonnet-4")
        
        print(f"Результат: {result}")
        assert len(result) == 1
        assert "userInputMessage" in result[0]
        assert result[0]["userInputMessage"]["content"] == "Hello"
        assert result[0]["userInputMessage"]["modelId"] == "claude-sonnet-4"
    
    def test_builds_assistant_message(self):
        """
        Что он делает: Проверяет построение assistant сообщения.
        Цель: Убедиться, что assistant сообщение преобразуется в assistantResponseMessage.
        """
        print("Настройка: Assistant сообщение...")
        messages = [ChatMessage(role="assistant", content="Hi there")]
        
        print("Действие: Построение истории...")
        result = build_kiro_history(messages, "claude-sonnet-4")
        
        print(f"Результат: {result}")
        assert len(result) == 1
        assert "assistantResponseMessage" in result[0]
        assert result[0]["assistantResponseMessage"]["content"] == "Hi there"
    
    def test_ignores_system_messages(self):
        """
        Что он делает: Проверяет игнорирование system сообщений.
        Цель: Убедиться, что system сообщения не добавляются в историю.
        """
        print("Настройка: System сообщение...")
        messages = [ChatMessage(role="system", content="You are helpful")]
        
        print("Действие: Построение истории...")
        result = build_kiro_history(messages, "claude-sonnet-4")
        
        print(f"Сравниваем длину: Ожидалось 0, Получено {len(result)}")
        assert len(result) == 0
    
    def test_builds_conversation_history(self):
        """
        Что он делает: Проверяет построение полной истории разговора.
        Цель: Убедиться, что чередование user/assistant сохраняется.
        """
        print("Настройка: Полная история разговора...")
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi"),
            ChatMessage(role="user", content="How are you?")
        ]
        
        print("Действие: Построение истории...")
        result = build_kiro_history(messages, "claude-sonnet-4")
        
        print(f"Результат: {result}")
        assert len(result) == 3
        assert "userInputMessage" in result[0]
        assert "assistantResponseMessage" in result[1]
        assert "userInputMessage" in result[2]
    
    def test_handles_empty_list(self):
        """
        Что он делает: Проверяет обработку пустого списка.
        Цель: Убедиться, что пустой список возвращает пустую историю.
        """
        print("Настройка: Пустой список...")
        
        print("Действие: Построение истории...")
        result = build_kiro_history([], "claude-sonnet-4")
        
        print(f"Сравниваем результат: Ожидалось [], Получено {result}")
        assert result == []


class TestExtractToolResults:
    """Тесты функции _extract_tool_results."""
    
    def test_extracts_tool_results_from_list(self):
        """
        Что он делает: Проверяет извлечение tool results из списка.
        Цель: Убедиться, что tool_result элементы извлекаются.
        """
        print("Настройка: Список с tool_result...")
        content = [
            {"type": "tool_result", "tool_use_id": "call_123", "content": "Result text"}
        ]
        
        print("Действие: Извлечение tool results...")
        result = _extract_tool_results(content)
        
        print(f"Результат: {result}")
        assert len(result) == 1
        assert result[0]["toolUseId"] == "call_123"
        assert result[0]["status"] == "success"
    
    def test_returns_empty_for_string_content(self):
        """
        Что он делает: Проверяет возврат пустого списка для строки.
        Цель: Убедиться, что строка не содержит tool results.
        """
        print("Настройка: Строка...")
        content = "Just a string"
        
        print("Действие: Извлечение tool results...")
        result = _extract_tool_results(content)
        
        print(f"Сравниваем результат: Ожидалось [], Получено {result}")
        assert result == []
    
    def test_returns_empty_for_list_without_tool_results(self):
        """
        Что он делает: Проверяет возврат пустого списка без tool_result.
        Цель: Убедиться, что обычные элементы не извлекаются.
        """
        print("Настройка: Список без tool_result...")
        content = [{"type": "text", "text": "Hello"}]
        
        print("Действие: Извлечение tool results...")
        result = _extract_tool_results(content)
        
        print(f"Сравниваем результат: Ожидалось [], Получено {result}")
        assert result == []


class TestExtractToolUses:
    """Тесты функции _extract_tool_uses."""
    
    def test_extracts_from_tool_calls_field(self):
        """
        Что он делает: Проверяет извлечение из поля tool_calls.
        Цель: Убедиться, что OpenAI tool_calls формат обрабатывается.
        """
        print("Настройка: Сообщение с tool_calls...")
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{
                "id": "call_123",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Moscow"}'
                }
            }]
        )
        
        print("Действие: Извлечение tool uses...")
        result = _extract_tool_uses(msg)
        
        print(f"Результат: {result}")
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["toolUseId"] == "call_123"
    
    def test_extracts_from_content_list(self):
        """
        Что он делает: Проверяет извлечение из content списка.
        Цель: Убедиться, что tool_use в content обрабатывается.
        """
        print("Настройка: Сообщение с tool_use в content...")
        msg = ChatMessage(
            role="assistant",
            content=[{
                "type": "tool_use",
                "id": "call_456",
                "name": "search",
                "input": {"query": "test"}
            }]
        )
        
        print("Действие: Извлечение tool uses...")
        result = _extract_tool_uses(msg)
        
        print(f"Результат: {result}")
        assert len(result) == 1
        assert result[0]["name"] == "search"
        assert result[0]["toolUseId"] == "call_456"
    
    def test_returns_empty_for_no_tool_uses(self):
        """
        Что он делает: Проверяет возврат пустого списка без tool uses.
        Цель: Убедиться, что обычное сообщение не содержит tool uses.
        """
        print("Настройка: Обычное сообщение...")
        msg = ChatMessage(role="assistant", content="Hello")
        
        print("Действие: Извлечение tool uses...")
        result = _extract_tool_uses(msg)
        
        print(f"Сравниваем результат: Ожидалось [], Получено {result}")
        assert result == []


class TestBuildUserInputContext:
    """Тесты функции _build_user_input_context."""
    
    def test_builds_tools_context(self):
        """
        Что он делает: Проверяет построение контекста с tools.
        Цель: Убедиться, что tools преобразуются в toolSpecification.
        """
        print("Настройка: Запрос с tools...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4",
            messages=[ChatMessage(role="user", content="Hello")],
            tools=[Tool(
                type="function",
                function=ToolFunction(
                    name="get_weather",
                    description="Get weather",
                    parameters={"type": "object", "properties": {}}
                )
            )]
        )
        current_msg = ChatMessage(role="user", content="Hello")
        
        print("Действие: Построение контекста...")
        result = _build_user_input_context(request, current_msg)
        
        print(f"Результат: {result}")
        assert "tools" in result
        assert len(result["tools"]) == 1
        assert result["tools"][0]["toolSpecification"]["name"] == "get_weather"
    
    def test_returns_empty_for_no_tools(self):
        """
        Что он делает: Проверяет возврат пустого контекста без tools.
        Цель: Убедиться, что запрос без tools возвращает пустой контекст.
        """
        print("Настройка: Запрос без tools...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4",
            messages=[ChatMessage(role="user", content="Hello")]
        )
        current_msg = ChatMessage(role="user", content="Hello")
        
        print("Действие: Построение контекста...")
        result = _build_user_input_context(request, current_msg)
        
        print(f"Сравниваем результат: Ожидалось {{}}, Получено {result}")
        assert result == {}


class TestBuildKiroPayload:
    """Тесты функции build_kiro_payload."""
    
    def test_builds_simple_payload(self):
        """
        Что он делает: Проверяет построение простого payload.
        Цель: Убедиться, что базовый запрос преобразуется корректно.
        """
        print("Настройка: Простой запрос...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="Hello")]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "arn:aws:test")
        
        print(f"Результат: {result}")
        assert "conversationState" in result
        assert result["conversationState"]["conversationId"] == "conv-123"
        assert "currentMessage" in result["conversationState"]
        assert result["profileArn"] == "arn:aws:test"
    
    def test_includes_system_prompt_in_first_message(self):
        """
        Что он делает: Проверяет добавление system prompt к первому сообщению.
        Цель: Убедиться, что system prompt объединяется с user сообщением.
        """
        print("Настройка: Запрос с system prompt...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(role="system", content="You are helpful"),
                ChatMessage(role="user", content="Hello")
            ]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "")
        
        print(f"Результат: {result}")
        current_content = result["conversationState"]["currentMessage"]["userInputMessage"]["content"]
        assert "You are helpful" in current_content
        assert "Hello" in current_content
    
    def test_builds_history_for_multi_turn(self):
        """
        Что он делает: Проверяет построение истории для multi-turn.
        Цель: Убедиться, что предыдущие сообщения попадают в history.
        """
        print("Настройка: Multi-turn запрос...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi"),
                ChatMessage(role="user", content="How are you?")
            ]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "")
        
        print(f"Результат: {result}")
        assert "history" in result["conversationState"]
        assert len(result["conversationState"]["history"]) == 2
    
    def test_handles_assistant_as_last_message(self):
        """
        Что он делает: Проверяет обработку assistant как последнего сообщения.
        Цель: Убедиться, что создаётся "Continue" сообщение.
        """
        print("Настройка: Запрос с assistant в конце...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there")
            ]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "")
        
        print(f"Результат: {result}")
        current_content = result["conversationState"]["currentMessage"]["userInputMessage"]["content"]
        assert current_content == "Continue"
    
    def test_raises_for_empty_messages(self):
        """
        Что он делает: Проверяет выброс исключения для пустых сообщений.
        Цель: Убедиться, что пустой запрос вызывает ValueError.
        """
        print("Настройка: Запрос только с system сообщением...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="system", content="You are helpful")]
        )
        
        print("Действие: Попытка построения payload...")
        with pytest.raises(ValueError) as exc_info:
            build_kiro_payload(request, "conv-123", "")
        
        print(f"Исключение: {exc_info.value}")
        assert "Нет сообщений" in str(exc_info.value)
    
    def test_uses_continue_for_empty_content(self):
        """
        Что он делает: Проверяет использование "Continue" для пустого контента.
        Цель: Убедиться, что пустое сообщение заменяется на "Continue".
        """
        print("Настройка: Запрос с пустым контентом...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="")]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "")
        
        print(f"Результат: {result}")
        current_content = result["conversationState"]["currentMessage"]["userInputMessage"]["content"]
        assert current_content == "Continue"
    
    def test_maps_model_id_correctly(self):
        """
        Что он делает: Проверяет маппинг внешнего ID модели во внутренний.
        Цель: Убедиться, что MODEL_MAPPING применяется.
        """
        print("Настройка: Запрос с внешним ID модели...")
        request = ChatCompletionRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="Hello")]
        )
        
        print("Действие: Построение payload...")
        result = build_kiro_payload(request, "conv-123", "")
        
        print(f"Результат: {result}")
        model_id = result["conversationState"]["currentMessage"]["userInputMessage"]["modelId"]
        # claude-sonnet-4-5 должен маппиться в CLAUDE_SONNET_4_5_20250929_V1_0
        assert model_id == "CLAUDE_SONNET_4_5_20250929_V1_0"