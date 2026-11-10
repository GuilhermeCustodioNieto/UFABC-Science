"""Enumerações do domínio.

Os valores são persistidos como texto (``native_enum=False``) para manter o
schema portável entre SQLite e PostgreSQL. Mudar o *valor* de um membro exige
migração de dados; adicionar membros novos não exige.
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """Equivalente a ``enum.StrEnum`` (Python 3.11+) compatível com 3.10."""

    def __str__(self) -> str:
        return self.value


class SourceType(_StrEnum):
    """Natureza técnica de uma fonte de dados."""

    API = "api"
    FEED = "feed"


class ArticleType(_StrEnum):
    """Tipo de publicação, conforme informado pela fonte ou inferido."""

    JOURNAL_ARTICLE = "journal_article"
    PREPRINT = "preprint"
    REVIEW = "review"
    CONFERENCE_PAPER = "conference_paper"
    BOOK_CHAPTER = "book_chapter"
    OTHER = "other"
    UNKNOWN = "unknown"


class PeerReviewStatus(_StrEnum):
    """Situação de revisão por pares.

    ``VERIFIED`` só deve ser atribuído quando houver evidência de publicação
    revisada por pares (ex.: registro em periódico via Crossref). Na ausência de
    evidência, o valor correto é ``UNKNOWN`` — nunca presumir revisão.
    """

    VERIFIED = "verified"
    PREPRINT = "preprint"
    UNKNOWN = "unknown"


class ClassificationMethod(_StrEnum):
    """Método que atribuiu uma categoria a um artigo (Etapa 3, seção 3.3)."""

    RULE_BASED = "rule_based"
    AI_ASSISTED = "ai_assisted"
    MANUAL = "manual"


class EditorialStatus(_StrEnum):
    """Estado editorial de um artigo/rascunho (espelha o front matter Markdown)."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class EditionStatus(_StrEnum):
    """Ciclo de vida de uma edição semanal."""

    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class VerificationStatus(_StrEnum):
    """Resultado da verificação determinística de um conteúdo gerado."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class Priority(_StrEnum):
    """Faixa de prioridade editorial derivada da pontuação (configurável)."""

    VERY_HIGH = "muito_alta"
    HIGH = "alta"
    MODERATE = "moderada"
    LOW = "baixa"


class RunStatus(_StrEnum):
    """Estado de uma execução do pipeline (Etapa 5)."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
