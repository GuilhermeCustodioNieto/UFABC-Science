"""Curadoria editorial: critérios de curiosidade e evidências, decisão justificada e nova
estrutura das matérias (subtítulo, descoberta, como funciona, por que importa).

Todas as colunas novas aceitam nulo: avaliações e conteúdos antigos continuam válidos e
são exibidos no formato antigo. As editorias novas são criadas e as antigas desativadas
por ``seed_categories`` (``init-db``), não aqui.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("curiosity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("evidence_quality", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("decision_reasons", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("rejection_flags", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("central_discovery", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("evidence_level", sa.String(length=40), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_relevance_assessments_decision"), ["decision"], unique=False
        )

    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subtitle", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("discovery", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("how_it_works", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("why_it_matters", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("editorial_review", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("generated_contents", schema=None) as batch_op:
        for column in (
            "editorial_review",
            "why_it_matters",
            "how_it_works",
            "discovery",
            "subtitle",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("relevance_assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_relevance_assessments_decision"))
        for column in (
            "evidence_level",
            "central_discovery",
            "rejection_flags",
            "decision_reasons",
            "decision",
            "evidence_quality",
            "curiosity",
        ):
            batch_op.drop_column(column)
