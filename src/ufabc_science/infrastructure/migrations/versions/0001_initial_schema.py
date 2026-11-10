"""Schema inicial: entidades principais da Etapa 1 (SPECIFICATION.md, seção 7).

Revision ID: 0001
Revises:
Create Date: 2026-11-10 01:50:01.295548+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("journal", sa.String(length=500), nullable=True),
        sa.Column("publisher", sa.String(length=500), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("institutions", sa.JSON(), nullable=False),
        sa.Column(
            "article_type",
            sa.Enum(
                "journal_article",
                "preprint",
                "review",
                "conference_paper",
                "book_chapter",
                "other",
                "unknown",
                name="articletype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "peer_review_status",
            sa.Enum(
                "verified",
                "preprint",
                "unknown",
                name="peerreviewstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("open_access", sa.Boolean(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("raw_data_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint("doi", name=op.f("uq_articles_doi")),
    )
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_articles_canonical_url"), ["canonical_url"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_articles_collected_at"), ["collected_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_articles_external_id"), ["external_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_articles_peer_review_status"), ["peer_review_status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_articles_publication_date"), ["publication_date"], unique=False
        )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", name=op.f("uq_categories_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_table(
        "newsletter_editions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("edition_number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "approved", "published", name="editionstatus", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "edition_number >= 1", name=op.f("ck_newsletter_editions_number_positive")
        ),
        sa.CheckConstraint(
            "end_date >= start_date", name=op.f("ck_newsletter_editions_period_order")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_editions")),
        sa.UniqueConstraint("edition_number", name=op.f("uq_newsletter_editions_edition_number")),
        sa.UniqueConstraint("slug", name=op.f("uq_newsletter_editions_slug")),
    )
    with op.batch_alter_table("newsletter_editions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_newsletter_editions_end_date"), ["end_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_newsletter_editions_published_at"), ["published_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_newsletter_editions_start_date"), ["start_date"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_newsletter_editions_status"), ["status"], unique=False)

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum("api", "feed", name="sourcetype", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_sources_name")),
    )
    op.create_table(
        "article_categories",
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "classification_method",
            sa.Enum(
                "keyword",
                "source_metadata",
                "ai",
                "manual",
                name="classificationmethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_article_categories_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"], ["articles.id"], name=op.f("fk_article_categories_article_id_articles")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_article_categories_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("article_id", "category_id", name=op.f("pk_article_categories")),
    )
    with op.batch_alter_table("article_categories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_article_categories_category_id"), ["category_id"], unique=False
        )

    op.create_table(
        "article_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.String(length=2048), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"], ["articles.id"], name=op.f("fk_article_sources_article_id_articles")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_article_sources_source_id_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_sources")),
        sa.UniqueConstraint(
            "source_id", "external_id", name=op.f("uq_article_sources_source_id_external_id")
        ),
    )
    with op.batch_alter_table("article_sources", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_article_sources_article_id"), ["article_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_article_sources_collected_at"), ["collected_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_article_sources_external_id"), ["external_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_article_sources_source_id"), ["source_id"], unique=False
        )

    op.create_table(
        "generated_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("research_question", sa.Text(), nullable=True),
        sa.Column("methodology", sa.Text(), nullable=True),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("relevance", sa.Text(), nullable=True),
        sa.Column("complete_content", sa.Text(), nullable=True),
        sa.Column("model_provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_generated_contents_version_positive")),
        sa.ForeignKeyConstraint(
            ["article_id"], ["articles.id"], name=op.f("fk_generated_contents_article_id_articles")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_contents")),
        sa.UniqueConstraint(
            "article_id", "version", name=op.f("uq_generated_contents_article_id_version")
        ),
    )
    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_generated_contents_article_id"), ["article_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_generated_contents_generated_at"), ["generated_at"], unique=False
        )

    op.create_table(
        "newsletter_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("edition_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("editorial_section", sa.String(length=100), nullable=True),
        sa.CheckConstraint("position >= 1", name=op.f("ck_newsletter_items_position_positive")),
        sa.ForeignKeyConstraint(
            ["article_id"], ["articles.id"], name=op.f("fk_newsletter_items_article_id_articles")
        ),
        sa.ForeignKeyConstraint(
            ["edition_id"],
            ["newsletter_editions.id"],
            name=op.f("fk_newsletter_items_edition_id_newsletter_editions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_items")),
        sa.UniqueConstraint(
            "edition_id", "article_id", name=op.f("uq_newsletter_items_edition_id_article_id")
        ),
        sa.UniqueConstraint(
            "edition_id", "position", name=op.f("uq_newsletter_items_edition_id_position")
        ),
    )
    with op.batch_alter_table("newsletter_items", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_newsletter_items_article_id"), ["article_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_newsletter_items_edition_id"), ["edition_id"], unique=False
        )

    op.create_table(
        "relevance_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("scientific_relevance", sa.Integer(), nullable=False),
        sa.Column("originality", sa.Integer(), nullable=False),
        sa.Column("potential_impact", sa.Integer(), nullable=False),
        sa.Column("interdisciplinarity", sa.Integer(), nullable=False),
        sa.Column("ufabc_interest", sa.Integer(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("justification", sa.JSON(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "final_score >= 0 AND final_score <= 100",
            name=op.f("ck_relevance_assessments_final_score_range"),
        ),
        sa.CheckConstraint(
            "interdisciplinarity >= 0 AND interdisciplinarity <= 100",
            name=op.f("ck_relevance_assessments_interdisciplinarity_range"),
        ),
        sa.CheckConstraint(
            "originality >= 0 AND originality <= 100",
            name=op.f("ck_relevance_assessments_originality_range"),
        ),
        sa.CheckConstraint(
            "potential_impact >= 0 AND potential_impact <= 100",
            name=op.f("ck_relevance_assessments_potential_impact_range"),
        ),
        sa.CheckConstraint(
            "scientific_relevance >= 0 AND scientific_relevance <= 100",
            name=op.f("ck_relevance_assessments_scientific_relevance_range"),
        ),
        sa.CheckConstraint(
            "ufabc_interest >= 0 AND ufabc_interest <= 100",
            name=op.f("ck_relevance_assessments_ufabc_interest_range"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_relevance_assessments_article_id_articles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relevance_assessments")),
    )
    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_relevance_assessments_article_id"), ["article_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_relevance_assessments_assessed_at"), ["assessed_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_relevance_assessments_final_score"), ["final_score"], unique=False
        )

    op.create_table(
        "editorial_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("generated_content_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending_review",
                "approved",
                "rejected",
                name="editorialstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"], ["articles.id"], name=op.f("fk_editorial_reviews_article_id_articles")
        ),
        sa.ForeignKeyConstraint(
            ["generated_content_id"],
            ["generated_contents.id"],
            name=op.f("fk_editorial_reviews_generated_content_id_generated_contents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editorial_reviews")),
    )
    with op.batch_alter_table("editorial_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_editorial_reviews_article_id"), ["article_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_editorial_reviews_generated_content_id"),
            ["generated_content_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_editorial_reviews_reviewed_at"), ["reviewed_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_editorial_reviews_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("editorial_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_editorial_reviews_status"))
        batch_op.drop_index(batch_op.f("ix_editorial_reviews_reviewed_at"))
        batch_op.drop_index(batch_op.f("ix_editorial_reviews_generated_content_id"))
        batch_op.drop_index(batch_op.f("ix_editorial_reviews_article_id"))

    op.drop_table("editorial_reviews")
    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_relevance_assessments_final_score"))
        batch_op.drop_index(batch_op.f("ix_relevance_assessments_assessed_at"))
        batch_op.drop_index(batch_op.f("ix_relevance_assessments_article_id"))

    op.drop_table("relevance_assessments")
    with op.batch_alter_table("newsletter_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_newsletter_items_edition_id"))
        batch_op.drop_index(batch_op.f("ix_newsletter_items_article_id"))

    op.drop_table("newsletter_items")
    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_generated_contents_generated_at"))
        batch_op.drop_index(batch_op.f("ix_generated_contents_article_id"))

    op.drop_table("generated_contents")
    with op.batch_alter_table("article_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_article_sources_source_id"))
        batch_op.drop_index(batch_op.f("ix_article_sources_external_id"))
        batch_op.drop_index(batch_op.f("ix_article_sources_collected_at"))
        batch_op.drop_index(batch_op.f("ix_article_sources_article_id"))

    op.drop_table("article_sources")
    with op.batch_alter_table("article_categories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_article_categories_category_id"))

    op.drop_table("article_categories")
    op.drop_table("sources")
    with op.batch_alter_table("newsletter_editions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_newsletter_editions_status"))
        batch_op.drop_index(batch_op.f("ix_newsletter_editions_start_date"))
        batch_op.drop_index(batch_op.f("ix_newsletter_editions_published_at"))
        batch_op.drop_index(batch_op.f("ix_newsletter_editions_end_date"))

    op.drop_table("newsletter_editions")
    op.drop_table("categories")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_articles_publication_date"))
        batch_op.drop_index(batch_op.f("ix_articles_peer_review_status"))
        batch_op.drop_index(batch_op.f("ix_articles_external_id"))
        batch_op.drop_index(batch_op.f("ix_articles_collected_at"))
        batch_op.drop_index(batch_op.f("ix_articles_canonical_url"))

    op.drop_table("articles")
