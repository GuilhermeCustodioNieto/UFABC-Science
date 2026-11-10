"""Edições semanais (SPECIFICATION.md, seção 13.3; Etapa 4, seção 6).

Estados: ``DRAFT`` → (validação) → ``READY`` → (publicação explícita) →
``PUBLISHED`` → (opcional) ``ARCHIVED``. Qualquer alteração na seleção de uma
edição ``READY`` a devolve para ``DRAFT``. Edições publicadas são imutáveis.

A introdução editorial fica em ``editions/drafts/<slug>.md`` e também exige
aprovação humana (``status: approved`` no front matter).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import EditionStatus, EditorialStatus, VerificationStatus
from ufabc_science.domain.models import (
    Article,
    Category,
    GeneratedContent,
    NewsletterEdition,
    NewsletterItem,
    utcnow,
)
from ufabc_science.domain.schemas import DEFAULT_CATEGORIES
from ufabc_science.editorial.approval import latest_approval
from ufabc_science.editorial.exceptions import EditionError, PublicationBlockedError
from ufabc_science.editorial.markdown import (
    EDITION_SCHEMA_ID,
    STATUS_DIRS,
    article_filename,
    body_hash,
    dump_document,
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
from ufabc_science.processing.classification import canonical_category

logger = logging.getLogger(__name__)

WEEK_PATTERN = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")
CATEGORY_ORDER = [c.slug for c in DEFAULT_CATEGORIES]


def week_range(week: str) -> tuple[date, date]:
    """Converte ``AAAA-Www`` (ISO 8601) em segunda-feira e domingo da semana."""
    match = WEEK_PATTERN.match(week.strip())
    if not match:
        raise EditionError(f"Semana inválida: {week!r}. Use o formato AAAA-Www (ex.: 2026-W46).")
    try:
        start = date.fromisocalendar(int(match.group("year")), int(match.group("week")), 1)
    except ValueError as exc:
        raise EditionError(f"Semana inexistente: {week}") from exc
    return start, start + timedelta(days=6)


def edition_slug(number: int) -> str:
    return f"edicao-{number:03d}"


def get_edition(session: Session, number: int) -> NewsletterEdition:
    edition = session.scalars(
        select(NewsletterEdition).where(NewsletterEdition.edition_number == number)
    ).first()
    if edition is None:
        raise EditionError(f"Edição {number} não encontrada.")
    return edition


def intro_path(editions_dir: Path, edition: NewsletterEdition) -> Path:
    return safe_child(editions_dir / "drafts", f"{edition.slug}.md")


INTRO_PLACEHOLDER = "ESCREVA AQUI a introdução editorial"


def _intro_template(edition: NewsletterEdition) -> str:
    return (
        f"# UFABC Science — Edição {edition.edition_number:03d}\n\n"
        f"{INTRO_PLACEHOLDER} (apague esta linha). O título acima não é publicado.\n\n"
        "Nesta edição, reunimos pesquisas recentes selecionadas pela curadoria do UFABC Science.\n"
    )


def _intro_text(body: str) -> str:
    """Corpo da introdução sem o título de nível 1 (a página já exibe o título da edição)."""
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def create_edition(
    session: Session, week: str, editions_dir: Path, *, title: str | None = None
) -> NewsletterEdition:
    """Cria uma edição ``DRAFT`` para a semana; impede duplicidade. Não adiciona artigos."""
    start, end = week_range(week)
    normalized_week = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
    existing = session.scalars(
        select(NewsletterEdition).where(NewsletterEdition.week == normalized_week)
    ).first()
    if existing is not None:
        raise EditionError(
            f"Já existe a edição {existing.edition_number} para a semana {normalized_week}."
        )
    number = (session.scalar(select(func.max(NewsletterEdition.edition_number))) or 0) + 1
    edition = NewsletterEdition(
        title=title or f"UFABC Science — Edição {number:03d}",
        slug=edition_slug(number),
        edition_number=number,
        week=normalized_week,
        start_date=start,
        end_date=end,
        status=EditionStatus.DRAFT,
        introduction_status=EditorialStatus.PENDING_REVIEW,
    )
    session.add(edition)
    session.flush()
    path = intro_path(editions_dir, edition)
    if not path.exists():
        metadata = {
            "schema": EDITION_SCHEMA_ID,
            "edition_number": number,
            "slug": edition.slug,
            "week": normalized_week,
            "status": EditorialStatus.PENDING_REVIEW.value,
            "reviewer": None,
            "reviewed_at": None,
        }
        write_text_atomic(path, dump_document(metadata, _intro_template(edition)))
    return edition


def _ensure_editable(edition: NewsletterEdition) -> None:
    if edition.status in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED):
        raise EditionError(f"A edição {edition.edition_number} já foi publicada e é imutável.")
    if edition.status is EditionStatus.READY:
        edition.status = EditionStatus.DRAFT
        logger.info("Edição %s voltou para DRAFT após alteração.", edition.edition_number)


def default_section(article: Article, editorial_dir: Path) -> str | None:
    """Categoria principal: a do arquivo aprovado, ou a de maior confiança."""
    path = editorial_dir / STATUS_DIRS[EditorialStatus.APPROVED] / article_filename(article.id)
    if path.exists():
        try:
            primary = read_document(path).metadata.get("primary_category")
            if primary:
                return canonical_category(str(primary))
        except Exception:
            pass
    if article.categories:
        return max(article.categories, key=lambda link: link.confidence).category.slug
    return None


def _renumber(edition: NewsletterEdition, ordered: list[NewsletterItem]) -> None:
    # Duas fases evitam violar a restrição única (edition_id, position) no flush.
    for offset, item in enumerate(ordered, start=1):
        item.position = 10_000 + offset
    session = Session.object_session(edition)
    assert session is not None
    session.flush()
    for position, item in enumerate(ordered, start=1):
        item.position = position
    session.flush()
    session.refresh(edition, ["items"])


def add_article(
    session: Session,
    number: int,
    article_id: int,
    editorial_dir: Path,
    *,
    section: str | None = None,
    position: int | None = None,
) -> NewsletterItem:
    """Adiciona um artigo **aprovado** à edição."""
    edition = get_edition(session, number)
    _ensure_editable(edition)
    article = session.get(Article, article_id)
    if article is None:
        raise EditionError(f"Artigo {article_id} não existe.")
    if latest_approval(article) is None:
        raise EditionError(f"Artigo {article_id} não está aprovado editorialmente.")
    if any(item.article_id == article_id for item in edition.items):
        raise EditionError(f"Artigo {article_id} já está na edição {number}.")
    slug = canonical_category(section) if section else default_section(article, editorial_dir)
    if slug is None or slug not in known_category_slugs(session):
        raise EditionError(f"Seção editorial inválida para o artigo {article_id}: {slug!r}.")
    item = NewsletterItem(edition=edition, article=article, position=10_000, editorial_section=slug)
    session.add(item)
    session.flush()
    ordered = [i for i in edition.items if i is not item]
    if position is None:
        # Ordem inicial: segue a ordem oficial das editorias (o editor pode reordenar).
        rank = _section_rank(slug)
        index = sum(1 for other in ordered if _section_rank(other.editorial_section) <= rank)
    else:
        index = max(0, min(position - 1, len(ordered)))
    ordered.insert(index, item)
    _renumber(edition, ordered)
    return item


def remove_article(session: Session, number: int, article_id: int) -> None:
    edition = get_edition(session, number)
    _ensure_editable(edition)
    item = next((i for i in edition.items if i.article_id == article_id), None)
    if item is None:
        raise EditionError(f"Artigo {article_id} não está na edição {number}.")
    edition.items.remove(item)
    session.flush()
    _renumber(edition, list(edition.items))


def reorder(session: Session, number: int, article_ids: list[int]) -> None:
    """Define a ordem completa dos artigos (lista com todos os ids da edição)."""
    edition = get_edition(session, number)
    _ensure_editable(edition)
    current = {item.article_id: item for item in edition.items}
    if sorted(article_ids) != sorted(current) or len(set(article_ids)) != len(article_ids):
        raise EditionError(
            "A nova ordem deve conter exatamente os artigos da edição: "
            + ", ".join(map(str, sorted(current)))
        )
    _renumber(edition, [current[a] for a in article_ids])


def set_section(session: Session, number: int, article_id: int, section: str) -> None:
    edition = get_edition(session, number)
    _ensure_editable(edition)
    item = next((i for i in edition.items if i.article_id == article_id), None)
    if item is None:
        raise EditionError(f"Artigo {article_id} não está na edição {number}.")
    slug = canonical_category(section)
    if slug not in known_category_slugs(session):
        raise EditionError(f"Seção editorial inválida: {section!r}.")
    item.editorial_section = slug


def _section_rank(slug: str | None) -> int:
    return CATEGORY_ORDER.index(slug) if slug in CATEGORY_ORDER else len(CATEGORY_ORDER)


def group_by_section(items: list[NewsletterItem]) -> list[tuple[str, list[NewsletterItem]]]:
    """Agrupa itens por editoria; cada artigo aparece uma única vez.

    As seções aparecem na ordem definida pelo editor (posição do primeiro artigo de cada
    seção). Sem reordenação manual, isso coincide com a ordem oficial das editorias.
    """
    groups: dict[str, list[NewsletterItem]] = {}
    for item in sorted(items, key=lambda i: i.position):
        groups.setdefault(item.editorial_section or "sem-categoria", []).append(item)
    return list(groups.items())


# --- Introdução --------------------------------------------------------------------------


def sync_introduction(
    session: Session, edition: NewsletterEdition, editions_dir: Path
) -> list[str]:
    """Lê a introdução e registra aprovação humana. Retorna problemas encontrados."""
    path = intro_path(editions_dir, edition)
    if not path.exists():
        return [f"Introdução ausente: {path.as_posix()}"]
    doc = read_document(path)
    meta = doc.metadata
    problems = []
    if meta.get("schema") != EDITION_SCHEMA_ID or meta.get("slug") != edition.slug:
        return [f"{path.as_posix()}: front matter não corresponde à edição {edition.slug}."]
    text = _intro_text(doc.body)
    status = meta.get("status")
    placeholder = INTRO_PLACEHOLDER.casefold() in text.casefold()
    if status == EditorialStatus.APPROVED.value and (placeholder or not text):
        return [
            f"{path.as_posix()}: a introdução ainda contém o texto-modelo ou está vazia; "
            "escreva a introdução antes de aprová-la."
        ]
    if status == EditorialStatus.APPROVED.value:
        if edition.introduction_status is not EditorialStatus.APPROVED or body_hash(
            text
        ) != body_hash(edition.introduction or ""):
            if edition.status in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED):
                return [f"{path.as_posix()}: edição publicada; introdução não pode mudar."]
            reviewed = parse_datetime(meta.get("reviewed_at"))
            if reviewed is not None and reviewed.tzinfo is None:
                reviewed = reviewed.replace(tzinfo=timezone.utc)
            edition.introduction = text
            edition.introduction_status = EditorialStatus.APPROVED
            edition.introduction_reviewer = str(meta.get("reviewer") or "") or None
            edition.introduction_reviewed_at = reviewed or utcnow()
            if edition.status is EditionStatus.READY:
                edition.status = EditionStatus.DRAFT
    else:
        if edition.introduction_status is EditorialStatus.APPROVED and edition.status not in (
            EditionStatus.PUBLISHED,
            EditionStatus.ARCHIVED,
        ):
            edition.introduction_status = EditorialStatus.PENDING_REVIEW
            if edition.status is EditionStatus.READY:
                edition.status = EditionStatus.DRAFT
        problems.append(f"{path.as_posix()}: introdução editorial ainda não aprovada.")
    return problems


# --- Validação e publicação --------------------------------------------------------------


@dataclass
class EditionValidation:
    edition_number: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_edition(
    session: Session,
    number: int,
    *,
    editorial_dir: Path,
    editions_dir: Path,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
    mark_ready: bool = True,
) -> EditionValidation:
    """Revalida tudo o que a publicação exige. Se válida e ``DRAFT``, marca ``READY``."""
    edition = get_edition(session, number)
    result = EditionValidation(number)
    published = edition.status in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED)
    if not published:
        result.errors += sync_introduction(session, edition, editions_dir)
    elif edition.introduction_status is not EditorialStatus.APPROVED:
        result.errors.append("Introdução editorial não aprovada.")
    if not edition.items:
        result.errors.append("A edição não possui artigos.")
    categories = known_category_slugs(session)
    for item in sorted(edition.items, key=lambda i: i.position):
        prefix = f"Artigo {item.article_id}"
        approval = item.review if published else latest_approval(item.article)
        if approval is None or approval.status is not EditorialStatus.APPROVED:
            result.errors.append(f"{prefix}: não está aprovado.")
            continue
        if item.editorial_section not in categories:
            result.errors.append(f"{prefix}: seção editorial inválida ({item.editorial_section}).")
        if published:
            continue
        path = (
            editorial_dir
            / STATUS_DIRS[EditorialStatus.APPROVED]
            / article_filename(item.article_id)
        )
        if not path.exists():
            result.errors.append(f"{prefix}: arquivo aprovado não encontrado em {path.as_posix()}.")
            continue
        doc = read_document(path)
        if doc.current_hash != approval.content_hash:
            result.errors.append(
                f"{prefix}: arquivo alterado após a aprovação; execute 'editorial sync' e revise."
            )
            continue
        validation: EditorialValidationResult = validate_document(
            doc,
            session,
            known_categories=categories,
            min_abstract_words=min_abstract_words,
            word_limits=word_limits,
            for_approval=True,
        )
        result.errors += [f"{prefix}: {e}" for e in validation.errors]
        result.warnings += [f"{prefix}: {w}" for w in validation.warnings]
        content = session.get(GeneratedContent, approval.generated_content_id or -1)
        if content is not None and content.verification_status is VerificationStatus.FAILED:
            result.warnings.append(
                f"{prefix}: o rascunho original da IA falhou na verificação; o texto aprovado "
                "foi revalidado após a edição humana."
            )
    if result.valid and mark_ready and edition.status is EditionStatus.DRAFT:
        edition.status = EditionStatus.READY
    elif not result.valid and edition.status is EditionStatus.READY:
        edition.status = EditionStatus.DRAFT
    return result


def edition_snapshot(edition: NewsletterEdition) -> dict[str, Any]:
    """Registro auditável da publicação (gravado em ``editions/published/``)."""
    return {
        "schema": "ufabc-science/edition-publication@1",
        "edition_number": edition.edition_number,
        "slug": edition.slug,
        "title": edition.title,
        "week": edition.week,
        "start_date": edition.start_date.isoformat(),
        "end_date": edition.end_date.isoformat(),
        "published_at": edition.published_at.isoformat() if edition.published_at else None,
        "published_by": edition.published_by,
        "introduction": edition.introduction,
        "introduction_reviewer": edition.introduction_reviewer,
        "items": [
            {
                "position": item.position,
                "article_id": item.article_id,
                "editorial_section": item.editorial_section,
                "review_id": item.review_id,
                "content_hash": item.review.content_hash if item.review else None,
                "reviewer": item.review.reviewer if item.review else None,
                "doi": item.article.doi,
                "title": item.article.title,
            }
            for item in sorted(edition.items, key=lambda i: i.position)
        ],
    }


def publish_edition(
    session: Session,
    number: int,
    *,
    editorial_dir: Path,
    editions_dir: Path,
    published_by: str,
    confirm: bool,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
) -> NewsletterEdition:
    """Publicação explícita e auditável. Só altera o estado para ``PUBLISHED`` aqui."""
    if not confirm:
        raise PublicationBlockedError("Publicação exige confirmação explícita (--confirm).")
    if not published_by.strip():
        raise PublicationBlockedError("Informe o responsável pela publicação (--by).")
    edition = get_edition(session, number)
    if edition.status in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED):
        raise PublicationBlockedError(f"A edição {number} já foi publicada.")
    validation = validate_edition(
        session,
        number,
        editorial_dir=editorial_dir,
        editions_dir=editions_dir,
        min_abstract_words=min_abstract_words,
        word_limits=word_limits,
    )
    if not validation.valid:
        raise PublicationBlockedError(
            f"A edição {number} não pode ser publicada.", validation.errors
        )
    if edition.status is not EditionStatus.READY:
        raise PublicationBlockedError("A edição precisa estar READY (execute 'edition validate').")
    for item in edition.items:
        approval = latest_approval(item.article)
        assert approval is not None
        item.review = approval
    edition.status = EditionStatus.PUBLISHED
    edition.published_at = utcnow()
    edition.published_by = published_by.strip()
    session.flush()
    snapshot = safe_child(editions_dir / "published", f"{edition.slug}.json")
    write_text_atomic(
        snapshot, json.dumps(edition_snapshot(edition), ensure_ascii=False, indent=2) + "\n"
    )
    logger.info("Edição %s publicada por %s.", number, edition.published_by)
    return edition


def archive_edition(session: Session, number: int) -> NewsletterEdition:
    edition = get_edition(session, number)
    if edition.status is not EditionStatus.PUBLISHED:
        raise EditionError("Somente edições publicadas podem ser arquivadas.")
    edition.status = EditionStatus.ARCHIVED
    return edition


def approved_articles(session: Session) -> list[Article]:
    """Artigos cuja revisão mais recente é uma aprovação."""
    return [
        article
        for article in session.scalars(select(Article).order_by(Article.id))
        if latest_approval(article) is not None
    ]


def category_names(session: Session) -> dict[str, str]:
    return {c.slug: c.name for c in session.scalars(select(Category))}
