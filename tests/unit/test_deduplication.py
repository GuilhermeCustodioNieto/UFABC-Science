"""Deduplicação (DOI > id externo > URL > título) e política de mesclagem."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, SourceType
from ufabc_science.domain.models import Article, ArticleSource
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.infrastructure.repositories.articles import (
    UpsertOutcome,
    get_or_create_source,
    upsert_article,
)
from ufabc_science.processing.deduplication import title_similarity


def item(source: str = "openalex", external_id: str = "W1", **kwargs: object) -> NormalizedArticle:
    data: dict[str, object] = {
        "source": source,
        "external_id": external_id,
        "title": "Synaptic plasticity in cortical neurons during sleep",
        "publication_date": date(2026, 11, 1),
    }
    data.update(kwargs)
    return NormalizedArticle(**data)


def src(session: Session, name: str = "openalex"):
    return get_or_create_source(session, name, f"https://{name}.example", SourceType.API)


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Article)) or 0


def test_same_doi_from_two_sources_is_one_article(session: Session) -> None:
    first = upsert_article(session, item(doi="10.1000/ABC"), src(session, "openalex"))
    second = upsert_article(
        session,
        item("crossref", "10.1000/abc", doi="https://doi.org/10.1000/abc", journal="Revista"),
        src(session, "crossref"),
    )

    assert first.outcome is UpsertOutcome.INSERTED
    assert second.outcome is UpsertOutcome.UPDATED
    assert second.matched_by == "doi"
    assert count(session) == 1
    article = first.article
    assert {link.source.name for link in article.sources} == {"openalex", "crossref"}
    assert article.journal == "Revista"  # campo vazio preenchido


def test_same_external_id_is_idempotent(session: Session) -> None:
    source = src(session)
    upsert_article(session, item(), source)
    again = upsert_article(session, item(), source)

    assert again.outcome is UpsertOutcome.UNCHANGED
    assert again.matched_by == "external_id"
    assert count(session) == 1
    assert session.scalar(select(func.count()).select_from(ArticleSource)) == 1


def test_canonical_url_match(session: Session) -> None:
    upsert_article(session, item(url="https://www.example.org/paper/1/"), src(session, "a"))
    result = upsert_article(
        session,
        item("b", "X9", url="http://example.org/paper/1?utm_source=feed"),
        src(session, "b"),
    )
    assert result.matched_by == "canonical_url"
    assert count(session) == 1


def test_similar_titles_are_flagged_not_merged(session: Session) -> None:
    upsert_article(session, item(external_id="W1"), src(session))
    similar = upsert_article(
        session,
        item("arxiv", "2611.1", title="Synaptic plasticity in cortical neurons during sleep."),
        src(session, "arxiv"),
    )

    assert similar.outcome is UpsertOutcome.INSERTED
    assert count(session) == 2  # nada é descartado
    assert similar.article.possible_duplicate_of_id is not None
    assert "título similar" in (similar.article.duplicate_reason or "")


def test_different_titles_are_not_flagged(session: Session) -> None:
    upsert_article(session, item(external_id="W1"), src(session))
    other = upsert_article(
        session,
        item(external_id="W2", title="Quantum error correction with cat qubits"),
        src(session),
    )
    assert other.article.possible_duplicate_of_id is None


def test_existing_data_is_not_overwritten(session: Session) -> None:
    upsert_article(
        session, item(doi="10.1000/x", abstract="Resumo original completo."), src(session)
    )
    upsert_article(
        session,
        item("crossref", "10.1000/x", doi="10.1000/x", abstract="Outro."),
        src(session, "c"),
    )
    article = session.scalars(select(Article)).one()
    assert article.abstract == "Resumo original completo."


def test_peer_review_status_is_upgraded_with_evidence_and_never_downgraded(
    session: Session,
) -> None:
    preprint = upsert_article(
        session,
        item(
            "arxiv",
            "2611.1",
            doi="10.1000/pub",
            article_type=ArticleType.PREPRINT,
            peer_review_status=PeerReviewStatus.PREPRINT,
        ),
        src(session, "arxiv"),
    ).article
    upsert_article(
        session,
        item(
            "crossref",
            "10.1000/pub",
            doi="10.1000/pub",
            article_type=ArticleType.JOURNAL_ARTICLE,
            peer_review_status=PeerReviewStatus.VERIFIED,
        ),
        src(session, "crossref"),
    )
    assert preprint.peer_review_status is PeerReviewStatus.VERIFIED
    assert preprint.article_type is ArticleType.JOURNAL_ARTICLE
    assert preprint.source_metadata["peer_review_evidence"]["source"] == "crossref"

    upsert_article(
        session,
        item("arxiv", "2611.1", doi="10.1000/pub", peer_review_status=PeerReviewStatus.PREPRINT),
        src(session, "arxiv"),
    )
    assert preprint.peer_review_status is PeerReviewStatus.VERIFIED


def test_title_similarity_scale() -> None:
    assert title_similarity("A study of X", "A Study of X!") == 1.0
    assert title_similarity("", "x") == 0.0
    assert title_similarity("Deep learning for proteins", "Ecology of river fish") < 0.5
