"""Publicação automática semanal, sem revisão humana (opt-in, ``AUTO_PUBLISH``).

Substitui a revisão humana por um critério determinístico e conservador:

* só rascunhos **gerados por um modelo de linguagem real** (nunca o ``mock``);
* só rascunhos que **não foram editados à mão** e estão em ``pending_review``;
* só conteúdos cuja verificação é ``PASSED`` no banco **e** cuja revalidação do
  arquivo não produz nenhum erro nem aviso (``WARNING`` e ``FAILED`` ficam de fora);
* a aprovação é registrada pelo mesmo caminho da aprovação humana
  (``editorial sync``), com ``reviewer`` igual a :data:`AUTO_REVIEWER`, mantendo o
  histórico auditável e o vínculo com o hash do texto.

Em seguida monta a edição da semana ISO corrente com os artigos aprovados que ainda
não foram publicados, escreve uma introdução padronizada que declara a ausência de
revisão humana e publica a edição. Sem artigos elegíveis, nada é publicado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import EditionStatus, EditorialStatus, VerificationStatus
from ufabc_science.domain.models import (
    Article,
    GeneratedContent,
    NewsletterEdition,
    NewsletterItem,
    utcnow,
)
from ufabc_science.editorial.approval import latest_approval, sync_editorial
from ufabc_science.editorial.edition import (
    add_article,
    category_names,
    create_edition,
    group_by_section,
    intro_path,
    publish_edition,
    remove_article,
    validate_edition,
)
from ufabc_science.editorial.exceptions import EditionError, PublicationBlockedError
from ufabc_science.editorial.markdown import (
    EDITION_SCHEMA_ID,
    STATUS_DIRS,
    MarkdownFormatError,
    dump_document,
    read_document,
    write_text_atomic,
)
from ufabc_science.editorial.validation import known_category_slugs, validate_document
from ufabc_science.processing.relevance import latest_assessment

logger = logging.getLogger(__name__)

AUTO_REVIEWER = "Publicação automática"
MOCK_PROVIDER = "mock"


@dataclass
class AutoPublishReport:
    approved: list[int] = field(default_factory=list)
    skipped: dict[int, str] = field(default_factory=dict)
    edition_number: int | None = None
    edition_articles: list[int] = field(default_factory=list)
    published: bool = False
    message: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "skipped": {str(k): v for k, v in sorted(self.skipped.items())},
            "edition_number": self.edition_number,
            "edition_articles": self.edition_articles,
            "published": self.published,
            "message": self.message,
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = ["## Publicação automática", ""]
        lines.append(f"- Aprovados automaticamente (PASSED): {len(self.approved)}")
        lines.append(f"- Rascunhos não aprovados: {len(self.skipped)}")
        for article_id, reason in sorted(self.skipped.items()):
            lines.append(f"  - artigo {article_id}: {reason}")
        if self.edition_number is not None:
            lines.append(
                f"- Edição {self.edition_number:03d}: {len(self.edition_articles)} artigo(s)"
            )
        lines.append(f"- Publicada: {'sim' if self.published else 'não'} — {self.message}")
        for error in self.errors:
            lines.append(f"- ERRO: {error}")
        return "\n".join(lines) + "\n"


# --- Aprovação automática -----------------------------------------------------------------


def _eligibility(
    doc: Any,
    session: Session,
    *,
    categories: set[str],
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]] | None,
) -> str | None:
    """Motivo pelo qual o rascunho NÃO pode ser aprovado automaticamente (ou ``None``)."""
    meta = doc.metadata
    if doc.status != EditorialStatus.PENDING_REVIEW.value:
        return f"status {doc.status!r}"
    if doc.manually_edited:
        return "editado manualmente (aguarda revisão humana)"
    if str(meta.get("model_provider") or "") in ("", MOCK_PROVIDER):
        return "gerado pelo provedor mock"
    if meta.get("verification_status") != VerificationStatus.PASSED.value:
        return f"verificação {str(meta.get('verification_status') or '?').upper()}"
    article = session.get(Article, doc.article_id) if isinstance(doc.article_id, int) else None
    if article is None:
        return "artigo inexistente no banco"
    content = session.get(GeneratedContent, meta.get("content_id") or -1)
    latest = article.generated_contents[-1] if article.generated_contents else None
    if content is None or latest is None or content.id != latest.id:
        return "não é a versão mais recente do rascunho"
    if content.verification_status is not VerificationStatus.PASSED:
        return "verificação no banco não é PASSED"
    validation = validate_document(
        doc,
        session,
        known_categories=categories,
        min_abstract_words=min_abstract_words,
        word_limits=word_limits,
        for_approval=True,
    )
    if validation.errors:
        return "revalidação com erro: " + validation.errors[0]
    if validation.warnings:
        return "revalidação com aviso: " + validation.warnings[0]
    return None


def auto_approve(
    session: Session,
    editorial_dir: Path,
    *,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
    report: AutoPublishReport | None = None,
) -> AutoPublishReport:
    """Aprova os rascunhos pendentes elegíveis e sincroniza com o banco."""
    report = report or AutoPublishReport()
    categories = known_category_slugs(session)
    pending_dir = editorial_dir / STATUS_DIRS[EditorialStatus.PENDING_REVIEW]
    paths = sorted(pending_dir.glob("article-*.md")) if pending_dir.is_dir() else []
    marked: list[int] = []
    for path in paths:
        try:
            doc = read_document(path)
        except (MarkdownFormatError, UnicodeDecodeError, OSError) as exc:
            report.errors.append(f"{path.as_posix()}: {exc}")
            continue
        reason = _eligibility(
            doc,
            session,
            categories=categories,
            min_abstract_words=min_abstract_words,
            word_limits=word_limits,
        )
        if reason is not None:
            if isinstance(doc.article_id, int):
                report.skipped[doc.article_id] = reason
            continue
        doc.metadata.update(
            status=EditorialStatus.APPROVED.value,
            reviewer=AUTO_REVIEWER,
            reviewed_at=utcnow().isoformat(timespec="seconds"),
        )
        # Só o front matter muda; o corpo (e seu hash) permanece idêntico.
        write_text_atomic(path, dump_document(doc.metadata, doc.body))
        marked.append(doc.article_id)

    sync = sync_editorial(
        session, editorial_dir, min_abstract_words=min_abstract_words, word_limits=word_limits
    )
    approved_now = {o.article_id for o in sync.outcomes if o.action == "approved"}
    for article_id in marked:
        if article_id in approved_now:
            report.approved.append(article_id)
        else:
            report.skipped[article_id] = "aprovação recusada pela sincronização"
    for outcome in sync.errors:
        if outcome.article_id in marked:
            report.errors.append(f"{outcome.path}: " + "; ".join(outcome.messages))
    return report


# --- Edição automática --------------------------------------------------------------------


def _published_article_ids(session: Session) -> set[int]:
    query = (
        select(NewsletterItem.article_id)
        .join(NewsletterEdition, NewsletterItem.edition_id == NewsletterEdition.id)
        .where(NewsletterEdition.status.in_([EditionStatus.PUBLISHED, EditionStatus.ARCHIVED]))
    )
    return set(session.scalars(query))


def _candidates(session: Session, limit: int) -> list[Article]:
    published = _published_article_ids(session)
    articles = [
        a
        for a in session.scalars(select(Article).order_by(Article.id))
        if a.id not in published and latest_approval(a) is not None
    ]

    def score(article: Article) -> float:
        assessment = latest_assessment(article)
        return assessment.final_score if assessment and assessment.final_score else 0.0

    articles.sort(key=lambda a: (score(a), a.id), reverse=True)
    return articles[:limit]


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def automatic_introduction(session: Session, edition: NewsletterEdition) -> str:
    names = category_names(session)
    sections = [names.get(slug, slug) for slug, _ in group_by_section(list(edition.items))]
    count = len(edition.items)
    if len(sections) > 1:
        areas = ", ".join(sections[:-1]) + " e " + sections[-1]
    else:
        areas = sections[0] if sections else "diversas áreas"
    return (
        f"Nesta edição, reunimos {_plural(count, 'pesquisa recente', 'pesquisas recentes')} "
        f"em {areas}.\n\n"
        "Os resumos foram escritos por inteligência artificial a partir dos dados públicos de "
        "cada estudo e só entraram na edição depois de passar por todas as checagens "
        "automáticas de fidelidade (números, autores, DOI, link e identificação de preprints). "
        "**Não houve revisão humana.** Consulte sempre a pesquisa original pelo link em cada "
        "texto.\n"
    )


def _write_introduction(session: Session, edition: NewsletterEdition, editions_dir: Path) -> None:
    metadata = {
        "schema": EDITION_SCHEMA_ID,
        "edition_number": edition.edition_number,
        "slug": edition.slug,
        "week": edition.week,
        "status": EditorialStatus.APPROVED.value,
        "reviewer": AUTO_REVIEWER,
        "reviewed_at": utcnow().isoformat(timespec="seconds"),
    }
    body = f"# UFABC Science — Edição {edition.edition_number:03d}\n\n" + automatic_introduction(
        session, edition
    )
    write_text_atomic(intro_path(editions_dir, edition), dump_document(metadata, body))


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def auto_publish(
    session: Session,
    *,
    editorial_dir: Path,
    editions_dir: Path,
    today: date,
    max_articles: int = 10,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
) -> AutoPublishReport:
    """Aprova automaticamente, monta a edição da semana e a publica."""
    report = auto_approve(
        session, editorial_dir, min_abstract_words=min_abstract_words, word_limits=word_limits
    )
    week = iso_week(today)
    edition = session.scalars(
        select(NewsletterEdition).where(NewsletterEdition.week == week)
    ).first()
    if edition is not None and edition.status in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED):
        report.edition_number = edition.edition_number
        report.message = f"a edição da semana {week} já foi publicada"
        return report

    candidates = _candidates(session, max_articles)
    if not candidates and (edition is None or not edition.items):
        report.message = "nenhum artigo aprovado e ainda não publicado; nada a publicar"
        return report

    if edition is None:
        edition = create_edition(session, week, editions_dir)
    report.edition_number = edition.edition_number
    kwargs = {
        "editorial_dir": editorial_dir,
        "editions_dir": editions_dir,
        "min_abstract_words": min_abstract_words,
        "word_limits": word_limits,
    }
    in_edition = {item.article_id for item in edition.items}
    for article in candidates:
        if article.id in in_edition:
            continue
        try:
            add_article(session, edition.edition_number, article.id, editorial_dir)
        except EditionError as exc:
            report.errors.append(str(exc))

    # Até duas tentativas: artigos que impedem a publicação são retirados da edição.
    for _ in range(2):
        session.refresh(edition, ["items"])
        if not edition.items:
            break
        _write_introduction(session, edition, editions_dir)
        check = validate_edition(session, edition.edition_number, **kwargs)
        if check.valid:
            break
        bad = {
            int(error.split(":", 1)[0].split()[1])
            for error in check.errors
            if error.startswith("Artigo ")
        }
        report.errors += check.errors
        if not bad:
            break
        for article_id in bad:
            remove_article(session, edition.edition_number, article_id)

    session.refresh(edition, ["items"])
    report.edition_articles = [
        i.article_id for i in sorted(edition.items, key=lambda i: i.position)
    ]
    if not edition.items:
        report.message = "nenhum artigo passou na validação da edição; nada a publicar"
        return report
    try:
        publish_edition(
            session,
            edition.edition_number,
            published_by=AUTO_REVIEWER,
            confirm=True,
            **kwargs,
        )
    except PublicationBlockedError as exc:
        report.errors += [str(exc), *exc.errors]
        report.message = "publicação bloqueada pela validação"
        return report
    report.published = True
    report.message = f"edição {edition.edition_number:03d} ({week}) publicada"
    logger.info("Publicação automática: %s", report.message)
    return report


def is_automatic(edition: NewsletterEdition) -> bool:
    return edition.published_by == AUTO_REVIEWER


__all__ = [
    "AUTO_REVIEWER",
    "AutoPublishReport",
    "auto_approve",
    "auto_publish",
    "automatic_introduction",
    "is_automatic",
]
