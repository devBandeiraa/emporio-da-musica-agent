from datetime import datetime
from pathlib import Path

import pytest

from emporio_agent import config
from emporio_agent.config import DEFAULT_MODEL, ConfigError, Settings, load_settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ["LLM_MODEL", "REFERENCE_DATETIME", "DATA_DIR"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_defaults():
    settings = load_settings()
    assert settings.api_key == "test-key"
    assert settings.model == DEFAULT_MODEL
    assert settings.reference_datetime is None
    assert settings.data_dir == Path("data")


def test_reads_overrides(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemini-outro")
    monkeypatch.setenv("REFERENCE_DATETIME", "2026-03-25T10:00:00")
    monkeypatch.setenv("DATA_DIR", "other")

    settings = load_settings()

    assert settings.model == "gemini-outro"
    assert settings.now() == datetime(2026, 3, 25, 10, 0)
    assert settings.data_dir == Path("other")


def test_blank_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("REFERENCE_DATETIME", "")
    settings = load_settings()
    assert settings.model == DEFAULT_MODEL
    assert settings.reference_datetime is None


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_settings()


def test_invalid_reference_datetime_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("REFERENCE_DATETIME", "ontem")
    with pytest.raises(ConfigError, match="REFERENCE_DATETIME"):
        load_settings()


def test_now_uses_the_clock_without_a_reference_date():
    assert Settings(api_key="k").now().year >= 2026
