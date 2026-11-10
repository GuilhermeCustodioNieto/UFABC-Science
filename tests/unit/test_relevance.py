from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, Priority
from ufabc_science.domain.models import Article
from ufabc_science.processing.relevance import (
    HEURISTIC_VERSION,
    WEIGHTS,
    PriorityBands,
    compute_final_score,
    heuristic_assessment,
    score_articles,
)

ABSTRACT = (
    "We present a novel open-source framework and dataset for decoding neural activity. "
    "In a randomized experiment with 40 participants, the method improved accuracy. "
    "These preliminary results suggest applications in brain-computer interfaces. " * 3
)


def test_formula_matches_specification() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert compute_final_score(100, 100, 100, 100, 100) == 100
    assert compute_final_score(0, 0, 0, 0, 0) == 0
    assert compute_final_score(80, 70, 60, 50, 90) == pytest.approx(
        80 * 0.30 + 70 * 0.20 + 60 * 0.20 + 50 * 0.15 + 90 * 0.15
    )


@pytest.mark.parametrize("value", [-1, 101])
def test_criteria_must_be_between_0_and_100(value: int) -> None:
    with pytest.raises(ValueError):
        compute_final_score(value, 50, 50, 50, 50)


def test_priority_bands_are_configurable() -> None:
    bands = PriorityBands()
    assert bands.classify(90) is Priority.VERY_HIGH
    assert bands.classify(85) is Priority.VERY_HIGH
    assert bands.classify(70) is Priority.HIGH
    assert bands.classify(50) is Priority.MODERATE
    assert bands.classify(49.9) is Priority.LOW
    assert PriorityBands(very_high=95, high=80, moderate=60).classify(85) is Priority.HIGH


def _article(**kwargs: object) -> Article:
    data: dict[str, object] = {
        "title": "Decoding neural activity",
        "abstract": ABSTRACT,
        "publication_date": date(2026, 11, 5),
        "peer_review_status": PeerReviewStatus.VERIFIED,
        "article_type": ArticleType.JOURNAL_ARTICLE,
    }
    data.update(kwargs)
    return Article(**data)


def test_every_score_has_a_justification() -> None:
    assessment = heuristic_assessment(_article(), today=date(2026, 11, 9), category_count=2)
    assert set(assessment.justification) == set(WEIGHTS)
    assert all(text for text in assessment.justification.values())
    assert all(0 <= value <= 100 for value in assessment.scores.values())
    assert "preliminar" in assessment.justification["scientific_relevance"]
    assert "não impacto comprovado" in assessment.justification["potential_impact"]


def test_preprints_are_not_penalized() -> None:
    today = date(2026, 11, 9)
    verified = heuristic_assessment(_article(), today=today, category_count=1)
    preprint = heuristic_assessment(
        _article(peer_review_status=PeerReviewStatus.PREPRINT), today=today, category_count=1
    )
    assert preprint.final_score == verified.final_score
    assert "preprint" in preprint.justification["scientific_relevance"]


def test_citations_and_institution_prestige_are_not_used() -> None:
    today = date(2026, 11, 9)
    base = heuristic_assessment(_article(), today=today, category_count=1)
    famous = heuristic_assessment(
        _article(
            institutions=[{"name": "Universidade Muito Famosa", "country": "US"}],
            source_metadata={"cited_by_count": 100000, "impact_factor": 80},
        ),
        today=today,
        category_count=1,
    )
    assert famous.final_score == base.final_score


def test_interdisciplinarity_grows_with_categories() -> None:
    today = date(2026, 11, 9)
    one = heuristic_assessment(_article(), today=today, category_count=1)
    three = heuristic_assessment(_article(), today=today, category_count=3)
    assert three.scores["interdisciplinarity"] > one.scores["interdisciplinarity"]


def test_scores_are_persisted_with_history(session: Session) -> None:
    article = _article()
    session.add(article)
    session.flush()

    first = score_articles(session, today=date(2026, 11, 9))
    again = score_articles(session, today=date(2026, 11, 9))
    forced = score_articles(session, rescore=True, today=date(2026, 11, 9))

    assert (first.assessed, again.skipped, forced.assessed) == (1, 1, 1)
    assert len(article.relevance_assessments) == 2
    record = article.relevance_assessments[-1]
    assert record.method_version == HEURISTIC_VERSION
    assert record.final_score == pytest.approx(
        compute_final_score(
            record.scientific_relevance,
            record.originality,
            record.potential_impact,
            record.interdisciplinarity,
            record.ufabc_interest,
        )
    )


def test_unmoderated_repository_is_flagged_but_preprint_servers_are_not() -> None:
    today = date(2026, 11, 9)
    base = heuristic_assessment(_article(), today=today, category_count=1)
    zenodo = heuristic_assessment(
        _article(journal="Zenodo (CERN European Organization for Nuclear Research)"),
        today=today,
        category_count=1,
    )
    arxiv = heuristic_assessment(
        _article(journal=None, publisher="arXiv", peer_review_status=PeerReviewStatus.PREPRINT),
        today=today,
        category_count=1,
    )
    assert zenodo.scores["scientific_relevance"] < base.scores["scientific_relevance"]
    assert "repositório genérico" in zenodo.justification["scientific_relevance"]
    assert arxiv.scores["scientific_relevance"] == base.scores["scientific_relevance"]


def test_atypically_long_abstract_gets_no_detail_bonus() -> None:
    today = date(2026, 11, 9)
    normal = heuristic_assessment(_article(), today=today, category_count=1)
    dump = heuristic_assessment(_article(abstract=ABSTRACT * 10), today=today, category_count=1)
    assert dump.scores["scientific_relevance"] < normal.scores["scientific_relevance"]
    assert "atípico" in dump.justification["scientific_relevance"]


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
    assert score_articles(session, today=date(2026, 11, 9)).assessed == 1
    assert [r.method_version for r in article.relevance_assessments] == [
        "antigo",
        HEURISTIC_VERSION,
    ]
