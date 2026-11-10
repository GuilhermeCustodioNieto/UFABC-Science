"""Coleta completa com APIs simuladas: persistência, idempotência e falhas isoladas."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from tests.conftest import FakeApis, Workspace
from ufabc_science.collectors.service import collect_articles, enrich_with_crossref
from ufabc_science.domain.enums import PeerReviewStatus
from ufabc_science.domain.models import Article, ArticleSource, Source

START, END = date(2026, 11, 1), date(2026, 11, 8)


def _collect(ws: Workspace, apis: FakeApis, sources: list[str] | None = None):
    return collect_articles(
        ws.settings,
        ws.factory,
        start_date=START,
        end_date=END,
        sources=sources,
        query="teste",
        max_articles=10,
        transport=apis.transport(),
    )


def test_collects_from_all_sources_and_saves_raw_responses(
    workspace: Workspace, fake_apis: FakeApis
) -> None:
    summary = _collect(workspace, fake_apis)

    per_source = {s.source: s for s in summary.sources}
    assert per_source["openalex"].inserted == 2
    assert per_source["pubmed"].inserted == 2
    assert per_source["arxiv"].inserted == 2
    assert per_source["crossref"].inserted == 2
    assert summary.errors == []

    with workspace.factory() as session:
        assert session.scalar(select(func.count()).select_from(Article)) == 8
        assert {s.name for s in session.scalars(select(Source))} == {
            "openalex",
            "pubmed",
            "arxiv",
            "crossref",
        }
        for article in session.scalars(select(Article)):
            assert article.sources, "toda origem deve ser rastreável"
            assert article.raw_data_path and Path(article.raw_data_path).is_file()
    raw_dirs = {p.name for p in (workspace.settings.raw_dir).iterdir()}
    assert raw_dirs == {"openalex", "pubmed", "arxiv", "crossref"}


def test_collection_is_idempotent(workspace: Workspace, fake_apis: FakeApis) -> None:
    _collect(workspace, fake_apis)
    raw_files = sorted(workspace.settings.raw_dir.rglob("*.*"))

    second = _collect(workspace, fake_apis)

    assert second.total("inserted") == 0
    assert second.total("ignored") == 8
    with workspace.factory() as session:
        assert session.scalar(select(func.count()).select_from(Article)) == 8
        assert session.scalar(select(func.count()).select_from(ArticleSource)) == 8
    # Mesma resposta bruta não gera arquivo duplicado.
    assert sorted(workspace.settings.raw_dir.rglob("*.*")) == raw_files


def test_failure_of_one_source_does_not_stop_the_others(workspace: Workspace) -> None:
    apis = FakeApis(fail={"pubmed"})

    summary = _collect(workspace, apis)

    stats = {s.source: s for s in summary.sources}
    assert stats["pubmed"].errors and stats["pubmed"].inserted == 0
    assert summary.failed_sources == ["pubmed"]
    assert stats["openalex"].inserted == 2 and stats["arxiv"].inserted == 2


def test_transient_failure_is_retried(workspace: Workspace) -> None:
    apis = FakeApis(status_overrides={"openalex": [503]})

    summary = _collect(workspace, apis, ["openalex"])

    assert summary.errors == []
    assert summary.sources[0].inserted == 2
    assert summary.sources[0].requests == 2


def test_preprints_are_identified(workspace: Workspace, fake_apis: FakeApis) -> None:
    _collect(workspace, fake_apis, ["arxiv"])
    with workspace.factory() as session:
        statuses = {a.peer_review_status for a in session.scalars(select(Article))}
    assert statuses == {PeerReviewStatus.PREPRINT}


def test_crossref_confirms_published_preprint_once(
    workspace: Workspace, fake_apis: FakeApis
) -> None:
    from ufabc_science.domain.enums import ArticleType, SourceType
    from ufabc_science.domain.schemas import NormalizedArticle
    from ufabc_science.infrastructure.database import session_scope
    from ufabc_science.infrastructure.repositories.articles import (
        get_or_create_source,
        upsert_article,
    )

    with session_scope(workspace.factory) as session:
        source = get_or_create_source(session, "arxiv", "https://arxiv.org", SourceType.FEED)
        upsert_article(
            session,
            NormalizedArticle(
                source="arxiv",
                external_id="2611.00001",
                title="Humanoid Robots: Applications, Commercial Readiness, and Challenges",
                doi="10.3390/robotics15110229",  # DOI informado pelos autores
                article_type=ArticleType.PREPRINT,
                peer_review_status=PeerReviewStatus.PREPRINT,
            ),
            source,
        )

    first = enrich_with_crossref(
        workspace.settings, workspace.factory, transport=fake_apis.transport()
    )
    second = enrich_with_crossref(
        workspace.settings, workspace.factory, transport=fake_apis.transport()
    )

    assert (first.checked, first.confirmed) == (1, 1)
    assert second.checked == 0  # cada artigo é consultado uma única vez
    with workspace.factory() as session:
        article = session.scalars(select(Article)).one()
        assert article.peer_review_status is PeerReviewStatus.VERIFIED
        assert article.journal == "Robotics"
        assert {link.source.name for link in article.sources} == {"arxiv", "crossref"}
