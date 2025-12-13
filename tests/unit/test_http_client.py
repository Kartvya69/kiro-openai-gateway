# -*- coding: utf-8 -*-

"""
Unit-тесты для KiroHttpClient.
Проверяет логику retry, обработку ошибок и управление HTTP клиентом.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException

from kiro_gateway.http_client import KiroHttpClient
from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.config import MAX_RETRIES, BASE_RETRY_DELAY


@pytest.fixture
def mock_auth_manager_for_http():
    """Создаёт мокированный KiroAuthManager для тестов HTTP клиента."""
    manager = Mock(spec=KiroAuthManager)
    manager.get_access_token = AsyncMock(return_value="test_access_token")
    manager.force_refresh = AsyncMock(return_value="new_access_token")
    manager.fingerprint = "test_fingerprint_12345678"
    manager._fingerprint = "test_fingerprint_12345678"
    return manager


class TestKiroHttpClientInitialization:
    """Тесты инициализации KiroHttpClient."""
    
    def test_initialization_stores_auth_manager(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет сохранение auth_manager при инициализации.
        Цель: Убедиться, что auth_manager доступен для получения токенов.
        """
        print("Настройка: Создание KiroHttpClient...")
        client = KiroHttpClient(mock_auth_manager_for_http)
        
        print("Проверка: auth_manager сохранён...")
        assert client.auth_manager is mock_auth_manager_for_http
    
    def test_initialization_client_is_none(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет, что HTTP клиент изначально None.
        Цель: Убедиться в lazy initialization.
        """
        print("Настройка: Создание KiroHttpClient...")
        client = KiroHttpClient(mock_auth_manager_for_http)
        
        print("Проверка: client изначально None...")
        assert client.client is None


class TestKiroHttpClientGetClient:
    """Тесты метода _get_client."""
    
    @pytest.mark.asyncio
    async def test_get_client_creates_new_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет создание нового HTTP клиента.
        Цель: Убедиться, что клиент создаётся при первом вызове.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        print("Действие: Получение клиента...")
        with patch('kiro_gateway.http_client.httpx.AsyncClient') as mock_async_client:
            mock_instance = AsyncMock()
            mock_instance.is_closed = False
            mock_async_client.return_value = mock_instance
            
            client = await http_client._get_client()
            
            print("Проверка: Клиент создан...")
            mock_async_client.assert_called_once()
            assert client is mock_instance
    
    @pytest.mark.asyncio
    async def test_get_client_reuses_existing_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет повторное использование существующего клиента.
        Цель: Убедиться, что клиент не создаётся заново.
        """
        print("Настройка: Создание KiroHttpClient с существующим клиентом...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_existing = AsyncMock()
        mock_existing.is_closed = False
        http_client.client = mock_existing
        
        print("Действие: Получение клиента...")
        client = await http_client._get_client()
        
        print("Проверка: Возвращён существующий клиент...")
        assert client is mock_existing
    
    @pytest.mark.asyncio
    async def test_get_client_recreates_closed_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет пересоздание закрытого клиента.
        Цель: Убедиться, что закрытый клиент заменяется новым.
        """
        print("Настройка: Создание KiroHttpClient с закрытым клиентом...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_closed = AsyncMock()
        mock_closed.is_closed = True
        http_client.client = mock_closed
        
        print("Действие: Получение клиента...")
        with patch('kiro_gateway.http_client.httpx.AsyncClient') as mock_async_client:
            mock_new = AsyncMock()
            mock_new.is_closed = False
            mock_async_client.return_value = mock_new
            
            client = await http_client._get_client()
            
            print("Проверка: Создан новый клиент...")
            mock_async_client.assert_called_once()
            assert client is mock_new


class TestKiroHttpClientClose:
    """Тесты метода close."""
    
    @pytest.mark.asyncio
    async def test_close_closes_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет закрытие HTTP клиента.
        Цель: Убедиться, что aclose() вызывается.
        """
        print("Настройка: Создание KiroHttpClient с клиентом...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        http_client.client = mock_client
        
        print("Действие: Закрытие клиента...")
        await http_client.close()
        
        print("Проверка: aclose() вызван...")
        mock_client.aclose.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_does_nothing_for_none_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет, что close() не падает для None клиента.
        Цель: Убедиться в безопасности вызова close() без клиента.
        """
        print("Настройка: Создание KiroHttpClient без клиента...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        print("Действие: Закрытие клиента...")
        await http_client.close()  # Не должно вызвать ошибку
        
        print("Проверка: Ошибок нет...")
    
    @pytest.mark.asyncio
    async def test_close_does_nothing_for_closed_client(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет, что close() не падает для закрытого клиента.
        Цель: Убедиться в безопасности повторного вызова close().
        """
        print("Настройка: Создание KiroHttpClient с закрытым клиентом...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_client = AsyncMock()
        mock_client.is_closed = True
        http_client.client = mock_client
        
        print("Действие: Закрытие клиента...")
        await http_client.close()
        
        print("Проверка: aclose() НЕ вызван...")
        mock_client.aclose.assert_not_called()


class TestKiroHttpClientRequestWithRetry:
    """Тесты метода request_with_retry."""
    
    @pytest.mark.asyncio
    async def test_successful_request_returns_response(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет успешный запрос.
        Цель: Убедиться, что 200 ответ возвращается сразу.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response = AsyncMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(return_value=mock_response)
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                response = await http_client.request_with_retry(
                    "POST",
                    "https://api.example.com/test",
                    {"data": "value"}
                )
        
        print("Проверка: Ответ получен...")
        assert response.status_code == 200
        mock_client.request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_403_triggers_token_refresh(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет обновление токена при 403.
        Цель: Убедиться, что force_refresh() вызывается при 403.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_403 = AsyncMock()
        mock_response_403.status_code = 403
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=[mock_response_403, mock_response_200])
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                response = await http_client.request_with_retry(
                    "POST",
                    "https://api.example.com/test",
                    {"data": "value"}
                )
        
        print("Проверка: force_refresh() вызван...")
        mock_auth_manager_for_http.force_refresh.assert_called_once()
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_429_triggers_backoff(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет exponential backoff при 429.
        Цель: Убедиться, что запрос повторяется после задержки.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_429 = AsyncMock()
        mock_response_429.status_code = 429
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=[mock_response_429, mock_response_200])
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    response = await http_client.request_with_retry(
                        "POST",
                        "https://api.example.com/test",
                        {"data": "value"}
                    )
        
        print("Проверка: sleep() вызван для backoff...")
        mock_sleep.assert_called_once()
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_5xx_triggers_backoff(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет exponential backoff при 5xx.
        Цель: Убедиться, что серверные ошибки обрабатываются с retry.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_500 = AsyncMock()
        mock_response_500.status_code = 500
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=[mock_response_500, mock_response_200])
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    response = await http_client.request_with_retry(
                        "POST",
                        "https://api.example.com/test",
                        {"data": "value"}
                    )
        
        print("Проверка: sleep() вызван для backoff...")
        mock_sleep.assert_called_once()
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_timeout_triggers_backoff(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет exponential backoff при таймауте.
        Цель: Убедиться, что таймауты обрабатываются с retry.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=[
            httpx.TimeoutException("Timeout"),
            mock_response_200
        ])
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    response = await http_client.request_with_retry(
                        "POST",
                        "https://api.example.com/test",
                        {"data": "value"}
                    )
        
        print("Проверка: sleep() вызван для backoff...")
        mock_sleep.assert_called_once()
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_request_error_triggers_backoff(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет exponential backoff при ошибке запроса.
        Цель: Убедиться, что сетевые ошибки обрабатываются с retry.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=[
            httpx.RequestError("Connection error"),
            mock_response_200
        ])
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    response = await http_client.request_with_retry(
                        "POST",
                        "https://api.example.com/test",
                        {"data": "value"}
                    )
        
        print("Проверка: sleep() вызван для backoff...")
        mock_sleep.assert_called_once()
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_502(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет выброс HTTPException после исчерпания попыток.
        Цель: Убедиться, что после MAX_RETRIES выбрасывается 502.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', new_callable=AsyncMock):
                    with pytest.raises(HTTPException) as exc_info:
                        await http_client.request_with_retry(
                            "POST",
                            "https://api.example.com/test",
                            {"data": "value"}
                        )
        
        print(f"Проверка: HTTPException с кодом 502...")
        assert exc_info.value.status_code == 502
        assert str(MAX_RETRIES) in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_other_status_codes_returned_as_is(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет возврат других статус-кодов без retry.
        Цель: Убедиться, что 400, 404 и т.д. возвращаются сразу.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response = AsyncMock()
        mock_response.status_code = 400
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(return_value=mock_response)
        
        print("Действие: Выполнение запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                response = await http_client.request_with_retry(
                    "POST",
                    "https://api.example.com/test",
                    {"data": "value"}
                )
        
        print("Проверка: Ответ 400 возвращён без retry...")
        assert response.status_code == 400
        mock_client.request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_streaming_request_uses_send(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет использование send() для streaming.
        Цель: Убедиться, что stream=True использует build_request + send.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response = AsyncMock()
        mock_response.status_code = 200
        
        mock_request = Mock()
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.build_request = Mock(return_value=mock_request)
        mock_client.send = AsyncMock(return_value=mock_response)
        
        print("Действие: Выполнение streaming запроса...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                response = await http_client.request_with_retry(
                    "POST",
                    "https://api.example.com/test",
                    {"data": "value"},
                    stream=True
                )
        
        print("Проверка: build_request и send вызваны...")
        mock_client.build_request.assert_called_once()
        mock_client.send.assert_called_once_with(mock_request, stream=True)
        assert response.status_code == 200


class TestKiroHttpClientContextManager:
    """Тесты async context manager."""
    
    @pytest.mark.asyncio
    async def test_context_manager_returns_self(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет, что __aenter__ возвращает self.
        Цель: Убедиться в корректной работе async with.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        print("Действие: Вход в контекст...")
        result = await http_client.__aenter__()
        
        print("Проверка: Возвращён self...")
        assert result is http_client
    
    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exit(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет закрытие клиента при выходе из контекста.
        Цель: Убедиться, что close() вызывается в __aexit__.
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        http_client.client = mock_client
        
        print("Действие: Выход из контекста...")
        await http_client.__aexit__(None, None, None)
        
        print("Проверка: aclose() вызван...")
        mock_client.aclose.assert_called_once()


class TestKiroHttpClientExponentialBackoff:
    """Тесты exponential backoff логики."""
    
    @pytest.mark.asyncio
    async def test_backoff_delay_increases_exponentially(self, mock_auth_manager_for_http):
        """
        Что он делает: Проверяет экспоненциальное увеличение задержки.
        Цель: Убедиться, что delay = BASE_RETRY_DELAY * (2 ** attempt).
        """
        print("Настройка: Создание KiroHttpClient...")
        http_client = KiroHttpClient(mock_auth_manager_for_http)
        
        mock_response_429 = AsyncMock()
        mock_response_429.status_code = 429
        
        mock_response_200 = AsyncMock()
        mock_response_200.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        # 3 ошибки 429, затем успех
        mock_client.request = AsyncMock(side_effect=[
            mock_response_429,
            mock_response_429,
            mock_response_200
        ])
        
        sleep_delays = []
        
        async def capture_sleep(delay):
            sleep_delays.append(delay)
        
        print("Действие: Выполнение запроса с несколькими retry...")
        with patch.object(http_client, '_get_client', return_value=mock_client):
            with patch('kiro_gateway.http_client.get_kiro_headers', return_value={}):
                with patch('kiro_gateway.http_client.asyncio.sleep', side_effect=capture_sleep):
                    response = await http_client.request_with_retry(
                        "POST",
                        "https://api.example.com/test",
                        {"data": "value"}
                    )
        
        print(f"Проверка: Задержки увеличиваются экспоненциально...")
        print(f"Задержки: {sleep_delays}")
        assert len(sleep_delays) == 2
        assert sleep_delays[0] == BASE_RETRY_DELAY * (2 ** 0)  # 1.0
        assert sleep_delays[1] == BASE_RETRY_DELAY * (2 ** 1)  # 2.0