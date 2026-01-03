# -*- coding: utf-8 -*-

"""
Kiro OAuth Authentication Module.

Implements OAuth authentication flows for Kiro:
- Social Auth (Google/GitHub) with HTTP localhost callback
- AWS Builder ID with device code polling

Based on AIClient-2-API's implementation.
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
from loguru import logger


# Kiro Auth Service endpoints
KIRO_AUTH_SERVICE = "https://prod.us-east-1.auth.desktop.kiro.dev"
AWS_SSO_OIDC_ENDPOINT = "https://oidc.us-east-1.amazonaws.com"
AWS_BUILDER_ID_START_URL = "https://view.awsapps.com/start"

# CodeWhisperer scopes for Builder ID
CODEWHISPERER_SCOPES = [
    "codewhisperer:completions",
    "codewhisperer:analysis",
    "codewhisperer:conversations",
    "codewhisperer:transformations",
    "codewhisperer:taskassist",
]


def generate_code_verifier() -> str:
    """Generate a PKCE code verifier (43-128 chars, base64url)."""
    return secrets.token_urlsafe(32)


def generate_code_challenge(code_verifier: str) -> str:
    """Generate a PKCE code challenge from verifier (S256 method)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Generate a random state token for CSRF protection."""
    return secrets.token_urlsafe(16)


class OAuthCallbackServer:
    """
    Simple HTTP server to handle OAuth callbacks.
    
    Listens on localhost for the OAuth redirect and captures the authorization code.
    """
    
    def __init__(
        self,
        port: int,
        code_verifier: str,
        expected_state: str,
        on_success: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.port = port
        self.code_verifier = code_verifier
        self.expected_state = expected_state
        self.on_success = on_success
        self.on_error = on_error
        self._server: Optional[asyncio.Server] = None
        self._result: Optional[Dict[str, Any]] = None
        self._error: Optional[str] = None
        self._done_event = asyncio.Event()
    
    async def start(self) -> None:
        """Start the callback server."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            "127.0.0.1",
            self.port,
        )
        logger.info(f"OAuth callback server started on port {self.port}")
    
    async def stop(self) -> None:
        """Stop the callback server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info(f"OAuth callback server stopped on port {self.port}")
    
    async def wait_for_callback(self, timeout: float = 600) -> Dict[str, Any]:
        """
        Wait for the OAuth callback.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            Token data from successful authentication
            
        Raises:
            TimeoutError: If callback not received within timeout
            ValueError: If authentication failed
        """
        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("OAuth callback timeout")
        
        if self._error:
            raise ValueError(self._error)
        
        return self._result
    
    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming HTTP connection."""
        try:
            request_line = await reader.readline()
            request_str = request_line.decode("utf-8").strip()
            
            # Parse request
            parts = request_str.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, "Bad Request")
                return
            
            method, path = parts[0], parts[1]
            
            # Read headers (we don't need them but must consume them)
            while True:
                line = await reader.readline()
                if line == b"\r\n" or line == b"\n" or not line:
                    break
            
            # Only handle GET /oauth/callback
            if method != "GET" or not path.startswith("/oauth/callback"):
                await self._send_response(writer, 204, "")
                return
            
            # Parse query parameters
            params = {}
            if "?" in path:
                query_string = path.split("?", 1)[1]
                for param in query_string.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        params[key] = value
            
            # Check for error
            if "error" in params:
                error_msg = f"OAuth error: {params.get('error')}"
                self._error = error_msg
                if self.on_error:
                    self.on_error(error_msg)
                await self._send_response(
                    writer, 400, self._generate_html(False, error_msg)
                )
                self._done_event.set()
                return
            
            # Validate state
            state = params.get("state", "")
            if state != self.expected_state:
                error_msg = "State validation failed"
                self._error = error_msg
                if self.on_error:
                    self.on_error(error_msg)
                await self._send_response(
                    writer, 400, self._generate_html(False, error_msg)
                )
                self._done_event.set()
                return
            
            # Get authorization code
            code = params.get("code")
            if not code:
                error_msg = "No authorization code received"
                self._error = error_msg
                if self.on_error:
                    self.on_error(error_msg)
                await self._send_response(
                    writer, 400, self._generate_html(False, error_msg)
                )
                self._done_event.set()
                return
            
            # Exchange code for tokens
            try:
                redirect_uri = f"http://127.0.0.1:{self.port}/oauth/callback"
                tokens = await self._exchange_code(code, redirect_uri)
                self._result = tokens
                if self.on_success:
                    self.on_success(tokens)
                await self._send_response(
                    writer, 200, self._generate_html(True, "Authorization successful! You can close this page.")
                )
            except Exception as e:
                error_msg = f"Token exchange failed: {e}"
                self._error = error_msg
                if self.on_error:
                    self.on_error(error_msg)
                await self._send_response(
                    writer, 500, self._generate_html(False, error_msg)
                )
            
            self._done_event.set()
            
        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}")
            try:
                await self._send_response(writer, 500, f"Server error: {e}")
            except Exception:
                pass
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{KIRO_AUTH_SERVICE}/oauth/token",
                json={
                    "code": code,
                    "code_verifier": self.code_verifier,
                    "redirect_uri": redirect_uri,
                },
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "KiroOpenAIGateway/1.0",
                },
            )
            response.raise_for_status()
            return response.json()
    
    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        body: str,
    ) -> None:
        """Send HTTP response."""
        status_text = {200: "OK", 204: "No Content", 400: "Bad Request", 500: "Internal Server Error"}
        content_type = "text/html; charset=utf-8" if body else "text/plain"
        
        response = f"HTTP/1.1 {status} {status_text.get(status, 'Unknown')}\r\n"
        response += f"Content-Type: {content_type}\r\n"
        response += f"Content-Length: {len(body.encode('utf-8'))}\r\n"
        response += "Connection: close\r\n"
        response += "\r\n"
        response += body
        
        writer.write(response.encode("utf-8"))
        await writer.drain()
    
    def _generate_html(self, success: bool, message: str) -> str:
        """Generate HTML response page."""
        title = "Authorization Successful!" if success else "Authorization Failed"
        color = "#4CAF50" if success else "#f44336"
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: #f5f5f5;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            max-width: 400px;
        }}
        h1 {{
            color: {color};
            margin-bottom: 20px;
        }}
        p {{
            color: #666;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p>{message}</p>
    </div>
</body>
</html>"""


class KiroOAuthManager:
    """
    Manages Kiro OAuth authentication flows.
    
    Supports:
    - Social Auth (Google/GitHub) with HTTP callback
    - AWS Builder ID with device code polling
    """
    
    def __init__(
        self,
        credentials_file: str = "auth.json",
        callback_port_start: int = 19876,
        callback_port_end: int = 19880,
        auth_timeout: int = 600,
        poll_interval: int = 5,
    ):
        self.credentials_file = Path(credentials_file).expanduser()
        self.callback_port_start = callback_port_start
        self.callback_port_end = callback_port_end
        self.auth_timeout = auth_timeout
        self.poll_interval = poll_interval
        
        self._active_server: Optional[OAuthCallbackServer] = None
        self._active_polling_task: Optional[asyncio.Task] = None
        self._current_auth: Optional[Dict[str, Any]] = None
    
    def _find_available_port(self) -> int:
        """Find an available port in the configured range."""
        for port in range(self.callback_port_start, self.callback_port_end + 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("127.0.0.1", port))
                sock.close()
                return port
            except OSError:
                continue
        raise RuntimeError(f"No available ports in range {self.callback_port_start}-{self.callback_port_end}")
    
    async def start_social_auth(
        self,
        provider: str = "Google",
        port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Start social authentication flow (Google or GitHub).
        
        Args:
            provider: "Google" or "Github"
            port: Specific port to use (optional)
            
        Returns:
            Dict with auth_url and other info
        """
        # Cancel any existing auth
        await self.cancel_auth()
        
        # Generate PKCE parameters
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = generate_state()
        
        # Find available port
        if port is None:
            port = self._find_available_port()
        
        redirect_uri = f"http://127.0.0.1:{port}/oauth/callback"
        
        # Build auth URL
        params = {
            "idp": provider,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "prompt": "select_account",
        }
        auth_url = f"{KIRO_AUTH_SERVICE}/login?{urlencode(params)}"
        
        # Start callback server
        self._active_server = OAuthCallbackServer(
            port=port,
            code_verifier=code_verifier,
            expected_state=state,
            on_success=self._on_auth_success,
            on_error=self._on_auth_error,
        )
        await self._active_server.start()
        
        self._current_auth = {
            "method": "social",
            "provider": provider,
            "port": port,
            "state": state,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        
        return {
            "auth_url": auth_url,
            "method": "social",
            "provider": provider,
            "port": port,
            "redirect_uri": redirect_uri,
            "expires_in": self.auth_timeout,
        }
    
    async def start_builder_id_auth(self) -> Dict[str, Any]:
        """
        Start AWS Builder ID authentication flow (device code).
        
        Returns:
            Dict with verification URL and other info
        """
        # Cancel any existing auth
        await self.cancel_auth()
        
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Register OIDC client
            reg_response = await client.post(
                f"{AWS_SSO_OIDC_ENDPOINT}/client/register",
                json={
                    "clientName": "Kiro OpenAI Gateway",
                    "clientType": "public",
                    "scopes": CODEWHISPERER_SCOPES,
                    "grantTypes": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                },
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "KiroOpenAIGateway/1.0",
                },
            )
            reg_response.raise_for_status()
            reg_data = reg_response.json()
            
            # 2. Start device authorization
            auth_response = await client.post(
                f"{AWS_SSO_OIDC_ENDPOINT}/device_authorization",
                json={
                    "clientId": reg_data["clientId"],
                    "clientSecret": reg_data["clientSecret"],
                    "startUrl": AWS_BUILDER_ID_START_URL,
                },
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "KiroOpenAIGateway/1.0",
                },
            )
            auth_response.raise_for_status()
            device_auth = auth_response.json()
        
        self._current_auth = {
            "method": "builder-id",
            "client_id": reg_data["clientId"],
            "client_secret": reg_data["clientSecret"],
            "device_code": device_auth["deviceCode"],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Start polling in background
        self._active_polling_task = asyncio.create_task(
            self._poll_builder_id_token(
                reg_data["clientId"],
                reg_data["clientSecret"],
                device_auth["deviceCode"],
            )
        )
        
        return {
            "auth_url": device_auth.get("verificationUriComplete", device_auth.get("verificationUri")),
            "method": "builder-id",
            "user_code": device_auth.get("userCode"),
            "verification_uri": device_auth.get("verificationUri"),
            "expires_in": device_auth.get("expiresIn", self.auth_timeout),
            "interval": device_auth.get("interval", self.poll_interval),
        }
    
    async def wait_for_auth(self) -> Dict[str, Any]:
        """
        Wait for the current authentication to complete.
        
        Returns:
            Token data from successful authentication
            
        Raises:
            RuntimeError: If no auth in progress
            TimeoutError: If auth times out
            ValueError: If auth fails
        """
        if not self._current_auth:
            raise RuntimeError("No authentication in progress")
        
        try:
            if self._current_auth["method"] == "social":
                if not self._active_server:
                    raise RuntimeError("Callback server not running")
                return await self._active_server.wait_for_callback(self.auth_timeout)
            
            elif self._current_auth["method"] == "builder-id":
                if not self._active_polling_task:
                    raise RuntimeError("Polling task not running")
                return await self._active_polling_task
            
            else:
                raise RuntimeError(f"Unknown auth method: {self._current_auth['method']}")
        finally:
            await self.cancel_auth()
    
    async def cancel_auth(self) -> None:
        """Cancel any ongoing authentication."""
        if self._active_server:
            await self._active_server.stop()
            self._active_server = None
        
        if self._active_polling_task:
            self._active_polling_task.cancel()
            try:
                await self._active_polling_task
            except asyncio.CancelledError:
                pass
            self._active_polling_task = None
        
        self._current_auth = None
    
    def get_auth_status(self) -> Optional[Dict[str, Any]]:
        """Get current authentication status."""
        if not self._current_auth:
            return None
        
        return {
            "in_progress": True,
            "method": self._current_auth["method"],
            "provider": self._current_auth.get("provider"),
            "started_at": self._current_auth["started_at"],
        }
    
    async def _poll_builder_id_token(
        self,
        client_id: str,
        client_secret: str,
        device_code: str,
    ) -> Dict[str, Any]:
        """Poll for Builder ID token completion."""
        max_attempts = self.auth_timeout // self.poll_interval
        attempts = 0
        
        async with httpx.AsyncClient(timeout=30) as client:
            while attempts < max_attempts:
                attempts += 1
                
                try:
                    response = await client.post(
                        f"{AWS_SSO_OIDC_ENDPOINT}/token",
                        json={
                            "clientId": client_id,
                            "clientSecret": client_secret,
                            "deviceCode": device_code,
                            "grantType": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "KiroOpenAIGateway/1.0",
                        },
                    )
                    
                    data = response.json()
                    
                    if response.status_code == 200 and "accessToken" in data:
                        # Success!
                        tokens = {
                            "accessToken": data["accessToken"],
                            "refreshToken": data.get("refreshToken"),
                            "expiresAt": datetime.fromtimestamp(
                                datetime.now(timezone.utc).timestamp() + data.get("expiresIn", 3600),
                                tz=timezone.utc,
                            ).isoformat().replace("+00:00", "Z"),
                            "authMethod": "IdC",
                            "_clientId": client_id,
                            "_clientSecret": client_secret,
                            "region": "us-east-1",
                        }
                        self._save_credentials(tokens)
                        return tokens
                    
                    error = data.get("error", "")
                    
                    if error == "authorization_pending":
                        logger.debug(f"Waiting for user authorization ({attempts}/{max_attempts})...")
                        await asyncio.sleep(self.poll_interval)
                        continue
                    
                    elif error == "slow_down":
                        logger.debug("Slowing down polling...")
                        await asyncio.sleep(self.poll_interval + 5)
                        continue
                    
                    elif error == "expired_token":
                        raise ValueError("Device code expired")
                    
                    elif error == "access_denied":
                        raise ValueError("User denied authorization")
                    
                    else:
                        raise ValueError(f"Authorization failed: {error}")
                        
                except httpx.HTTPError as e:
                    logger.warning(f"HTTP error during polling: {e}")
                    await asyncio.sleep(self.poll_interval)
                    continue
        
        raise TimeoutError("Authorization timeout")
    
    def _on_auth_success(self, tokens: Dict[str, Any]) -> None:
        """Handle successful authentication."""
        # Transform tokens to our format
        credentials = {
            "accessToken": tokens.get("accessToken"),
            "refreshToken": tokens.get("refreshToken"),
            "profileArn": tokens.get("profileArn"),
            "expiresAt": datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + tokens.get("expiresIn", 3600),
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z"),
            "authMethod": "social",
            "region": "us-east-1",
        }
        self._save_credentials(credentials)
        logger.info("OAuth authentication successful, credentials saved")
    
    def _on_auth_error(self, error: str) -> None:
        """Handle authentication error."""
        logger.error(f"OAuth authentication failed: {error}")
    
    def _save_credentials(self, credentials: Dict[str, Any]) -> None:
        """Save credentials to file."""
        self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Add metadata
        credentials["savedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        with open(self.credentials_file, "w", encoding="utf-8") as f:
            json.dump(credentials, f, indent=2)
        
        # Set restrictive permissions (owner read/write only)
        try:
            os.chmod(self.credentials_file, 0o600)
        except OSError:
            pass  # Windows doesn't support chmod
        
        logger.info(f"Credentials saved to {self.credentials_file}")
