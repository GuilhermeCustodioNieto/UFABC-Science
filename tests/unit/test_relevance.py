"""Pré-filtro heurístico da curadoria: notas, faixas, histórico e confiabilidade da fonte."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, Priority
from ufabc_science.domain.models import Article
from ufabc_science.processing.curation import (
    WEIGHTS,
    compute_editorial_score,
    heuristic_curation,
)
from ufabc_science.processing.relevance import HEURISTIC_VERSION, PriorityBands, score_articles

TODAY = date(2026, 11, 9)
ABSTRACT = (
    "We present a novel open-source framework and dataset for decoding neural activity. "
    "In a randomized experiment with 40 participants, the method improved accuracy. "
    "These preliminary results suggest applications in brain-computer interfaces. " * 3
)


def _article(**kwargs: object) -> Article:
    data: dict[str, object] = {
        "title": "Decoding neural activity",
        "abstract": ABSTRACT,
        "publication_date": date(2026, 11, 5),
        "peer_review_status": PeerReviewStatus.VERIFIED,
        "article_type": ArticleType.JOURNAL_ARTICLE,
        "doi": "10.1234/x",
    }
    data.update(kwargs)
    return Article(**data)


def test_formula_matches_editorial_policy() -> None:
    assert WEIGHTS == {
        "curiosity": 0.30,
        "scientific_relevance": 0.25,
        "novelty": 0.20,
        "impact": 0.15,
        "evidence_quality": 0.10,
    }
    names = list(WEIGHTS)
    assert compute_editorial_score(dict.fromkeys(names, 100)) == 100
    assert compute_editorial_score(dict.fromkeys(names, 0)) == 0
    scores = dict(zip(names, (80, 70, 60, 50, 90), strict=True))
    assert compute_editorial_score(scores) == pytest.approx(
        80 * 0.30 + 70 * 0.25 + 60 * 0.20 + 50 * 0.15 + 90 * 0.10
    )


@pytest.mark.parametrize("value", [-1, 101])
def test_criteria_must_be_between_0_and_100(value: int) -> None:
    with pytest.raises(ValueError):
        compute_editorial_score(dict.fromkeys(WEIGHTS, 50) | {"curiosity": value})


def test_priority_bands_follow_the_editorial_policy() -> None:
    bands = PriorityBands()
    assert bands.classify(90) is Priority.VERY_HIGH
    assert bands.classify(85) is Priority.VERY_HIGH
    assert bands.classify(80) is Priority.HIGH
    assert bands.classify(70) is Priority.MODERATE
    assert bands.classify(64.9) is Priority.LOW
    assert PriorityBands(very_high=95, high=80, moderate=60).classify(85) is Priority.HIGH


def test_every_score_has_a_justification() -> None:
    assessment = heuristic_curation(_article(), today=TODAY, categories=["computacao-e-ia"])
    assert set(assessment.justification) == set(WEIGHTS)
    assert all(text for text in assessment.justification.values())
    assert all(0 <= value <= 100 for value in assessment.scores.values())
    assert "preliminar" in assessment.justification["evidence_quality"]
    assert "não impacto comprovado" in assessment.justification["impact"]
    assert assessment.reasons  # toda decisão é explicada


def test_preprints_stay_eligible_but_have_weaker_evidence() -> None:
    verified = heuristic_curation(_article(), today=TODAY, categories=[])
    preprint = heuristic_curation(
        _article(peer_review_status=PeerReviewStatus.PREPRINT), today=TODAY, categories=[]
    )
    assert preprint.flags == []
    assert preprint.scores["curiosity"] == verified.scores["curiosity"]
    assert preprint.scores["evidence_quality"] < verified.scores["evidence_quality"]
    assert "preprint" in preprint.justification["evidence_quality"]


def test_citations_and_institution_names_are_not_used() -> None:
    base = heuristic_curation(_article(), today=TODAY, categories=[])
    famous = heuristic_curation(
        _article(
            institutions=[{"name": "Universidade Muito Famosa", "country": "US"}],
            source_metadata={"cited_by_count": 100000, "impact_factor": 80},
        ),
        today=TODAY,
        categories=[],
    )
    assert famous.final_score == base.final_score


def test_recognized_venue_raises_reliability() -> None:
    generic = heuristic_curation(_article(journal="Revista Regional"), today=TODAY, categories=[])
    nature = heuristic_curation(_article(journal="Nature"), today=TODAY, categories=[])
    assert nature.scores["scientific_relevance"] > generic.scores["scientific_relevance"]
    assert nature.scores["evidence_quality"] > generic.scores["evidence_quality"]


def test_unmoderated_repository_is_penalized_but_preprint_servers_are_not() -> None:
    base = heuristic_curation(_article(journal=None), today=TODAY, categories=[])
    zenodo = heuristic_curation(
        _article(journal="Zenodo (CERN European Organization for Nuclear Research)"),
        today=TODAY,
        categories=[],
    )
    assert zenodo.scores["scientific_relevance"] < base.scores["scientific_relevance"]
    assert "sem triagem" in zenodo.justification["scientific_relevance"]


def test_atypically_long_abstract_gets_no_detail_bonus() -> None:
    normal = heuristic_curation(_article(), today=TODAY, categories=[])
    dump = heuristic_curation(_article(abstract=ABSTRACT * 10), today=TODAY, categories=[])
    assert dump.scores["scientific_relevance"] < normal.scores["scientific_relevance"]
    assert "atípico" in dump.justification["scientific_relevance"]


def test_scores_are_persisted_with_history(session: Session) -> None:
    article = _article()
    session.add(article)
    session.flush()

    first = score_articles(session, today=TODAY)
    again = score_articles(session, today=TODAY)
    forced = score_articles(session, rescore=True, today=TODAY)

    assert (first.assessed, again.skipped, forced.assessed) == (1, 1, 1)
    assert len(article.relevance_assessments) == 2
    record = article.relevance_assessments[-1]
    assert record.method_version == HEURISTIC_VERSION
    assert record.decision in {"priority", "publish", "consider", "reject"}
    assert record.decision_reasons
    assert record.final_score == pytest.approx(
        compute_editorial_score(
            {
                "curiosity": record.curiosity,
                "scientific_relevance": record.scientific_relevance,
                "novelty": record.originality,
                "impact": record.potential_impact,
                "evidence_quality": record.evidence_quality,
            }
        )
    )


def test_new_method_version_triggers_reassessment(session: Session) -> None:
    from ufabc_science.domain.models import RelevanceAssessment

    article = _article()
    session.add(article)
    session.flush()
    session.add(
        RelevanceAssessment(
            article=article, scientific_relevance=1, originality=1, potential_impact=1,
            interdisciplinarity=1, ufabc_interest=1, final_score=1, method_version="antigo",
        )
    )  # fmt: skip
    session.flush()
    assert score_articles(session, today=TODAY).assessed == 1
    assert [r.method_version for r in article.relevance_assessments] == [
        "antigo",
        HEURISTIC_VERSION,
    ]
