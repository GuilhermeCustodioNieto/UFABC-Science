"""Relevância editorial (SPECIFICATION.md, seção 10; Etapa 3, seção 4).

A pontuação (0 a 100) é uma **prioridade editorial**, não uma avaliação da
qualidade científica. O avaliador padrão é heurístico e determinístico e, por
regra, **não** usa número de citações, fator de impacto ou prestígio
institucional. Preprints não são penalizados; seu status é apenas registrado
na justificativa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, Priority
from ufabc_science.domain.models import Article, RelevanceAssessment, utcnow
from ufabc_science.processing.normalization import strip_accents, word_count

WEIGHTS = {
    "scientific_relevance": 0.30,
    "originality": 0.20,
    "potential_impact": 0.20,
    "interdisciplinarity": 0.15,
    "ufabc_interest": 0.15,
}
HEURISTIC_VERSION = "heuristic-v2"

# Abstracts reais raramente passam disso; acima, é texto completo ou registro atípico.
MAX_TYPICAL_ABSTRACT_WORDS = 600

# Repositórios de depósito livre, sem triagem editorial ou de moderação. Servidores de
# preprint com moderação (arXiv, bioRxiv, medRxiv, SciELO Preprints...) NÃO entram aqui.
UNMODERATED_REPOSITORIES = {
    "zenodo": "Zenodo",
    "osf preprints": "OSF Preprints",
    "figshare": "Figshare",
    "researchgate": "ResearchGate",
    "academia.edu": "Academia.edu",
}
_UNMODERATED_DOI_PREFIXES = {"10.5281/": "Zenodo", "10.6084/": "Figshare", "10.31219/": "OSF"}


def unmoderated_repository(article: Article) -> str | None:
    """Nome do repositório genérico sem triagem em que o registro foi depositado, se houver."""
    venue = (article.journal or "").casefold()
    for key, name in UNMODERATED_REPOSITORIES.items():
        if key in venue:
            return name
    for prefix, name in _UNMODERATED_DOI_PREFIXES.items():
        if (article.doi or "").startswith(prefix):
            return name
    return None


def compute_final_score(
    scientific_relevance: float,
    originality: float,
    potential_impact: float,
    interdisciplinarity: float,
    ufabc_interest: float,
) -> float:
    """Fórmula da especificação. Cada critério deve estar entre 0 e 100."""
    values = {
        "scientific_relevance": scientific_relevance,
        "originality": originality,
        "potential_impact": potential_impact,
        "interdisciplinarity": interdisciplinarity,
        "ufabc_interest": ufabc_interest,
    }
    for name, value in values.items():
        if not 0 <= value <= 100:
            raise ValueError(f"{name} fora do intervalo 0-100: {value}")
    score = sum(values[name] * weight for name, weight in WEIGHTS.items())
    return round(score, 2)


@dataclass(frozen=True)
class PriorityBands:
    very_high: float = 85
    high: float = 70
    moderate: float = 50

    def classify(self, score: float) -> Priority:
        if score >= self.very_high:
            return Priority.VERY_HIGH
        if score >= self.high:
            return Priority.HIGH
        if score >= self.moderate:
            return Priority.MODERATE
        return Priority.LOW


@dataclass(frozen=True)
class Assessment:
    scores: dict[str, int]
    justification: dict[str, str]
    method_version: str

    @property
    def final_score(self) -> float:
        return compute_final_score(**self.scores)


def _has(text: str, patterns: tuple[str, ...]) -> list[str]:
    found = []
    for pattern in patterns:
        if re.search(rf"(?<!\w){pattern}", text):
            label = pattern.replace("[- ]", "-").replace("[sz]", "z").replace(r"\d", "N")
            found.append(label.replace("?", "").replace("\\", "").strip())
    return found


_METHOD_CUES = (
    r"randomi[sz]ed",
    r"cohort",
    r"cross-sectional",
    r"meta-analys",
    r"systematic review",
    r"experiment",
    r"dataset",
    r"we measured",
    r"sample of",
    r"participants",
    r"simulation",
    r"benchmark",
    r"longitudinal",
    r"n ?= ?\d",
)
_NOVELTY_CUES = (
    r"novel",
    r"first ",
    r"new approach",
    r"new method",
    r"we propose",
    r"we introduce",
    r"we present",
    r"unprecedented",
    r"for the first time",
    r"previously unknown",
)
_IMPACT_CUES = (
    r"application",
    r"open[- ]source",
    r"framework",
    r"scalab",
    r"public health",
    r"policy",
    r"sustainab",
    r"energy",
    r"climate",
    r"diagnos",
    r"therap",
    r"reproducib",
    r"tool",
)
_PRELIMINARY_CUES = (r"preliminary", r"pilot", r"proof[- ]of[- ]concept", r"exploratory")
_UFABC_FOCUS = (
    r"neuro",
    r"artificial intelligence",
    r"machine learning",
    r"robot",
    r"energy",
    r"materials",
    r"quantum",
    r"data",
    r"brain",
    r"computational",
)


def heuristic_assessment(
    article: Article, *, today: date | None = None, category_count: int | None = None
) -> Assessment:
    """Avaliação determinística baseada apenas nos metadados e no texto coletados."""
    today = today or datetime.now(timezone.utc).date()
    text = strip_accents(f"{article.title} {article.abstract or ''}").casefold()
    abstract_words = word_count(article.abstract)
    if category_count is None:
        # Só categorias atribuídas com confiança contam como interdisciplinaridade.
        category_count = sum(1 for link in article.categories if not link.is_uncertain)
    categories = category_count
    just: dict[str, str] = {}

    # Relevância científica: evidência metodológica descrita e completude do registro.
    sci = 30
    notes = []
    if abstract_words > MAX_TYPICAL_ABSTRACT_WORDS:
        sci += 5
        notes.append(
            f"texto atípico para um abstract ({abstract_words} palavras): possível texto "
            "completo ou registro não padronizado — conferir"
        )
    elif abstract_words >= 150:
        sci += 25
        notes.append("abstract detalhado")
    elif abstract_words >= 60:
        sci += 15
        notes.append("abstract moderado")
    else:
        notes.append("pouca informação no abstract")
    methods = _has(text, _METHOD_CUES)
    if methods:
        sci += min(25, 8 * len(methods))
        notes.append("método descrito (" + ", ".join(methods[:3]) + ")")
    if article.article_type is ArticleType.REVIEW:
        sci += 10
        notes.append("revisão (síntese de evidências)")
    preliminary = _has(text, _PRELIMINARY_CUES)
    if preliminary:
        sci -= 10
        notes.append("estudo preliminar (" + ", ".join(preliminary) + ")")
    if article.peer_review_status is PeerReviewStatus.PREPRINT:
        notes.append("preprint: não penalizado, mas sem revisão por pares confirmada")
    repository = unmoderated_repository(article)
    if repository:
        # Não é critério de prestígio: indica ausência de qualquer triagem editorial.
        sci -= 15
        notes.append(
            f"depósito em repositório genérico sem triagem ({repository}): conferir antes de "
            "priorizar"
        )
    just["scientific_relevance"] = "; ".join(notes)

    # Originalidade: sinais textuais de novidade e recência.
    orig = 35
    novelty = _has(text, _NOVELTY_CUES)
    notes = []
    if novelty:
        orig += min(35, 12 * len(novelty))
        notes.append("sinais de novidade (" + ", ".join(novelty[:3]) + ")")
    else:
        notes.append("sem sinais explícitos de novidade")
    if article.publication_date:
        age = (today - article.publication_date).days
        if age <= 14:
            orig += 15
            notes.append(f"publicação recente ({age} dias)")
        elif age <= 60:
            orig += 8
            notes.append(f"publicação de {age} dias")
        else:
            notes.append(f"publicação há {age} dias")
    else:
        notes.append("data de publicação ausente")
    just["originality"] = "; ".join(notes)

    # Impacto potencial: possibilidades de aplicação descritas (não impacto comprovado).
    imp = 30
    impact = _has(text, _IMPACT_CUES)
    notes = []
    if impact:
        imp += min(40, 10 * len(impact))
        notes.append("aplicações potenciais mencionadas (" + ", ".join(impact[:4]) + ")")
    else:
        notes.append("aplicações não descritas")
    if article.open_access:
        imp += 10
        notes.append("acesso aberto facilita reuso")
    just["potential_impact"] = "; ".join(notes) + " — potencial, não impacto comprovado"

    # Interdisciplinaridade: número de editorias atribuídas.
    inter = {0: 15, 1: 30, 2: 65, 3: 80}.get(categories, 90)
    just["interdisciplinarity"] = f"{categories} editoria(s) atribuída(s)"

    # Interesse UFABC: aderência aos eixos da comunidade, sem exigir autoria da UFABC.
    ufabc = 35 + (15 if categories else 0)
    focus = _has(text, _UFABC_FOCUS)
    notes = []
    if focus:
        ufabc += min(30, 8 * len(focus))
        notes.append("temas próximos aos cursos da UFABC (" + ", ".join(focus[:4]) + ")")
    if article.open_access:
        ufabc += 10
        notes.append("leitura acessível a estudantes (acesso aberto)")
    brazil = any((inst.get("country") or "").upper() == "BR" for inst in article.institutions or [])
    if brazil:
        ufabc += 5
        notes.append("participação de instituição brasileira")
    just["ufabc_interest"] = "; ".join(notes) or "aderência genérica"

    scores = {
        "scientific_relevance": sci,
        "originality": orig,
        "potential_impact": imp,
        "interdisciplinarity": inter,
        "ufabc_interest": ufabc,
    }
    scores = {k: max(0, min(100, int(v))) for k, v in scores.items()}
    return Assessment(scores=scores, justification=just, method_version=HEURISTIC_VERSION)


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
) -> ScoringSummary:
    """Calcula e persiste a relevância. Preserva avaliações anteriores (histórico)."""
    summary = ScoringSummary()
    query = select(Article).order_by(Article.id)
    if article_ids:
        query = query.where(Article.id.in_(article_ids))
    for article in session.scalars(query).all():
        previous = latest_assessment(article)
        if (
            previous is not None
            and previous.method_version == HEURISTIC_VERSION
            and not (rescore or article_ids)
        ):
            summary.skipped += 1
            continue
        assessment = heuristic_assessment(article, today=today)
        record = RelevanceAssessment(
            article=article,
            **assessment.scores,
            final_score=assessment.final_score,
            justification=assessment.justification,
            method_version=assessment.method_version,
            assessed_at=utcnow(),
        )
        session.add(record)
        summary.assessed += 1
    session.flush()
    return summary
