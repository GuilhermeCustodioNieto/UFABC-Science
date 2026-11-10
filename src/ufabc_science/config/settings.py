"""Configurações carregadas de variáveis de ambiente e do arquivo ``.env``.

Todas as variáveis possuem valores padrão seguros: sem nenhuma configuração o
projeto funciona em modo de desenvolvimento, com SQLite local e provedor de IA
``mock``. Integrações externas sem credenciais funcionam no modo anônimo
(quando a fonte permite) ou ficam desabilitadas.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]

KNOWN_SOURCES = ("openalex", "pubmed", "arxiv", "crossref")
KNOWN_AI_PROVIDERS = ("mock", "openai_compatible")


class Settings(BaseSettings):
    """Configurações da aplicação (ver ``.env.example`` e ``docs/AUTOMATION_GUIDE.md``)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Geral -------------------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///data/database/ufabc_science.db"
    log_level: LogLevel = "INFO"
    editorial_language: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"

    # --- Diretórios --------------------------------------------------------------------
    data_dir: Path = Path("data")
    editions_dir: Path = Path("editions")
    output_dir: Path = Path("dist")
    preview_dir: Path = Path("build/preview")

    # --- Fontes científicas ------------------------------------------------------------
    enabled_sources: str = ",".join(KNOWN_SOURCES)
    contact_email: str | None = None
    openalex_email: str | None = None
    openalex_api_key: SecretStr | None = None
    ncbi_api_key: SecretStr | None = None
    collection_days: int = Field(default=7, ge=1, le=365)
    max_articles_per_source: int = Field(default=100, ge=1, le=10_000)
    http_timeout: float = Field(default=30.0, gt=0, le=300)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    http_backoff_seconds: float = Field(default=1.0, ge=0, le=60)

    # --- Inteligência artificial -------------------------------------------------------
    ai_provider: str = "mock"
    ai_api_key: SecretStr | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None
    ai_timeout: float = Field(default=60.0, gt=0, le=600)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    ai_temperature: float | None = Field(default=0.2, ge=0, le=2)
    ai_max_tokens: int | None = Field(default=2000, ge=64, le=32_000)

    # --- Classificação e relevância ----------------------------------------------------
    classification_rules_path: Path | None = None
    classification_min_confidence: float = Field(default=0.35, ge=0, le=1)
    classification_uncertain_below: float = Field(default=0.5, ge=0, le=1)
    priority_very_high: float = Field(default=85, ge=0, le=100)
    priority_high: float = Field(default=70, ge=0, le=100)
    priority_moderate: float = Field(default=50, ge=0, le=100)

    # --- Geração -----------------------------------------------------------------------
    generation_limit: int = Field(default=10, ge=1, le=500)
    min_abstract_words: int = Field(default=40, ge=0, le=1000)
    # JSON opcional: {"introduction": [50, 100], ..., "total": [350, 650]}
    generation_word_limits: dict[str, tuple[int, int]] | None = None

    # --- Automação ---------------------------------------------------------------------
    pipeline_lock_stale_hours: float = Field(default=6, gt=0, le=168)

    # --- Validadores -------------------------------------------------------------------

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "ai_api_key",
        "ncbi_api_key",
        "openalex_api_key",
        "openalex_email",
        "contact_email",
        "ai_model",
        "ai_base_url",
        "classification_rules_path",
        "generation_word_limits",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        # Variáveis vazias no .env (ex.: ``AI_API_KEY=``) significam "não configurado".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ai_temperature", "ai_max_tokens", mode="before")
    @classmethod
    def _empty_optional_number(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ai_provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower().replace("-", "_") or "mock"
        return value

    @field_validator("ai_provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if value not in KNOWN_AI_PROVIDERS:
            raise ValueError(
                f"AI_PROVIDER desconhecido: {value!r}. Use um de: {', '.join(KNOWN_AI_PROVIDERS)}"
            )
        return value

    @field_validator("enabled_sources")
    @classmethod
    def _validate_sources(cls, value: str) -> str:
        names = [name.strip().lower() for name in value.split(",") if name.strip()]
        unknown = sorted(set(names) - set(KNOWN_SOURCES))
        if unknown:
            raise ValueError(
                f"Fontes desconhecidas em ENABLED_SOURCES: {', '.join(unknown)}. "
                f"Disponíveis: {', '.join(KNOWN_SOURCES)}"
            )
        return ",".join(dict.fromkeys(names))

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Fuso horário inválido: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _validate_consistency(self) -> Settings:
        if not (self.priority_moderate <= self.priority_high <= self.priority_very_high):
            raise ValueError(
                "As faixas de prioridade devem respeitar "
                "PRIORITY_MODERATE <= PRIORITY_HIGH <= PRIORITY_VERY_HIGH."
            )
        if self.classification_uncertain_below < self.classification_min_confidence:
            raise ValueError(
                "CLASSIFICATION_UNCERTAIN_BELOW deve ser >= CLASSIFICATION_MIN_CONFIDENCE."
            )
        if self.ai_provider == "openai_compatible" and not self.ai_model:
            raise ValueError("AI_PROVIDER=openai_compatible exige AI_MODEL.")
        if self.ai_provider == "openai_compatible" and not self.ai_base_url:
            raise ValueError("AI_PROVIDER=openai_compatible exige AI_BASE_URL.")
        for name, bounds in (self.generation_word_limits or {}).items():
            low, high = bounds
            if low < 0 or high < low:
                raise ValueError(f"Limite de palavras inválido para {name!r}: {bounds}")
        return self

    # --- Propriedades derivadas --------------------------------------------------------

    @property
    def tzinfo(self) -> ZoneInfo:
        """Fuso horário usado na apresentação de datas (armazenamento é sempre UTC)."""
        return ZoneInfo(self.timezone)

    @property
    def ai_enabled(self) -> bool:
        """Indica se há um provedor de IA externo (não mock) configurado."""
        return self.ai_provider != "mock"

    @property
    def sources(self) -> list[str]:
        """Fontes habilitadas, na ordem configurada."""
        return [name for name in self.enabled_sources.split(",") if name]

    @property
    def openalex_contact(self) -> str | None:
        return self.openalex_email or self.contact_email

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def editorial_dir(self) -> Path:
        return self.data_dir / "editorial"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "database" / "pipeline.lock"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna as configurações (cacheadas) do processo."""
    return Settings()
