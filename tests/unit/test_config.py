# -*- coding: utf-8 -*-

"""
Unit tests for the configuration module.
Verifies loading settings from YAML configuration file.
"""

import pytest
import tempfile
import os
from pathlib import Path

import yaml


class TestYamlConfigLoading:
    """Tests for YAML config loading functionality."""
    
    def test_load_yaml_config_returns_dict(self):
        """Verifies that _load_yaml_config returns a dictionary."""
        from kiro_gateway.config import _load_yaml_config
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("log_level: DEBUG\n")
            temp_path = f.name
        
        try:
            result = _load_yaml_config(temp_path)
            assert isinstance(result, dict)
            assert result.get("log_level") == "DEBUG"
        finally:
            os.unlink(temp_path)
    
    def test_load_yaml_config_missing_file_returns_empty(self):
        """Verifies that missing config file returns empty dict."""
        from kiro_gateway.config import _load_yaml_config
        
        result = _load_yaml_config("/nonexistent/path/config.yml")
        assert result == {}
    
    def test_load_yaml_config_empty_file_returns_empty(self):
        """Verifies that empty config file returns empty dict."""
        from kiro_gateway.config import _load_yaml_config
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("")
            temp_path = f.name
        
        try:
            result = _load_yaml_config(temp_path)
            assert result == {}
        finally:
            os.unlink(temp_path)


class TestGetConfigValue:
    """Tests for _get_config_value helper function."""
    
    def test_get_config_value_returns_value(self):
        """Verifies that existing key returns its value."""
        from kiro_gateway.config import _get_config_value
        
        config = {"log_level": "DEBUG", "timeout": 30}
        assert _get_config_value(config, "log_level") == "DEBUG"
        assert _get_config_value(config, "timeout") == 30
    
    def test_get_config_value_returns_default(self):
        """Verifies that missing key returns default."""
        from kiro_gateway.config import _get_config_value
        
        config = {"log_level": "DEBUG"}
        assert _get_config_value(config, "missing_key", "default") == "default"
        assert _get_config_value(config, "another_missing") is None


class TestLogLevelConfig:
    """Tests for LOG_LEVEL configuration logic."""
    
    def test_log_level_uppercase_conversion(self):
        """Verifies LOG_LEVEL conversion to uppercase."""
        from kiro_gateway.config import _get_config_value
        
        config = {"log_level": "warning"}
        log_level = str(_get_config_value(config, "log_level", "INFO")).upper()
        assert log_level == "WARNING"
    
    def test_log_level_default_is_info(self):
        """Verifies that LOG_LEVEL defaults to INFO."""
        from kiro_gateway.config import _get_config_value
        
        config = {}
        log_level = str(_get_config_value(config, "log_level", "INFO")).upper()
        assert log_level == "INFO"
    
    def test_log_level_from_config(self):
        """Verifies loading LOG_LEVEL from config."""
        from kiro_gateway.config import _get_config_value
        
        for level in ["DEBUG", "TRACE", "ERROR", "CRITICAL", "WARNING"]:
            config = {"log_level": level}
            log_level = str(_get_config_value(config, "log_level", "INFO")).upper()
            assert log_level == level


class TestToolDescriptionMaxLengthConfig:
    """Tests for TOOL_DESCRIPTION_MAX_LENGTH configuration logic."""
    
    def test_default_tool_description_max_length(self):
        """Verifies the default value for TOOL_DESCRIPTION_MAX_LENGTH."""
        from kiro_gateway.config import _get_config_value
        
        config = {}
        value = int(_get_config_value(config, "tool_description_max_length", 10000))
        assert value == 10000
    
    def test_tool_description_max_length_from_config(self):
        """Verifies loading TOOL_DESCRIPTION_MAX_LENGTH from config."""
        from kiro_gateway.config import _get_config_value
        
        config = {"tool_description_max_length": 5000}
        value = int(_get_config_value(config, "tool_description_max_length", 10000))
        assert value == 5000
    
    def test_tool_description_max_length_zero(self):
        """Verifies that 0 is a valid value."""
        from kiro_gateway.config import _get_config_value
        
        config = {"tool_description_max_length": 0}
        value = int(_get_config_value(config, "tool_description_max_length", 10000))
        assert value == 0


class TestTimeoutConfigurationWarning:
    """Tests for _warn_timeout_configuration() function."""
    
    def test_no_warning_when_first_token_less_than_streaming(self, capsys, monkeypatch):
        """Verifies that warning is NOT shown with correct configuration."""
        import kiro_gateway.config as config_module
        
        monkeypatch.setattr(config_module, 'FIRST_TOKEN_TIMEOUT', 15.0)
        monkeypatch.setattr(config_module, 'STREAMING_READ_TIMEOUT', 300.0)
        
        config_module._warn_timeout_configuration()
        captured = capsys.readouterr()
        
        assert "WARNING" not in captured.err
        assert "Suboptimal timeout configuration" not in captured.err
    
    def test_warning_when_first_token_equals_streaming(self, capsys, monkeypatch):
        """Verifies that warning is shown when timeouts are equal."""
        import kiro_gateway.config as config_module
        
        monkeypatch.setattr(config_module, 'FIRST_TOKEN_TIMEOUT', 300.0)
        monkeypatch.setattr(config_module, 'STREAMING_READ_TIMEOUT', 300.0)
        
        config_module._warn_timeout_configuration()
        captured = capsys.readouterr()
        
        assert "WARNING" in captured.err or "Suboptimal timeout configuration" in captured.err
    
    def test_warning_when_first_token_greater_than_streaming(self, capsys, monkeypatch):
        """Verifies that warning is shown when FIRST_TOKEN > STREAMING."""
        import kiro_gateway.config as config_module
        
        monkeypatch.setattr(config_module, 'FIRST_TOKEN_TIMEOUT', 500.0)
        monkeypatch.setattr(config_module, 'STREAMING_READ_TIMEOUT', 300.0)
        
        config_module._warn_timeout_configuration()
        captured = capsys.readouterr()
        
        assert "WARNING" in captured.err or "Suboptimal timeout configuration" in captured.err
        assert "500" in captured.err
        assert "300" in captured.err
    
    def test_warning_contains_recommendation(self, capsys, monkeypatch):
        """Verifies that warning contains a recommendation."""
        import kiro_gateway.config as config_module
        
        monkeypatch.setattr(config_module, 'FIRST_TOKEN_TIMEOUT', 400.0)
        monkeypatch.setattr(config_module, 'STREAMING_READ_TIMEOUT', 300.0)
        
        config_module._warn_timeout_configuration()
        captured = capsys.readouterr()
        
        assert "Recommendation" in captured.err or "LESS than" in captured.err


class TestConfigConstants:
    """Tests for configuration constants."""
    
    def test_model_mapping_exists(self):
        """Verifies MODEL_MAPPING is defined."""
        from kiro_gateway.config import MODEL_MAPPING
        
        assert isinstance(MODEL_MAPPING, dict)
        assert len(MODEL_MAPPING) > 0
    
    def test_available_models_exists(self):
        """Verifies AVAILABLE_MODELS is defined."""
        from kiro_gateway.config import AVAILABLE_MODELS
        
        assert isinstance(AVAILABLE_MODELS, list)
        assert len(AVAILABLE_MODELS) > 0
    
    def test_get_internal_model_id(self):
        """Verifies get_internal_model_id function."""
        from kiro_gateway.config import get_internal_model_id, MODEL_MAPPING
        
        for external, internal in MODEL_MAPPING.items():
            assert get_internal_model_id(external) == internal
        
        # Unknown model returns itself
        assert get_internal_model_id("unknown-model") == "unknown-model"
    
    def test_url_template_functions(self):
        """Verifies URL template functions."""
        from kiro_gateway.config import get_kiro_refresh_url, get_kiro_api_host, get_kiro_q_host
        
        region = "us-east-1"
        
        refresh_url = get_kiro_refresh_url(region)
        assert region in refresh_url
        assert "refreshToken" in refresh_url
        
        api_host = get_kiro_api_host(region)
        assert region in api_host
        assert "codewhisperer" in api_host
        
        q_host = get_kiro_q_host(region)
        assert region in q_host


class TestAwsSsoOidcUrlConfig:
    """Tests for AWS SSO OIDC URL configuration."""
    
    def test_aws_sso_oidc_url_template_exists(self):
        """
        What it does: Verifies that AWS_SSO_OIDC_URL_TEMPLATE constant exists.
        Purpose: Ensure the template is defined in config.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro_gateway.config as config_module
        importlib.reload(config_module)
        
        print("Verification: AWS_SSO_OIDC_URL_TEMPLATE exists...")
        assert hasattr(config_module, 'AWS_SSO_OIDC_URL_TEMPLATE')
        
        print(f"AWS_SSO_OIDC_URL_TEMPLATE: {config_module.AWS_SSO_OIDC_URL_TEMPLATE}")
        assert "oidc" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
        assert "amazonaws.com" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
        assert "{region}" in config_module.AWS_SSO_OIDC_URL_TEMPLATE
    
    def test_get_aws_sso_oidc_url_returns_correct_url(self):
        """
        What it does: Verifies that get_aws_sso_oidc_url returns correct URL.
        Purpose: Ensure the function formats URL correctly.
        """
        print("Setup: Importing get_aws_sso_oidc_url...")
        from kiro_gateway.config import get_aws_sso_oidc_url
        
        print("Action: Calling get_aws_sso_oidc_url('us-east-1')...")
        url = get_aws_sso_oidc_url("us-east-1")
        
        print(f"Verification: URL is correct...")
        expected = "https://oidc.us-east-1.amazonaws.com/token"
        print(f"Comparing: Expected '{expected}', Got '{url}'")
        assert url == expected
    
    def test_get_aws_sso_oidc_url_with_different_regions(self):
        """
        What it does: Verifies URL generation for different regions.
        Purpose: Ensure the function works with various AWS regions.
        """
        print("Setup: Importing get_aws_sso_oidc_url...")
        from kiro_gateway.config import get_aws_sso_oidc_url
        
        test_cases = [
            ("us-east-1", "https://oidc.us-east-1.amazonaws.com/token"),
            ("eu-west-1", "https://oidc.eu-west-1.amazonaws.com/token"),
            ("ap-southeast-1", "https://oidc.ap-southeast-1.amazonaws.com/token"),
            ("us-west-2", "https://oidc.us-west-2.amazonaws.com/token"),
        ]
        
        for region, expected in test_cases:
            print(f"Action: Calling get_aws_sso_oidc_url('{region}')...")
            url = get_aws_sso_oidc_url(region)
            print(f"Comparing: Expected '{expected}', Got '{url}'")
            assert url == expected


class TestKiroCliDbFileConfig:
    """Tests for KIRO_CLI_DB_FILE configuration."""
    
    def test_kiro_cli_db_file_config_exists(self):
        """
        What it does: Verifies that KIRO_CLI_DB_FILE constant exists.
        Purpose: Ensure the config parameter is defined.
        """
        print("Setup: Importing config module...")
        import importlib
        import kiro_gateway.config as config_module
        importlib.reload(config_module)
        
        print("Verification: KIRO_CLI_DB_FILE exists...")
        assert hasattr(config_module, 'KIRO_CLI_DB_FILE')
        
        print(f"KIRO_CLI_DB_FILE: '{config_module.KIRO_CLI_DB_FILE}'")
        # Default should be empty string
        assert isinstance(config_module.KIRO_CLI_DB_FILE, str)
    
    def test_kiro_cli_db_file_from_environment(self):
        """
        What it does: Verifies loading KIRO_CLI_DB_FILE from environment variable.
        Purpose: Ensure the value from environment is used.
        """
        print("Setup: Setting KIRO_CLI_DB_FILE=~/.local/share/kiro-cli/data.sqlite3...")
        
        with patch.dict(os.environ, {"KIRO_CLI_DB_FILE": "~/.local/share/kiro-cli/data.sqlite3"}):
            import importlib
            import kiro_gateway.config as config_module
            importlib.reload(config_module)
            
            print(f"KIRO_CLI_DB_FILE: {config_module.KIRO_CLI_DB_FILE}")
            # Path should be normalized
            assert "kiro-cli" in config_module.KIRO_CLI_DB_FILE or "kiro_cli" in config_module.KIRO_CLI_DB_FILE.lower()
