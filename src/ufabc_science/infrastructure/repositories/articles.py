"""Persistência incremental de artigos normalizados, com deduplicação e mesclagem.

Política de mesclagem (quando o artigo já existe):

* campos vazios são preenchidos; campos já preenchidos **não** são sobrescritos
  por dados de outra fonte (evita trocar dados melhores por incompletos);
* palavras-chave, instituições e metadados por fonte são unidos;
* ``peer_review_status`` só "sobe" com evidência (``unknown`` → ``preprint`` →
  ``verified``); nunca é rebaixado automaticamente;
* cada fonte em que o artigo foi encontrado gera um ``ArticleSource``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, SourceType
from ufabc_science.domain.models import Article, ArticleSource, Source, utcnow
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.deduplication import (
    find_exact_match,
    find_similar_titles,
)
from ufabc_science.processing.normalization import normalize_url

logger = logging.getLogger(__name__)

_PEER_RANK = {
    PeerReviewStatus.UNKNOWN: 0,
    PeerReviewStatus.PREPRINT: 1,
    PeerReviewStatus.VERIFIED: 2,
}


class UpsertOutcome(str, Enum):
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class UpsertResult:
    article: Article
    outcome: UpsertOutcome
    matched_by: str | None = None
    flagged_duplicate_of: int | None = None


def get_or_create_source(
    session: Session, name: str, base_url: str, source_type: SourceType
) -> Source:
    source = session.scalars(select(Source).where(Source.name == name)).first()
    if source is None:
        source = Source(name=name, base_url=base_url, source_type=source_type, active=True)
        session.add(source)
        session.flush()
    return source


def _authors_json(item: NormalizedArticle) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in a.model_dump(mode="json").items() if v not in (None, [], ())}
        for a in item.authors
    ]


def _institutions_json(item: NormalizedArticle) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in i.model_dump(mode="json").items() if v is not None}
        for i in item.institutions
    ]


def _new_article(item: NormalizedArticle) -> Article:
    return Article(
        title=item.title,
        abstract=item.abstract,
        doi=item.doi,
        external_id=item.external_key,
        canonical_url=normalize_url(item.url),
        publication_date=item.publication_date,
        collected_at=utcnow(),
        journal=item.journal,
        publisher=item.publisher,
        authors=_authors_json(item),
        institutions=_institutions_json(item),
        keywords=list(item.keywords),
        article_type=item.article_type,
        peer_review_status=item.peer_review_status,
        open_access=item.open_access,
        language=item.language,
        source_metadata=dict(item.source_metadata),
        raw_data_path=item.raw_data_path,
    )


def _merge(session: Session, article: Article, item: NormalizedArticle) -> bool:
    """Mescla ``item`` em ``article``. Retorna ``True`` se algo mudou."""
    changed = False

    def fill(attr: str, value: Any) -> None:
        nonlocal changed
        if value not in (None, "", [], {}) and getattr(article, attr) in (None, "", [], {}):
            setattr(article, attr, value)
            changed = True

    if item.doi and not article.doi:
        owner = session.scalars(select(Article).where(Article.doi == item.doi)).first()
        if owner is None:
            article.doi = item.doi
            changed = True
        else:
            logger.warning(
                "DOI %s já pertence ao artigo %s; não atribuído ao artigo %s",
                item.doi,
                owner.id,
                article.id,
            )
    fill("abstract", item.abstract)
    fill("canonical_url", normalize_url(item.url))
    fill("publication_date", item.publication_date)
    fill("journal", item.journal)
    fill("publisher", item.publisher)
    fill("language", item.language)
    fill("raw_data_path", item.raw_data_path)
    fill("authors", _authors_json(item))
    if article.open_access is None and item.open_access is not None:
        article.open_access = item.open_access
        changed = True

    keywords = list(dict.fromkeys([*(article.keywords or []), *item.keywords]))
    if keywords != (article.keywords or []):
        article.keywords = keywords  # atribuição nova: JSON não rastreia mutação
        changed = True

    known = {inst.get("name") for inst in article.institutions or []}
    extra = [i for i in _institutions_json(item) if i.get("name") not in known]
    if extra:
        article.institutions = [*(article.institutions or []), *extra]
        changed = True

    metadata = dict(article.source_metadata or {})
    for key, value in item.source_metadata.items():
        if metadata.get(key) != value:
            metadata[key] = value
    if _PEER_RANK[item.peer_review_status] > _PEER_RANK[article.peer_review_status]:
        metadata["peer_review_evidence"] = {
            "status": item.peer_review_status.value,
            "source": item.source,
            "external_id": item.external_id,
        }
        article.peer_review_status = item.peer_review_status
        changed = True
        if article.article_type in (ArticleType.PREPRINT, ArticleType.UNKNOWN, ArticleType.OTHER):
            article.article_type = item.article_type
    elif article.article_type is ArticleType.UNKNOWN and item.article_type != ArticleType.UNKNOWN:
        article.article_type = item.article_type
        changed = True
    if metadata != (article.source_metadata or {}):
        article.source_metadata = metadata
        changed = True
    return changed


def upsert_article(session: Session, item: NormalizedArticle, source: Source) -> UpsertResult:
    """Insere ou mescla um artigo normalizado. Não faz ``commit``."""
    match = find_exact_match(session, item, source)
    if match is None:
        article = _new_article(item)
        similar = find_similar_titles(session, item)
        if similar:
            best = similar[0]
            article.possible_duplicate_of_id = best.article.id
            article.duplicate_reason = f"título similar ({best.ratio:.2f})"
            logger.info(
                "Possível duplicata sinalizada: %r ~ artigo %s (%.2f)",
                item.title[:60],
                best.article.id,
                best.ratio,
            )
        article.sources.append(
            ArticleSource(
                source=source,
                external_id=item.external_id,
                original_url=item.url,
                collected_at=utcnow(),
            )
        )
        session.add(article)
        session.flush()
        return UpsertResult(
            article,
            UpsertOutcome.INSERTED,
            flagged_duplicate_of=article.possible_duplicate_of_id,
        )

    article = match.article
    changed = _merge(session, article, item)
    has_link = any(
        link.source_id == source.id and link.external_id == item.external_id
        for link in article.sources
    )
    if not has_link:
        article.sources.append(
            ArticleSource(
                source=source,
                external_id=item.external_id,
                original_url=item.url,
                collected_at=utcnow(),
            )
        )
        changed = True
    session.flush()
    return UpsertResult(
        article,
        UpsertOutcome.UPDATED if changed else UpsertOutcome.UNCHANGED,
        matched_by=match.kind.value,
    )
