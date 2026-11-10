"""Deduplicação de artigos (SPECIFICATION.md, seção 8.1).

Ordem de prioridade:

1. DOI normalizado;
2. identificador externo associado à fonte (``article_sources``);
3. URL canônica normalizada;
4. similaridade de títulos normalizados — **somente sinaliza** possível
   duplicidade; nunca mescla nem descarta registros automaticamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from enum import Enum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ufabc_science.domain.models import Article, ArticleSource, Source
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.normalization import normalize_title, normalize_url

TITLE_SIMILARITY_THRESHOLD = 0.92
_MIN_TITLE_LENGTH = 20
_DATE_WINDOW = timedelta(days=400)


class MatchKind(str, Enum):
    DOI = "doi"
    EXTERNAL_ID = "external_id"
    CANONICAL_URL = "canonical_url"


@dataclass(frozen=True)
class Match:
    article: Article
    kind: MatchKind


@dataclass(frozen=True)
class SimilarTitle:
    article: Article
    ratio: float


def title_similarity(a: str | None, b: str | None) -> float:
    """Similaridade (0 a 1) entre títulos normalizados."""
    left, right = normalize_title(a), normalize_title(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def find_exact_match(session: Session, item: NormalizedArticle, source: Source) -> Match | None:
    """Procura o mesmo artigo pelas regras 1 a 3 (determinísticas)."""
    if item.doi:
        article = session.scalars(select(Article).where(Article.doi == item.doi)).first()
        if article is not None:
            return Match(article, MatchKind.DOI)

    link = session.scalars(
        select(ArticleSource).where(
            ArticleSource.source_id == source.id, ArticleSource.external_id == item.external_id
        )
    ).first()
    if link is not None:
        return Match(link.article, MatchKind.EXTERNAL_ID)

    canonical = normalize_url(item.url)
    if canonical:
        article = session.scalars(select(Article).where(Article.canonical_url == canonical)).first()
        if article is not None:
            return Match(article, MatchKind.CANONICAL_URL)
    return None


def find_similar_titles(
    session: Session,
    item: NormalizedArticle,
    *,
    exclude_id: int | None = None,
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
) -> list[SimilarTitle]:
    """Artigos com título muito parecido (fallback). Resultado apenas informativo."""
    normalized = normalize_title(item.title)
    if len(normalized) < _MIN_TITLE_LENGTH:
        return []
    query = select(Article)
    if item.publication_date:
        low = item.publication_date - _DATE_WINDOW
        high = item.publication_date + _DATE_WINDOW
        query = query.where(
            or_(
                Article.publication_date.is_(None),
                Article.publication_date.between(low, high),
            )
        )
    if exclude_id is not None:
        query = query.where(Article.id != exclude_id)
    matches = []
    for candidate in session.scalars(query):
        candidate_title = normalize_title(candidate.title)
        # Pré-filtro barato por tamanho antes do cálculo de similaridade.
        if abs(len(candidate_title) - len(normalized)) > 0.3 * len(normalized):
            continue
        ratio = title_similarity(item.title, candidate.title)
        if ratio >= threshold:
            matches.append(SimilarTitle(candidate, ratio))
    return sorted(matches, key=lambda m: m.ratio, reverse=True)
