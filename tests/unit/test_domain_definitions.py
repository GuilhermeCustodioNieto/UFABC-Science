from __future__ import annotations

import pytest
from pydantic import ValidationError

from ufabc_science.domain.enums import EditorialStatus, PeerReviewStatus
from ufabc_science.domain.schemas import (
    DEFAULT_CATEGORIES,
    LEGACY_CATEGORY_SLUGS,
    CategoryDefinition,
)


def test_editorial_status_values_match_markdown_front_matter() -> None:
    # Valores usados no front matter (SPECIFICATION.md, seções 13.1 e 13.2).
    assert {s.value for s in EditorialStatus} == {
        "pending_review",
        "approved",
        "rejected",
        "needs_revision",
    }
    assert str(EditorialStatus.APPROVED) == "approved"


def test_peer_review_status_distinguishes_preprints() -> None:
    assert PeerReviewStatus.PREPRINT != PeerReviewStatus.VERIFIED
    assert PeerReviewStatus("verified") is PeerReviewStatus.VERIFIED
    assert PeerReviewStatus("unknown") is PeerReviewStatus.UNKNOWN


def test_default_categories_follow_the_editorial_policy() -> None:
    slugs = [category.slug for category in DEFAULT_CATEGORIES]

    assert slugs == [
        "computacao-e-ia",
        "engenharia-aeroespacial",
        "astronomia-e-universo",
        "medicina-e-biotecnologia",
        "neurociencia-e-psicologia",
        "filosofia-sociologia-e-arte",
        "economia",
        "interseccoes-cientificas",
        "outras-ciencias",
    ]
    assert len({category.name for category in DEFAULT_CATEGORIES}) == 9
    assert not set(slugs) & set(LEGACY_CATEGORY_SLUGS)


@pytest.mark.parametrize("slug", ["Neurociência", "com espaço", "-inicio", "fim-", "a--b", ""])
def test_category_slug_must_be_url_safe(slug: str) -> None:
    with pytest.raises(ValidationError):
        CategoryDefinition(name="X", slug=slug, description="Y")
