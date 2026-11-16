"""Curadoria editorial (política editorial, seções 3, 4, 9 e 10).

Os oito cenários da seção 10 são artigos sintéticos, escritos para representar cada caso:
o pipeline deve selecionar as descobertas interessantes, rejeitar o irrelevante e explicar
cada decisão.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.domain.models import Article, ArticleSource, Source
from ufabc_science.intelligence.base import AIProvider, AIResponse
from ufabc_science.intelligence.generation import select_for_generation
from ufabc_science.intelligence.schemas import DEFAULT_WORD_LIMITS
from ufabc_science.processing.classification import (
    ArticleText,
    classify_articles,
    classify_text,
    load_rules,
    primary_category,
)
from ufabc_science.processing.curation import (
    CONSIDER_SCORE,
    REJECT,
    ai_curation,
    curate_articles,
    effective_assessment,
    explain_record,
    heuristic_curation,
    is_ai_assessment,
    triage_candidates,
)
from ufabc_science.processing.relevance import score_articles

TODAY = date(2026, 11, 16)
RULES = load_rules()

# --- Os oito cenários da seção 10 -------------------------------------------------------

SCENARIOS: dict[str, dict[str, Any]] = {
    "ia_extraordinaria": {
        "title": "Neuromorphic chip learns new tasks without forgetting old ones",
        "journal": "Nature",
        "abstract": (
            "For the first time, we demonstrate a neuromorphic chip that learns new tasks "
            "continuously without forgetting previously learned ones, a long-standing "
            "limitation of artificial intelligence. Inspired by synaptic plasticity in the "
            "brain, the chip adjusts its own connections during learning. In experiments with "
            "50 sequential tasks, the system retained 94% of earlier performance while using "
            "a fraction of the energy of conventional deep learning hardware. These results "
            "challenge the assumption that catastrophic forgetting is unavoidable in neural "
            "networks and could enable autonomous robots that keep learning after deployment."
        ),
        "expected": "accept",
    },
    "atualizacao_irrelevante": {
        "title": "DataKit version 2.3.1: release notes and minor performance improvements",
        "journal": "Journal of Open Source Software",
        "abstract": (
            "We describe version 2.3.1 of DataKit, a Python library for tabular data. This "
            "release fixes several bugs, updates dependencies and improves the performance of "
            "the CSV parser by 8%. We also present the updated documentation and the new "
            "continuous integration pipeline used by the project maintainers. The software "
            "is available under an open-source license."
        ),
        "expected": "reject",
    },
    "astronomia_surpreendente": {
        "title": "Webb telescope detects an unexpected atmosphere on a rocky exoplanet",
        "journal": "Nature Astronomy",
        "abstract": (
            "Rocky exoplanets orbiting close to small stars were expected to have lost their "
            "atmospheres. Using the James Webb Space Telescope, we observed thermal emission "
            "from a rocky exoplanet and found, surprisingly, evidence of a thick atmosphere "
            "rich in carbon dioxide. The measured dayside temperature is 420 K lower than "
            "predicted for a bare rock. This is the first detection of a secondary atmosphere "
            "on a rocky planet outside the Solar System, and it challenges current models of "
            "atmospheric escape. Further observations are needed to confirm the composition."
        ),
        "expected": "accept",
    },
    "medicina_experimental": {
        "title": "Gene therapy restores hearing in deaf mice",
        "journal": "Science Translational Medicine",
        "abstract": (
            "Hereditary deafness caused by mutations in the OTOF gene has no treatment. We "
            "delivered a working copy of the gene to the inner ear of deaf mice using a dual "
            "viral vector. Treated mice recovered hearing thresholds close to normal within 4 "
            "weeks and the effect lasted for at least 6 months. No toxicity was observed. "
            "These results in mice suggest a path toward gene therapy for a form of human "
            "deafness, but safety and efficacy in people have not been tested."
        ),
        "expected": "accept",
        "evidence_level": "estudo_em_animais",
    },
    "psicologia_contraintuitiva": {
        "title": "Forgetting helps people learn faster, contrary to common belief",
        "journal": "Psychological Science",
        "abstract": (
            "Contrary to the common belief that forgetting is a failure of memory, we found "
            "that partially forgetting studied material improves later learning. In three "
            "randomized experiments with 1,200 participants, people who studied, partly forgot "
            "and then restudied a list of words remembered 30% more one week later than people "
            "who studied continuously. The effect was surprising in its size and was replicated "
            "in a preregistered study. The findings suggest that spaced study works because "
            "some forgetting makes memories stronger."
        ),
        "expected": "accept",
    },
    "economia_relevante": {
        "title": "Generative AI raises the productivity of novice workers but not of experts",
        "journal": "The Quarterly Journal of Economics",
        "abstract": (
            "We study the staggered introduction of a generative AI assistant among 5,179 "
            "customer support agents. Access to the tool increased productivity by 14% on "
            "average, with the largest gains, 34%, for novice and low-skilled workers and "
            "minimal impact on experienced workers. The evidence suggests that AI can reduce "
            "inequality within occupations by spreading the knowledge of the best workers, "
            "with implications for labor markets, training and economic policy."
        ),
        "expected": "accept",
    },
    "complexo_sem_curiosidade": {
        "title": (
            "A comparative performance evaluation of parameter optimization strategies for "
            "finite element mesh refinement in reinforced concrete slab analysis"
        ),
        "journal": "Revista de Engenharia Estrutural Regional",
        "abstract": (
            "This case study presents a comparative performance evaluation of three parameter "
            "optimization strategies for finite element mesh refinement in the analysis of "
            "reinforced concrete slabs. We evaluate convergence rates and computational cost "
            "for a set of benchmark slabs from a municipality building inventory. The adaptive "
            "strategy improved the accuracy of deflection estimates by 3% relative to the "
            "uniform refinement with similar computational cost. The results provide practical "
            "guidance for the optimization of mesh parameters in routine structural design."
        ),
        "expected": "reject",
    },
    "interdisciplinar": {
        "title": "Machine learning discovers a new antibiotic that kills drug-resistant bacteria",
        "journal": "Cell",
        "abstract": (
            "Antibiotic resistance is a growing threat. We trained a deep learning model on "
            "the growth inhibition of 39,000 compounds and used it to screen millions of "
            "molecules. The model discovered a structurally new class of antibiotic that "
            "killed drug-resistant bacteria in laboratory tests and cleared infections in "
            "mice. For the first time, an artificial intelligence screen revealed a previously "
            "unknown mechanism of action, which targets the bacterial membrane. Clinical "
            "trials in humans have not yet been performed."
        ),
        "expected": "accept",
        "interdisciplinary": True,
    },
}


def scenario_article(name: str, **kwargs: Any) -> Article:
    data = SCENARIOS[name]
    values: dict[str, Any] = {
        "title": data["title"],
        "abstract": data["abstract"],
        "journal": data["journal"],
        "doi": f"10.5555/{name}",
        "publication_date": date(2026, 11, 10),
        "peer_review_status": PeerReviewStatus.VERIFIED,
        "article_type": ArticleType.JOURNAL_ARTICLE,
    }
    values.update(kwargs)
    return Article(**values)


def categories_of(article: Article) -> list[str]:
    result = classify_text(
        ArticleText(article.title, article.abstract or "", ()), RULES, min_confidence=0.35
    )
    return [a.slug for a in result.assignments if not a.uncertain]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenarios_are_selected_or_rejected_with_reasons(name: str) -> None:
    article = scenario_article(name)
    assessment = heuristic_curation(article, today=TODAY, categories=categories_of(article))
    accepted = assessment.decision != REJECT
    assert accepted is (SCENARIOS[name]["expected"] == "accept"), assessment.explain()
    # Toda decisão é explicável: motivos e uma justificativa por critério.
    assert assessment.reasons
    assert all(assessment.justification.values())
    assert "Potencial de curiosidade" in assessment.explain()


def test_good_discoveries_outscore_dull_research() -> None:
    def score(name: str) -> float:
        article = scenario_article(name)
        return heuristic_curation(
            article, today=TODAY, categories=categories_of(article)
        ).final_score

    dull = score("complexo_sem_curiosidade")
    for name, data in SCENARIOS.items():
        if data["expected"] == "accept":
            assert score(name) > dull + 10, name


def test_software_update_is_rejected_by_rule_not_just_by_score() -> None:
    assessment = heuristic_curation(scenario_article("atualizacao_irrelevante"), today=TODAY)
    assert "atualizacao_menor" in assessment.flags
    assert any("atualização" in reason for reason in assessment.reasons)


def test_experimental_medical_study_keeps_its_maturity() -> None:
    assessment = heuristic_curation(scenario_article("medicina_experimental"), today=TODAY)
    assert assessment.evidence_level == "estudo_em_animais"
    verified_human = heuristic_curation(
        scenario_article(
            "medicina_experimental",
            abstract=SCENARIOS["medicina_experimental"]["abstract"].replace("mice", "patients"),
        ),
        today=TODAY,
    )
    assert assessment.scores["evidence_quality"] < verified_human.scores["evidence_quality"]


def test_interdisciplinary_research_is_identified() -> None:
    article = scenario_article("interdisciplinar")
    slugs = categories_of(article)
    assert {"computacao-e-ia", "medicina-e-biotecnologia", "interseccoes-cientificas"} <= set(slugs)


@pytest.mark.parametrize(
    ("title", "flag"),
    [
        ("Erratum: Neural circuits of fear", "sem_novidade"),
        ("Editorial: The future of neuroscience", "opiniao_como_descoberta"),
        ("Study protocol for a randomized trial of sleep therapy", "sem_novidade"),
        ("Quarterly earnings and stock price of chip makers", "noticia_empresarial"),
    ],
)
def test_rejection_rules(title: str, flag: str) -> None:
    article = scenario_article("ia_extraordinaria", title=title)
    assessment = heuristic_curation(article, today=TODAY)
    assert flag in assessment.flags
    assert assessment.decision == REJECT


def test_old_research_and_missing_source_are_rejected() -> None:
    old = heuristic_curation(
        scenario_article("ia_extraordinaria", publication_date=date(2020, 1, 1)), today=TODAY
    )
    assert "pesquisa_antiga" in old.flags
    no_source = heuristic_curation(scenario_article("ia_extraordinaria", doi=None), today=TODAY)
    assert "sem_fonte_verificavel" in no_source.flags


def test_other_sciences_need_an_exceptional_discovery() -> None:
    article = scenario_article("ia_extraordinaria")
    assessment = heuristic_curation(article, today=TODAY, categories=["outras-ciencias"])
    assessment.scores = dict.fromkeys(assessment.scores, 78)
    assert assessment.finalize().decision == REJECT
    assessment.scores = dict.fromkeys(assessment.scores, 90)
    assert assessment.finalize().decision == "priority"


# --- Curadoria por IA --------------------------------------------------------------------


def curation_response(
    *,
    scores: dict[str, int] | None = None,
    flags: list[str] | None = None,
    editorias: list[str] | None = None,
    links: list[str] | None = None,
    level: str = "estudo_computacional",
    decision: str = "publish",
) -> dict[str, Any]:
    values = scores or {}
    return {
        "central_discovery": "Pesquisadores criaram um chip que aprende sem esquecer.",
        "evidence_level": level,
        "editorias": editorias or ["computacao-e-ia"],
        "interdisciplinary_links": links or [],
        "scores": {
            name: {"score": values.get(name, 80), "justification": f"justificativa de {name}"}
            for name in (
                "curiosity",
                "scientific_relevance",
                "novelty",
                "impact",
                "evidence_quality",
            )
        },
        "rejection_flags": flags or [],
        "decision_justification": f"O modelo sugeriu {decision}, mas quem decide é o código.",
    }


class CurationProvider(AIProvider):
    name = "fake_llm"
    model = "fake"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.prompts: list[str] = []

    def generate_structured(self, prompt, response_schema, *, system=None) -> AIResponse:
        self.prompts.append(prompt)
        assert response_schema["title"] == "AICurationOutput"
        assert "<dados_nao_confiaveis>" in prompt
        return AIResponse(self.data, self.name, self.model, {"total_tokens": 10})


ALLOWED = {
    "computacao-e-ia": "IA",
    "medicina-e-biotecnologia": "Medicina",
    "interseccoes-cientificas": "Intersecções",
}


def test_ai_scores_are_weighted_by_code() -> None:
    article = scenario_article("ia_extraordinaria")
    heuristic = heuristic_curation(article, today=TODAY, categories=["computacao-e-ia"])
    scores = {
        "curiosity": 90,
        "scientific_relevance": 80,
        "novelty": 70,
        "impact": 60,
        "evidence_quality": 50,
    }
    result = ai_curation(
        CurationProvider(curation_response(scores=scores)), article, heuristic, ALLOWED
    )
    assert result.final_score == pytest.approx(90 * 0.3 + 80 * 0.25 + 70 * 0.2 + 60 * 0.15 + 5)
    assert result.decision == "publish"
    assert result.central_discovery
    assert result.method_version.startswith("curation-ai")


def test_ai_rejection_flags_reject_regardless_of_score() -> None:
    article = scenario_article("ia_extraordinaria")
    heuristic = heuristic_curation(article, today=TODAY)
    response = curation_response(
        scores=dict.fromkeys(["curiosity"], 95), flags=["correlacao_como_causa"]
    )
    result = ai_curation(CurationProvider(response), article, heuristic, ALLOWED)
    assert result.decision == REJECT
    assert any("correlação" in reason for reason in result.reasons)


def test_deterministic_rules_still_apply_after_ai() -> None:
    article = scenario_article("atualizacao_irrelevante")
    heuristic = heuristic_curation(article, today=TODAY)
    response = curation_response(scores=dict.fromkeys(["curiosity", "novelty"], 99))
    result = ai_curation(CurationProvider(response), article, heuristic, ALLOWED)
    assert result.decision == REJECT
    assert "atualizacao_menor" in result.flags


def test_preprint_evidence_is_capped_by_metadata() -> None:
    article = scenario_article("ia_extraordinaria", peer_review_status=PeerReviewStatus.PREPRINT)
    heuristic = heuristic_curation(article, today=TODAY)
    response = curation_response(scores={"evidence_quality": 95})
    result = ai_curation(CurationProvider(response), article, heuristic, ALLOWED)
    assert result.scores["evidence_quality"] == 60
    assert any("limitadas a 60" in reason for reason in result.reasons)


def test_ai_identifies_interdisciplinary_links_and_ignores_unknown_editorias() -> None:
    article = scenario_article("interdisciplinar")
    heuristic = heuristic_curation(article, today=TODAY, categories=[])
    response = curation_response(
        editorias=["computacao-e-ia", "medicina-e-biotecnologia", "astrologia"],
        links=["IA aplicada à descoberta de medicamentos"],
    )
    result = ai_curation(CurationProvider(response), article, heuristic, ALLOWED)
    assert "astrologia" not in result.categories
    assert "interseccoes-cientificas" in result.categories
    assert result.interdisciplinary_links == ["IA aplicada à descoberta de medicamentos"]


# --- Persistência e seleção ----------------------------------------------------------------


def persist(session: Session, article: Article) -> Article:
    source = session.query(Source).first() or Source(
        name="fonte", base_url="https://fonte", source_type="api"
    )
    article.sources.append(ArticleSource(source=source, external_id=article.doi or article.title))
    session.add(article)
    session.flush()
    return article


def test_pipeline_selects_interesting_and_rejects_irrelevant(seeded_session: Session) -> None:
    session = seeded_session
    ids = {name: persist(session, scenario_article(name)).id for name in SCENARIOS}
    classify_articles(session, rules=RULES, min_confidence=0.35, uncertain_below=0.5)
    score_articles(session, today=TODAY)

    selection = select_for_generation(
        session, limit=20, min_abstract_words=40, word_limits=DEFAULT_WORD_LIMITS
    )
    selected = {c.article.id for c in selection.selected}
    for name, data in SCENARIOS.items():
        assert (ids[name] in selected) is (data["expected"] == "accept"), name
    assert ids["atualizacao_irrelevante"] in selection.skipped["rejeitado_pela_curadoria"]
    assert ids["complexo_sem_curiosidade"] in selection.skipped["abaixo_do_corte_editorial"]
    # A pesquisa interdisciplinar é apresentada na editoria de Intersecções.
    article = session.get(Article, ids["interdisciplinar"])
    assert primary_category(list(article.categories)) == "interseccoes-cientificas"


def test_with_ai_configured_only_ai_curated_articles_are_written(
    seeded_session: Session,
) -> None:
    session = seeded_session
    article = persist(session, scenario_article("ia_extraordinaria"))
    other = persist(session, scenario_article("astronomia_surpreendente"))
    score_articles(session, today=TODAY)

    provider = CurationProvider(curation_response(scores=dict.fromkeys(["curiosity"], 92)))
    summary = curate_articles(session, provider, limit=1, today=TODAY)
    assert summary.assessed == 1
    curated = article if is_ai_assessment(effective_assessment(article)) else other

    selection = select_for_generation(
        session,
        limit=10,
        min_abstract_words=40,
        word_limits=DEFAULT_WORD_LIMITS,
        require_ai_curation=True,
    )
    assert [c.article.id for c in selection.selected] == [curated.id]
    waiting = other if curated is article else article
    assert waiting.id in selection.skipped["aguardando_curadoria"]
    explanation = explain_record(effective_assessment(curated))
    assert "Descoberta central" in explanation and "Potencial de curiosidade" in explanation


def test_heuristic_rescoring_never_replaces_ai_curation(seeded_session: Session) -> None:
    session = seeded_session
    article = persist(session, scenario_article("ia_extraordinaria"))
    score_articles(session, today=TODAY)
    curate_articles(session, CurationProvider(curation_response()), limit=5, today=TODAY)
    score_articles(session, rescore=True, today=TODAY)
    assert is_ai_assessment(effective_assessment(article))


def test_editoria_dominance_is_limited_without_forcing_quotas(seeded_session: Session) -> None:
    session = seeded_session
    for index in range(4):
        persist(
            session,
            scenario_article(
                "ia_extraordinaria",
                title=f"Neuromorphic chip learns task family {index} without forgetting",
                doi=f"10.5555/ia-{index}",
            ),
        )
    persist(session, scenario_article("astronomia_surpreendente"))
    classify_articles(session, rules=RULES, min_confidence=0.35, uncertain_below=0.5)
    score_articles(session, today=TODAY)
    selection = select_for_generation(
        session, limit=3, min_abstract_words=40, word_limits=DEFAULT_WORD_LIMITS
    )
    sections = [c.primary for c in selection.selected]
    # Quatro artigos quase iguais de uma área não ocupam todas as vagas.
    assert max(sections.count(s) for s in set(sections)) <= 2
    assert "astronomia-e-universo" in sections
    assert all((c.score or 0) >= CONSIDER_SCORE for c in selection.selected)


def test_other_sciences_threshold_is_80() -> None:
    """Pesquisa forte de área sem editoria própria (ex.: ATP e envelhecimento celular)."""
    article = scenario_article("ia_extraordinaria")
    assessment = heuristic_curation(article, today=TODAY, categories=["outras-ciencias"])
    assessment.scores = dict.fromkeys(assessment.scores, 79)
    assert assessment.finalize().decision == REJECT
    assessment.scores = dict.fromkeys(assessment.scores, 83)
    assert assessment.finalize().decision == "publish"


# --- Triagem em lote -----------------------------------------------------------------------


class TriageProvider(AIProvider):
    name = "fake_llm"
    model = "fake"

    def __init__(self, scores: dict[str, int], fail_batches: set[int] | None = None) -> None:
        self.scores = scores  # título -> nota
        self.fail_batches = fail_batches or set()
        self.calls = 0

    def generate_structured(self, prompt, response_schema, *, system=None) -> AIResponse:
        from ufabc_science.intelligence.exceptions import AIProviderError
        from ufabc_science.intelligence.provider import extract_payload

        self.calls += 1
        if response_schema["title"] == "AICurationOutput":
            return AIResponse(curation_response(), self.name, self.model, {})
        assert response_schema["title"] == "AITriageOutput"
        if self.calls in self.fail_batches:
            raise AIProviderError("HTTP 429")
        items = [
            {"id": p["id"], "curiosity": self.scores.get(p["titulo"], 10), "reason": "r"}
            for p in extract_payload(prompt)["pesquisas"]
        ]
        items.append({"id": 99999, "curiosity": 100, "reason": "id inventado"})
        return AIResponse({"items": items}, self.name, self.model, {})


def test_triage_promotes_curious_titles_over_heuristic_order(seeded_session: Session) -> None:
    session = seeded_session
    dull = [
        persist(
            session,
            scenario_article(
                "complexo_sem_curiosidade",
                title=f"Mesh refinement benchmark number {i}",
                doi=f"10.5555/dull-{i}",
            ),
        )
        for i in range(30)
    ]
    gem = persist(session, scenario_article("astronomia_surpreendente"))
    provider = TriageProvider({gem.title: 95})

    result = triage_candidates(provider, [*dull, gem], keep=3, batch_size=25)

    assert provider.calls == 2  # 31 candidatos em lotes de 25
    assert result.ranked[0] is gem
    assert 99999 not in result.scores  # id inventado pela IA é ignorado
    assert len(result.ranked) == 3


def test_failed_triage_batch_keeps_candidates(seeded_session: Session) -> None:
    session = seeded_session
    articles = [
        persist(session, scenario_article(name, doi=f"10.5555/t-{name}")) for name in SCENARIOS
    ]
    result = triage_candidates(
        TriageProvider({}, fail_batches={1}), articles, keep=20, batch_size=4
    )
    assert len(result.ranked) == len(articles)
    assert result.errors and "429" in result.errors[0]


def test_curation_uses_triage_when_pool_is_larger(seeded_session: Session) -> None:
    session = seeded_session
    for name in SCENARIOS:
        persist(session, scenario_article(name))
    score_articles(session, today=TODAY)
    gem_title = SCENARIOS["economia_relevante"]["title"]
    provider = TriageProvider({gem_title: 99})
    summary = curate_articles(session, provider, limit=1, triage_pool=8, today=TODAY)
    assert summary.triaged >= 2 and summary.triage_calls == 1
    assert summary.assessed == 1
    (article_id,) = summary.explanations
    assert session.get(Article, article_id).title == gem_title
    assert "Triagem: curiosidade 99" in summary.explanations[article_id]


def test_policy_changes_apply_to_stored_assessments(seeded_session: Session) -> None:
    """Uma avaliação gravada como rejeitada pelo corte antigo de Outras Ciências (85) é
    selecionada com o corte atual (80)."""
    from ufabc_science.domain.models import RelevanceAssessment

    session = seeded_session
    article = persist(session, scenario_article("ia_extraordinaria"))
    score_articles(session, today=TODAY)
    session.add(
        RelevanceAssessment(
            article=article, scientific_relevance=83, originality=83, potential_impact=83,
            interdisciplinarity=30, ufabc_interest=83, curiosity=83, evidence_quality=83,
            final_score=82.9, method_version="curation-ai-antigo", decision=REJECT,
            decision_reasons=["Rejeitado: nota 83 < 85."], rejection_flags=[],
        )
    )  # fmt: skip
    session.flush()
    selection = select_for_generation(
        session, limit=5, min_abstract_words=40, word_limits=DEFAULT_WORD_LIMITS
    )
    assert [c.article.id for c in selection.selected] == [article.id]
