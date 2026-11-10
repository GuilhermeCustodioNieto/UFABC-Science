"""Orquestração da coleta: consulta as fontes, persiste e contabiliza (seção 8).

Cada fonte é processada em sua própria transação: a falha de uma fonte é
registrada e não impede o processamento das demais.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science.collectors import COLLECTORS, build_collector
from ufabc_science.collectors.base import CollectorError
from ufabc_science.collectors.crossref import CrossrefCollector
from ufabc_science.config.settings import Settings
from ufabc_science.domain.enums import PeerReviewStatus
from ufabc_science.domain.models import Article
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.infrastructure.repositories.articles import (
    UpsertOutcome,
    get_or_create_source,
    upsert_article,
)

logger = logging.getLogger(__name__)


@dataclass
class SourceStats:
    source: str
    collected: int = 0
    inserted: int = 0
    updated: int = 0
    ignored: int = 0  # já existentes e sem alterações
    flagged_duplicates: int = 0
    invalid: int = 0
    requests: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class CollectionSummary:
    start_date: date
    end_date: date
    sources: list[SourceStats] = field(default_factory=list)

    def total(self, attr: str) -> int:
        return sum(getattr(s, attr) for s in self.sources)

    @property
    def errors(self) -> list[str]:
        return [error for s in self.sources for error in s.errors]

    @property
    def failed_sources(self) -> list[str]:
        return [s.source for s in self.sources if s.errors and s.collected == 0]

    def as_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "sources": [asdict(s) for s in self.sources],
            "totals": {
                key: self.total(key)
                for key in (
                    "collected",
                    "inserted",
                    "updated",
                    "ignored",
                    "flagged_duplicates",
                    "invalid",
                )
            },
        }


def collection_window(days: int, today: date | None = None) -> tuple[date, date]:
    """Intervalo ``[hoje - days, hoje]`` em UTC."""
    end = today or datetime.now(timezone.utc).date()
    return end - timedelta(days=days), end


def collect_articles(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    start_date: date,
    end_date: date,
    sources: list[str] | None = None,
    query: str | None = None,
    max_articles: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CollectionSummary:
    """Coleta e persiste artigos das fontes habilitadas no período informado."""
    summary = CollectionSummary(start_date, end_date)
    for name in sources or settings.sources:
        stats = SourceStats(source=name)
        summary.sources.append(stats)
        collector = build_collector(settings, name, max_articles=max_articles, transport=transport)
        try:
            result = collector.collect(query, start_date, end_date)
        except Exception as exc:  # falha inesperada isolada por fonte
            stats.errors.append(f"{name}: {type(exc).__name__}: {exc}")
            logger.exception("%s: falha na coleta", name)
            continue
        stats.collected = len(result.articles)
        stats.invalid = result.invalid_records
        stats.requests = result.requests
        stats.errors.extend(result.errors)
        try:
            with session_scope(factory) as session:
                source = get_or_create_source(
                    session, collector.name, collector.base_url, collector.source_type
                )
                for item in result.articles:
                    outcome = upsert_article(session, item, source)
                    if outcome.outcome is UpsertOutcome.INSERTED:
                        stats.inserted += 1
                    elif outcome.outcome is UpsertOutcome.UPDATED:
                        stats.updated += 1
                    else:
                        stats.ignored += 1
                    if outcome.flagged_duplicate_of:
                        stats.flagged_duplicates += 1
        except Exception as exc:
            stats.errors.append(f"{name}: falha ao persistir: {exc}")
            stats.inserted = stats.updated = stats.ignored = stats.flagged_duplicates = 0
            logger.exception("%s: falha ao persistir (transação desfeita)", name)
        logger.info(
            "%s: coletados=%d inseridos=%d atualizados=%d ignorados=%d "
            "possíveis_duplicatas=%d inválidos=%d",
            name,
            stats.collected,
            stats.inserted,
            stats.updated,
            stats.ignored,
            stats.flagged_duplicates,
            stats.invalid,
        )
    return summary


@dataclass
class EnrichmentSummary:
    checked: int = 0
    confirmed: int = 0
    not_found: int = 0
    errors: list[str] = field(default_factory=list)


def enrich_with_crossref(
    settings: Settings,
    factory: sessionmaker[Session],
    *,
    limit: int = 50,
    transport: httpx.BaseTransport | None = None,
) -> EnrichmentSummary:
    """Complementa artigos com DOI e revisão não confirmada consultando o Crossref.

    Cada artigo é consultado no máximo uma vez (marca ``crossref_lookup`` em
    ``source_metadata``), tornando a operação idempotente.
    """
    summary = EnrichmentSummary()
    if "crossref" not in COLLECTORS:
        return summary
    collector = build_collector(settings, "crossref", transport=transport)
    assert isinstance(collector, CrossrefCollector)
    with session_scope(factory) as session, collector._client() as client:
        candidates = [
            article
            for article in session.scalars(
                select(Article)
                .where(Article.doi.is_not(None))
                .where(Article.peer_review_status != PeerReviewStatus.VERIFIED)
                .order_by(Article.id)
            )
            if "crossref_lookup" not in (article.source_metadata or {})
        ][:limit]
        if not candidates:
            return summary
        source = get_or_create_source(
            session, collector.name, collector.base_url, collector.source_type
        )
        for article in candidates:
            summary.checked += 1
            assert article.doi is not None
            try:
                found = collector.lookup(article.doi, client)
            except CollectorError as exc:
                summary.errors.append(str(exc))
                continue
            metadata = dict(article.source_metadata or {})
            metadata["crossref_lookup"] = {
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "found": found is not None,
            }
            article.source_metadata = metadata
            if found is None:
                summary.not_found += 1
                continue
            upsert_article(session, found, source)
            if article.peer_review_status is PeerReviewStatus.VERIFIED:
                summary.confirmed += 1
    return summary
