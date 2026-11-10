"""Coletores de fontes científicas e registro das fontes disponíveis.

Para adicionar uma fonte, ver ``docs/ADDING_SOURCES.md``.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ufabc_science.collectors.arxiv import ArxivCollector
from ufabc_science.collectors.base import BaseCollector, CollectorConfig, RawStore
from ufabc_science.collectors.crossref import CrossrefCollector
from ufabc_science.collectors.openalex import OpenAlexCollector
from ufabc_science.collectors.pubmed import PubMedCollector
from ufabc_science.config.settings import Settings

COLLECTORS: dict[str, type[BaseCollector]] = {
    OpenAlexCollector.name: OpenAlexCollector,
    PubMedCollector.name: PubMedCollector,
    ArxivCollector.name: ArxivCollector,
    CrossrefCollector.name: CrossrefCollector,
}


def collector_config(
    settings: Settings,
    source: str,
    *,
    max_articles: int | None = None,
    transport: httpx.BaseTransport | None = None,
    raw_root: Path | None = None,
) -> CollectorConfig:
    """Monta a configuração de um coletor a partir de ``Settings`` (sem expor segredos)."""
    api_key = None
    if source == "openalex" and settings.openalex_api_key:
        api_key = settings.openalex_api_key.get_secret_value()
    if source == "pubmed" and settings.ncbi_api_key:
        api_key = settings.ncbi_api_key.get_secret_value()
    contact = settings.openalex_contact if source == "openalex" else settings.contact_email
    return CollectorConfig(
        max_articles=max_articles or settings.max_articles_per_source,
        timeout=settings.http_timeout,
        max_retries=settings.http_max_retries,
        backoff_seconds=settings.http_backoff_seconds,
        contact_email=contact,
        api_key=api_key,
        raw_store=RawStore(raw_root or settings.raw_dir),
        transport=transport,
    )


def build_collector(
    settings: Settings,
    source: str,
    *,
    max_articles: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> BaseCollector:
    try:
        cls = COLLECTORS[source]
    except KeyError as exc:
        raise ValueError(f"Fonte desconhecida: {source}") from exc
    return cls(collector_config(settings, source, max_articles=max_articles, transport=transport))


__all__ = [
    "COLLECTORS",
    "ArxivCollector",
    "BaseCollector",
    "CollectorConfig",
    "CrossrefCollector",
    "OpenAlexCollector",
    "PubMedCollector",
    "RawStore",
    "build_collector",
    "collector_config",
]
