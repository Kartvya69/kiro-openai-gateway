# Тесты для Kiro OpenAI Gateway

Комплексный набор unit и integration тестов для Kiro OpenAI Gateway, обеспечивающий полное покрытие всех компонентов системы.

## Философия тестирования: Полная изоляция от сети

**Ключевой принцип этого тестового набора — 100% изоляция от реальных сетевых запросов.**

Это достигается с помощью глобальной, автоматически применяемой фикстуры `block_all_network_calls` в `tests/conftest.py`. Она перехватывает и блокирует любые попытки `httpx.AsyncClient` установить соединение на уровне всего приложения.

**Преимущества:**
1.  **Надежность**: Тесты не зависят от доступности внешних API и состояния сети.
2.  **Скорость**: Отсутствие реальных сетевых задержек делает выполнение тестов мгновенным.
3.  **Безопасность**: Гарантирует, что тестовые запуски никогда не используют реальные учетные данные.

Любая попытка совершить несанкционированный сетевой вызов приведет к немедленному падению теста с ошибкой, что обеспечивает строгий контроль над изоляцией.

## Запуск тестов

### Установка зависимостей

```bash
# Основные зависимости проекта
pip install -r requirements.txt

# Дополнительные зависимости для тестирования
pip install pytest pytest-asyncio hypothesis
```

### Запуск всех тестов

```bash
# Запуск всего набора тестов
pytest

# Запуск с подробным выводом
pytest -v

# Запуск с подробным выводом и покрытием
pytest -v -s --tb=short

# Запуск только unit-тестов
pytest tests/unit/ -v

# Запуск только integration-тестов
pytest tests/integration/ -v

# Запуск конкретного файла
pytest tests/unit/test_auth_manager.py -v

# Запуск конкретного теста
pytest tests/unit/test_auth_manager.py::TestKiroAuthManagerInitialization::test_initialization_stores_credentials -v
```

### Опции pytest

```bash
# Остановка на первой ошибке
pytest -x

# Показать локальные переменные при ошибках
pytest -l

# Запуск в параллельном режиме (требует pytest-xdist)
pip install pytest-xdist
pytest -n auto
```

## Структура тестов

```
tests/
├── conftest.py                      # Общие фикстуры и утилиты
├── unit/                            # Unit-тесты отдельных компонентов
│   ├── test_auth_manager.py        # Тесты KiroAuthManager
│   ├── test_cache.py               # Тесты ModelInfoCache
│   ├── test_converters.py          # Тесты конвертеров OpenAI <-> Kiro
│   ├── test_parsers.py             # Тесты AwsEventStreamParser
│   ├── test_http_client.py         # Тесты KiroHttpClient
│   └── test_routes.py              # Тесты API endpoints
├── integration/                     # Integration-тесты полного flow
│   └── test_full_flow.py           # End-to-end тесты
└── README.md                        # Этот файл
```

## Покрытие тестами

### `conftest.py`

Общие фикстуры и утилиты для всех тестов:

**Фикстуры окружения:**
- **`mock_env_vars()`**: Мокирует переменные окружения (REFRESH_TOKEN, PROXY_API_KEY)
  - **Что он делает**: Изолирует тесты от реальных credentials
  - **Цель**: Безопасность и воспроизводимость тестов

**Фикстуры данных:**
- **`valid_kiro_token()`**: Возвращает мок Kiro access token
  - **Что он делает**: Предоставляет предсказуемый токен для тестов
  - **Цель**: Тестирование без реальных запросов к Kiro

- **`mock_kiro_token_response()`**: Фабрика для создания мок ответов refreshToken
  - **Что он делает**: Генерирует структуру ответа Kiro auth endpoint
  - **Цель**: Тестирование различных сценариев обновления токена

- **`temp_creds_file()`**: Создаёт временный JSON файл с credentials
  - **Что он делает**: Предоставляет файл для тестирования загрузки credentials
  - **Цель**: Тестирование работы с файлами credentials

- **`sample_openai_chat_request()`**: Фабрика для создания OpenAI запросов
  - **Что он делает**: Генерирует валидные chat completion requests
  - **Цель**: Удобное создание тестовых запросов с разными параметрами

**Фикстуры безопасности:**
- **`valid_proxy_api_key()`**: Валидный API ключ прокси
- **`invalid_proxy_api_key()`**: Невалидный ключ для негативных тестов
- **`auth_headers()`**: Фабрика для создания Authorization заголовков

**Фикстуры HTTP:**
- **`mock_httpx_client()`**: Мокированный httpx.AsyncClient
  - **Что он делает**: Изолирует тесты от реальных HTTP запросов
  - **Цель**: Скорость и надежность тестов

- **`mock_httpx_response()`**: Фабрика для создания мок HTTP responses
  - **Что он делает**: Создает настраиваемые httpx.Response объекты
  - **Цель**: Тестирование различных HTTP сценариев

**Фикстуры приложения:**
- **`clean_app()`**: Чистый экземпляр FastAPI app
  - **Что он делает**: Возвращает "чистый" экземпляр приложения
  - **Цель**: Обеспечить изоляцию состояния приложения между тестами

- **`test_client()`**: Синхронный FastAPI TestClient
- **`async_test_client()`**: Асинхронный test client для async endpoints

---

### `tests/unit/test_auth_manager.py`

Unit-тесты для **KiroAuthManager** (управление токенами Kiro).

#### `TestKiroAuthManagerInitialization`

- **`test_initialization_stores_credentials()`**:
  - **Что он делает**: Проверяет корректное сохранение credentials при создании
  - **Цель**: Убедиться, что все параметры конструктора сохраняются в приватных полях

- **`test_initialization_sets_correct_urls_for_region()`**:
  - **Что он делает**: Проверяет формирование URL на основе региона
  - **Цель**: Убедиться, что URL динамически формируются с правильным регионом

- **`test_initialization_generates_fingerprint()`**:
  - **Что он делает**: Проверяет генерацию уникального fingerprint
  - **Цель**: Убедиться, что fingerprint генерируется и имеет корректный формат

#### `TestKiroAuthManagerCredentialsFile`

- **`test_load_credentials_from_file()`**:
  - **Что он делает**: Проверяет загрузку credentials из JSON файла
  - **Цель**: Убедиться, что данные корректно читаются из файла

- **`test_load_credentials_file_not_found()`**:
  - **Что он делает**: Проверяет обработку отсутствующего файла credentials
  - **Цель**: Убедиться, что приложение не падает при отсутствии файла

#### `TestKiroAuthManagerTokenExpiration`

- **`test_is_token_expiring_soon_returns_true_when_no_expires_at()`**:
  - **Что он делает**: Проверяет, что без expires_at токен считается истекающим
  - **Цель**: Убедиться в безопасном поведении при отсутствии информации о времени

- **`test_is_token_expiring_soon_returns_true_when_expired()`**:
  - **Что он делает**: Проверяет, что истекший токен определяется корректно
  - **Цель**: Убедиться, что токен в прошлом считается истекающим

- **`test_is_token_expiring_soon_returns_true_within_threshold()`**:
  - **Что он делает**: Проверяет, что токен в пределах threshold считается истекающим
  - **Цель**: Убедиться, что токен обновляется заранее (за 10 минут до истечения)

- **`test_is_token_expiring_soon_returns_false_when_valid()`**:
  - **Что он делает**: Проверяет, что валидный токен не считается истекающим
  - **Цель**: Убедиться, что токен далеко в будущем не требует обновления

#### `TestKiroAuthManagerTokenRefresh`

- **`test_refresh_token_successful()`**:
  - **Что он делает**: Тестирует успешное обновление токена через Kiro API
  - **Цель**: Проверить корректную установку access_token и expires_at

- **`test_refresh_token_updates_refresh_token()`**:
  - **Что он делает**: Проверяет обновление refresh_token из ответа
  - **Цель**: Убедиться, что новый refresh_token сохраняется

- **`test_refresh_token_missing_access_token_raises()`**:
  - **Что он делает**: Проверяет обработку ответа без accessToken
  - **Цель**: Убедиться, что выбрасывается исключение при некорректном ответе

- **`test_refresh_token_no_refresh_token_raises()`**:
  - **Что он делает**: Проверяет обработку отсутствия refresh_token
  - **Цель**: Убедиться, что выбрасывается исключение без refresh_token

#### `TestKiroAuthManagerGetAccessToken`

- **`test_get_access_token_refreshes_when_expired()`**:
  - **Что он делает**: Проверяет автоматическое обновление истекшего токена
  - **Цель**: Убедиться, что устаревший токен обновляется перед возвратом

- **`test_get_access_token_returns_valid_without_refresh()`**:
  - **Что он делает**: Проверяет возврат валидного токена без лишних запросов
  - **Цель**: Оптимизация - не делать запросы, если токен еще действителен

- **`test_get_access_token_thread_safety()`**:
  - **Что он делает**: Проверяет потокобезопасность через asyncio.Lock
  - **Цель**: Предотвращение race conditions при параллельных вызовах

#### `TestKiroAuthManagerForceRefresh`

- **`test_force_refresh_updates_token()`**:
  - **Что он делает**: Проверяет принудительное обновление токена
  - **Цель**: Убедиться, что force_refresh всегда обновляет токен

#### `TestKiroAuthManagerProperties`

- **`test_profile_arn_property()`**:
  - **Что он делает**: Проверяет свойство profile_arn
  - **Цель**: Убедиться, что profile_arn доступен через property

- **`test_region_property()`**:
  - **Что он делает**: Проверяет свойство region
  - **Цель**: Убедиться, что region доступен через property

- **`test_api_host_property()`**:
  - **Что он делает**: Проверяет свойство api_host
  - **Цель**: Убедиться, что api_host формируется корректно

- **`test_fingerprint_property()`**:
  - **Что он делает**: Проверяет свойство fingerprint
  - **Цель**: Убедиться, что fingerprint доступен через property

---

### `tests/unit/test_cache.py`

Unit-тесты для **ModelInfoCache** (кэш метаданных моделей). **23 теста.**

#### `TestModelInfoCacheInitialization`

- **`test_initialization_creates_empty_cache()`**:
  - **Что он делает**: Проверяет, что кэш создаётся пустым
  - **Цель**: Убедиться в корректной инициализации

- **`test_initialization_with_custom_ttl()`**:
  - **Что он делает**: Проверяет создание кэша с кастомным TTL
  - **Цель**: Убедиться, что TTL можно настроить

- **`test_initialization_last_update_is_none()`**:
  - **Что он делает**: Проверяет, что last_update_time изначально None
  - **Цель**: Убедиться, что время обновления не установлено до первого update

#### `TestModelInfoCacheUpdate`

- **`test_update_populates_cache()`**:
  - **Что он делает**: Проверяет заполнение кэша данными
  - **Цель**: Убедиться, что update() корректно сохраняет модели

- **`test_update_sets_last_update_time()`**:
  - **Что он делает**: Проверяет установку времени последнего обновления
  - **Цель**: Убедиться, что last_update_time устанавливается после update

- **`test_update_replaces_existing_data()`**:
  - **Что он делает**: Проверяет замену данных при повторном update
  - **Цель**: Убедиться, что старые данные полностью заменяются

- **`test_update_with_empty_list()`**:
  - **Что он делает**: Проверяет обновление пустым списком
  - **Цель**: Убедиться, что кэш очищается при пустом update

#### `TestModelInfoCacheGet`

- **`test_get_returns_model_info()`**:
  - **Что он делает**: Проверяет получение информации о модели
  - **Цель**: Убедиться, что get() возвращает корректные данные

- **`test_get_returns_none_for_unknown_model()`**:
  - **Что он делает**: Проверяет возврат None для неизвестной модели
  - **Цель**: Убедиться, что get() не падает при отсутствии модели

- **`test_get_from_empty_cache()`**:
  - **Что он делает**: Проверяет get() из пустого кэша
  - **Цель**: Убедиться, что пустой кэш не вызывает ошибок

#### `TestModelInfoCacheGetMaxInputTokens`

- **`test_get_max_input_tokens_returns_value()`**:
  - **Что он делает**: Проверяет получение maxInputTokens для модели
  - **Цель**: Убедиться, что значение извлекается из tokenLimits

- **`test_get_max_input_tokens_returns_default_for_unknown()`**:
  - **Что он делает**: Проверяет возврат дефолта для неизвестной модели
  - **Цель**: Убедиться, что возвращается DEFAULT_MAX_INPUT_TOKENS

- **`test_get_max_input_tokens_returns_default_when_no_token_limits()`**:
  - **Что он делает**: Проверяет возврат дефолта при отсутствии tokenLimits
  - **Цель**: Убедиться, что модель без tokenLimits не ломает логику

- **`test_get_max_input_tokens_returns_default_when_max_input_is_none()`**:
  - **Что он делает**: Проверяет возврат дефолта при maxInputTokens=None
  - **Цель**: Убедиться, что None в tokenLimits обрабатывается корректно

#### `TestModelInfoCacheIsEmpty` и `TestModelInfoCacheIsStale`

- **`test_is_empty_returns_true_for_new_cache()`**: Проверяет is_empty() для нового кэша
- **`test_is_empty_returns_false_after_update()`**: Проверяет is_empty() после заполнения
- **`test_is_stale_returns_true_for_new_cache()`**: Проверяет is_stale() для нового кэша
- **`test_is_stale_returns_false_after_recent_update()`**: Проверяет is_stale() сразу после обновления
- **`test_is_stale_returns_true_after_ttl_expires()`**: Проверяет is_stale() после истечения TTL

#### `TestModelInfoCacheGetAllModelIds`

- **`test_get_all_model_ids_returns_empty_for_new_cache()`**: Проверяет get_all_model_ids() для пустого кэша
- **`test_get_all_model_ids_returns_all_ids()`**: Проверяет get_all_model_ids() для заполненного кэша

#### `TestModelInfoCacheThreadSafety`

- **`test_concurrent_updates_dont_corrupt_cache()`**:
  - **Что он делает**: Проверяет потокобезопасность при параллельных update
  - **Цель**: Убедиться, что asyncio.Lock защищает от race conditions

- **`test_concurrent_reads_are_safe()`**:
  - **Что он делает**: Проверяет безопасность параллельных чтений
  - **Цель**: Убедиться, что множественные get() не вызывают проблем

---

### `tests/unit/test_converters.py`

Unit-тесты для конвертеров **OpenAI <-> Kiro**. **27 тестов.**

#### `TestExtractTextContent`

- **`test_extracts_from_string()`**: Проверяет извлечение текста из строки
- **`test_extracts_from_none()`**: Проверяет обработку None
- **`test_extracts_from_list_with_text_type()`**: Проверяет извлечение из списка с type=text
- **`test_extracts_from_list_with_text_key()`**: Проверяет извлечение из списка с ключом text
- **`test_extracts_from_list_with_strings()`**: Проверяет извлечение из списка строк
- **`test_extracts_from_mixed_list()`**: Проверяет извлечение из смешанного списка
- **`test_converts_other_types_to_string()`**: Проверяет конвертацию других типов в строку
- **`test_handles_empty_list()`**: Проверяет обработку пустого списка

#### `TestMergeAdjacentMessages`

- **`test_merges_adjacent_user_messages()`**: Проверяет объединение соседних user сообщений
- **`test_preserves_alternating_messages()`**: Проверяет сохранение чередующихся сообщений
- **`test_handles_empty_list()`**: Проверяет обработку пустого списка
- **`test_handles_single_message()`**: Проверяет обработку одного сообщения
- **`test_merges_multiple_adjacent_groups()`**: Проверяет объединение нескольких групп

#### `TestBuildKiroHistory`

- **`test_builds_user_message()`**: Проверяет построение user сообщения
- **`test_builds_assistant_message()`**: Проверяет построение assistant сообщения
- **`test_ignores_system_messages()`**: Проверяет игнорирование system сообщений
- **`test_builds_conversation_history()`**: Проверяет построение полной истории разговора
- **`test_handles_empty_list()`**: Проверяет обработку пустого списка

#### `TestExtractToolResults` и `TestExtractToolUses`

- **`test_extracts_tool_results_from_list()`**: Проверяет извлечение tool results из списка
- **`test_returns_empty_for_string_content()`**: Проверяет возврат пустого списка для строки
- **`test_extracts_from_tool_calls_field()`**: Проверяет извлечение из поля tool_calls
- **`test_extracts_from_content_list()`**: Проверяет извлечение из content списка

#### `TestBuildUserInputContext`

- **`test_builds_tools_context()`**: Проверяет построение контекста с tools
- **`test_returns_empty_for_no_tools()`**: Проверяет возврат пустого контекста без tools

#### `TestBuildKiroPayload`

- **`test_builds_simple_payload()`**: Проверяет построение простого payload
- **`test_includes_system_prompt_in_first_message()`**: Проверяет добавление system prompt
- **`test_builds_history_for_multi_turn()`**: Проверяет построение истории для multi-turn
- **`test_handles_assistant_as_last_message()`**: Проверяет обработку assistant как последнего сообщения
- **`test_raises_for_empty_messages()`**: Проверяет выброс исключения для пустых сообщений
- **`test_uses_continue_for_empty_content()`**: Проверяет использование "Continue" для пустого контента
- **`test_maps_model_id_correctly()`**: Проверяет маппинг внешнего ID модели во внутренний

---

### `tests/unit/test_parsers.py`

Unit-тесты для **AwsEventStreamParser** и вспомогательных функций парсинга. **37 тестов.**

#### `TestFindMatchingBrace`

- **`test_simple_json_object()`**: Проверяет поиск закрывающей скобки для простого JSON
- **`test_nested_json_object()`**: Проверяет поиск для вложенного JSON
- **`test_json_with_braces_in_string()`**: Проверяет игнорирование скобок внутри строк
- **`test_json_with_escaped_quotes()`**: Проверяет обработку экранированных кавычек
- **`test_incomplete_json()`**: Проверяет обработку незавершённого JSON
- **`test_invalid_start_position()`**: Проверяет обработку невалидной стартовой позиции
- **`test_start_position_out_of_bounds()`**: Проверяет обработку позиции за пределами текста

#### `TestParseBracketToolCalls`

- **`test_parses_single_tool_call()`**: Проверяет парсинг одного tool call
- **`test_parses_multiple_tool_calls()`**: Проверяет парсинг нескольких tool calls
- **`test_returns_empty_for_no_tool_calls()`**: Проверяет возврат пустого списка без tool calls
- **`test_returns_empty_for_empty_string()`**: Проверяет обработку пустой строки
- **`test_returns_empty_for_none()`**: Проверяет обработку None
- **`test_handles_nested_json_in_args()`**: Проверяет парсинг вложенного JSON в аргументах
- **`test_generates_unique_ids()`**: Проверяет генерацию уникальных ID для tool calls

#### `TestDeduplicateToolCalls`

- **`test_removes_duplicates()`**: Проверяет удаление дубликатов
- **`test_preserves_first_occurrence()`**: Проверяет сохранение первого вхождения
- **`test_handles_empty_list()`**: Проверяет обработку пустого списка

#### `TestAwsEventStreamParserInitialization`

- **`test_initialization_creates_empty_state()`**: Проверяет начальное состояние парсера

#### `TestAwsEventStreamParserFeed`

- **`test_parses_content_event()`**: Проверяет парсинг события с контентом
- **`test_parses_multiple_content_events()`**: Проверяет парсинг нескольких событий контента
- **`test_deduplicates_repeated_content()`**: Проверяет дедупликацию повторяющегося контента
- **`test_parses_usage_event()`**: Проверяет парсинг события usage
- **`test_parses_context_usage_event()`**: Проверяет парсинг события context_usage
- **`test_handles_incomplete_json()`**: Проверяет обработку неполного JSON
- **`test_completes_json_across_chunks()`**: Проверяет сборку JSON из нескольких chunks
- **`test_decodes_escape_sequences()`**: Проверяет декодирование escape-последовательностей
- **`test_handles_invalid_bytes()`**: Проверяет обработку невалидных байтов

#### `TestAwsEventStreamParserToolCalls`

- **`test_parses_tool_start_event()`**: Проверяет парсинг начала tool call
- **`test_parses_tool_input_event()`**: Проверяет парсинг input для tool call
- **`test_parses_tool_stop_event()`**: Проверяет завершение tool call
- **`test_get_tool_calls_returns_all()`**: Проверяет получение всех tool calls
- **`test_get_tool_calls_finalizes_current()`**: Проверяет завершение незавершённого tool call

#### `TestAwsEventStreamParserReset`

- **`test_reset_clears_state()`**: Проверяет сброс состояния парсера

#### `TestAwsEventStreamParserEdgeCases`

- **`test_handles_followup_prompt()`**: Проверяет игнорирование followupPrompt
- **`test_handles_mixed_events()`**: Проверяет парсинг смешанных событий
- **`test_handles_garbage_between_events()`**: Проверяет обработку мусора между событиями
- **`test_handles_empty_chunk()`**: Проверяет обработку пустого chunk

---

### `tests/unit/test_http_client.py`

Unit-тесты для **KiroHttpClient** (HTTP клиент с retry логикой). **21 тест.**

#### `TestKiroHttpClientInitialization`

- **`test_initialization_stores_auth_manager()`**: Проверяет сохранение auth_manager при инициализации
- **`test_initialization_client_is_none()`**: Проверяет, что HTTP клиент изначально None

#### `TestKiroHttpClientGetClient`

- **`test_get_client_creates_new_client()`**: Проверяет создание нового HTTP клиента
- **`test_get_client_reuses_existing_client()`**: Проверяет повторное использование существующего клиента
- **`test_get_client_recreates_closed_client()`**: Проверяет пересоздание закрытого клиента

#### `TestKiroHttpClientClose`

- **`test_close_closes_client()`**: Проверяет закрытие HTTP клиента
- **`test_close_does_nothing_for_none_client()`**: Проверяет, что close() не падает для None клиента
- **`test_close_does_nothing_for_closed_client()`**: Проверяет, что close() не падает для закрытого клиента

#### `TestKiroHttpClientRequestWithRetry`

- **`test_successful_request_returns_response()`**: Проверяет успешный запрос
- **`test_403_triggers_token_refresh()`**: Проверяет обновление токена при 403
- **`test_429_triggers_backoff()`**: Проверяет exponential backoff при 429
- **`test_5xx_triggers_backoff()`**: Проверяет exponential backoff при 5xx
- **`test_timeout_triggers_backoff()`**: Проверяет exponential backoff при таймауте
- **`test_request_error_triggers_backoff()`**: Проверяет exponential backoff при ошибке запроса
- **`test_max_retries_exceeded_raises_502()`**: Проверяет выброс HTTPException после исчерпания попыток
- **`test_other_status_codes_returned_as_is()`**: Проверяет возврат других статус-кодов без retry
- **`test_streaming_request_uses_send()`**: Проверяет использование send() для streaming

#### `TestKiroHttpClientContextManager`

- **`test_context_manager_returns_self()`**: Проверяет, что __aenter__ возвращает self
- **`test_context_manager_closes_on_exit()`**: Проверяет закрытие клиента при выходе из контекста

#### `TestKiroHttpClientExponentialBackoff`

- **`test_backoff_delay_increases_exponentially()`**: Проверяет экспоненциальное увеличение задержки

---

### `tests/unit/test_routes.py`

Unit-тесты для **API endpoints** (/v1/models, /v1/chat/completions). **22 теста.**

#### `TestVerifyApiKey`

- **`test_valid_api_key_returns_true()`**: Проверяет успешную валидацию корректного ключа
- **`test_invalid_api_key_raises_401()`**: Проверяет отклонение невалидного ключа
- **`test_missing_api_key_raises_401()`**: Проверяет отклонение отсутствующего ключа
- **`test_empty_api_key_raises_401()`**: Проверяет отклонение пустого ключа
- **`test_wrong_format_raises_401()`**: Проверяет отклонение ключа без Bearer

#### `TestRootEndpoint`

- **`test_root_returns_status_ok()`**: Проверяет ответ корневого эндпоинта
- **`test_root_returns_version()`**: Проверяет наличие версии в ответе

#### `TestHealthEndpoint`

- **`test_health_returns_healthy()`**: Проверяет ответ health эндпоинта
- **`test_health_returns_timestamp()`**: Проверяет наличие timestamp в ответе
- **`test_health_returns_version()`**: Проверяет наличие версии в ответе

#### `TestModelsEndpoint`

- **`test_models_requires_auth()`**: Проверяет требование авторизации
- **`test_models_returns_list()`**: Проверяет возврат списка моделей
- **`test_models_returns_available_models()`**: Проверяет наличие доступных моделей
- **`test_models_format_is_openai_compatible()`**: Проверяет формат ответа на совместимость с OpenAI

#### `TestChatCompletionsEndpoint`

- **`test_chat_completions_requires_auth()`**: Проверяет требование авторизации
- **`test_chat_completions_validates_messages()`**: Проверяет валидацию пустых сообщений
- **`test_chat_completions_validates_model()`**: Проверяет валидацию отсутствующей модели

#### `TestChatCompletionsWithMockedKiro`

- **`test_chat_completions_accepts_valid_request_format()`**: Проверяет, что валидный формат запроса принимается

#### `TestChatCompletionsErrorHandling`

- **`test_invalid_json_returns_422()`**: Проверяет обработку невалидного JSON
- **`test_missing_content_in_message_returns_200()`**: Проверяет обработку сообщения без content

#### `TestRouterIntegration`

- **`test_router_has_all_endpoints()`**: Проверяет наличие всех эндпоинтов в роутере
- **`test_router_methods()`**: Проверяет HTTP методы эндпоинтов

---

### `tests/integration/test_full_flow.py`

Integration-тесты для **полного end-to-end flow**. **12 тестов (11 passed, 1 skipped).**

#### `TestFullChatCompletionFlow`

- **`test_full_flow_health_to_models_to_chat()`**: Проверяет полный flow от health check до chat completions
- **`test_authentication_flow()`**: Проверяет flow аутентификации
- **`test_openai_compatibility_format()`**: Проверяет совместимость формата ответов с OpenAI API

#### `TestRequestValidationFlow`

- **`test_chat_completions_request_validation()`**: Проверяет валидацию различных форматов запросов
- **`test_complex_message_formats()`**: Проверяет обработку сложных форматов сообщений

#### `TestErrorHandlingFlow`

- **`test_invalid_json_handling()`**: Проверяет обработку невалидного JSON
- **`test_wrong_content_type_handling()`**: SKIPPED - обнаружен баг в validation_exception_handler

#### `TestModelsEndpointIntegration`

- **`test_models_returns_all_available_models()`**: Проверяет, что все модели из конфига возвращаются
- **`test_models_caching_behavior()`**: Проверяет поведение кэширования моделей

#### `TestStreamingFlagHandling`

- **`test_stream_true_accepted()`**: Проверяет, что stream=true принимается
- **`test_stream_false_accepted()`**: Проверяет, что stream=false принимается

#### `TestHealthEndpointIntegration`

- **`test_root_and_health_consistency()`**: Проверяет консистентность / и /health

---

## Философия тестирования

### Принципы

1. **Изоляция**: Каждый тест полностью изолирован от внешних сервисов через моки
2. **Детализация**: Обильные print() для понимания хода теста при отладке
3. **Покрытие**: Тесты покрывают не только happy path, но и граничные случаи и ошибки
4. **Безопасность**: Все тесты используют мок credentials, никогда не реальные

### Структура теста (Arrange-Act-Assert)

Каждый тест следует паттерну:
1. **Arrange** (Настройка): Подготовка моков и данных
2. **Act** (Действие): Выполнение тестируемого действия
3. **Assert** (Проверка): Верификация результата с явным сравнением

### Типы тестов

- **Unit-тесты**: Тестируют отдельные функции/классы в изоляции
- **Integration-тесты**: Проверяют взаимодействие компонентов
- **Security-тесты**: Верифицируют систему безопасности
- **Edge case-тесты**: Параноидальные проверки граничных случаев

## Добавление новых тестов

При добавлении новых тестов:

1. Следуйте существующей структуре классов (`Test*Success`, `Test*Errors`, `Test*EdgeCases`)
2. Используйте описательные имена: `test_<что_он_делает>_<ожидаемый_результат>`
3. Добавляйте docstring с "Что он делает" и "Цель"
4. Используйте print() для логирования шагов теста
5. Обновляйте этот README с описанием нового теста

## Troubleshooting

### Тесты падают с ImportError

```bash
# Убедитесь, что вы в корне проекта
cd /path/to/kiro-openai-gateway

# pytest.ini уже содержит pythonpath = .
# Просто запустите pytest
pytest
```

### Тесты проходят локально, но падают в CI

- Проверьте версии зависимостей в requirements.txt
- Убедитесь, что все моки корректно изолируют внешние вызовы

### Async тесты не работают

```bash
# Убедитесь, что pytest-asyncio установлен
pip install pytest-asyncio

# Проверьте наличие @pytest.mark.asyncio декоратора
```

## Метрики покрытия

Для проверки покрытия кода тестами:

```bash
# Установка coverage
pip install pytest-cov

# Запуск с отчетом о покрытии
pytest --cov=kiro_gateway --cov-report=html

# Просмотр отчета
open htmlcov/index.html  # macOS/Linux
start htmlcov/index.html  # Windows
```

## Контакты и поддержка

При обнаружении багов или предложениях по улучшению тестов, создайте issue в репозитории проекта.