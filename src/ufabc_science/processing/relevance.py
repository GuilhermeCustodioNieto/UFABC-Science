"""Relevância editorial (pré-filtro heurístico da curadoria).

Calcula, sem IA, as cinco notas da curadoria (``processing/curation.py``): curiosidade,
relevância científica, novidade, impacto e qualidade das evidências, com a decisão
editorial e as regras de rejeição verificáveis por padrão de texto. A nota final (0 a
100) é uma **prioridade editorial**, não uma avaliação definitiva da qualidade
científica. Número de citações nunca é usado.

Mudança em relação à primeira versão: a confiabilidade da fonte (periódico reconhecido,
revisado, preprint, repositório sem triagem) agora entra nos critérios de relevância e
de evidências, como pede a política editorial (seção 4). Preprints continuam elegíveis,
mas com teto na nota de evidências.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import Priority
from ufabc_science.domain.models import Article, RelevanceAssessment
from ufabc_science.processing.curation import (
    HEURISTIC_VERSION,
    MAX_TYPICAL_ABSTRACT_WORDS,
    UNMODERATED_REPOSITORIES,
    effective_assessment,
    heuristic_curation,
    unmoderated_repository,
)

__all__ = [
    "HEURISTIC_VERSION",
    "MAX_TYPICAL_ABSTRACT_WORDS",
    "UNMODERATED_REPOSITORIES",
    "PriorityBands",
    "ScoringSummary",
    "effective_assessment",
    "latest_assessment",
    "score_articles",
    "unmoderated_repository",
]


@dataclass(frozen=True)
class PriorityBands:
    """Faixas da política editorial: 85+ prioridade, 75+ publicar, 65+ avaliar."""

    very_high: float = 85
    high: float = 75
    moderate: float = 65

    def classify(self, score: float) -> Priority:
        if score >= self.very_high:
            return Priority.VERY_HIGH
        if score >= self.high:
            return Priority.HIGH
        if score >= self.moderate:
            return Priority.MODERATE
        return Priority.LOW


@dataclass
class ScoringSummary:
    assessed: int = 0
    skipped: int = 0


def latest_assessment(article: Article) -> RelevanceAssessment | None:
    return article.relevance_assessments[-1] if article.relevance_assessments else None


def score_articles(
    session: Session,
    *,
    article_ids: list[int] | None = None,
    rescore: bool = False,
    today: date | None = None,
    min_abstract_words: int = 40,
) -> ScoringSummary:
    """Calcula e persiste a avaliação heurística. Preserva avaliações anteriores (histórico).

    Um artigo já avaliado com a versão atual do heurístico é ignorado, salvo ``rescore``
    ou ``article_ids``. Avaliações por IA nunca são substituídas: a seleção sempre usa a
    curadoria por IA quando ela existe (``effective_assessment``).
    """
    summary = ScoringSummary()
    query = select(Article).order_by(Article.id)
    if article_ids:
        query = query.where(Article.id.in_(article_ids))
    for article in session.scalars(query).all():
        current = any(
            record.method_version == HEURISTIC_VERSION for record in article.relevance_assessments
        )
        if current and not (rescore or article_ids):
            summary.skipped += 1
            continue
        assessment = heuristic_curation(article, today=today, min_abstract_words=min_abstract_words)
        session.add(assessment.to_record(article))
        summary.assessed += 1
    session.flush()
    return summary
