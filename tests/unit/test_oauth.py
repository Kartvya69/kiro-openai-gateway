# -*- coding: utf-8 -*-

"""
Unit tests for OAuth module.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kiro_gateway.oauth import (
    generate_code_verifier,
    generate_code_challenge,
    generate_state,
    KiroOAuthManager,
    OAuthCallbackServer,
)


class TestPKCE:
    """Tests for PKCE functions."""
    
    def test_generate_code_verifier_length(self):
        """Code verifier should be 43 characters (base64url of 32 bytes)."""
        verifier = generate_code_verifier()
        assert len(verifier) == 43
    
    def test_generate_code_verifier_unique(self):
        """Each code verifier should be unique."""
        verifiers = [generate_code_verifier() for _ in range(10)]
        assert len(set(verifiers)) == 10
    
    def test_generate_code_challenge_deterministic(self):
        """Same verifier should produce same challenge."""
        verifier = "test_verifier_12345678901234567890123"
        challenge1 = generate_code_challenge(verifier)
        challenge2 = generate_code_challenge(verifier)
        assert challenge1 == challenge2
    
    def test_generate_code_challenge_different_for_different_verifiers(self):
        """Different verifiers should produce different challenges."""
        verifier1 = generate_code_verifier()
        verifier2 = generate_code_verifier()
        challenge1 = generate_code_challenge(verifier1)
        challenge2 = generate_code_challenge(verifier2)
        assert challenge1 != challenge2
    
    def test_generate_state_length(self):
        """State should be 22 characters (base64url of 16 bytes)."""
        state = generate_state()
        assert len(state) == 22
    
    def test_generate_state_unique(self):
        """Each state should be unique."""
        states = [generate_state() for _ in range(10)]
        assert len(set(states)) == 10


class TestKiroOAuthManager:
    """Tests for KiroOAuthManager."""
    
    def test_init_defaults(self):
        """Manager should initialize with default values."""
        manager = KiroOAuthManager()
        assert manager.callback_port_start == 19876
        assert manager.callback_port_end == 19880
        assert manager.auth_timeout == 600
        assert manager.poll_interval == 5
    
    def test_init_custom_values(self):
        """Manager should accept custom values."""
        manager = KiroOAuthManager(
            credentials_file="/tmp/test.json",
            callback_port_start=8000,
            callback_port_end=8010,
            auth_timeout=300,
            poll_interval=10,
        )
        assert str(manager.credentials_file) == "/tmp/test.json"
        assert manager.callback_port_start == 8000
        assert manager.callback_port_end == 8010
        assert manager.auth_timeout == 300
        assert manager.poll_interval == 10
    
    def test_get_auth_status_no_auth(self):
        """Status should be None when no auth in progress."""
        manager = KiroOAuthManager()
        assert manager.get_auth_status() is None
    
    @pytest.mark.asyncio
    async def test_cancel_auth_no_auth(self):
        """Cancel should work even when no auth in progress."""
        manager = KiroOAuthManager()
        await manager.cancel_auth()  # Should not raise
    
    @pytest.mark.asyncio
    async def test_find_available_port(self):
        """Should find an available port in range."""
        manager = KiroOAuthManager(
            callback_port_start=19876,
            callback_port_end=19880,
        )
        port = manager._find_available_port()
        assert 19876 <= port <= 19880
    
    @pytest.mark.asyncio
    async def test_start_social_auth_google(self):
        """Should start Google OAuth flow."""
        manager = KiroOAuthManager()
        
        with patch.object(manager, '_find_available_port', return_value=19876):
            result = await manager.start_social_auth(provider="Google")
        
        assert "auth_url" in result
        assert result["method"] == "social"
        assert result["provider"] == "Google"
        assert result["port"] == 19876
        assert "idp=Google" in result["auth_url"]
        assert "code_challenge=" in result["auth_url"]
        
        # Cleanup
        await manager.cancel_auth()
    
    @pytest.mark.asyncio
    async def test_start_social_auth_github(self):
        """Should start GitHub OAuth flow."""
        manager = KiroOAuthManager()
        
        with patch.object(manager, '_find_available_port', return_value=19877):
            result = await manager.start_social_auth(provider="Github")
        
        assert "auth_url" in result
        assert result["method"] == "social"
        assert result["provider"] == "Github"
        assert "idp=Github" in result["auth_url"]
        
        # Cleanup
        await manager.cancel_auth()
    
    @pytest.mark.asyncio
    async def test_start_social_auth_cancels_previous(self):
        """Starting new auth should cancel previous one."""
        manager = KiroOAuthManager()
        
        with patch.object(manager, '_find_available_port', return_value=19876):
            await manager.start_social_auth(provider="Google")
            status1 = manager.get_auth_status()
            assert status1 is not None
            
            # Start new auth
            await manager.start_social_auth(provider="Github")
            status2 = manager.get_auth_status()
            assert status2["provider"] == "Github"
        
        # Cleanup
        await manager.cancel_auth()
    
    @pytest.mark.asyncio
    async def test_get_auth_status_in_progress(self):
        """Status should show auth in progress."""
        manager = KiroOAuthManager()
        
        with patch.object(manager, '_find_available_port', return_value=19876):
            await manager.start_social_auth(provider="Google")
        
        status = manager.get_auth_status()
        assert status is not None
        assert status["in_progress"] is True
        assert status["method"] == "social"
        assert status["provider"] == "Google"
        assert "started_at" in status
        
        # Cleanup
        await manager.cancel_auth()
    
    @pytest.mark.asyncio
    async def test_wait_for_auth_no_auth(self):
        """Wait should raise when no auth in progress."""
        manager = KiroOAuthManager()
        
        with pytest.raises(RuntimeError, match="No authentication in progress"):
            await manager.wait_for_auth()


class TestOAuthCallbackServer:
    """Tests for OAuthCallbackServer."""
    
    def test_init(self):
        """Server should initialize with parameters."""
        server = OAuthCallbackServer(
            port=19876,
            code_verifier="test_verifier",
            expected_state="test_state",
        )
        assert server.port == 19876
        assert server.code_verifier == "test_verifier"
        assert server.expected_state == "test_state"
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Server should start and stop cleanly."""
        server = OAuthCallbackServer(
            port=19876,
            code_verifier="test_verifier",
            expected_state="test_state",
        )
        
        await server.start()
        assert server._server is not None
        
        await server.stop()
        assert server._server is None
    
    def test_generate_html_success(self):
        """Should generate success HTML."""
        server = OAuthCallbackServer(
            port=19876,
            code_verifier="test",
            expected_state="test",
        )
        html = server._generate_html(True, "Success!")
        assert "Authorization Successful!" in html
        assert "Success!" in html
        assert "#4CAF50" in html  # Green color
    
    def test_generate_html_failure(self):
        """Should generate failure HTML."""
        server = OAuthCallbackServer(
            port=19876,
            code_verifier="test",
            expected_state="test",
        )
        html = server._generate_html(False, "Error occurred")
        assert "Authorization Failed" in html
        assert "Error occurred" in html
        assert "#f44336" in html  # Red color


class TestOAuthModels:
    """Tests for OAuth Pydantic models."""
    
    def test_oauth_start_request(self):
        """OAuthStartRequest should validate correctly."""
        from kiro_gateway.models import OAuthStartRequest
        
        req = OAuthStartRequest(method="google")
        assert req.method == "google"
        assert req.port is None
        
        req_with_port = OAuthStartRequest(method="github", port=19876)
        assert req_with_port.method == "github"
        assert req_with_port.port == 19876
    
    def test_oauth_start_response(self):
        """OAuthStartResponse should serialize correctly."""
        from kiro_gateway.models import OAuthStartResponse
        
        resp = OAuthStartResponse(
            auth_url="https://example.com/auth",
            method="social",
            provider="Google",
            port=19876,
            expires_in=600,
        )
        assert resp.auth_url == "https://example.com/auth"
        assert resp.method == "social"
        assert resp.provider == "Google"
    
    def test_oauth_status_response(self):
        """OAuthStatusResponse should serialize correctly."""
        from kiro_gateway.models import OAuthStatusResponse
        
        resp = OAuthStatusResponse(in_progress=False)
        assert resp.in_progress is False
        assert resp.method is None
        
        resp_active = OAuthStatusResponse(
            in_progress=True,
            method="social",
            provider="Google",
            started_at="2024-01-01T00:00:00Z",
        )
        assert resp_active.in_progress is True
        assert resp_active.method == "social"
