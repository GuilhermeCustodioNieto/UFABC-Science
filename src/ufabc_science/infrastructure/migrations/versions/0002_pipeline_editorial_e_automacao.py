"""Etapas 2 a 5: deduplicação, inteligência editorial, fluxo editorial e automação.

Colunas NOT NULL recebem ``server_default`` para que bancos existentes possam ser
migrados. Também converte valores de enum renomeados (dados textuais):
``classification_method`` keyword/source_metadata -> rule_based, ai -> ai_assisted;
``newsletter_editions.status`` approved -> ready.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10 02:14:25.848328+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "success",
                "partial_success",
                "failed",
                name="runstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
    )
    with op.batch_alter_table("pipeline_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pipeline_runs_started_at"), ["started_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_pipeline_runs_status"), ["status"], unique=False)

    with op.batch_alter_table("article_categories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_uncertain", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("possible_duplicate_of_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("duplicate_reason", sa.String(length=255), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_articles_possible_duplicate_of_id"),
            ["possible_duplicate_of_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_articles_possible_duplicate_of_id_articles"),
            "articles",
            ["possible_duplicate_of_id"],
            ["id"],
        )

    with op.batch_alter_table("editorial_reviews", schema=None) as batch_op:
        batch_op.add_column(sa.Column("warning_justification", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("content_snapshot", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("file_path", sa.String(length=1024), nullable=True))

    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("original_title", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reference", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(
            sa.Column("uncertainty_notes", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("study_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("input_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("usage", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.Enum(
                    "passed",
                    "warning",
                    "failed",
                    name="verificationstatus",
                    native_enum=False,
                    length=32,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("verification_report", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_generated_contents_input_hash"), ["input_hash"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_generated_contents_verification_status"),
            ["verification_status"],
            unique=False,
        )

    with op.batch_alter_table("newsletter_editions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("week", sa.String(length=10), nullable=True))
        batch_op.add_column(
            sa.Column(
                "introduction_status",
                sa.Enum(
                    "pending_review",
                    "approved",
                    "rejected",
                    "needs_revision",
                    name="editorialstatus",
                    native_enum=False,
                    length=32,
                ),
                nullable=False,
                server_default="pending_review",
            )
        )
        batch_op.add_column(
            sa.Column("introduction_reviewer", sa.String(length=200), nullable=True)
        )
        batch_op.add_column(
            sa.Column("introduction_reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("published_by", sa.String(length=200), nullable=True))
        batch_op.create_unique_constraint(batch_op.f("uq_newsletter_editions_week"), ["week"])

    with op.batch_alter_table("newsletter_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("review_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_newsletter_items_review_id"), ["review_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_newsletter_items_review_id_editorial_reviews"),
            "editorial_reviews",
            ["review_id"],
            ["id"],
        )

    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "method_version",
                sa.String(length=50),
                nullable=False,
                server_default="heuristic-v1",
            )
        )

    op.execute(
        "UPDATE article_categories SET classification_method = 'rule_based' "
        "WHERE classification_method IN ('keyword', 'source_metadata')"
    )
    op.execute(
        "UPDATE article_categories SET classification_method = 'ai_assisted' "
        "WHERE classification_method = 'ai'"
    )
    op.execute("UPDATE newsletter_editions SET status = 'ready' WHERE status = 'approved'")


def downgrade() -> None:
    op.execute(
        "UPDATE newsletter_editions SET status = 'draft' WHERE status IN ('ready', 'archived')"
    )
    op.execute(
        "UPDATE article_categories SET classification_method = 'keyword' "
        "WHERE classification_method = 'rule_based'"
    )
    op.execute(
        "UPDATE article_categories SET classification_method = 'ai' "
        "WHERE classification_method = 'ai_assisted'"
    )
    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.drop_column("method_version")

    with op.batch_alter_table("newsletter_items", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_newsletter_items_review_id_editorial_reviews"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_newsletter_items_review_id"))
        batch_op.drop_column("review_id")

    with op.batch_alter_table("newsletter_editions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_newsletter_editions_week"), type_="unique")
        batch_op.drop_column("published_by")
        batch_op.drop_column("introduction_reviewed_at")
        batch_op.drop_column("introduction_reviewer")
        batch_op.drop_column("introduction_status")
        batch_op.drop_column("week")

    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_generated_contents_verification_status"))
        batch_op.drop_index(batch_op.f("ix_generated_contents_input_hash"))
        batch_op.drop_column("verified_at")
        batch_op.drop_column("verification_report")
        batch_op.drop_column("verification_status")
        batch_op.drop_column("usage")
        batch_op.drop_column("input_hash")
        batch_op.drop_column("study_type")
        batch_op.drop_column("uncertainty_notes")
        batch_op.drop_column("source_url")
        batch_op.drop_column("reference")
        batch_op.drop_column("original_title")

    with op.batch_alter_table("editorial_reviews", schema=None) as batch_op:
        batch_op.drop_column("file_path")
        batch_op.drop_column("content_snapshot")
        batch_op.drop_column("content_hash")
        batch_op.drop_column("warning_justification")

    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_articles_possible_duplicate_of_id_articles"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_articles_possible_duplicate_of_id"))
        batch_op.drop_column("duplicate_reason")
        batch_op.drop_column("possible_duplicate_of_id")
        batch_op.drop_column("keywords")

    with op.batch_alter_table("article_categories", schema=None) as batch_op:
        batch_op.drop_column("is_uncertain")

    with op.batch_alter_table("pipeline_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_status"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_started_at"))

    op.drop_table("pipeline_runs")
