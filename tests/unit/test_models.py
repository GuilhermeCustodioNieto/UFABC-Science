"""Restrições de integridade e comportamento dos modelos ORM."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import (
    ArticleType,
    ClassificationMethod,
    EditionStatus,
    EditorialStatus,
    PeerReviewStatus,
    SourceType,
)
from ufabc_science.domain.models import (
    Article,
    ArticleCategory,
    ArticleSource,
    Category,
    EditorialReview,
    GeneratedContent,
    NewsletterEdition,
    NewsletterItem,
    RelevanceAssessment,
    Source,
)


def make_article(**overrides: object) -> Article:
    data: dict[str, object] = {"title": "Um estudo sobre plasticidade sináptica"}
    data.update(overrides)
    return Article(**data)


def make_source(name: str = "openalex") -> Source:
    return Source(name=name, base_url=f"https://{name}.example", source_type=SourceType.API)


def make_category(slug: str) -> Category:
    return Category(name=slug.title(), slug=slug, description="desc")


def make_edition(number: int = 1, **overrides: object) -> NewsletterEdition:
    data: dict[str, object] = {
        "title": f"Edição {number}",
        "slug": f"edicao-{number:03d}",
        "edition_number": number,
        "start_date": date(2026, 11, 9),
        "end_date": date(2026, 11, 15),
    }
    data.update(overrides)
    return NewsletterEdition(**data)


def make_content(article: Article, version: int) -> GeneratedContent:
    return GeneratedContent(
        article=article, version=version, model_provider="mock", prompt_version="v1"
    )


# --- Article -----------------------------------------------------------------


def test_article_defaults_are_conservative(session: Session) -> None:
    article = make_article()
    session.add(article)
    session.commit()

    stored = session.get(Article, article.id)
    assert stored is not None
    # Na ausência de evidência, o artigo NÃO é tratado como revisado por pares.
    assert stored.peer_review_status is PeerReviewStatus.UNKNOWN
    assert stored.article_type is ArticleType.UNKNOWN
    assert stored.authors == []
    assert stored.institutions == []
    assert stored.source_metadata == {}
    assert stored.collected_at.tzinfo is not None
    assert stored.created_at.tzinfo is not None


def test_article_json_fields_roundtrip(session: Session) -> None:
    article = make_article(
        authors=[{"name": "Ana Souza", "orcid": "0000-0002-1825-0097"}],
        institutions=[{"name": "Universidade Federal do ABC", "country": "BR"}],
        source_metadata={"openalex": {"concepts": ["Neuroscience"]}},
    )
    session.add(article)
    session.commit()
    session.expire_all()

    stored = session.scalars(select(Article)).one()
    assert stored.authors[0]["orcid"] == "0000-0002-1825-0097"
    assert stored.institutions[0]["country"] == "BR"
    assert stored.source_metadata["openalex"]["concepts"] == ["Neuroscience"]


def test_doi_is_unique(session: Session) -> None:
    session.add_all([make_article(doi="10.1000/xyz"), make_article(doi="10.1000/xyz")])

    with pytest.raises(IntegrityError):
        session.commit()


def test_articles_without_doi_are_allowed(session: Session) -> None:
    session.add_all([make_article(doi=None), make_article(doi=None)])
    session.commit()

    assert len(session.scalars(select(Article)).all()) == 2


def test_title_is_required(session: Session) -> None:
    session.add(Article(title=None))

    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_enum_value_is_rejected(session: Session) -> None:
    session.add(make_article(peer_review_status="peer_reviewed_probably"))

    with pytest.raises(StatementError):
        session.commit()


def test_updated_at_changes_on_update(session: Session) -> None:
    article = make_article()
    session.add(article)
    session.commit()
    first_update = article.updated_at

    article.title = "Título revisado"
    session.commit()

    assert article.updated_at >= first_update


# --- Timestamps --------------------------------------------------------------


def test_datetimes_are_stored_and_returned_in_utc(session: Session) -> None:
    sao_paulo = timezone(timedelta(hours=-3))
    local = datetime(2026, 11, 9, 9, 0, tzinfo=sao_paulo)
    article = make_article(collected_at=local)
    session.add(article)
    session.commit()
    session.expire_all()

    stored = session.get(Article, article.id)
    assert stored is not None
    assert stored.collected_at == local  # mesmo instante
    assert stored.collected_at.utcoffset() == timedelta(0)
    assert stored.collected_at.hour == 12


def test_naive_datetimes_are_rejected(session: Session) -> None:
    session.add(make_article(collected_at=datetime(2026, 11, 9, 12, 0)))

    with pytest.raises(StatementError, match="fuso horário"):
        session.commit()


# --- Sources -----------------------------------------------------------------


def test_article_can_be_found_in_multiple_sources(session: Session) -> None:
    openalex, crossref = make_source("openalex"), make_source("crossref")
    article = make_article(doi="10.1000/abc")
    article.sources = [
        ArticleSource(source=openalex, external_id="W123"),
        ArticleSource(source=crossref, external_id="10.1000/abc"),
    ]
    session.add(article)
    session.commit()

    assert {link.source.name for link in article.sources} == {"openalex", "crossref"}


def test_source_external_id_is_unique_per_source(session: Session) -> None:
    source = make_source()
    session.add_all(
        [
            make_article(sources=[ArticleSource(source=source, external_id="W1")]),
            make_article(sources=[ArticleSource(source=source, external_id="W1")]),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_same_external_id_in_different_sources_is_allowed(session: Session) -> None:
    session.add_all(
        [
            make_article(sources=[ArticleSource(source=make_source("a"), external_id="1")]),
            make_article(sources=[ArticleSource(source=make_source("b"), external_id="1")]),
        ]
    )
    session.commit()


def test_foreign_keys_are_enforced(session: Session) -> None:
    session.add(ArticleSource(article_id=999, source_id=999, external_id="x"))

    with pytest.raises(IntegrityError):
        session.commit()


# --- Categories --------------------------------------------------------------


def test_article_can_belong_to_multiple_categories(session: Session) -> None:
    neuro, bio = make_category("neurociencia"), make_category("ciencias-biologicas")
    article = make_article()
    article.categories = [
        ArticleCategory(
            category=neuro,
            confidence=0.9,
            classification_method=ClassificationMethod.RULE_BASED,
            justification="Termos: sinapse, córtex",
        ),
        ArticleCategory(
            category=bio, confidence=0.6, classification_method=ClassificationMethod.RULE_BASED
        ),
    ]
    session.add(article)
    session.commit()
    session.expire_all()

    stored = session.get(Article, article.id)
    assert stored is not None
    assert {link.category.slug for link in stored.categories} == {
        "neurociencia",
        "ciencias-biologicas",
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_classification_confidence_must_be_between_0_and_1(
    session: Session, confidence: float
) -> None:
    session.add(
        ArticleCategory(
            article=make_article(),
            category=make_category("engenharias"),
            confidence=confidence,
            classification_method=ClassificationMethod.RULE_BASED,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_category_slug_is_unique(session: Session) -> None:
    session.add_all([make_category("x"), Category(name="Outra", slug="x")])

    with pytest.raises(IntegrityError):
        session.commit()


# --- Relevance ---------------------------------------------------------------


def _assessment(article: Article, **overrides: float) -> RelevanceAssessment:
    scores: dict[str, float] = {
        "scientific_relevance": 80,
        "originality": 70,
        "potential_impact": 60,
        "interdisciplinarity": 50,
        "ufabc_interest": 90,
        "final_score": 71.5,
    }
    scores.update(overrides)
    return RelevanceAssessment(article=article, justification={"originality": "..."}, **scores)


def test_relevance_assessment_history_is_preserved(session: Session) -> None:
    article = make_article()
    session.add_all([_assessment(article), _assessment(article, final_score=50)])
    session.commit()

    assert len(article.relevance_assessments) == 2


@pytest.mark.parametrize(
    "field", ["scientific_relevance", "originality", "ufabc_interest", "final_score"]
)
@pytest.mark.parametrize("value", [-1, 101])
def test_relevance_scores_must_be_between_0_and_100(
    session: Session, field: str, value: int
) -> None:
    session.add(_assessment(make_article(), **{field: value}))

    with pytest.raises(IntegrityError):
        session.commit()


# --- Generated content and reviews -------------------------------------------


def test_generated_content_versions_are_unique_per_article(session: Session) -> None:
    article = make_article()
    session.add_all([make_content(article, 1), make_content(article, 1)])

    with pytest.raises(IntegrityError):
        session.commit()


def test_generated_content_history_is_ordered_by_version(session: Session) -> None:
    article = make_article()
    other = make_article(title="Outro")
    session.add_all([make_content(article, 2), make_content(article, 1), make_content(other, 1)])
    session.commit()
    session.expire_all()

    stored = session.get(Article, article.id)
    assert stored is not None
    assert [c.version for c in stored.generated_contents] == [1, 2]


def test_generated_content_version_must_be_positive(session: Session) -> None:
    session.add(make_content(make_article(), 0))

    with pytest.raises(IntegrityError):
        session.commit()


def test_rejected_review_does_not_delete_article(session: Session) -> None:
    article = make_article()
    content = make_content(article, 1)
    session.add(
        EditorialReview(
            article=article,
            generated_content=content,
            status=EditorialStatus.REJECTED,
            reviewer="editor",
            comments="Fora do escopo.",
        )
    )
    session.commit()

    assert session.get(Article, article.id) is not None
    assert article.editorial_reviews[0].status is EditorialStatus.REJECTED
    assert article.editorial_reviews[0].generated_content is content


# --- Editions ----------------------------------------------------------------


def test_edition_defaults_to_draft(session: Session) -> None:
    edition = make_edition()
    session.add(edition)
    session.commit()

    assert edition.status is EditionStatus.DRAFT
    assert edition.published_at is None


def test_edition_number_and_slug_are_unique(session: Session) -> None:
    session.add_all([make_edition(1), make_edition(1, slug="outra")])

    with pytest.raises(IntegrityError):
        session.commit()


def test_edition_period_must_be_ordered(session: Session) -> None:
    session.add(make_edition(start_date=date(2026, 11, 15), end_date=date(2026, 11, 9)))

    with pytest.raises(IntegrityError):
        session.commit()


def test_edition_items_are_ordered_by_position(session: Session) -> None:
    edition = make_edition()
    first, second = make_article(title="A"), make_article(title="B")
    edition.items = [
        NewsletterItem(article=second, position=2, editorial_section="neurociencia"),
        NewsletterItem(article=first, position=1, editorial_section="engenharias"),
    ]
    session.add(edition)
    session.commit()
    session.expire_all()

    stored = session.get(NewsletterEdition, edition.id)
    assert stored is not None
    assert [item.article.title for item in stored.items] == ["A", "B"]


def test_edition_positions_are_unique(session: Session) -> None:
    edition = make_edition()
    edition.items = [
        NewsletterItem(article=make_article(), position=1),
        NewsletterItem(article=make_article(), position=1),
    ]
    session.add(edition)

    with pytest.raises(IntegrityError):
        session.commit()


def test_article_cannot_appear_twice_in_same_edition(session: Session) -> None:
    article = make_article()
    edition = make_edition()
    edition.items = [
        NewsletterItem(article=article, position=1),
        NewsletterItem(article=article, position=2),
    ]
    session.add(edition)

    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_edition_keeps_articles(session: Session) -> None:
    article = make_article()
    edition = make_edition()
    edition.items = [NewsletterItem(article=article, position=1)]
    session.add(edition)
    session.commit()

    session.delete(edition)
    session.commit()

    assert session.scalars(select(NewsletterItem)).all() == []
    assert session.get(Article, article.id) is not None
