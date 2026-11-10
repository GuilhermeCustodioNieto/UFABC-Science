"""Engine, sessões e inicialização do banco de dados.

O schema é definido exclusivamente pelas migrações Alembic: ``init_database``
executa ``alembic upgrade head`` e depois popula os dados de referência
(editorias). A operação é idempotente.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science.domain.models import Category
from ufabc_science.domain.schemas import DEFAULT_CATEGORIES, CategoryDefinition

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # O SQLite só aplica chaves estrangeiras com este PRAGMA, por conexão.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def ensure_sqlite_directory(database_url: str) -> None:
    """Cria o diretório do arquivo SQLite, se necessário."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return
    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Cria a engine SQLAlchemy para a URL informada."""
    ensure_sqlite_directory(database_url)
    engine = create_engine(database_url, echo=echo)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Cria a fábrica de sessões (``expire_on_commit=False`` para uso na CLI)."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão transacional: confirma ao final ou desfaz em caso de erro."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def alembic_config(database_url: str) -> Config:
    """Configuração Alembic independente do diretório corrente e do ``alembic.ini``."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # '%' precisa ser escapado no ConfigParser do Alembic.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(engine: Engine, database_url: str) -> None:
    """Aplica todas as migrações pendentes (``alembic upgrade head``)."""
    config = alembic_config(database_url)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def current_revision(engine: Engine) -> str | None:
    """Revisão Alembic aplicada ao banco (``None`` se não inicializado)."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision(database_url: str) -> str | None:
    """Revisão mais recente disponível nas migrações."""
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def seed_categories(
    session: Session, definitions: tuple[CategoryDefinition, ...] = DEFAULT_CATEGORIES
) -> int:
    """Insere as editorias ausentes (pelo ``slug``). Retorna quantas foram criadas.

    Editorias existentes não são sobrescritas, preservando ajustes manuais.
    """
    existing = set(session.scalars(select(Category.slug)))
    created = 0
    for definition in definitions:
        if definition.slug in existing:
            continue
        session.add(
            Category(
                name=definition.name,
                slug=definition.slug,
                description=definition.description,
                active=True,
            )
        )
        created += 1
    return created


@dataclass(frozen=True)
class InitResult:
    """Resultado de ``init_database``."""

    previous_revision: str | None
    current_revision: str | None
    categories_created: int

    @property
    def migrated(self) -> bool:
        return self.previous_revision != self.current_revision


def init_database(database_url: str) -> InitResult:
    """Cria/atualiza o schema e popula as editorias. Idempotente."""
    engine = create_db_engine(database_url)
    try:
        previous = current_revision(engine)
        upgrade_database(engine, database_url)
        current = current_revision(engine)
        with session_scope(create_session_factory(engine)) as session:
            created = seed_categories(session)
    finally:
        engine.dispose()
    logger.debug("Banco em %s: revisão %s -> %s", database_url, previous, current)
    return InitResult(previous, current, created)
