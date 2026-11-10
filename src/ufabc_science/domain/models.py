"""Modelos ORM (SQLAlchemy 2.x) das entidades principais.

Regras gerais (SPECIFICATION.md, seção 7.11):

* chaves estrangeiras e índices em DOI, datas, status e identificadores externos;
* timestamps sempre em UTC (``UTCDateTime`` rejeita ``datetime`` sem fuso);
* artigos nunca são removidos em cascata por rejeição editorial;
* conteúdos gerados são versionados (``article_id`` + ``version`` únicos).

Somente tipos genéricos do SQLAlchemy são usados, para que o mesmo modelo
funcione em SQLite e PostgreSQL.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from ufabc_science.domain.enums import (
    ArticleType,
    ClassificationMethod,
    EditionStatus,
    EditorialStatus,
    PeerReviewStatus,
    RunStatus,
    SourceType,
    VerificationStatus,
)

# Convenção de nomes explícita: necessária para que o Alembic consiga alterar e
# remover constraints de forma determinística (inclusive no modo batch do SQLite).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Instante atual em UTC, com fuso horário."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime`` que armazena e devolve sempre ``datetime`` em UTC com fuso.

    O SQLite não guarda fuso horário; por isso a conversão é feita aqui, de
    forma independente do banco. Valores sem fuso são rejeitados para evitar
    ambiguidade entre horário local e UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetimes devem possuir fuso horário (use UTC).")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def enum_type(enum_cls: type[PyEnum]) -> SAEnum:
    """Enum persistido como texto (``VARCHAR``), usando o *valor* do membro."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Source(Base):
    """Fonte de dados científicos (OpenAlex, PubMed, arXiv, Crossref...)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    base_url: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[SourceType] = mapped_column(enum_type(SourceType))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    article_links: Mapped[list[ArticleSource]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"Source(id={self.id!r}, name={self.name!r})"


class Article(Base):
    """Artigo ou pesquisa científica.

    ``doi`` deve ser armazenado já normalizado (minúsculas, sem prefixo de URL)
    e é único quando presente. ``external_id`` guarda o identificador externo
    principal (``<fonte>:<id>``); os identificadores de cada fonte ficam em
    ``ArticleSource``.
    """

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(255), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    publication_date: Mapped[date | None] = mapped_column(Date, index=True)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    journal: Mapped[str | None] = mapped_column(String(500))
    publisher: Mapped[str | None] = mapped_column(String(500))
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    institutions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Palavras-chave, conceitos e categorias informados pelas fontes (classificação).
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    article_type: Mapped[ArticleType] = mapped_column(
        enum_type(ArticleType), default=ArticleType.UNKNOWN
    )
    peer_review_status: Mapped[PeerReviewStatus] = mapped_column(
        enum_type(PeerReviewStatus), default=PeerReviewStatus.UNKNOWN, index=True
    )
    open_access: Mapped[bool | None] = mapped_column(Boolean)
    language: Mapped[str | None] = mapped_column(String(16))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_data_path: Mapped[str | None] = mapped_column(String(1024))
    # Possível duplicata detectada por similaridade de título (seção 8.1): o registro é
    # mantido e sinalizado para análise humana, nunca mesclado automaticamente.
    possible_duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id"), index=True
    )
    duplicate_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list[ArticleSource]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    categories: Mapped[list[ArticleCategory]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    relevance_assessments: Mapped[list[RelevanceAssessment]] = relationship(
        back_populates="article", order_by="RelevanceAssessment.id"
    )
    generated_contents: Mapped[list[GeneratedContent]] = relationship(
        back_populates="article", order_by="GeneratedContent.version"
    )
    editorial_reviews: Mapped[list[EditorialReview]] = relationship(
        back_populates="article", order_by="EditorialReview.id"
    )

    def __repr__(self) -> str:
        return f"Article(id={self.id!r}, doi={self.doi!r}, title={self.title[:40]!r})"


class ArticleSource(Base):
    """Registro de que um artigo foi encontrado em determinada fonte."""

    __tablename__ = "article_sources"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    original_url: Mapped[str | None] = mapped_column(String(2048))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    article: Mapped[Article] = relationship(back_populates="sources")
    source: Mapped[Source] = relationship(back_populates="article_links")


class Category(Base):
    """Editoria (Neurociência, Computação e Tecnologia, ...)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    article_links: Mapped[list[ArticleCategory]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"Category(slug={self.slug!r})"


class ArticleCategory(Base):
    """Associação N:N artigo-categoria com confiança, método e justificativa."""

    __tablename__ = "article_categories"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), primary_key=True, index=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        enum_type(ClassificationMethod)
    )
    justification: Mapped[str | None] = mapped_column(Text)
    # Confiança abaixo do limiar de certeza: exige atenção do editor.
    is_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    classified_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    article: Mapped[Article] = relationship(back_populates="categories")
    category: Mapped[Category] = relationship(back_populates="article_links")


_SCORE_CRITERIA = (
    "scientific_relevance",
    "originality",
    "potential_impact",
    "interdisciplinarity",
    "ufabc_interest",
    "final_score",
)


class RelevanceAssessment(Base):
    """Avaliação de prioridade editorial (0 a 100). Histórico preservado."""

    __tablename__ = "relevance_assessments"
    __table_args__ = tuple(
        CheckConstraint(f"{col} >= 0 AND {col} <= 100", name=f"{col}_range")
        for col in _SCORE_CRITERIA
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    scientific_relevance: Mapped[int] = mapped_column(Integer)
    originality: Mapped[int] = mapped_column(Integer)
    potential_impact: Mapped[int] = mapped_column(Integer)
    interdisciplinarity: Mapped[int] = mapped_column(Integer)
    ufabc_interest: Mapped[int] = mapped_column(Integer)
    final_score: Mapped[float] = mapped_column(Float, index=True)
    # Uma justificativa por critério: {"scientific_relevance": "...", ...}
    justification: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    method_version: Mapped[str] = mapped_column(String(50), default="heuristic-v1")
    assessed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    article: Mapped[Article] = relationship(back_populates="relevance_assessments")


class GeneratedContent(Base):
    """Rascunho gerado por IA. Cada nova geração cria uma nova versão."""

    __tablename__ = "generated_contents"
    __table_args__ = (
        UniqueConstraint("article_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    headline: Mapped[str | None] = mapped_column(Text)
    original_title: Mapped[str | None] = mapped_column(Text)
    introduction: Mapped[str | None] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    research_question: Mapped[str | None] = mapped_column(Text)
    methodology: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    relevance: Mapped[str | None] = mapped_column(Text)
    complete_content: Mapped[str | None] = mapped_column(Text)
    # Referência e link são montados pelo sistema a partir dos metadados, nunca pela IA.
    reference: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    uncertainty_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    study_type: Mapped[str | None] = mapped_column(String(50))
    model_provider: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(50))
    # SHA-256 dos dados de entrada + versão do prompt: evita regenerar sem necessidade.
    input_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[VerificationStatus | None] = mapped_column(
        enum_type(VerificationStatus), index=True
    )
    verification_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    article: Mapped[Article] = relationship(back_populates="generated_contents")


class EditorialReview(Base):
    """Decisão editorial humana sobre um artigo (histórico preservado)."""

    __tablename__ = "editorial_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    # Versão do rascunho que foi revisada (opcional): vincula a aprovação ao texto.
    generated_content_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_contents.id"), index=True
    )
    status: Mapped[EditorialStatus] = mapped_column(enum_type(EditorialStatus), index=True)
    reviewer: Mapped[str | None] = mapped_column(String(200))
    comments: Mapped[str | None] = mapped_column(Text)
    # Justificativa obrigatória para aprovar conteúdo com verificação WARNING.
    warning_justification: Mapped[str | None] = mapped_column(Text)
    # SHA-256 do corpo Markdown revisado e cópia do texto aprovado (preserva versões).
    content_hash: Mapped[str | None] = mapped_column(String(64))
    content_snapshot: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(1024))
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    article: Mapped[Article] = relationship(back_populates="editorial_reviews")
    generated_content: Mapped[GeneratedContent | None] = relationship()


class NewsletterEdition(Base):
    """Edição semanal da newsletter."""

    __tablename__ = "newsletter_editions"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="period_order"),
        CheckConstraint("edition_number >= 1", name="number_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    edition_number: Mapped[int] = mapped_column(Integer, unique=True)
    # Semana ISO de referência (ex.: "2026-W46"); impede duas edições para a mesma semana.
    week: Mapped[str | None] = mapped_column(String(10), unique=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[EditionStatus] = mapped_column(
        enum_type(EditionStatus), default=EditionStatus.DRAFT, index=True
    )
    introduction: Mapped[str | None] = mapped_column(Text)
    introduction_status: Mapped[EditorialStatus] = mapped_column(
        enum_type(EditorialStatus), default=EditorialStatus.PENDING_REVIEW
    )
    introduction_reviewer: Mapped[str | None] = mapped_column(String(200))
    introduction_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    published_by: Mapped[str | None] = mapped_column(String(200))

    items: Mapped[list[NewsletterItem]] = relationship(
        back_populates="edition",
        cascade="all, delete-orphan",
        order_by="NewsletterItem.position",
    )


class NewsletterItem(Base):
    """Artigo selecionado para uma edição, com posição e seção editorial."""

    __tablename__ = "newsletter_items"
    __table_args__ = (
        UniqueConstraint("edition_id", "position"),
        UniqueConstraint("edition_id", "article_id"),
        CheckConstraint("position >= 1", name="position_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("newsletter_editions.id"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    editorial_section: Mapped[str | None] = mapped_column(String(100))
    # Revisão aprovada fixada no momento da publicação: o site publicado usa este texto.
    review_id: Mapped[int | None] = mapped_column(ForeignKey("editorial_reviews.id"), index=True)

    edition: Mapped[NewsletterEdition] = relationship(back_populates="items")
    article: Mapped[Article] = relationship()
    review: Mapped[EditorialReview | None] = relationship()


class PipelineRun(Base):
    """Registro de uma execução do pipeline automatizado (Etapa 5)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(50), default="local")
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    messages: Mapped[list[str]] = mapped_column(JSON, default=list)


__all__ = [
    "NAMING_CONVENTION",
    "Article",
    "ArticleCategory",
    "ArticleSource",
    "Base",
    "Category",
    "EditorialReview",
    "GeneratedContent",
    "NewsletterEdition",
    "NewsletterItem",
    "PipelineRun",
    "RelevanceAssessment",
    "Source",
    "UTCDateTime",
    "utcnow",
]
