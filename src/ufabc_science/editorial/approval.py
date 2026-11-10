"""Sincronização dos arquivos Markdown com o banco e aprovação editorial (Etapa 4, seções 3 e 4).

O estado editorial é controlado pelo front matter (``status``) e validado aqui:

* ``approved`` só é registrado se o arquivo passar na validação de aprovação
  (``FAILED`` bloqueia; ``WARNING`` exige ``warning_justification``);
* a aprovação fica vinculada ao hash do corpo: qualquer alteração posterior
  invalida a aprovação (o arquivo volta a ``pending_review``);
* cada mudança de estado gera um ``EditorialReview`` (histórico preservado),
  com cópia do texto aprovado;
* arquivos são movidos para ``pending/``, ``approved/`` ou ``rejected/``.

Nenhuma aprovação é feita por código automático: a única origem de
``approved`` é um humano editando o arquivo.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ufabc_science.domain.enums import EditorialStatus
from ufabc_science.domain.models import Article, EditorialReview, utcnow
from ufabc_science.editorial.markdown import (
    STATUS_DIRS,
    ArticleDocument,
    MarkdownFormatError,
    dump_document,
    find_article_files,
    read_document,
    safe_child,
    write_text_atomic,
)
from ufabc_science.editorial.validation import (
    EditorialValidationResult,
    known_category_slugs,
    parse_datetime,
    validate_document,
)

logger = logging.getLogger(__name__)


@dataclass
class FileOutcome:
    path: str
    article_id: int | None
    action: str
    messages: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    outcomes: list[FileOutcome] = field(default_factory=list)

    def count(self, action: str) -> int:
        return sum(1 for o in self.outcomes if o.action == action)

    @property
    def errors(self) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.action == "error"]


def latest_review(article: Article) -> EditorialReview | None:
    return article.editorial_reviews[-1] if article.editorial_reviews else None


def latest_approval(article: Article) -> EditorialReview | None:
    review = latest_review(article)
    return review if review is not None and review.status is EditorialStatus.APPROVED else None


def _move(doc: ArticleDocument, editorial_dir: Path, status: EditorialStatus) -> Path:
    assert doc.path is not None
    target = safe_child(editorial_dir / STATUS_DIRS[status], doc.path.name)
    if target.resolve() != doc.path.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.path.replace(target)
        doc.path = target
    return target


def _rewrite_metadata(doc: ArticleDocument, **changes: object) -> None:
    assert doc.path is not None
    doc.metadata.update(changes)
    # Somente o front matter muda; o corpo é preservado byte a byte.
    write_text_atomic(doc.path, dump_document(doc.metadata, doc.body))


def _record(
    session: Session,
    article: Article,
    doc: ArticleDocument,
    status: EditorialStatus,
    *,
    comments: str | None = None,
    snapshot: bool = False,
) -> EditorialReview:
    reviewed_at = parse_datetime(doc.metadata.get("reviewed_at"))
    if reviewed_at is not None and reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
    content_id = doc.metadata.get("content_id")
    review = EditorialReview(
        article=article,
        generated_content_id=content_id if isinstance(content_id, int) else None,
        status=status,
        reviewer=(str(doc.metadata.get("reviewer")) if doc.metadata.get("reviewer") else None),
        comments=comments or (str(doc.metadata.get("editorial_notes") or "") or None),
        warning_justification=str(doc.metadata.get("warning_justification") or "") or None,
        content_hash=doc.current_hash,
        content_snapshot=doc.body if snapshot else None,
        file_path=doc.path.as_posix() if doc.path else None,
        reviewed_at=reviewed_at or utcnow(),
    )
    session.add(review)
    session.flush()
    session.refresh(article, ["editorial_reviews"])
    return review


def sync_editorial(
    session: Session,
    editorial_dir: Path,
    *,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
    dry_run: bool = False,
) -> SyncReport:
    """Lê todos os arquivos editoriais, valida e sincroniza estados com o banco."""
    report = SyncReport()
    categories = known_category_slugs(session)
    documents: dict[int, list[ArticleDocument]] = defaultdict(list)

    for path in find_article_files(editorial_dir):
        try:
            doc = read_document(path)
        except (MarkdownFormatError, UnicodeDecodeError, OSError) as exc:
            report.outcomes.append(FileOutcome(path.as_posix(), None, "error", [str(exc)]))
            continue
        article_id = doc.article_id
        if not isinstance(article_id, int):
            report.outcomes.append(
                FileOutcome(path.as_posix(), None, "error", ["'article_id' ausente ou inválido."])
            )
            continue
        documents[article_id].append(doc)

    for article_id, docs in sorted(documents.items()):
        if len(docs) > 1:
            paths = [d.path.as_posix() for d in docs if d.path]
            for doc in docs:
                report.outcomes.append(
                    FileOutcome(
                        doc.path.as_posix() if doc.path else "",
                        article_id,
                        "error",
                        ["Arquivo duplicado para o mesmo artigo: " + ", ".join(paths)],
                    )
                )
            continue
        report.outcomes.append(
            _sync_one(
                session,
                docs[0],
                editorial_dir,
                categories=categories,
                min_abstract_words=min_abstract_words,
                word_limits=word_limits,
                dry_run=dry_run,
            )
        )
    return report


def _sync_one(
    session: Session,
    doc: ArticleDocument,
    editorial_dir: Path,
    *,
    categories: set[str],
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]] | None,
    dry_run: bool,
) -> FileOutcome:
    assert doc.path is not None
    path = doc.path.as_posix()
    validation: EditorialValidationResult = validate_document(
        doc,
        session,
        known_categories=categories,
        min_abstract_words=min_abstract_words,
        word_limits=word_limits,
    )
    article_id = doc.article_id
    article = session.get(Article, article_id) if isinstance(article_id, int) else None
    if article is None or any("não pertence ao projeto" in e for e in validation.errors):
        return FileOutcome(path, article_id, "error", validation.lines())

    status = (
        EditorialStatus(doc.status) if doc.status in {s.value for s in EditorialStatus} else None
    )
    if status is None:
        return FileOutcome(path, article_id, "error", validation.lines())

    previous = latest_review(article)
    approval = latest_approval(article)
    messages = validation.lines()

    # Alteração de conteúdo após aprovação: invalida até nova revisão.
    if approval is not None and approval.content_hash != doc.current_hash:
        if dry_run:
            return FileOutcome(path, article_id, "would_invalidate", messages)
        note = (
            f"Aprovação de {approval.reviewed_at:%Y-%m-%d %H:%M} UTC invalidada: "
            "conteúdo alterado após a aprovação."
        )
        _record(session, article, doc, EditorialStatus.PENDING_REVIEW, comments=note)
        _rewrite_metadata(doc, status=EditorialStatus.PENDING_REVIEW.value, reviewed_at=None)
        _move(doc, editorial_dir, EditorialStatus.PENDING_REVIEW)
        logger.warning("Artigo %s: %s", article_id, note)
        return FileOutcome(doc.path.as_posix(), article_id, "invalidated", [note, *messages])

    if status is EditorialStatus.APPROVED:
        if approval is not None:
            if not dry_run:
                _move(doc, editorial_dir, status)
            return FileOutcome(doc.path.as_posix(), article_id, "unchanged", messages)
        if not validation.valid:
            # Aprovação bloqueada: o arquivo permanece onde está; nada é registrado.
            return FileOutcome(
                path, article_id, "error", ["Aprovação bloqueada.", *validation.lines()]
            )
        if dry_run:
            return FileOutcome(path, article_id, "would_approve", messages)
        if not doc.metadata.get("reviewed_at"):
            _rewrite_metadata(doc, reviewed_at=utcnow().isoformat(timespec="seconds"))
        _record(session, article, doc, status, snapshot=True)
        _move(doc, editorial_dir, status)
        logger.info("Artigo %s aprovado por %s", article_id, doc.metadata.get("reviewer") or "-")
        return FileOutcome(doc.path.as_posix(), article_id, "approved", messages)

    # pending_review, needs_revision, rejected
    unchanged = (
        previous is not None
        and previous.status is status
        and previous.content_hash == doc.current_hash
    )
    if unchanged:
        if not dry_run:
            _move(doc, editorial_dir, status)
        return FileOutcome(doc.path.as_posix(), article_id, "unchanged", messages)
    if dry_run:
        return FileOutcome(path, article_id, f"would_{status.value}", messages)
    _record(session, article, doc, status)
    _move(doc, editorial_dir, status)
    action = {
        EditorialStatus.PENDING_REVIEW: "registered",
        EditorialStatus.NEEDS_REVISION: "needs_revision",
        EditorialStatus.REJECTED: "rejected",
    }[status]
    return FileOutcome(doc.path.as_posix(), article_id, action, messages)


def validate_files(
    session: Session,
    editorial_dir: Path,
    *,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
) -> list[EditorialValidationResult]:
    """Valida todos os arquivos sem alterar banco ou arquivos."""
    categories = known_category_slugs(session)
    results = []
    seen: dict[int, str] = {}
    for path in find_article_files(editorial_dir):
        try:
            doc = read_document(path)
        except (MarkdownFormatError, UnicodeDecodeError, OSError) as exc:
            results.append(EditorialValidationResult(path=path.as_posix(), errors=[str(exc)]))
            continue
        result = validate_document(
            doc,
            session,
            known_categories=categories,
            min_abstract_words=min_abstract_words,
            word_limits=word_limits,
        )
        if isinstance(doc.article_id, int):
            if doc.article_id in seen:
                result.error(f"Arquivo duplicado para o artigo (também em {seen[doc.article_id]}).")
            seen[doc.article_id] = path.as_posix()
        results.append(result)
    return results
