"""Classificação científica híbrida (SPECIFICATION.md, seção 9; Etapa 3, seção 3).

Fase A — regras determinísticas e configuráveis (``rules/classification.json``)
aplicadas a título, palavras-chave/categorias das fontes e abstract.

Fase B — classificação assistida por IA, opcional, somente para casos sem
categoria ou ambíguos. A IA não remove nem rebaixa categorias atribuídas com
boa confiança pelas regras.

Nenhum artigo é forçado a uma categoria sem evidência suficiente.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ClassificationMethod
from ufabc_science.domain.models import Article, ArticleCategory, Category, utcnow
from ufabc_science.intelligence.base import AIProvider
from ufabc_science.intelligence.exceptions import AIError
from ufabc_science.processing.normalization import strip_accents

logger = logging.getLogger(__name__)

# Nomes usados na especificação da Etapa 3 -> slugs persistidos (seção 2.2/13.1).
CATEGORY_ALIASES = {
    "computacao_tecnologia": "computacao-e-tecnologia",
    "ciencias_biologicas": "ciencias-biologicas",
    "ciencias_stem": "ciencias-e-stem",
    "neurociencia": "neurociencia",
    "engenharias": "engenharias",
}


def canonical_category(slug: str) -> str:
    value = slug.strip().lower()
    return CATEGORY_ALIASES.get(value, value.replace("_", "-"))


# --- Regras -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryRules:
    slug: str
    strong: tuple[re.Pattern[str], ...]
    weak: tuple[re.Pattern[str], ...]
    source_categories: frozenset[str]
    strong_terms: tuple[str, ...]
    weak_terms: tuple[str, ...]


@dataclass(frozen=True)
class RuleSet:
    version: str
    field_weights: dict[str, float]
    term_weights: dict[str, float]
    saturation: float
    min_strong_evidence: int
    categories: tuple[CategoryRules, ...]
    # Categorias secundárias precisam de confiança >= relative_threshold x a principal.
    relative_threshold: float = 0.6
    max_categories: int = 3


def _normalize(text: str) -> str:
    return strip_accents(text).casefold()


def _compile(term: str) -> re.Pattern[str]:
    normalized = _normalize(term.strip())
    if normalized.endswith("*"):
        body = re.escape(normalized[:-1])
        return re.compile(rf"(?<![\w-]){body}[\w-]*")
    return re.compile(rf"(?<![\w-]){re.escape(normalized)}s?(?![\w-])")


def parse_rules(data: dict[str, Any]) -> RuleSet:
    categories = []
    for slug, spec in data["categories"].items():
        strong = tuple(spec.get("strong", []))
        weak = tuple(spec.get("weak", []))
        categories.append(
            CategoryRules(
                slug=canonical_category(slug),
                strong=tuple(_compile(t) for t in strong),
                weak=tuple(_compile(t) for t in weak),
                source_categories=frozenset(
                    _normalize(t) for t in spec.get("source_categories", [])
                ),
                strong_terms=strong,
                weak_terms=weak,
            )
        )
    return RuleSet(
        version=str(data.get("version", "rules")),
        field_weights={"title": 2.0, "keywords": 1.5, "abstract": 1.0}
        | dict(data.get("field_weights", {})),
        term_weights={"strong": 3.0, "weak": 1.0, "source_category": 4.0}
        | dict(data.get("term_weights", {})),
        saturation=float(data.get("saturation", 9.0)),
        min_strong_evidence=int(data.get("min_strong_evidence", 1)),
        categories=tuple(categories),
        relative_threshold=float(data.get("relative_threshold", 0.6)),
        max_categories=int(data.get("max_categories", 3)),
    )


@lru_cache(maxsize=8)
def load_rules(path: str | None = None) -> RuleSet:
    """Carrega as regras do arquivo informado ou das regras padrão do pacote."""
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    else:
        raw = (
            resources.files("ufabc_science.processing")
            .joinpath("rules/classification.json")
            .read_text(encoding="utf-8")
        )
    return parse_rules(json.loads(raw))


# --- Fase A -----------------------------------------------------------------------------


@dataclass
class CategoryAssignment:
    slug: str
    confidence: float
    method: ClassificationMethod
    justification: str
    uncertain: bool = False


@dataclass
class ClassificationResult:
    assignments: list[CategoryAssignment] = field(default_factory=list)
    ambiguous: bool = False
    evidence_without_category: bool = False

    @property
    def slugs(self) -> list[str]:
        return [a.slug for a in self.assignments]


@dataclass(frozen=True)
class ArticleText:
    title: str
    abstract: str
    keywords: tuple[str, ...]

    @classmethod
    def from_article(cls, article: Article) -> ArticleText:
        return cls(
            title=article.title or "",
            abstract=article.abstract or "",
            keywords=tuple(article.keywords or ()),
        )


def _score_category(
    rules: RuleSet, cat: CategoryRules, text: ArticleText
) -> tuple[float, int, list[str]]:
    fields = {
        "title": _normalize(text.title),
        "keywords": _normalize(" ; ".join(text.keywords)),
        "abstract": _normalize(text.abstract),
    }
    score = 0.0
    strong_hits = 0
    evidence: list[str] = []

    keyword_set = {_normalize(k) for k in text.keywords}
    source_hits = sorted(keyword_set & cat.source_categories)
    if source_hits:
        score += rules.term_weights["source_category"] * min(2, len(source_hits))
        strong_hits += 1
        evidence.append("categorias da fonte: " + ", ".join(source_hits[:4]))

    for kind, patterns, terms in (
        ("strong", cat.strong, cat.strong_terms),
        ("weak", cat.weak, cat.weak_terms),
    ):
        for pattern, term in zip(patterns, terms, strict=True):
            for field_name, value in fields.items():
                count = len(pattern.findall(value))
                if not count:
                    continue
                # Repetições no abstract contam com retorno decrescente (máx. 2).
                repeat = min(count, 2) if field_name == "abstract" else 1
                score += rules.term_weights[kind] * rules.field_weights[field_name] * repeat
                if kind == "strong":
                    strong_hits += 1
                evidence.append(f"{term.rstrip('*')} ({field_name})")
    return score, strong_hits, evidence


def classify_text(
    text: ArticleText,
    rules: RuleSet,
    *,
    min_confidence: float = 0.35,
    uncertain_below: float = 0.5,
) -> ClassificationResult:
    """Classificação determinística. Um artigo pode receber várias categorias."""
    result = ClassificationResult()
    scored = []
    for cat in rules.categories:
        score, strong_hits, evidence = _score_category(rules, cat, text)
        if score <= 0:
            continue
        confidence = round(1 - math.exp(-score / rules.saturation), 3)
        # Contexto: só termos genéricos (ex.: "brain" de passagem) não bastam.
        if strong_hits < rules.min_strong_evidence:
            result.evidence_without_category = True
            continue
        scored.append((cat.slug, confidence, evidence))

    scored.sort(key=lambda item: item[1], reverse=True)
    top = scored[0][1] if scored else 0.0
    for slug, confidence, evidence in scored:
        if confidence < min_confidence:
            result.evidence_without_category = True
            continue
        # Secundárias fracas em relação à principal são ruído (ex.: "model" em biologia).
        if confidence < top * rules.relative_threshold:
            continue
        if len(result.assignments) >= rules.max_categories:
            break
        uncertain = confidence < uncertain_below
        justification = f"Regras {rules.version}: " + "; ".join(dict.fromkeys(evidence[:8]))
        if uncertain:
            justification += " — confiança baixa: revisar."
        result.assignments.append(
            CategoryAssignment(
                slug=slug,
                confidence=confidence,
                method=ClassificationMethod.RULE_BASED,
                justification=justification,
                uncertain=uncertain,
            )
        )
    if not result.assignments:
        result.ambiguous = result.evidence_without_category
    elif all(a.uncertain for a in result.assignments):
        result.ambiguous = True
    return result


# --- Fase B -----------------------------------------------------------------------------


class AICategory(BaseModel):
    slug: str
    confidence: float = Field(ge=0, le=1)
    justification: str = Field(min_length=3, max_length=600)

    @field_validator("slug")
    @classmethod
    def _canonical(cls, value: str) -> str:
        return canonical_category(value)


class AIClassificationOutput(BaseModel):
    categories: list[AICategory] = Field(default_factory=list, max_length=5)


def classify_with_ai(
    provider: AIProvider,
    article: Article,
    rule_result: ClassificationResult,
    allowed: dict[str, str],
    *,
    max_confidence: float = 0.75,
) -> list[CategoryAssignment]:
    """Sugestões da IA para casos ambíguos; categorias desconhecidas são descartadas."""
    from ufabc_science.intelligence.prompts import CLASSIFICATION_PROMPT, untrusted_block

    payload = {
        "titulo": article.title,
        "abstract": article.abstract,
        "palavras_chave": list(article.keywords or [])[:30],
        "categorias_regras": rule_result.slugs,
    }
    prompt = CLASSIFICATION_PROMPT.render(
        categorias="\n".join(f"- {slug}: {desc}" for slug, desc in allowed.items()),
        dados=untrusted_block(payload),
    )
    try:
        response = provider.generate_structured(
            prompt,
            AIClassificationOutput.model_json_schema(),
            system=CLASSIFICATION_PROMPT.system,
        )
        output = AIClassificationOutput.model_validate(response.data)
    except (AIError, ValidationError) as exc:
        logger.warning("Classificação por IA ignorada para artigo %s: %s", article.id, exc)
        return []
    suggestions = []
    for item in output.categories:
        if item.slug not in allowed:
            logger.warning("IA sugeriu categoria desconhecida %r; ignorada", item.slug)
            continue
        confidence = min(item.confidence, max_confidence)
        suggestions.append(
            CategoryAssignment(
                slug=item.slug,
                confidence=round(confidence, 3),
                method=ClassificationMethod.AI_ASSISTED,
                justification=(
                    f"IA ({provider.name}, prompt {CLASSIFICATION_PROMPT.version}): "
                    f"{item.justification}"
                ),
                uncertain=True,  # sugestões da IA sempre exigem atenção humana
            )
        )
    return suggestions


# --- Persistência -----------------------------------------------------------------------


@dataclass
class ClassificationSummary:
    processed: int = 0
    classified: int = 0
    without_category: int = 0
    uncertain: int = 0
    ai_assisted: int = 0


def classify_articles(
    session: Session,
    *,
    rules: RuleSet,
    min_confidence: float,
    uncertain_below: float,
    article_ids: list[int] | None = None,
    reclassify: bool = False,
    provider: AIProvider | None = None,
) -> ClassificationSummary:
    """Classifica artigos sem classificação (ou os informados) e persiste o resultado.

    Classificações ``MANUAL`` nunca são removidas. Sem ``reclassify``, artigos já
    classificados são ignorados (idempotência).
    """
    summary = ClassificationSummary()
    categories = {c.slug: c for c in session.scalars(select(Category).where(Category.active))}
    allowed = {slug: c.description or c.name for slug, c in categories.items()}

    query = select(Article).order_by(Article.id)
    if article_ids:
        query = query.where(Article.id.in_(article_ids))
    for article in session.scalars(query).all():
        # Já classificado com a versão atual das regras: nada a fazer (idempotência).
        # Uma nova versão das regras reclassifica automaticamente (MANUAL é preservado).
        current = bool(article.categories) and all(
            link.classification_method is not ClassificationMethod.RULE_BASED
            or (link.justification or "").startswith(f"Regras {rules.version}:")
            for link in article.categories
        )
        if current and not (reclassify or article_ids):
            continue
        summary.processed += 1
        result = classify_text(
            ArticleText.from_article(article),
            rules,
            min_confidence=min_confidence,
            uncertain_below=uncertain_below,
        )
        assignments = list(result.assignments)
        if provider is not None and (result.ambiguous or not assignments):
            confident = {a.slug for a in assignments if not a.uncertain}
            for suggestion in classify_with_ai(provider, article, result, allowed):
                if suggestion.slug in confident:
                    continue
                assignments = [a for a in assignments if a.slug != suggestion.slug]
                assignments.append(suggestion)
                summary.ai_assisted += 1

        manual = {
            link.category.slug
            for link in article.categories
            if link.classification_method is ClassificationMethod.MANUAL
        }
        session.execute(
            delete(ArticleCategory).where(
                ArticleCategory.article_id == article.id,
                ArticleCategory.classification_method != ClassificationMethod.MANUAL,
            )
        )
        session.expire(article, ["categories"])
        for assignment in assignments:
            if assignment.slug in manual or assignment.slug not in categories:
                continue
            session.add(
                ArticleCategory(
                    article_id=article.id,
                    category_id=categories[assignment.slug].id,
                    confidence=assignment.confidence,
                    classification_method=assignment.method,
                    justification=assignment.justification,
                    is_uncertain=assignment.uncertain,
                    classified_at=utcnow(),
                )
            )
        session.flush()
        if assignments or manual:
            summary.classified += 1
        else:
            summary.without_category += 1
        if any(a.uncertain for a in assignments):
            summary.uncertain += 1
    return summary
