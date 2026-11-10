"""Fixtures compartilhadas. Nenhum teste acessa a internet ou serviços externos.

As respostas em ``tests/fixtures/api`` são amostras reais das APIs (OpenAlex,
PubMed, arXiv e Crossref), servidas por um ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science.config.settings import Settings
from ufabc_science.domain.models import Base
from ufabc_science.infrastructure.database import (
    create_db_engine,
    create_session_factory,
    init_database,
    seed_categories,
)

FIXTURES = Path(__file__).parent / "fixtures" / "api"

_ENV_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "LOG_LEVEL",
    "AI_PROVIDER",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_BASE_URL",
    "OPENALEX_EMAIL",
    "OPENALEX_API_KEY",
    "CONTACT_EMAIL",
    "NCBI_API_KEY",
    "COLLECTION_DAYS",
    "MAX_ARTICLES_PER_SOURCE",
    "EDITORIAL_LANGUAGE",
    "TIMEZONE",
    "ENABLED_SOURCES",
    "DATA_DIR",
    "EDITIONS_DIR",
    "OUTPUT_DIR",
    "PREVIEW_DIR",
    "GITHUB_STEP_SUMMARY",
    "HTTP_BACKOFF_SECONDS",
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isola cada teste do ``.env`` e das variáveis de ambiente do desenvolvedor."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_BACKOFF_SECONDS", "0")
    # Intervalos minimos entre requisicoes nao precisam esperar de verdade nos testes.
    monkeypatch.setattr("ufabc_science.collectors.base._sleep", lambda seconds: None)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """URL de um banco SQLite em arquivo temporário (ainda não criado)."""
    return f"sqlite:///{(tmp_path / 'db' / 'test.db').as_posix()}"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Banco SQLite em memória com o schema criado a partir dos modelos."""
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture
def seeded_session(session: Session) -> Session:
    """Sessao em memoria com as cinco editorias cadastradas."""
    seed_categories(session)
    session.commit()
    return session


# --- Ambiente completo (banco migrado + diretórios) -------------------------------------


@dataclass
class Workspace:
    root: Path
    settings: Settings
    engine: Engine
    factory: sessionmaker[Session]

    @property
    def editorial(self) -> Path:
        return self.settings.editorial_dir


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Workspace]:
    url = f"sqlite:///{(tmp_path / 'data' / 'database' / 'ufabc.db').as_posix()}"
    init_database(url)
    settings = Settings(
        _env_file=None,
        database_url=url,
        data_dir=tmp_path / "data",
        editions_dir=tmp_path / "editions",
        output_dir=tmp_path / "dist",
        preview_dir=tmp_path / "build" / "preview",
        http_backoff_seconds=0,
        http_max_retries=1,
        min_abstract_words=40,
    )
    engine = create_db_engine(url)
    yield Workspace(tmp_path, settings, engine, create_session_factory(engine))
    engine.dispose()


# --- Transporte HTTP simulado -----------------------------------------------------------


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@dataclass
class FakeApis:
    """Simula as quatro APIs a partir das fixtures; registra as requisições."""

    fail: set[str] = field(default_factory=set)
    requests: list[httpx.Request] = field(default_factory=list)
    status_overrides: dict[str, list[int]] = field(default_factory=dict)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        source = {
            "api.openalex.org": "openalex",
            "eutils.ncbi.nlm.nih.gov": "pubmed",
            "export.arxiv.org": "arxiv",
            "api.crossref.org": "crossref",
        }.get(host)
        if source is None:
            return httpx.Response(404)
        if source in self.fail:
            return httpx.Response(500, text="erro simulado")
        queue = self.status_overrides.get(source)
        if queue:
            return httpx.Response(queue.pop(0), text="falha transitória")
        path = request.url.path
        if source == "openalex":
            return httpx.Response(200, content=load_fixture("openalex_raw.json"))
        if source == "pubmed":
            if path.endswith("esearch.fcgi"):
                return httpx.Response(200, content=load_fixture("pubmed_esearch.json"))
            return httpx.Response(200, content=load_fixture("pubmed_efetch.xml"))
        if source == "arxiv":
            return httpx.Response(200, content=load_fixture("arxiv_feed.xml"))
        payload = json.loads(load_fixture("crossref_works.json"))
        if path.startswith("/works/"):
            doi = path.split("/works/", 1)[1].lower()
            for item in payload["message"]["items"]:
                if item["DOI"].lower() == doi:
                    return httpx.Response(200, json={"status": "ok", "message": item})
            return httpx.Response(404, text="Resource not found.")
        return httpx.Response(200, json=payload)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def fake_apis() -> FakeApis:
    return FakeApis()


@pytest.fixture
def make_transport() -> Callable[..., httpx.MockTransport]:
    def factory(**kwargs: object) -> httpx.MockTransport:
        return FakeApis(**kwargs).transport()  # type: ignore[arg-type]

    return factory
