from __future__ import annotations

import pytest
from pydantic import ValidationError

from ufabc_science.domain.enums import EditorialStatus, PeerReviewStatus
from ufabc_science.domain.schemas import DEFAULT_CATEGORIES, CategoryDefinition


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


def test_default_categories_cover_the_five_editorias() -> None:
    slugs = [category.slug for category in DEFAULT_CATEGORIES]

    assert slugs == [
        "neurociencia",
        "computacao-e-tecnologia",
        "engenharias",
        "ciencias-biologicas",
        "ciencias-e-stem",
    ]
    assert len({category.name for category in DEFAULT_CATEGORIES}) == 5


@pytest.mark.parametrize("slug", ["Neurociência", "com espaço", "-inicio", "fim-", "a--b", ""])
def test_category_slug_must_be_url_safe(slug: str) -> None:
    with pytest.raises(ValidationError):
        CategoryDefinition(name="X", slug=slug, description="Y")
