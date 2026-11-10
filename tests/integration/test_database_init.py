"""Inicialização do banco via migrações Alembic (sem ``create_all``)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, inspect, select

from ufabc_science.domain.models import Base, Category
from ufabc_science.infrastructure.database import (
    alembic_config,
    create_db_engine,
    create_session_factory,
    current_revision,
    head_revision,
    init_database,
    session_scope,
)

EXPECTED_TABLES = {
    "alembic_version",
    "articles",
    "sources",
    "article_sources",
    "categories",
    "article_categories",
    "relevance_assessments",
    "generated_contents",
    "editorial_reviews",
    "newsletter_editions",
    "newsletter_items",
    "pipeline_runs",
}


def _count_categories(db_url: str) -> int:
    engine = create_db_engine(db_url)
    try:
        with create_session_factory(engine)() as session:
            return session.scalar(select(func.count()).select_from(Category)) or 0
    finally:
        engine.dispose()


def test_init_creates_schema_and_seeds_categories(db_url: str, tmp_path: Path) -> None:
    result = init_database(db_url)

    assert (tmp_path / "db" / "test.db").is_file()  # diretório criado automaticamente
    assert result.previous_revision is None
    assert result.current_revision == head_revision(db_url)
    assert result.migrated is True
    assert result.categories_created == 5

    engine = create_db_engine(db_url)
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    finally:
        engine.dispose()
    assert _count_categories(db_url) == 5


def test_init_is_idempotent(db_url: str) -> None:
    init_database(db_url)

    second = init_database(db_url)

    assert second.migrated is False
    assert second.categories_created == 0
    assert _count_categories(db_url) == 5


def test_seed_does_not_overwrite_manual_changes(db_url: str) -> None:
    init_database(db_url)
    engine = create_db_engine(db_url)
    try:
        with session_scope(create_session_factory(engine)) as session:
            category = session.scalars(select(Category).where(Category.slug == "engenharias")).one()
            category.description = "Descrição ajustada pelo editor."
            category.active = False
    finally:
        engine.dispose()

    init_database(db_url)

    engine = create_db_engine(db_url)
    try:
        with create_session_factory(engine)() as session:
            category = session.scalars(select(Category).where(Category.slug == "engenharias")).one()
            assert category.description == "Descrição ajustada pelo editor."
            assert category.active is False
    finally:
        engine.dispose()


def test_migrations_match_orm_models(db_url: str) -> None:
    """Garante que não há divergência entre modelos e migrações."""
    init_database(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "render_as_batch": True}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == []


def test_migrations_are_reversible(db_url: str) -> None:
    init_database(db_url)
    engine = create_db_engine(db_url)
    config = alembic_config(db_url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        assert current_revision(engine) is None
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()

    result = init_database(db_url)
    assert result.current_revision == head_revision(db_url)


def test_sqlite_foreign_keys_pragma_is_enabled(db_url: str) -> None:
    init_database(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        engine.dispose()
