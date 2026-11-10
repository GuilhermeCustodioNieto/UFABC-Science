"""Verificação determinística de fidelidade (PASSED / WARNING / FAILED)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, VerificationStatus
from ufabc_science.domain.models import Article
from ufabc_science.intelligence.verification import (
    ContentUnderReview,
    build_reference,
    source_url_for,
    verify_content,
)

ABSTRACT = (
    "We trained a convolutional network on 1,200 retinal images from 300 patients. "
    "The model reached an accuracy of 0.94 and reduced screening time by 35%. "
    "However, the dataset came from a single hospital, which limits generalization. "
    "Future studies should include external validation cohorts across different populations."
)


def make_article(**kwargs: object) -> Article:
    data: dict[str, object] = {
        "id": 1,
        "title": "Deep learning screening of diabetic retinopathy",
        "abstract": ABSTRACT,
        "doi": "10.1000/retina.2026",
        "publication_date": date(2026, 11, 3),
        "journal": "Journal of Retina",
        "authors": [{"name": "Ana Souza"}, {"name": "Bruno Lima"}],
        "article_type": ArticleType.JOURNAL_ARTICLE,
        "peer_review_status": PeerReviewStatus.VERIFIED,
    }
    data.update(kwargs)
    return Article(**data)


def make_content(article: Article, **sections: str) -> ContentUnderReview:
    base = {
        "introduction": (
            "Pesquisadores avaliaram uma rede neural convolucional para triagem de retinopatia "
            "diabética em imagens de retina."
        ),
        "context": "A retinopatia diabética é uma complicação ocular do diabetes.",
        "research_question": "O estudo investigou se a rede consegue apoiar a triagem.",
        "methodology": "A rede foi treinada com 1.200 imagens de 300 pacientes.",
        "findings": (
            "O modelo atingiu acurácia de 0,94 e reduziu o tempo de triagem em 35% no "
            "conjunto de imagens retinal analisado."
        ),
        "limitations": "Os dados vieram de um único hospital, o que limita a generalização.",
        "ufabc_relevance": "O tema interessa a estudantes de computação e engenharia biomédica.",
    }
    base.update(sections)
    return ContentUnderReview(
        headline="Rede neural apoia triagem de retinopatia",
        original_title=article.title,
        sections=base,
        reference=build_reference(article),
        source_url=source_url_for(article) or "",
    )


def statuses(report) -> dict[str, VerificationStatus]:
    return {check.code: check.status for check in report.checks}


def test_faithful_content_has_no_failures() -> None:
    article = make_article()
    report = verify_content(article, make_content(article), word_limits={"total": (0, 1000)})
    assert report.status is not VerificationStatus.FAILED, report.failures
    assert statuses(report)["numbers_ok"] is VerificationStatus.PASSED
    assert statuses(report)["doi_ok"] is VerificationStatus.PASSED


def test_invented_numbers_fail() -> None:
    article = make_article()
    content = make_content(article, findings="O modelo acertou 99% dos casos em 5.000 exames.")
    report = verify_content(article, content)
    assert report.status is VerificationStatus.FAILED
    details = next(c.details for c in report.checks if c.code == "numbers_unmatched")
    assert "99%" in details and "5.000" in details


def test_insufficient_source_fails() -> None:
    article = make_article(abstract="Short abstract only.")
    report = verify_content(article, make_content(article), min_abstract_words=40)
    assert statuses(report)["insufficient_source"] is VerificationStatus.FAILED


def test_foreign_doi_and_links_fail() -> None:
    article = make_article()
    content = make_content(
        article, context="Ver também 10.9999/outro.artigo e https://site-qualquer.example/x."
    )
    codes = statuses(verify_content(article, content))
    assert codes["doi_foreign"] is VerificationStatus.FAILED
    assert codes["url_foreign"] is VerificationStatus.FAILED


def test_source_url_must_match_record() -> None:
    article = make_article()
    content = replace(make_content(article), source_url="https://example.org/falso")
    assert statuses(verify_content(article, content))["source_url_mismatch"] is (
        VerificationStatus.FAILED
    )


def test_title_must_match_record() -> None:
    article = make_article()
    content = replace(make_content(article), original_title="Outro título qualquer")
    assert statuses(verify_content(article, content))["title_mismatch"] is VerificationStatus.FAILED


def test_invented_authors_and_citations_fail() -> None:
    article = make_article()
    content = make_content(
        article, context="Como mostraram Pereira et al., o problema é antigo (Silva, 2019)."
    )
    codes = statuses(verify_content(article, content))
    assert codes["authors_mismatch"] is VerificationStatus.FAILED
    assert codes["citations"] is VerificationStatus.FAILED


def test_preprint_must_be_identified() -> None:
    article = make_article(peer_review_status=PeerReviewStatus.PREPRINT, doi=None)
    article.canonical_url = "https://arxiv.org/abs/2611.1"
    content = replace(make_content(article), source_url="https://arxiv.org/abs/2611.1")
    assert statuses(verify_content(article, content))["preprint_unlabeled"] is (
        VerificationStatus.FAILED
    )
    labeled = make_content(
        article,
        introduction="Trata-se de um preprint, ainda não revisado por pares, sobre retinopatia.",
    )
    labeled = replace(labeled, source_url="https://arxiv.org/abs/2611.1")
    assert statuses(verify_content(article, labeled))["preprint_labeled"] is (
        VerificationStatus.PASSED
    )


def test_unconfirmed_peer_review_claim_fails() -> None:
    article = make_article(peer_review_status=PeerReviewStatus.UNKNOWN)
    content = make_content(article, context="O estudo foi revisado por pares e publicado.")
    assert statuses(verify_content(article, content))["peer_review_claim"] is (
        VerificationStatus.FAILED
    )


def test_sensationalism_is_a_warning_and_clinical_advice_fails() -> None:
    article = make_article()
    sensational = make_content(article, introduction="Cientistas provaram a cura definitiva.")
    assert statuses(verify_content(article, sensational))["sensationalism"] is (
        VerificationStatus.WARNING
    )
    clinical = make_content(article, ufabc_relevance="Pacientes devem usar o modelo em casa.")
    assert statuses(verify_content(article, clinical))["clinical_advice"] is (
        VerificationStatus.FAILED
    )


def test_omitted_limitations_are_flagged() -> None:
    article = make_article()
    content = make_content(article, limitations="As limitações não foram informadas na fonte.")
    assert statuses(verify_content(article, content))["limitations_omitted"] is (
        VerificationStatus.WARNING
    )


def test_unsupported_claims_are_listed() -> None:
    article = make_article()
    content = make_content(
        article,
        findings="O sistema foi adotado por todos os hospitais públicos do país sem custo algum.",
    )
    report = verify_content(article, content)
    assert any(not claim.supported for claim in report.claims)
    assert statuses(report)["claims_unsupported"] is VerificationStatus.WARNING


@pytest.mark.parametrize(
    ("doi", "expected"),
    [("10.1000/retina.2026", "https://doi.org/10.1000/retina.2026"), (None, None)],
)
def test_source_url_prefers_doi(doi: str | None, expected: str | None) -> None:
    assert source_url_for(make_article(doi=doi)) == expected


def test_reference_is_built_from_metadata_only() -> None:
    reference = build_reference(make_article())
    assert reference.startswith("Ana Souza, Bruno Lima. Deep learning screening")
    assert "DOI: 10.1000/retina.2026" in reference
    preprint = build_reference(make_article(peer_review_status=PeerReviewStatus.PREPRINT))
    assert "Preprint" in preprint


def test_atypical_sources_are_flagged_for_the_editor() -> None:
    article = make_article(journal="OSF Preprints", abstract=ABSTRACT * 20)
    report = verify_content(article, make_content(article))
    check = next(c for c in report.checks if c.code == "source_quality")
    assert check.status is VerificationStatus.WARNING
    assert any("OSF" in d for d in check.details)
    assert any("abstract atípico" in d for d in check.details)
