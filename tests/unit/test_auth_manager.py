# -*- coding: utf-8 -*-

"""
Unit-тесты для KiroAuthManager.
Проверяет логику управления токенами Kiro без реальных сетевых запросов.
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock, patch
import httpx

from kiro_gateway.auth import KiroAuthManager
from kiro_gateway.config import TOKEN_REFRESH_THRESHOLD


class TestKiroAuthManagerInitialization:
    """Тесты инициализации KiroAuthManager."""
    
    def test_initialization_stores_credentials(self):
        """
        Что он делает: Проверяет корректное сохранение credentials при инициализации.
        Цель: Убедиться, что все параметры конструктора сохраняются в приватных полях.
        """
        print("Настройка: Создание KiroAuthManager с тестовыми credentials...")
        manager = KiroAuthManager(
            refresh_token="test_refresh_123",
            profile_arn="arn:aws:codewhisperer:us-east-1:123456789:profile/test",
            region="us-east-1"
        )
        
        print("Проверка: Все credentials сохранены корректно...")
        print(f"Сравниваем refresh_token: Ожидалось 'test_refresh_123', Получено '{manager._refresh_token}'")
        assert manager._refresh_token == "test_refresh_123"
        
        print(f"Сравниваем profile_arn: Ожидалось 'arn:aws:...', Получено '{manager._profile_arn}'")
        assert manager._profile_arn == "arn:aws:codewhisperer:us-east-1:123456789:profile/test"
        
        print(f"Сравниваем region: Ожидалось 'us-east-1', Получено '{manager._region}'")
        assert manager._region == "us-east-1"
        
        print("Проверка: Токен изначально пустой...")
        assert manager._access_token is None
        assert manager._expires_at is None
    
    def test_initialization_sets_correct_urls_for_region(self):
        """
        Что он делает: Проверяет формирование URL на основе региона.
        Цель: Убедиться, что URL динамически формируются с правильным регионом.
        """
        print("Настройка: Создание KiroAuthManager с регионом eu-west-1...")
        manager = KiroAuthManager(
            refresh_token="test_token",
            region="eu-west-1"
        )
        
        print("Проверка: URL содержат правильный регион...")
        print(f"Сравниваем refresh_url: Ожидалось 'eu-west-1' в URL, Получено '{manager._refresh_url}'")
        assert "eu-west-1" in manager._refresh_url
        
        print(f"Сравниваем api_host: Ожидалось 'eu-west-1' в URL, Получено '{manager._api_host}'")
        assert "eu-west-1" in manager._api_host
        
        print(f"Сравниваем q_host: Ожидалось 'eu-west-1' в URL, Получено '{manager._q_host}'")
        assert "eu-west-1" in manager._q_host
    
    def test_initialization_generates_fingerprint(self):
        """
        Что он делает: Проверяет генерацию уникального fingerprint.
        Цель: Убедиться, что fingerprint генерируется и имеет корректный формат.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(refresh_token="test_token")
        
        print("Проверка: Fingerprint сгенерирован...")
        print(f"Fingerprint: {manager._fingerprint}")
        assert manager._fingerprint is not None
        assert len(manager._fingerprint) == 64  # SHA256 hex digest


class TestKiroAuthManagerCredentialsFile:
    """Тесты загрузки credentials из файла."""
    
    def test_load_credentials_from_file(self, temp_creds_file):
        """
        Что он делает: Проверяет загрузку credentials из JSON файла.
        Цель: Убедиться, что данные корректно читаются из файла.
        """
        print(f"Настройка: Создание KiroAuthManager с файлом credentials: {temp_creds_file}")
        manager = KiroAuthManager(creds_file=temp_creds_file)
        
        print("Проверка: Данные загружены из файла...")
        print(f"Сравниваем access_token: Ожидалось 'file_access_token', Получено '{manager._access_token}'")
        assert manager._access_token == "file_access_token"
        
        print(f"Сравниваем refresh_token: Ожидалось 'file_refresh_token', Получено '{manager._refresh_token}'")
        assert manager._refresh_token == "file_refresh_token"
        
        print(f"Сравниваем region: Ожидалось 'us-east-1', Получено '{manager._region}'")
        assert manager._region == "us-east-1"
        
        print("Проверка: expiresAt распарсен корректно...")
        assert manager._expires_at is not None
        assert manager._expires_at.year == 2099
    
    def test_load_credentials_file_not_found(self, tmp_path):
        """
        Что он делает: Проверяет обработку отсутствующего файла credentials.
        Цель: Убедиться, что приложение не падает при отсутствии файла.
        """
        print("Настройка: Создание KiroAuthManager с несуществующим файлом...")
        non_existent_file = str(tmp_path / "non_existent.json")
        
        manager = KiroAuthManager(
            refresh_token="fallback_token",
            creds_file=non_existent_file
        )
        
        print("Проверка: Используется fallback refresh_token...")
        print(f"Сравниваем refresh_token: Ожидалось 'fallback_token', Получено '{manager._refresh_token}'")
        assert manager._refresh_token == "fallback_token"


class TestKiroAuthManagerTokenExpiration:
    """Тесты проверки истечения токена."""
    
    def test_is_token_expiring_soon_returns_true_when_no_expires_at(self):
        """
        Что он делает: Проверяет, что без expires_at токен считается истекающим.
        Цель: Убедиться в безопасном поведении при отсутствии информации о времени.
        """
        print("Настройка: Создание KiroAuthManager без expires_at...")
        manager = KiroAuthManager(refresh_token="test_token")
        manager._expires_at = None
        
        print("Проверка: is_token_expiring_soon возвращает True...")
        result = manager.is_token_expiring_soon()
        print(f"Сравниваем результат: Ожидалось True, Получено {result}")
        assert result is True
    
    def test_is_token_expiring_soon_returns_true_when_expired(self):
        """
        Что он делает: Проверяет, что истекший токен определяется корректно.
        Цель: Убедиться, что токен в прошлом считается истекающим.
        """
        print("Настройка: Создание KiroAuthManager с истекшим токеном...")
        manager = KiroAuthManager(refresh_token="test_token")
        manager._expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        
        print("Проверка: is_token_expiring_soon возвращает True для истекшего токена...")
        result = manager.is_token_expiring_soon()
        print(f"Сравниваем результат: Ожидалось True, Получено {result}")
        assert result is True
    
    def test_is_token_expiring_soon_returns_true_within_threshold(self):
        """
        Что он делает: Проверяет, что токен в пределах threshold считается истекающим.
        Цель: Убедиться, что токен обновляется заранее (за 10 минут до истечения).
        """
        print("Настройка: Создание KiroAuthManager с токеном, истекающим через 5 минут...")
        manager = KiroAuthManager(refresh_token="test_token")
        manager._expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        print(f"TOKEN_REFRESH_THRESHOLD = {TOKEN_REFRESH_THRESHOLD} секунд")
        print("Проверка: is_token_expiring_soon возвращает True (5 мин < 10 мин threshold)...")
        result = manager.is_token_expiring_soon()
        print(f"Сравниваем результат: Ожидалось True, Получено {result}")
        assert result is True
    
    def test_is_token_expiring_soon_returns_false_when_valid(self):
        """
        Что он делает: Проверяет, что валидный токен не считается истекающим.
        Цель: Убедиться, что токен далеко в будущем не требует обновления.
        """
        print("Настройка: Создание KiroAuthManager с токеном, истекающим через 1 час...")
        manager = KiroAuthManager(refresh_token="test_token")
        manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        print("Проверка: is_token_expiring_soon возвращает False...")
        result = manager.is_token_expiring_soon()
        print(f"Сравниваем результат: Ожидалось False, Получено {result}")
        assert result is False


class TestKiroAuthManagerTokenRefresh:
    """Тесты механизма обновления токена."""
    
    @pytest.mark.asyncio
    async def test_refresh_token_successful(self, valid_kiro_token, mock_kiro_token_response):
        """
        Что он делает: Тестирует успешное обновление токена через Kiro API.
        Цель: Проверить, что при успешном ответе токен и время истечения устанавливаются.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(
            refresh_token="test_refresh",
            region="us-east-1"
        )
        
        print("Настройка: Мокирование успешного ответа от Kiro...")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_kiro_token_response())
        mock_response.raise_for_status = Mock()
        
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            print("Действие: Вызов _refresh_token_request()...")
            await manager._refresh_token_request()
            
            print("Проверка: Токен установлен корректно...")
            print(f"Сравниваем access_token: Ожидалось '{valid_kiro_token}', Получено '{manager._access_token}'")
            assert manager._access_token == valid_kiro_token
            
            print("Проверка: Время истечения установлено...")
            assert manager._expires_at is not None
            
            print("Проверка: Был сделан POST запрос...")
            mock_client.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_refresh_token_updates_refresh_token(self, mock_kiro_token_response):
        """
        Что он делает: Проверяет обновление refresh_token из ответа.
        Цель: Убедиться, что новый refresh_token сохраняется.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(refresh_token="old_refresh_token")
        
        print("Настройка: Мокирование ответа с новым refresh_token...")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_kiro_token_response())
        mock_response.raise_for_status = Mock()
        
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            print("Действие: Обновление токена...")
            await manager._refresh_token_request()
            
            print("Проверка: refresh_token обновлен...")
            print(f"Сравниваем refresh_token: Ожидалось 'new_refresh_token_xyz', Получено '{manager._refresh_token}'")
            assert manager._refresh_token == "new_refresh_token_xyz"
    
    @pytest.mark.asyncio
    async def test_refresh_token_missing_access_token_raises(self):
        """
        Что он делает: Проверяет обработку ответа без accessToken.
        Цель: Убедиться, что выбрасывается исключение при некорректном ответе.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(refresh_token="test_refresh")
        
        print("Настройка: Мокирование ответа без accessToken...")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"expiresIn": 3600})  # Нет accessToken!
        mock_response.raise_for_status = Mock()
        
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            print("Действие: Попытка обновления токена...")
            with pytest.raises(ValueError) as exc_info:
                await manager._refresh_token_request()
            
            print(f"Проверка: Выброшено ValueError сообщением: {exc_info.value}")
            assert "accessToken" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token_raises(self):
        """
        Что он делает: Проверяет обработку отсутствия refresh_token.
        Цель: Убедиться, что выбрасывается исключение без refresh_token.
        """
        print("Настройка: Создание KiroAuthManager без refresh_token...")
        manager = KiroAuthManager()
        manager._refresh_token = None
        
        print("Действие: Попытка обновления токена без refresh_token...")
        with pytest.raises(ValueError) as exc_info:
            await manager._refresh_token_request()
        
        print(f"Проверка: Выброшено ValueError: {exc_info.value}")
        assert "Refresh token" in str(exc_info.value)


class TestKiroAuthManagerGetAccessToken:
    """Тесты публичного метода get_access_token."""
    
    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_when_expired(self, valid_kiro_token, mock_kiro_token_response):
        """
        Что он делает: Проверяет автоматическое обновление истекшего токена.
        Цель: Убедиться, что устаревший токен обновляется перед возвратом.
        """
        print("Настройка: Создание KiroAuthManager с истекшим токеном...")
        manager = KiroAuthManager(refresh_token="test_refresh")
        manager._access_token = "old_expired_token"
        manager._expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        
        print("Настройка: Мокирование успешного обновления...")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_kiro_token_response())
        mock_response.raise_for_status = Mock()
        
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            print("Действие: Запрос токена через get_access_token()...")
            token = await manager.get_access_token()
            
            print("Проверка: Получен новый токен, а не истекший...")
            print(f"Сравниваем токен: Ожидалось '{valid_kiro_token}', Получено '{token}'")
            assert token == valid_kiro_token
            assert token != "old_expired_token"
            
            print("Проверка: _refresh_token_request был вызван...")
            mock_client.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_access_token_returns_valid_without_refresh(self, valid_kiro_token):
        """
        Что он делает: Проверяет возврат валидного токена без обновления.
        Цель: Убедиться, что не делаются лишние запросы, если токен валиден.
        """
        print("Настройка: Создание KiroAuthManager с валидным токеном...")
        manager = KiroAuthManager(refresh_token="test_refresh")
        manager._access_token = valid_kiro_token
        manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        print("Настройка: Мокирование httpx для отслеживания вызовов...")
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock()
            mock_client_class.return_value = mock_client
            
            print("Действие: Запрос валидного токена...")
            token = await manager.get_access_token()
            
            print("Проверка: Возвращен существующий токен...")
            print(f"Сравниваем токен: Ожидалось '{valid_kiro_token}', Получено '{token}'")
            assert token == valid_kiro_token
            
            print("Проверка: _refresh_token НЕ был вызван (нет сетевых запросов)...")
            mock_client.post.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_access_token_thread_safety(self, valid_kiro_token, mock_kiro_token_response):
        """
        Что он делает: Проверяет потокобезопасность через asyncio.Lock.
        Цель: Убедиться, что параллельные вызовы не приводят к race condition.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(refresh_token="test_refresh")
        manager._access_token = None
        manager._expires_at = None
        
        refresh_call_count = 0
        
        async def mock_refresh():
            nonlocal refresh_call_count
            refresh_call_count += 1
            await asyncio.sleep(0.1)  # Имитация задержки
            manager._access_token = valid_kiro_token
            manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        print("Настройка: Патчинг _refresh_token_request для отслеживания вызовов...")
        with patch.object(manager, '_refresh_token_request', side_effect=mock_refresh):
            print("Действие: 5 параллельных вызовов get_access_token()...")
            tokens = await asyncio.gather(*[
                manager.get_access_token() for _ in range(5)
            ])
            
            print("Проверка: Все вызовы получили одинаковый токен...")
            assert all(token == valid_kiro_token for token in tokens)
            
            print(f"Проверка: _refresh_token вызван ТОЛЬКО ОДИН РАЗ (благодаря lock)...")
            print(f"Сравниваем количество вызовов: Ожидалось 1, Получено {refresh_call_count}")
            assert refresh_call_count == 1


class TestKiroAuthManagerForceRefresh:
    """Тесты принудительного обновления токена."""
    
    @pytest.mark.asyncio
    async def test_force_refresh_updates_token(self, valid_kiro_token, mock_kiro_token_response):
        """
        Что он делает: Проверяет принудительное обновление токена.
        Цель: Убедиться, что force_refresh всегда обновляет токен.
        """
        print("Настройка: Создание KiroAuthManager с валидным токеном...")
        manager = KiroAuthManager(refresh_token="test_refresh")
        manager._access_token = "old_but_valid_token"
        manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        print("Настройка: Мокирование обновления...")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_kiro_token_response())
        mock_response.raise_for_status = Mock()
        
        with patch('kiro_gateway.auth.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            print("Действие: Принудительное обновление токена...")
            token = await manager.force_refresh()
            
            print("Проверка: Токен обновлен, несмотря на валидность старого...")
            print(f"Сравниваем токен: Ожидалось '{valid_kiro_token}', Получено '{token}'")
            assert token == valid_kiro_token
            
            print("Проверка: POST запрос был сделан...")
            mock_client.post.assert_called_once()


class TestKiroAuthManagerProperties:
    """Тесты свойств KiroAuthManager."""
    
    def test_profile_arn_property(self):
        """
        Что он делает: Проверяет свойство profile_arn.
        Цель: Убедиться, что profile_arn доступен через property.
        """
        print("Настройка: Создание KiroAuthManager с profile_arn...")
        manager = KiroAuthManager(
            refresh_token="test",
            profile_arn="arn:aws:test:profile"
        )
        
        print("Проверка: profile_arn доступен...")
        print(f"Сравниваем profile_arn: Ожидалось 'arn:aws:test:profile', Получено '{manager.profile_arn}'")
        assert manager.profile_arn == "arn:aws:test:profile"
    
    def test_region_property(self):
        """
        Что он делает: Проверяет свойство region.
        Цель: Убедиться, что region доступен через property.
        """
        print("Настройка: Создание KiroAuthManager с region...")
        manager = KiroAuthManager(
            refresh_token="test",
            region="eu-west-1"
        )
        
        print("Проверка: region доступен...")
        print(f"Сравниваем region: Ожидалось 'eu-west-1', Получено '{manager.region}'")
        assert manager.region == "eu-west-1"
    
    def test_api_host_property(self):
        """
        Что он делает: Проверяет свойство api_host.
        Цель: Убедиться, что api_host формируется корректно.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(
            refresh_token="test",
            region="us-east-1"
        )
        
        print("Проверка: api_host содержит codewhisperer и регион...")
        print(f"api_host: {manager.api_host}")
        assert "codewhisperer" in manager.api_host
        assert "us-east-1" in manager.api_host
    
    def test_fingerprint_property(self):
        """
        Что он делает: Проверяет свойство fingerprint.
        Цель: Убедиться, что fingerprint доступен через property.
        """
        print("Настройка: Создание KiroAuthManager...")
        manager = KiroAuthManager(refresh_token="test")
        
        print("Проверка: fingerprint доступен и имеет корректную длину...")
        print(f"fingerprint: {manager.fingerprint}")
        assert len(manager.fingerprint) == 64