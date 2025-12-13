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

import json
import os
import requests
from dotenv import load_dotenv

# --- Загрузка переменных окружения ---
load_dotenv()

# --- Конфигурация ---
KIRO_API_HOST = "https://q.us-east-1.amazonaws.com"
TOKEN_URL = "https://prod.us-east-1.auth.desktop.kiro.dev/refreshToken"
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
PROFILE_ARN = os.getenv("PROFILE_ARN", "arn:aws:codewhisperer:us-east-1:699475941385:profile/EHGA3GRVQMUK")

# Глобальные переменные
AUTH_TOKEN = None
HEADERS = {
    "Authorization": None,
    "Content-Type": "application/json",
    "User-Agent": "aws-sdk-js/1.0.27 ua/2.1 os/win32#10.0.19044 lang/js md/nodejs#22.21.1 api/codewhispererstreaming#1.0.27 m/E KiroIDE-0.7.45-31c325a0ff0a9c8dec5d13048f4257462d751fe5b8af4cb1088f1fca45856c64",
    "x-amz-user-agent": "aws-sdk-js/1.0.27 KiroIDE-0.7.45-31c325a0ff0a9c8dec5d13048f4257462d751fe5b8af4cb1088f1fca45856c64",
    "x-amzn-codewhisperer-optout": "true",
    "x-amzn-kiro-agent-mode": "vibe",
}


def refresh_auth_token():
    """Refreshes AUTH_TOKEN via Kiro API."""
    global AUTH_TOKEN, HEADERS
    print("--- Refreshing Kiro token ---")
    
    payload = {"refreshToken": REFRESH_TOKEN}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "KiroIDE-0.7.45-31c325a0ff0a9c8dec5d13048f4257462d751fe5b8af4cb1088f1fca45856c64",
    }
    
    try:
        response = requests.post(TOKEN_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        new_token = data.get("accessToken")
        expires_in = data.get("expiresIn")
        
        if not new_token:
            print("ERROR: failed to get accessToken")
            return False

        print(f"Token successfully refreshed. Expires in: {expires_in}s")
        AUTH_TOKEN = new_token
        HEADERS['Authorization'] = f"Bearer {AUTH_TOKEN}"
        print("--- Token refresh COMPLETED ---\n")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"ERROR refreshing token: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Server response: {e.response.status_code} {e.response.text}")
        return False


def test_get_models():
    """Tests the ListAvailableModels endpoint."""
    print("--- Testing /ListAvailableModels ---")
    url = f"{KIRO_API_HOST}/ListAvailableModels"
    params = {
        "origin": "AI_EDITOR",
        "profileArn": PROFILE_ARN
    }

    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()

        print(f"Response status: {response.status_code}")
        print("Response (JSON):")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        print("--- ListAvailableModels test COMPLETED SUCCESSFULLY ---\n")
        return True
    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return False


def test_generate_content():
    """Tests the generateAssistantResponse endpoint."""
    print("--- Testing /generateAssistantResponse ---")
    url = f"{KIRO_API_HOST}/generateAssistantResponse"
    
    import uuid
    payload = {
        "conversationState": {
            "agentContinuationId": str(uuid.uuid4()),
            "agentTaskType": "vibe",
            "chatTriggerType": "MANUAL",
            "conversationId": str(uuid.uuid4()),
            "currentMessage": {
                "userInputMessage": {
                    "content": "Привет! Скажи что-нибудь короткое.",
                    "modelId": "claude-haiku-4.5",
                    "origin": "AI_EDITOR",
                    "userInputMessageContext": {
                        "tools": []
                    }
                }
            },
            "history": []
        },
        "profileArn": PROFILE_ARN
    }

    try:
        with requests.post(url, headers=HEADERS, json=payload, stream=True) as response:
            response.raise_for_status()
            print(f"Response status: {response.status_code}")
            print("Streaming response:")

            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    # Пытаемся декодировать и найти JSON
                    chunk_str = chunk.decode('utf-8', errors='ignore')
                    print(f"  Chunk: {chunk_str[:200]}...")

        print("\n--- generateAssistantResponse test COMPLETED ---\n")
        return True
    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    print("Starting Kiro API tests...\n")

    token_ok = refresh_auth_token()

    if token_ok:
        models_ok = test_get_models()
        generate_ok = test_generate_content()

        print("="*40)
        if models_ok and generate_ok:
            print("All tests passed successfully!")
        else:
            print("One or more tests failed.")
    else:
        print("="*40)
        print("Failed to refresh token. Tests not started.")
