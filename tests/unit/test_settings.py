from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ufabc_science.config.settings import Settings


def test_defaults_work_without_any_configuration() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url == "sqlite:///data/database/ufabc_science.db"
    assert settings.ai_provider == "mock"
    assert settings.ai_api_key is None
    assert settings.ai_enabled is False
    assert settings.collection_days == 7
    assert settings.max_articles_per_source == 100
    assert settings.editorial_language == "pt-BR"
    assert str(settings.tzinfo) == "America/Sao_Paulo"


def test_reads_dotenv_file(isolated_env: Path) -> None:
    (isolated_env / ".env").write_text(
        "LOG_LEVEL=debug\nCOLLECTION_DAYS=14\nAI_API_KEY=\nNCBI_API_KEY=\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.log_level == "DEBUG"
    assert settings.collection_days == 14
    # Valores vazios significam "não configurado".
    assert settings.ai_api_key is None
    assert settings.ncbi_api_key is None


def test_environment_overrides_dotenv(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated_env / ".env").write_text("COLLECTION_DAYS=14\n", encoding="utf-8")
    monkeypatch.setenv("COLLECTION_DAYS", "3")

    assert Settings().collection_days == 3


def test_secrets_are_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "OpenAI-Compatible")
    monkeypatch.setenv("AI_API_KEY", "super-secret-value")
    monkeypatch.setenv("AI_MODEL", "modelo-x")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")

    settings = Settings()

    assert settings.ai_provider == "openai_compatible"
    assert settings.ai_enabled is True
    assert "super-secret-value" not in repr(settings)
    assert settings.ai_api_key is not None
    assert settings.ai_api_key.get_secret_value() == "super-secret-value"


def test_mock_provider_is_never_considered_external(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("AI_API_KEY", "irrelevante")

    assert Settings().ai_enabled is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TIMEZONE", "Mars/Olympus_Mons"),
        ("COLLECTION_DAYS", "0"),
        ("MAX_ARTICLES_PER_SOURCE", "-1"),
        ("LOG_LEVEL", "VERBOSE"),
        ("APP_ENV", "staging"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()
