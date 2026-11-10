"""Coletor OpenAlex (https://docs.openalex.org/).

Observação de custo: o OpenAlex passou a medir o uso por orçamento diário. Sem
chave, as requisições compartilham um orçamento gratuito por IP; com uma chave
gratuita (``OPENALEX_API_KEY``) o orçamento é individual. Ver
``docs/ADDING_SOURCES.md``. O campo ``select`` reduz o custo de cada chamada.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ufabc_science.collectors.base import BaseCollector, CollectionResult, RateLimitedClient
from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.normalization import (
    clean_text,
    normalize_language,
    normalize_orcid,
    reconstruct_inverted_index,
)

_SELECT = (
    "id,doi,title,display_name,publication_date,type,language,open_access,authorships,"
    "primary_location,abstract_inverted_index,keywords,topics,concepts"
)

_TYPE_MAP = {
    "article": ArticleType.JOURNAL_ARTICLE,
    "preprint": ArticleType.PREPRINT,
    "review": ArticleType.REVIEW,
    "book-chapter": ArticleType.BOOK_CHAPTER,
    "proceedings-article": ArticleType.CONFERENCE_PAPER,
}


def _short_id(value: str | None) -> str | None:
    return value.rsplit("/", 1)[-1] if value else None


def classify_openalex(work: dict[str, Any]) -> tuple[ArticleType, PeerReviewStatus]:
    """Tipo e situação de revisão a partir dos metadados do OpenAlex.

    ``VERIFIED`` exige evidência de publicação em periódico (fonte do tipo
    ``journal`` e versão publicada). Repositórios e ``preprint`` → ``PREPRINT``.
    """
    work_type = (work.get("type") or "").lower()
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    source_type = (source.get("type") or "").lower()
    version = (location.get("version") or "").lower()

    article_type = _TYPE_MAP.get(work_type, ArticleType.OTHER if work_type else ArticleType.UNKNOWN)
    if work_type == "preprint" or source_type == "repository" or version == "submittedversion":
        return ArticleType.PREPRINT if work_type in ("", "preprint", "article") else article_type, (
            PeerReviewStatus.PREPRINT
        )
    if source_type == "journal" and work_type in ("article", "review"):
        return article_type, PeerReviewStatus.VERIFIED
    if article_type is ArticleType.JOURNAL_ARTICLE and source_type != "journal":
        article_type = ArticleType.OTHER
    return article_type, PeerReviewStatus.UNKNOWN


def parse_openalex_work(work: dict[str, Any], raw_path: str = "") -> dict[str, Any] | None:
    """Converte um ``work`` do OpenAlex na estrutura de ``NormalizedArticle``."""
    external_id = _short_id(work.get("id"))
    title = work.get("title") or work.get("display_name")
    if not external_id or not title:
        return None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}

    authors: list[dict[str, Any]] = []
    institutions: dict[str, dict[str, Any]] = {}
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name") or authorship.get("raw_author_name")
        affiliations = []
        for inst in authorship.get("institutions") or []:
            inst_name = inst.get("display_name")
            if not inst_name:
                continue
            affiliations.append(inst_name)
            key = inst.get("id") or inst_name
            institutions.setdefault(
                key,
                {"name": inst_name, "ror": inst.get("ror"), "country": inst.get("country_code")},
            )
        if name:
            authors.append(
                {
                    "name": name,
                    "orcid": normalize_orcid(author.get("orcid")),
                    "affiliations": tuple(affiliations),
                }
            )

    keywords: list[str] = [k.get("display_name", "") for k in work.get("keywords") or []]
    topics_meta = []
    for topic in work.get("topics") or []:
        keywords.append(topic.get("display_name", ""))
        for level in ("subfield", "field", "domain"):
            if (topic.get(level) or {}).get("display_name"):
                keywords.append(topic[level]["display_name"])
        topics_meta.append(topic.get("display_name"))
    for concept in work.get("concepts") or []:
        if (concept.get("level") or 0) <= 1 and (concept.get("score") or 0) >= 0.3:
            keywords.append(concept.get("display_name", ""))

    article_type, peer_status = classify_openalex(work)
    open_access = (work.get("open_access") or {}).get("is_oa")
    url = location.get("landing_page_url") or work.get("doi") or work.get("id")
    return {
        "external_id": external_id,
        "title": title,
        "abstract": clean_text(reconstruct_inverted_index(work.get("abstract_inverted_index"))),
        "doi": work.get("doi"),
        "url": url,
        "publication_date": work.get("publication_date"),
        "journal": source.get("display_name"),
        "publisher": source.get("host_organization_name"),
        "authors": authors,
        "institutions": list(institutions.values()),
        "article_type": article_type,
        "peer_review_status": peer_status,
        "open_access": open_access,
        "language": normalize_language(work.get("language")),
        "keywords": keywords,
        "source_metadata": {
            "openalex": {
                "id": work.get("id"),
                "type": work.get("type"),
                "source_type": source.get("type"),
                "version": location.get("version"),
                "topics": topics_meta,
                "oa_status": (work.get("open_access") or {}).get("oa_status"),
            }
        },
        "raw_data_path": raw_path or None,
    }


class OpenAlexCollector(BaseCollector):
    name = "openalex"
    base_url = "https://api.openalex.org"
    min_interval = 0.2  # bem abaixo do limite documentado de 10 req/s
    default_queries = (
        "neuroscience",
        "artificial intelligence",
        "engineering",
        "molecular biology",
        "physics",
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
        articles: list[NormalizedArticle] = []
        cursor = "*"
        while cursor and len(articles) < limit:
            params: dict[str, Any] = {
                "filter": (
                    f"from_publication_date:{start_date.isoformat()},"
                    f"to_publication_date:{end_date.isoformat()},"
                    "has_abstract:true,type:article|preprint|review"
                ),
                "search": query,
                "per-page": min(100, limit - len(articles)),
                "cursor": cursor,
                "select": _SELECT,
            }
            if self.config.contact_email:
                params["mailto"] = self.config.contact_email
            if self.config.api_key:
                params["api_key"] = self.config.api_key
            response = client.get(f"{self.base_url}/works", params=params)
            raw_path = self._save_raw(result, f"works-{query}", response.content, "json")
            payload = response.json()
            works = payload.get("results") or []
            for work in works:
                data = parse_openalex_work(work, raw_path)
                if data is None:
                    result.invalid_records += 1
                    continue
                article = self._build(result, data)
                if article is not None:
                    articles.append(article)
                if len(articles) >= limit:
                    break
            cursor = (payload.get("meta") or {}).get("next_cursor") if works else None
        return articles
