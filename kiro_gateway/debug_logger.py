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
Модуль для отладочного логирования последнего запроса.

Сохраняет данные запроса и потоки ответов в файлы для последующего анализа.
Активен только когда DEBUG_LAST_REQUEST=true в окружении.
"""

import json
import shutil
from pathlib import Path
from loguru import logger

from kiro_gateway.config import DEBUG_LAST_REQUEST, DEBUG_DIR


class DebugLogger:
    """
    Синглтон для управления отладочными логами последнего запроса.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DebugLogger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.debug_dir = Path(DEBUG_DIR)
        self._initialized = True

    def prepare_new_request(self):
        """
        Очищает папку с логами и создает её заново для нового запроса.
        """
        if not DEBUG_LAST_REQUEST:
            return

        try:
            if self.debug_dir.exists():
                shutil.rmtree(self.debug_dir)
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"[DebugLogger] Directory {self.debug_dir} cleared for new request.")
        except Exception as e:
            logger.error(f"[DebugLogger] Error preparing directory: {e}")

    def log_request_body(self, body: bytes):
        """
        Сохраняет тело запроса (от клиента, OpenAI формат) в JSON файл.
        """
        if not DEBUG_LAST_REQUEST:
            return

        try:
            file_path = self.debug_dir / "request_body.json"
            # Пытаемся сохранить как красивый JSON
            try:
                json_obj = json.loads(body)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(json_obj, f, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                # Если не JSON, пишем как есть (байты -> строка, если получится)
                with open(file_path, "wb") as f:
                    f.write(body)
        except Exception as e:
            logger.error(f"[DebugLogger] Error writing request_body: {e}")

    def log_kiro_request_body(self, body: bytes):
        """
        Сохраняет модифицированное тело запроса (к Kiro API) в JSON файл.
        """
        if not DEBUG_LAST_REQUEST:
            return

        try:
            file_path = self.debug_dir / "kiro_request_body.json"
            # Пытаемся сохранить как красивый JSON
            try:
                json_obj = json.loads(body)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(json_obj, f, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                # Если не JSON, пишем как есть (байты -> строка, если получится)
                with open(file_path, "wb") as f:
                    f.write(body)
        except Exception as e:
            logger.error(f"[DebugLogger] Error writing kiro_request_body: {e}")

    def log_raw_chunk(self, chunk: bytes):
        """
        Дописывает сырой чанк ответа (от провайдера) в файл.
        """
        if not DEBUG_LAST_REQUEST:
            return

        try:
            file_path = self.debug_dir / "response_stream_raw.txt"
            with open(file_path, "ab") as f:
                f.write(chunk)
        except Exception:
            # Не логируем ошибку на каждый чанк, чтобы не спамить
            pass

    def log_modified_chunk(self, chunk: bytes):
        """
        Дописывает модифицированный чанк (клиенту) в файл.
        """
        if not DEBUG_LAST_REQUEST:
            return

        try:
            file_path = self.debug_dir / "response_stream_modified.txt"
            with open(file_path, "ab") as f:
                f.write(chunk)
        except Exception:
            pass


# Глобальный экземпляр
debug_logger = DebugLogger()