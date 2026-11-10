"""Coletor Crossref (https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

Usado para descoberta (``/works`` com filtro de datas) e para complementar e
verificar metadados por DOI (``lookup``), por exemplo para confirmar que um
preprint foi publicado em periódico.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from ufabc_science.collectors.base import (
    BaseCollector,
    CollectionResult,
    CollectorError,
    RateLimitedClient,
)
from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.normalization import (
    clean_text,
    normalize_doi,
    normalize_language,
    normalize_orcid,
    strip_abstract_label,
)


def _date_from_parts(value: dict[str, Any] | None) -> date | None:
    parts = ((value or {}).get("date-parts") or [[None]])[0]
    if not parts or parts[0] is None:
        return None
    year, month, day = [*list(parts), 1, 1][:3]
    try:
        return date(int(year), int(month or 1), int(day or 1))
    except (TypeError, ValueError):
        return None


def classify_crossref(item: dict[str, Any]) -> tuple[ArticleType, PeerReviewStatus]:
    """``journal-article`` registrado por uma editora é evidência de publicação em periódico."""
    work_type = (item.get("type") or "").lower()
    subtype = (item.get("subtype") or "").lower()
    if work_type == "posted-content" or subtype == "preprint":
        return ArticleType.PREPRINT, PeerReviewStatus.PREPRINT
    if work_type == "journal-article":
        return ArticleType.JOURNAL_ARTICLE, PeerReviewStatus.VERIFIED
    if work_type == "proceedings-article":
        return ArticleType.CONFERENCE_PAPER, PeerReviewStatus.UNKNOWN
    if work_type in ("book-chapter", "book-section"):
        return ArticleType.BOOK_CHAPTER, PeerReviewStatus.UNKNOWN
    return (ArticleType.OTHER if work_type else ArticleType.UNKNOWN), PeerReviewStatus.UNKNOWN


def parse_crossref_item(item: dict[str, Any], raw_path: str = "") -> dict[str, Any] | None:
    """Converte um item ``/works`` na estrutura de ``NormalizedArticle``."""
    doi = normalize_doi(item.get("DOI"))
    titles = item.get("title") or []
    if not doi or not titles:
        return None
    authors: list[dict[str, Any]] = []
    institutions: dict[str, dict[str, Any]] = {}
    for author in item.get("author") or []:
        name = " ".join(p for p in (author.get("given"), author.get("family")) if p)
        name = name or author.get("name")
        if not name:
            continue
        affiliations = []
        for aff in author.get("affiliation") or []:
            aff_name = clean_text(aff.get("name"))
            if aff_name:
                affiliations.append(aff_name[:500])
                institutions.setdefault(aff_name[:500], {"name": aff_name[:500]})
        authors.append(
            {
                "name": name,
                "orcid": normalize_orcid(author.get("ORCID")),
                "affiliations": tuple(affiliations),
            }
        )
    article_type, peer_status = classify_crossref(item)
    licenses = item.get("license") or []
    open_access = (
        True
        if any(
            "creativecommons.org" in (lic.get("URL") or "")
            and lic.get("content-version") in ("vor", "am")
            for lic in licenses
        )
        else None
    )
    publication_date = (
        _date_from_parts(item.get("published"))
        or _date_from_parts(item.get("published-online"))
        or _date_from_parts(item.get("published-print"))
        or _date_from_parts(item.get("issued"))
    )
    containers = item.get("container-title") or []
    return {
        "external_id": doi,
        "title": titles[0],
        "abstract": strip_abstract_label(clean_text(item.get("abstract"))),
        "doi": doi,
        "url": item.get("URL") or f"https://doi.org/{doi}",
        "publication_date": publication_date,
        "journal": containers[0] if containers else None,
        "publisher": item.get("publisher"),
        "authors": authors,
        "institutions": list(institutions.values()),
        "article_type": article_type,
        "peer_review_status": peer_status,
        "open_access": open_access,
        "language": normalize_language(item.get("language")),
        "keywords": list(item.get("subject") or []),
        "source_metadata": {
            "crossref": {
                "type": item.get("type"),
                "subtype": item.get("subtype"),
                "member": item.get("member"),
                "licenses": sorted({lic.get("URL") for lic in licenses if lic.get("URL")}),
            }
        },
        "raw_data_path": raw_path or None,
    }


class CrossrefCollector(BaseCollector):
    name = "crossref"
    base_url = "https://api.crossref.org"
    min_interval = 1.0  # o pool público responde 429 com intervalos menores
    default_queries = ("engineering", "materials science", "robotics", "physics", "ecology")

    def _params(self) -> dict[str, Any]:
        return {"mailto": self.config.contact_email} if self.config.contact_email else {}

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
        cursor: str | None = "*"
        while cursor and len(articles) < limit:
            response = client.get(
                f"{self.base_url}/works",
                params={
                    **self._params(),
                    "filter": (
                        f"from-pub-date:{start_date.isoformat()},"
                        f"until-pub-date:{end_date.isoformat()},"
                        "type:journal-article,has-abstract:true"
                    ),
                    "query": query,
                    "rows": min(100, limit - len(articles)),
                    "cursor": cursor,
                },
            )
            raw_path = self._save_raw(result, f"works-{query}", response.content, "json")
            message = response.json().get("message") or {}
            items = message.get("items") or []
            for item in items:
                data = parse_crossref_item(item, raw_path)
                if data is None:
                    result.invalid_records += 1
                    continue
                article = self._build(result, data)
                if article is not None:
                    articles.append(article)
                if len(articles) >= limit:
                    break
            cursor = message.get("next-cursor") if items else None
        return articles

    def lookup(self, doi: str, client: RateLimitedClient | None = None) -> NormalizedArticle | None:
        """Busca os metadados de um DOI. Retorna ``None`` se o DOI não existir no Crossref.

        Passe ``client`` para reutilizar o mesmo limite de requisições em várias consultas.
        """
        normalized = normalize_doi(doi)
        if normalized is None:
            return None
        result = CollectionResult(source=self.name)
        own_client = client is None
        active = client or self._client()
        try:
            response = active.get(
                f"{self.base_url}/works/{quote(normalized, safe='')}", params=self._params()
            )
        except CollectorError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        finally:
            if own_client:
                active.close()
        raw_path = self._save_raw(result, "lookup", response.content, "json")
        data = parse_crossref_item(response.json().get("message") or {}, raw_path)
        return self._build(result, data) if data else None
