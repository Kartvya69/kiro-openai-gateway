# -*- coding: utf-8 -*-

"""
Общие фикстуры и утилиты для тестирования Kiro OpenAI Gateway.

Обеспечивает изоляцию тестов от внешних сервисов и глобального состояния.
Все тесты ДОЛЖНЫ быть полностью изолированы от сети.
"""

import asyncio
import json
import pytest
import time
from typing import AsyncGenerator, Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient


# =============================================================================
# Event Loop фикстуры
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """
    Создает event loop для всей сессии тестов.
    Необходимо для корректной работы async фикстур.
    """
    print("Создание event loop для сессии тестов...")
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    print("Закрытие event loop...")
    loop.close()


# =============================================================================
# Фикстуры окружения
# =============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """
    Мокирует переменные окружения для изоляции от реальных credentials.
    """
    print("Настройка мокированных переменных окружения...")
    monkeypatch.setenv("REFRESH_TOKEN", "test_refresh_token_abcdef")
    monkeypatch.setenv("PROXY_API_KEY", "test_proxy_key_12345")
    monkeypatch.setenv("PROFILE_ARN", "arn:aws:codewhisperer:us-east-1:123456789:profile/test")
    monkeypatch.setenv("KIRO_REGION", "us-east-1")
    return {
        "REFRESH_TOKEN": "test_refresh_token_abcdef",
        "PROXY_API_KEY": "test_proxy_key_12345",
        "PROFILE_ARN": "arn:aws:codewhisperer:us-east-1:123456789:profile/test",
        "KIRO_REGION": "us-east-1"
    }


# =============================================================================
# Фикстуры токенов и аутентификации
# =============================================================================

@pytest.fixture
def valid_kiro_token():
    """Возвращает валидный мок Kiro access token."""
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test_kiro_access_token"


@pytest.fixture
def mock_kiro_token_response(valid_kiro_token):
    """
    Фабрика для создания мок-ответа Kiro token refresh endpoint.
    """
    def _create_response(expires_in: int = 3600, token: str = None):
        return {
            "accessToken": token or valid_kiro_token,
            "refreshToken": "new_refresh_token_xyz",
            "expiresIn": expires_in,
            "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
        }
    return _create_response


@pytest.fixture
def valid_proxy_api_key():
    """Возвращает валидный API ключ прокси (из config)."""
    return "changeme_proxy_secret"


@pytest.fixture
def invalid_proxy_api_key():
    """Возвращает невалидный API ключ для негативных тестов."""
    return "invalid_wrong_secret_key"


@pytest.fixture
def auth_headers(valid_proxy_api_key):
    """
    Фабрика для создания валидных и невалидных Authorization headers.
    """
    def _create_headers(api_key: str = None, invalid: bool = False):
        if invalid:
            return {"Authorization": "Bearer wrong_key_123"}
        key = api_key or valid_proxy_api_key
        return {"Authorization": f"Bearer {key}"}
    
    return _create_headers


# =============================================================================
# Фикстуры моделей Kiro
# =============================================================================

@pytest.fixture
def mock_kiro_models_response():
    """
    Мок успешного ответа от Kiro API для ListAvailableModels.
    """
    return {
        "models": [
            {
                "modelId": "claude-sonnet-4.5",
                "displayName": "Claude Sonnet 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            },
            {
                "modelId": "claude-opus-4.5",
                "displayName": "Claude Opus 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            },
            {
                "modelId": "claude-haiku-4.5",
                "displayName": "Claude Haiku 4.5",
                "tokenLimits": {
                    "maxInputTokens": 200000,
                    "maxOutputTokens": 8192
                }
            }
        ]
    }


# =============================================================================
# Фикстуры streaming ответов Kiro
# =============================================================================

@pytest.fixture
def mock_kiro_streaming_chunks():
    """
    Возвращает список мок SSE chunks от Kiro API для streaming response.
    Покрывает: обычный текст, tool calls, usage.
    """
    return [
        # Chunk 1: Начало текста
        b'{"content":"Hello"}',
        # Chunk 2: Продолжение текста
        b'{"content":" World!"}',
        # Chunk 3: Tool call start
        b'{"name":"get_weather","toolUseId":"call_abc123"}',
        # Chunk 4: Tool call input
        b'{"input":"{\\"location\\": \\"Moscow\\"}"}',
        # Chunk 5: Tool call stop
        b'{"stop":true}',
        # Chunk 6: Usage
        b'{"usage":1.5}',
        # Chunk 7: Context usage
        b'{"contextUsagePercentage":25.5}',
    ]

@pytest.fixture
def mock_kiro_simple_text_chunks():
    """
    Мок простого текстового ответа от Kiro (без tool calls).
    """
    return [
        b'{"content":"This is a complete response."}',
        b'{"usage":0.5}',
        b'{"contextUsagePercentage":10.0}',
    ]


@pytest.fixture
def mock_kiro_stream_with_usage():
    """
    Мок SSE ответа Kiro с информацией о usage.
    """
    return [
        b'{"content":"Final text."}',
        b'{"usage":1.3}',
        b'{"contextUsagePercentage":50.0}',
    ]


# =============================================================================
# Фикстуры OpenAI запросов
# =============================================================================

@pytest.fixture
def sample_openai_chat_request():
    """
    Фабрика для создания валидных OpenAI chat completion requests.
    """
    def _create_request(
        model: str = "claude-sonnet-4-5",
        messages: list = None,
        stream: bool = False,
        temperature: float = None,
        max_tokens: int = None,
        tools: list = None,
        **kwargs
    ):
        if messages is None:
            messages = [{"role": "user", "content": "Hello, AI!"}]
        
        request = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        if tools is not None:
            request["tools"] = tools
        
        request.update(kwargs)
        return request
    
    return _create_request


@pytest.fixture
def sample_tool_definition():
    """
    Пример определения tool для тестирования tool calling.
    """
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }
    }


# =============================================================================
# Фикстуры HTTP клиента
# =============================================================================

@pytest.fixture
async def mock_httpx_client():
    """
    Создает мокированный httpx.AsyncClient для изоляции от сетевых запросов.
    """
    print("Создание мокированного httpx.AsyncClient...")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    
    # Мокируем методы
    mock_client.post = AsyncMock()
    mock_client.get = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_client.build_request = Mock()
    mock_client.send = AsyncMock()
    mock_client.is_closed = False
    
    return mock_client


@pytest.fixture
def mock_httpx_response():
    """
    Фабрика для создания мокированных httpx.Response объектов.
    """
    def _create_response(
        status_code: int = 200,
        json_data: Dict[str, Any] = None,
        text: str = None,
        stream_chunks: list = None
    ):
        print(f"Создание мок httpx.Response (status={status_code})...")
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = status_code
        
        if json_data is not None:
            mock_response.json = Mock(return_value=json_data)
        
        if text is not None:
            mock_response.text = text
            mock_response.content = text.encode()
        
        if stream_chunks is not None:
            # Для streaming responses
            async def mock_aiter_bytes():
                for chunk in stream_chunks:
                    yield chunk
            
            mock_response.aiter_bytes = mock_aiter_bytes
        
        mock_response.raise_for_status = Mock()
        mock_response.aclose = AsyncMock()
        mock_response.aread = AsyncMock(return_value=b'{"error": "mocked error"}')
        
        return mock_response
    
    return _create_response


# =============================================================================
# Глобальная блокировка сети
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def block_all_network_calls():
    """
    КРИТИЧЕСКАЯ ФИКСТУРА: Глобально блокирует ВСЕ сетевые вызовы.
    Гарантирует, что НИ ОДИН тест не сможет сделать реальный сетевой запрос.
    """
    
    # Создаем мок, который будет использоваться для всех инстансов AsyncClient
    mock_async_client = AsyncMock(spec=httpx.AsyncClient)

    async def network_call_error(*args, **kwargs):
        raise RuntimeError(
            "🚨 КРИТИЧЕСКАЯ ОШИБКА: Обнаружена попытка реального сетевого запроса! "
            "Тест не предоставил мок для httpx.AsyncClient. "
            "Все HTTP вызовы должны быть явно замокированы."
        )

    mock_async_client.post.side_effect = network_call_error
    mock_async_client.get.side_effect = network_call_error
    mock_async_client.send.side_effect = network_call_error
    
    # Мокируем контекстный менеджер
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock()
    mock_async_client.aclose = AsyncMock()
    mock_async_client.is_closed = False

    # Патчим AsyncClient в модулях где он используется
    patchers = [
        patch('kiro_gateway.auth.httpx.AsyncClient', return_value=mock_async_client),
        patch('kiro_gateway.http_client.httpx.AsyncClient', return_value=mock_async_client),
        patch('kiro_gateway.routes.httpx.AsyncClient', return_value=mock_async_client),
    ]
    
    # Запускаем патчеры
    for patcher in patchers:
        patcher.start()
    
    print("🛡️ ГЛОБАЛЬНАЯ БЛОКИРОВКА СЕТИ АКТИВИРОВАНА")
    
    yield

    # Останавливаем патчеры
    for patcher in patchers:
        patcher.stop()
    
    print("🛡️ ГЛОБАЛЬНАЯ БЛОКИРОВКА СЕТИ ДЕАКТИВИРОВАНА")


# =============================================================================
# Фикстуры приложения
# =============================================================================

@pytest.fixture
def clean_app():
    """
    Возвращает "чистый" экземпляр приложения для каждого теста.
    """
    print("Импорт приложения для теста...")
    from main import app
    # Сбрасываем все переопределения зависимостей перед тестом
    app.dependency_overrides = {}
    return app


@pytest.fixture
def test_client(clean_app):
    """
    Создает FastAPI TestClient для синхронных тестов endpoints,
    корректно обрабатывая lifespan события.
    """
    print("Создание TestClient с поддержкой lifespan...")
    with TestClient(clean_app) as client:
        yield client
    print("Закрытие TestClient...")


@pytest.fixture
async def async_test_client(clean_app):
    """
    Создает асинхронный test client для async endpoints.
    """
    print("Создание async test client...")
    from httpx import AsyncClient, ASGITransport
    
    transport = ASGITransport(app=clean_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    print("Закрытие async test client...")


# =============================================================================
# Фикстуры для KiroAuthManager
# =============================================================================

@pytest.fixture
def mock_auth_manager():
    """
    Создает мокированный KiroAuthManager для тестов.
    """
    from kiro_gateway.auth import KiroAuthManager
    
    manager = KiroAuthManager(
        refresh_token="test_refresh_token",
        profile_arn="arn:aws:codewhisperer:us-east-1:123456789:profile/test",
        region="us-east-1"
    )
    
    # Устанавливаем валидный токен
    manager._access_token = "test_access_token"
    manager._expires_at = datetime.now(timezone.utc).replace(
        year=2099  # Далеко в будущем
    )
    
    return manager


@pytest.fixture
def expired_auth_manager():
    """
    Создает KiroAuthManager с истекшим токеном.
    """
    from kiro_gateway.auth import KiroAuthManager
    
    manager = KiroAuthManager(
        refresh_token="test_refresh_token",
        profile_arn="arn:aws:codewhisperer:us-east-1:123456789:profile/test",
        region="us-east-1"
    )
    
    # Устанавливаем истекший токен
    manager._access_token = "expired_token"
    manager._expires_at = datetime.now(timezone.utc).replace(
        year=2020  # В прошлом
    )
    
    return manager


# =============================================================================
# Фикстуры для ModelInfoCache
# =============================================================================

@pytest.fixture
def sample_models_data():
    """
    Возвращает список моделей для тестирования ModelInfoCache.
    """
    return [
        {
            "modelId": "claude-sonnet-4",
            "displayName": "Claude Sonnet 4",
            "tokenLimits": {
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192
            }
        },
        {
            "modelId": "claude-opus-4.5",
            "displayName": "Claude Opus 4.5",
            "tokenLimits": {
                "maxInputTokens": 200000,
                "maxOutputTokens": 8192
            }
        },
        {
            "modelId": "claude-haiku-4.5",
            "displayName": "Claude Haiku 4.5",
            "tokenLimits": {
                "maxInputTokens": 100000,
                "maxOutputTokens": 4096
            }
        }
    ]


@pytest.fixture
def empty_model_cache():
    """
    Создает пустой ModelInfoCache.
    """
    from kiro_gateway.cache import ModelInfoCache
    return ModelInfoCache()


@pytest.fixture
async def populated_model_cache(mock_kiro_models_response):
    """
    Создает ModelInfoCache с предзаполненными данными.
    """
    from kiro_gateway.cache import ModelInfoCache
    
    cache = ModelInfoCache()
    await cache.update(mock_kiro_models_response["models"])
    return cache


# =============================================================================
# Фикстуры времени
# =============================================================================

@pytest.fixture
def mock_time():
    """
    Мокирует time.time() для предсказуемого поведения в тестах.
    """
    with patch('time.time') as mock:
        # Фиксированная точка времени: 2024-01-01 12:00:00
        mock.return_value = 1704110400.0
        yield mock


@pytest.fixture
def mock_datetime():
    """
    Мокирует datetime.now() для предсказуемого поведения.
    """
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    with patch('kiro_gateway.auth.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_time
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        yield mock_dt


# =============================================================================
# Фикстуры для временных файлов
# =============================================================================

@pytest.fixture
def temp_creds_file(tmp_path):
    """
    Создает временный файл credentials для тестов.
    """
    creds_file = tmp_path / "kiro-auth-token.json"
    creds_data = {
        "accessToken": "file_access_token",
        "refreshToken": "file_refresh_token",
        "expiresAt": "2099-01-01T00:00:00.000Z",
        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789:profile/test",
        "region": "us-east-1"
    }
    creds_file.write_text(json.dumps(creds_data))
    return str(creds_file)


@pytest.fixture
def temp_debug_dir(tmp_path):
    """
    Создает временную директорию для debug файлов.
    """
    debug_dir = tmp_path / "debug_logs"
    debug_dir.mkdir()
    return debug_dir


# =============================================================================
# Фикстуры для парсера
# =============================================================================

@pytest.fixture
def aws_event_parser():
    """
    Создает экземпляр AwsEventStreamParser для тестов.
    """
    from kiro_gateway.parsers import AwsEventStreamParser
    return AwsEventStreamParser()


# =============================================================================
# Утилиты для тестов
# =============================================================================

def create_kiro_content_chunk(content: str) -> bytes:
    """Утилита для создания Kiro SSE chunk с контентом."""
    return f'{{"content":"{content}"}}'.encode()


def create_kiro_tool_start_chunk(name: str, tool_id: str) -> bytes:
    """Утилита для создания Kiro SSE chunk с началом tool call."""
    return f'{{"name":"{name}","toolUseId":"{tool_id}"}}'.encode()


def create_kiro_tool_input_chunk(input_json: str) -> bytes:
    """Утилита для создания Kiro SSE chunk с input для tool call."""
    escaped = input_json.replace('"', '\\"')
    return f'{{"input":"{escaped}"}}'.encode()


def create_kiro_tool_stop_chunk() -> bytes:
    """Утилита для создания Kiro SSE chunk с завершением tool call."""
    return b'{"stop":true}'


def create_kiro_usage_chunk(usage: float) -> bytes:
    """Утилита для создания Kiro SSE chunk с usage."""
    return f'{{"usage":{usage}}}'.encode()


def create_kiro_context_usage_chunk(percentage: float) -> bytes:
    """Утилита для создания Kiro SSE chunk с context usage."""
    return f'{{"contextUsagePercentage":{percentage}}}'.encode()