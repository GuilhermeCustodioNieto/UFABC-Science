"""Ambiente Alembic do UFABC Science.

Ordem de resolução da conexão:

1. ``config.attributes["connection"]`` — usado por ``init-db`` e pelos testes;
2. ``sqlalchemy.url`` definido programaticamente (``alembic_config``);
3. ``DATABASE_URL`` via ``Settings`` — usado pela CLI ``alembic`` com ``alembic.ini``.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection

from ufabc_science.config.settings import Settings
from ufabc_science.domain.models import Base, UTCDateTime
from ufabc_science.infrastructure.database import create_db_engine

config = context.config
target_metadata = Base.metadata

# Logging do alembic.ini apenas quando executado pela CLI `alembic`.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    return url or Settings().database_url


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Renderiza tipos customizados como tipos genéricos nas migrações geradas."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # ALTER TABLE compatível com SQLite
        compare_type=True,
        render_item=render_item,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_db_engine(_database_url())
    try:
        with engine.connect() as conn:
            _configure(conn)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
