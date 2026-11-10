from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ClassificationMethod
from ufabc_science.domain.models import Article, ArticleCategory, ArticleSource, Category, Source
from ufabc_science.intelligence.base import AIProvider, AIResponse
from ufabc_science.processing.classification import (
    ArticleText,
    canonical_category,
    classify_articles,
    classify_text,
    load_rules,
    parse_rules,
)

RULES = load_rules()


def text(title: str, abstract: str = "", keywords: tuple[str, ...] = ()) -> ArticleText:
    return ArticleText(title=title, abstract=abstract, keywords=keywords)


def test_keyword_classification() -> None:
    result = classify_text(
        text(
            "Hippocampal neurons encode spatial memory",
            "We recorded synaptic activity of cortical neurons in mice.",
        ),
        RULES,
    )
    assert result.slugs[0] == "neurociencia"
    assert 0 < result.assignments[0].confidence <= 1
    assert "neuron" in result.assignments[0].justification


def test_interdisciplinary_article_receives_multiple_categories() -> None:
    result = classify_text(
        text(
            "Deep learning decodes neural activity for brain-computer interfaces",
            "A machine learning algorithm trained on EEG recordings from cortical neurons "
            "controls a robotic arm.",
        ),
        RULES,
    )
    assert {"neurociencia", "computacao-e-tecnologia"} <= set(result.slugs)


def test_incidental_mention_is_not_enough() -> None:
    result = classify_text(
        text(
            "Supply chain logistics in coastal ports",
            "Managers often say the brain of the operation is the scheduling office.",
        ),
        RULES,
    )
    assert "neurociencia" not in result.slugs


def test_no_category_without_evidence() -> None:
    result = classify_text(text("Medieval poetry in Portugal", "A literary analysis."), RULES)
    assert result.assignments == []


def test_source_categories_count_as_strong_evidence() -> None:
    result = classify_text(text("A short note", "", ("q-bio.NC",)), RULES)
    assert result.slugs == ["neurociencia"]


def test_low_confidence_is_flagged_as_uncertain() -> None:
    result = classify_text(text("A note", "We used an algorithm."), RULES, min_confidence=0.2)
    assert result.assignments
    assert all(a.uncertain for a in result.assignments)
    assert result.ambiguous
    assert "revisar" in result.assignments[0].justification


def test_portuguese_terms_and_accents() -> None:
    result = classify_text(
        text("Neurociência da memória", "Estudo sobre neurônios e sinapses."), RULES
    )
    assert "neurociencia" in result.slugs


def test_rules_are_configurable() -> None:
    rules = parse_rules(
        {
            "version": "custom",
            "categories": {"engenharias": {"strong": ["widget*"], "weak": []}},
        }
    )
    result = classify_text(text("Widgets everywhere"), rules)
    assert result.slugs == ["engenharias"]
    assert "custom" in result.assignments[0].justification


def test_stage3_aliases_map_to_persisted_slugs() -> None:
    assert canonical_category("computacao_tecnologia") == "computacao-e-tecnologia"
    assert canonical_category("ciencias_stem") == "ciencias-e-stem"


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls = 0

    def generate_structured(self, prompt, response_schema, *, system=None) -> AIResponse:
        self.calls += 1
        assert "<dados_nao_confiaveis>" in prompt
        return AIResponse(self.data, self.name, "fake-1")


def _article(session: Session, title: str, abstract: str = "") -> Article:
    source = Source(name="s", base_url="https://s", source_type="api")
    article = Article(title=title, abstract=abstract)
    article.sources.append(ArticleSource(source=source, external_id=title[:20]))
    session.add(article)
    session.flush()
    return article


def test_persistence_with_ai_for_ambiguous_cases(seeded_session: Session) -> None:
    session = seeded_session
    article = _article(session, "An essay on measurement", "")
    provider = FakeProvider(
        {
            "categories": [
                {"slug": "ciencias_stem", "confidence": 0.95, "justification": "física"},
                {"slug": "astrologia", "confidence": 0.9, "justification": "inexistente"},
            ]
        }
    )
    summary = classify_articles(
        session,
        rules=RULES,
        min_confidence=0.35,
        uncertain_below=0.5,
        provider=provider,
    )
    assert provider.calls == 1
    assert summary.ai_assisted == 1
    link = article.categories[0]
    assert link.category.slug == "ciencias-e-stem"
    assert link.classification_method is ClassificationMethod.AI_ASSISTED
    assert link.confidence <= 0.75  # teto para sugestões da IA
    assert link.is_uncertain


def test_reclassification_preserves_manual_categories(seeded_session: Session) -> None:
    session = seeded_session
    article = _article(session, "Cortical neurons and synaptic plasticity", "Neurons fire.")
    bio = session.query(Category).filter_by(slug="ciencias-biologicas").one()
    session.add(
        ArticleCategory(
            article_id=article.id,
            category_id=bio.id,
            confidence=1.0,
            classification_method=ClassificationMethod.MANUAL,
        )
    )
    session.flush()
    classify_articles(
        session, rules=RULES, min_confidence=0.35, uncertain_below=0.5, article_ids=[article.id]
    )
    session.expire(article, ["categories"])
    methods = {link.category.slug: link.classification_method for link in article.categories}
    assert methods["ciencias-biologicas"] is ClassificationMethod.MANUAL
    assert methods["neurociencia"] is ClassificationMethod.RULE_BASED


def test_classification_is_idempotent(seeded_session: Session) -> None:
    session = seeded_session
    _article(session, "Cortical neurons and synaptic plasticity", "Neurons fire.")
    first = classify_articles(session, rules=RULES, min_confidence=0.35, uncertain_below=0.5)
    second = classify_articles(session, rules=RULES, min_confidence=0.35, uncertain_below=0.5)
    assert first.processed == 1
    assert second.processed == 0


def test_weak_secondary_categories_are_dropped() -> None:
    # Artigo de biologia que só menciona IA de passagem não vira "Computação".
    result = classify_text(
        text(
            "Gene therapy for genetic epilepsy",
            "Genetic epilepsy with defined molecular mechanisms. CRISPR gene expression, viral "
            "vectors, DNA and RNA delivery in cell models. Artificial intelligence may help.",
            ("Genetics",),
        ),
        RULES,
    )
    assert result.slugs == ["ciencias-biologicas"]


def test_maximum_number_of_categories() -> None:
    rules = parse_rules(
        {
            "max_categories": 2,
            "relative_threshold": 0.0,
            "categories": {
                name: {"strong": [f"{name}x"]}
                for name in ("neurociencia", "engenharias", "ciencias-e-stem")
            },
        }
    )
    result = classify_text(text("neurocienciax engenhariasx ciencias-e-stemx"), rules)
    assert len(result.assignments) == 2


def test_new_rules_version_reclassifies_automatically(seeded_session: Session) -> None:
    session = seeded_session
    article = _article(session, "Cortical neurons and synaptic plasticity", "Neurons fire.")
    classify_articles(session, rules=RULES, min_confidence=0.35, uncertain_below=0.5)
    newer = parse_rules(
        {"version": "rules-v99", "categories": {"neurociencia": {"strong": ["neuron*"]}}}
    )
    summary = classify_articles(session, rules=newer, min_confidence=0.35, uncertain_below=0.5)
    assert summary.processed == 1
    session.expire(article, ["categories"])
    assert article.categories[0].justification.startswith("Regras rules-v99:")
