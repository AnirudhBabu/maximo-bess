from __future__ import annotations

from pathlib import Path

import pytest

from mxbess.config import ConfigError, Settings, load_settings, parse_dotenv


def test_parse_dotenv(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text(
        """
# comment
MAXIMO_HOST=example.manage.ibm.com
export MAXIMO_APIKEY="secret"
EMPTY=
QUOTED='single'
""",
        encoding="utf-8",
    )
    values = parse_dotenv(path)
    assert values["MAXIMO_HOST"] == "example.manage.ibm.com"
    assert values["MAXIMO_APIKEY"] == "secret"
    assert values["QUOTED"] == "single"
    assert values["EMPTY"] == ""


def test_missing_dotenv_is_ignored(tmp_path: Path):
    assert parse_dotenv(tmp_path / "nope.env") == {}


def test_environment_wins_over_dotenv(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("MAXIMO_HOST=file.example.com\nMAXIMO_SITE_ID=FILE-SITE\n", encoding="utf-8")
    settings = load_settings(env={"MAXIMO_HOST": "env.example.com"}, dotenv_path=path)
    assert settings.host == "env.example.com"
    assert settings.site_id == "FILE-SITE"


def test_load_settings_defaults():
    settings = load_settings(env={})
    assert settings.site_id == "BISHA-BESS"
    assert settings.org_id == "BISHA"
    assert settings.live_enabled is False
    assert settings.timeout_seconds == 30.0


def test_boolean_parsing():
    settings = load_settings(env={"MAXIMO_LIVE_ENABLED": "YES"})
    assert settings.live_enabled is True
    assert load_settings(env={"MAXIMO_LIVE_ENABLED": "off"}).live_enabled is False


def test_host_is_normalised():
    settings = load_settings(env={"MAXIMO_HOST": "https://example.com/maximo/"})
    assert settings.host == "example.com/maximo"
    assert settings.api_root == "https://example.com/maximo"


def test_blank_host_becomes_none():
    assert load_settings(env={"MAXIMO_HOST": "   "}).host is None


def test_api_root_requires_host():
    with pytest.raises(ConfigError):
        _ = load_settings(env={}).api_root


def test_require_live_refuses_by_default():
    with pytest.raises(ConfigError, match="disabled"):
        load_settings(env={}).require_live()


def test_require_live_lists_missing_values():
    with pytest.raises(ConfigError, match="MAXIMO_HOST"):
        load_settings(env={"MAXIMO_LIVE_ENABLED": "true"}).require_live()


def test_require_live_accepts_complete_config():
    settings = load_settings(
        env={
            "MAXIMO_LIVE_ENABLED": "true",
            "MAXIMO_HOST": "example.com",
            "MAXIMO_APIKEY": "secret",
        }
    )
    settings.require_live()


def test_secret_is_masked_in_repr():
    settings = Settings(api_key="super-secret")
    assert "super-secret" not in repr(settings)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "super-secret"
