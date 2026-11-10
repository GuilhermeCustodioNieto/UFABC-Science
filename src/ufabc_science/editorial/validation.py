"""Validação editorial independente (Etapa 4, seção 5).

Separa **erros** (impedem aprovação/publicação) de **avisos** (exigem atenção)
e sempre indica o arquivo correspondente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ufabc_science.domain.enums import EditorialStatus, PeerReviewStatus, VerificationStatus
from ufabc_science.domain.models import Article, GeneratedContent
from ufabc_science.editorial.markdown import (
    ARTICLE_FILE,
    SCHEMA_ID,
    ArticleDocument,
)
from ufabc_science.intelligence.schemas import SECTION_FIELDS, SECTION_TITLES
from ufabc_science.intelligence.verification import (
    ContentUnderReview,
    VerificationReport,
    verify_content,
)
from ufabc_science.processing.classification import canonical_category
from ufabc_science.processing.normalization import is_http_url, is_valid_doi, normalize_doi

VALID_STATUSES = {status.value for status in EditorialStatus}


@dataclass
class EditorialValidationResult:
    path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verification: VerificationReport | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: EditorialValidationResult) -> None:
        self.errors += other.errors
        self.warnings += other.warnings

    def lines(self) -> list[str]:
        prefix = f"{self.path}: " if self.path else ""
        return [f"{prefix}ERRO: {e}" for e in self.errors] + [
            f"{prefix}AVISO: {w}" for w in self.warnings
        ]


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def document_content(doc: ArticleDocument) -> ContentUnderReview:
    """Texto editado pelo editor, no formato aceito pela verificação."""
    return ContentUnderReview(
        headline=doc.headline,
        original_title=str(doc.metadata.get("original_title") or ""),
        sections={name: doc.sections.get(name, "") for name in SECTION_FIELDS},
        reference=doc.reference,
        source_url=str(doc.metadata.get("source_url") or doc.source_link or ""),
    )


def validate_document(
    doc: ArticleDocument,
    session: Session,
    *,
    known_categories: set[str],
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
    for_approval: bool | None = None,
) -> EditorialValidationResult:
    """Valida front matter, estrutura, consistência com o banco e fidelidade do texto.

    ``for_approval`` aplica as regras de aprovação (padrão: quando ``status: approved``).
    """
    meta = doc.metadata
    result = EditorialValidationResult(path=doc.path.as_posix() if doc.path else None)
    approving = for_approval if for_approval is not None else doc.status == "approved"

    # Front matter e pertencimento ao projeto.
    if meta.get("schema") != SCHEMA_ID:
        result.error(f"Front matter sem 'schema: {SCHEMA_ID}': arquivo não pertence ao projeto.")
    article_id = meta.get("article_id")
    if not isinstance(article_id, int) or isinstance(article_id, bool) or article_id < 1:
        result.error("'article_id' ausente ou não é inteiro positivo.")
        return result
    if doc.path is not None:
        match = ARTICLE_FILE.match(doc.path.name)
        if not match or int(match.group("id")) != article_id:
            result.error(f"Nome do arquivo não corresponde a article_id={article_id}.")
    status = meta.get("status")
    if status not in VALID_STATUSES:
        result.error(f"Status inválido: {status!r}. Use: {', '.join(sorted(VALID_STATUSES))}.")
        return result
    # Arquivo fora da pasta do seu status é o caso normal antes do sync (que o move).

    article = session.get(Article, article_id)
    if article is None:
        result.error(f"Artigo {article_id} não existe no banco.")
        return result

    content_id = meta.get("content_id")
    content = session.get(GeneratedContent, content_id) if isinstance(content_id, int) else None
    if content is None or content.article_id != article_id:
        result.error("'content_id' ausente ou não pertence ao artigo.")

    # Categorias.
    categories = meta.get("categories")
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        result.error("'categories' deve ser uma lista de identificadores.")
        categories = []
    canonical = [canonical_category(c) for c in categories]
    unknown = sorted(set(canonical) - known_categories)
    if unknown:
        result.error(f"Categorias desconhecidas: {', '.join(unknown)}.")
    if approving and not canonical:
        result.error("Artigo aprovado precisa de ao menos uma categoria.")
    primary = meta.get("primary_category")
    if primary and canonical_category(str(primary)) not in canonical:
        result.error("'primary_category' deve estar entre as categorias do artigo.")

    # Fonte, DOI e revisão por pares.
    source_url = meta.get("source_url")
    if not isinstance(source_url, str) or not is_http_url(source_url):
        result.error("'source_url' ausente ou não é uma URL http(s) válida.")
    elif doc.source_link and doc.source_link != source_url:
        result.error("O link 'Consultar pesquisa original' difere de 'source_url'.")
    if doc.source_link is None:
        result.error("Link 'Consultar pesquisa original' ausente na seção Referência.")
    doi = meta.get("doi")
    if doi:
        if not isinstance(doi, str) or not is_valid_doi(normalize_doi(doi)):
            result.error(f"DOI mal formatado: {doi!r}.")
        elif normalize_doi(doi) != article.doi:
            result.error("DOI do arquivo difere do registro coletado.")
    elif article.doi:
        result.error("DOI do registro removido do front matter.")
    peer = meta.get("peer_review_status")
    if peer != article.peer_review_status.value:
        result.error(
            f"peer_review_status '{peer}' difere do registro "
            f"('{article.peer_review_status.value}')."
        )

    # Estrutura do corpo.
    if not doc.headline:
        result.error("Título editorial (# ...) ausente.")
    missing = [SECTION_TITLES[n] for n in SECTION_FIELDS if not doc.sections.get(n, "").strip()]
    if missing:
        result.error("Seções ausentes ou vazias: " + ", ".join(missing) + ".")
    if not doc.reference.strip():
        result.error("Referência bibliográfica ausente.")
    for extra in doc.extra_sections:
        result.warn(f"Seção não reconhecida será ignorada na publicação: '{extra}'.")

    # Verificação científica sobre o texto atual (inclusive edições manuais).
    if not result.errors:
        report = verify_content(
            article,
            document_content(doc),
            min_abstract_words=min_abstract_words,
            word_limits=word_limits,
        )
        result.verification = report
        for message in report.failures:
            result.error(f"Verificação FAILED: {message}")
        warnings = report.warnings
        for message in warnings:
            result.warn(f"Verificação WARNING: {message}")
        if approving and warnings and not str(meta.get("warning_justification") or "").strip():
            result.error(
                "Conteúdo com avisos (WARNING) exige 'warning_justification' para aprovação."
            )
        if (
            approving
            and article.peer_review_status is PeerReviewStatus.PREPRINT
            and report.status is VerificationStatus.FAILED
        ):
            result.error("Preprint precisa estar identificado no texto antes da aprovação.")

    reviewed_at = meta.get("reviewed_at")
    if reviewed_at not in (None, "") and parse_datetime(reviewed_at) is None:
        result.error("'reviewed_at' deve estar no formato ISO 8601 (ex.: 2026-11-10T14:00:00Z).")
    return result


def known_category_slugs(session: Session) -> set[str]:
    from sqlalchemy import select

    from ufabc_science.domain.models import Category

    return set(session.scalars(select(Category.slug).where(Category.active)))


def describe_path(path: Path | None) -> str:
    return path.as_posix() if path else "(sem arquivo)"
