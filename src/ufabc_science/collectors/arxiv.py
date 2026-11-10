"""Coletor arXiv (https://info.arxiv.org/help/api/index.html).

Todo resultado do arXiv é registrado como **preprint**. Um DOI ou ``journal_ref``
informado pelos autores não é tratado como confirmação de revisão por pares: a
confirmação depende de outra fonte bibliográfica (ex.: Crossref, OpenAlex).

O arXiv pede no máximo uma requisição a cada 3 segundos.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

import feedparser

from ufabc_science.collectors.base import (
    BaseCollector,
    CollectionResult,
    CollectorError,
    RateLimitedClient,
)
from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, SourceType
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.normalization import clean_text

_ARXIV_ID = re.compile(r"arxiv\.org/abs/(?P<id>[^\s?#]+?)(?:v(?P<version>\d+))?$")


def parse_arxiv_entry(entry: Any, raw_path: str = "") -> dict[str, Any] | None:
    """Converte uma entrada Atom do arXiv na estrutura de ``NormalizedArticle``."""
    match = _ARXIV_ID.search(entry.get("id", ""))
    title = clean_text(entry.get("title"))
    if not match or not title:
        return None
    arxiv_id = match.group("id")
    published = entry.get("published_parsed")
    publication_date = datetime(*published[:6], tzinfo=timezone.utc).date() if published else None
    categories = [tag.get("term") for tag in entry.get("tags", []) if tag.get("term")]
    primary = (entry.get("arxiv_primary_category") or {}).get("term")
    authors = [
        {
            "name": author.get("name"),
            "affiliations": (author.get("arxiv_affiliation"),)
            if author.get("arxiv_affiliation")
            else (),
        }
        for author in entry.get("authors", [])
        if author.get("name")
    ]
    return {
        "external_id": arxiv_id,
        "title": title,
        "abstract": clean_text(entry.get("summary")),
        # DOI informado pelos autores (versão publicada, se houver). Usado para
        # deduplicação; não altera o status de preprint deste registro.
        "doi": entry.get("arxiv_doi"),
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "publication_date": publication_date,
        "journal": None,
        "publisher": "arXiv",
        "authors": authors,
        "institutions": [],
        "article_type": ArticleType.PREPRINT,
        "peer_review_status": PeerReviewStatus.PREPRINT,
        "open_access": True,
        "language": None,
        "keywords": categories,
        "source_metadata": {
            "arxiv": {
                "id": arxiv_id,
                "version": match.group("version"),
                "primary_category": primary,
                "categories": categories,
                "comment": entry.get("arxiv_comment"),
                "journal_ref": entry.get("arxiv_journal_ref"),
                "author_reported_doi": entry.get("arxiv_doi"),
            }
        },
        "raw_data_path": raw_path or None,
    }


class ArxivCollector(BaseCollector):
    name = "arxiv"
    base_url = "https://export.arxiv.org/api/query"
    source_type = SourceType.FEED
    min_interval = 3.0
    default_queries = (
        "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.RO OR cat:cs.CR",
        "cat:q-bio.NC OR cat:q-bio.GN OR cat:q-bio.BM OR cat:q-bio.PE",
        "cat:quant-ph OR cat:cond-mat.mtrl-sci OR cat:physics.app-ph OR cat:astro-ph.EP "
        "OR cat:eess.SY OR cat:math.OC",
    )

    def _collect_query(
        self,
        client: RateLimitedClient,
        result: CollectionResult,
        query: str,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[NormalizedArticle]:
        window = f"submittedDate:[{start_date:%Y%m%d}0000 TO {end_date:%Y%m%d}2359]"
        articles: list[NormalizedArticle] = []
        start = 0
        while len(articles) < limit:
            page = min(100, limit - len(articles))
            response = client.get(
                self.base_url,
                params={
                    "search_query": f"({query}) AND {window}",
                    "start": start,
                    "max_results": page,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            raw_path = self._save_raw(result, "query", response.content, "xml")
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                raise CollectorError(f"arxiv: feed inválido: {feed.bozo_exception}")
            for entry in feed.entries:
                data = parse_arxiv_entry(entry, raw_path)
                if data is None:
                    result.invalid_records += 1
                    continue
                article = self._build(result, data)
                if article is not None:
                    articles.append(article)
            if len(feed.entries) < page:
                break
            start += page
        return articles[:limit]
