"""Geração do site estático (SPECIFICATION.md, seção 14; Etapa 4, seção 7).

Garantias:

* somente edições ``PUBLISHED``/``ARCHIVED`` entram no site público; cada artigo
  usa o texto da revisão aprovada fixada na publicação;
* a pré-visualização (``build_preview``) é gerada em outro diretório e marcada
  como não publicada;
* conteúdo dinâmico é escapado (autoescape do Jinja2); Markdown editorial é
  convertido e **sanitizado** com ``nh3`` (sem scripts, sem ``javascript:``);
* links externos só são emitidos para URLs ``http(s)`` válidas;
* caminhos de saída são validados contra *path traversal*;
* saída determinística: mesma base e templates produzem os mesmos arquivos.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import markdown as md
import nh3
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import EditionStatus, EditorialStatus, PeerReviewStatus
from ufabc_science.domain.models import Article, EditorialReview, NewsletterEdition
from ufabc_science.editorial.approval import latest_approval
from ufabc_science.editorial.edition import category_names, get_edition, group_by_section
from ufabc_science.editorial.markdown import parse_body, safe_child
from ufabc_science.intelligence.schemas import SECTION_FIELDS, SECTION_TITLES
from ufabc_science.processing.normalization import doi_url, is_http_url, is_valid_doi

logger = logging.getLogger(__name__)

SITE_MARKER = ".ufabc-science-site"
DISCLAIMER = (
    "UFABC Science é uma iniciativa independente de curadoria e divulgação científica. "
    "Não representa oficialmente a Universidade Federal do ABC."
)
ALLOWED_TAGS = {
    "p", "br", "em", "strong", "a", "ul", "ol", "li", "code", "blockquote", "sup", "sub", "h3",
    "h4",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_SCHEMES = {"http", "https", "mailto"}


def render_markdown(text: str | None) -> Markup:
    """Markdown → HTML sanitizado. HTML embutido, scripts e esquemas perigosos são removidos."""
    if not text:
        return Markup("")
    html = md.markdown(text, extensions=[], output_format="html")
    clean = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer nofollow",
    )
    return Markup(clean)


def safe_url(value: str | None) -> str | None:
    return value if is_http_url(value) else None


@dataclass
class ArticleView:
    id: int
    headline: str
    original_title: str
    sections: list[tuple[str, Markup]]
    reference: str
    source_url: str | None
    doi: str | None
    doi_url: str | None
    authors: list[str]
    journal: str | None
    publication_date: str | None
    is_preprint: bool
    peer_review_label: str
    primary_category: str
    primary_category_name: str
    secondary_categories: list[str]
    summary: Markup
    path: str
    edition_slug: str | None = None


@dataclass
class EditionView:
    number: int
    title: str
    slug: str
    period: str
    published: str | None
    introduction: Markup
    groups: list[tuple[str, str, list[ArticleView]]]
    blocked: list[str] = field(default_factory=list)

    @property
    def articles(self) -> list[ArticleView]:
        return [a for _, _, items in self.groups for a in items]


def _fmt_date(value: date | datetime | None, tz: ZoneInfo) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.astimezone(tz)
        return value.strftime("%d/%m/%Y")
    return value.strftime("%d/%m/%Y")


def _peer_label(status: PeerReviewStatus) -> str:
    return {
        PeerReviewStatus.VERIFIED: "Publicado em periódico",
        PeerReviewStatus.PREPRINT: "Preprint — sem revisão por pares",
        PeerReviewStatus.UNKNOWN: "Revisão por pares não confirmada",
    }[status]


def article_view(
    article: Article,
    review: EditorialReview,
    section: str,
    names: dict[str, str],
    tz: ZoneInfo,
) -> ArticleView:
    if review.status is not EditorialStatus.APPROVED or not review.content_snapshot:
        raise ValueError(f"Artigo {article.id} sem revisão aprovada.")
    headline, sections, reference, link, _ = parse_body(review.content_snapshot)
    rendered = [
        (SECTION_TITLES[name], render_markdown(sections.get(name)))
        for name in SECTION_FIELDS
        if sections.get(name)
    ]
    doi = article.doi if article.doi and is_valid_doi(article.doi) else None
    authors = [a.get("name") for a in article.authors or [] if a.get("name")]
    categories = sorted(link_.category.slug for link_ in article.categories)
    return ArticleView(
        id=article.id,
        headline=headline or article.title,
        original_title=article.title,
        sections=rendered,
        reference=reference,
        source_url=safe_url(link),
        doi=doi,
        doi_url=doi_url(doi) if doi else None,
        authors=authors,
        journal=article.journal or article.publisher,
        publication_date=_fmt_date(article.publication_date, tz),
        is_preprint=article.peer_review_status is PeerReviewStatus.PREPRINT,
        peer_review_label=_peer_label(article.peer_review_status),
        primary_category=section,
        primary_category_name=names.get(section, section),
        secondary_categories=[names.get(c, c) for c in categories if c != section],
        summary=render_markdown(sections.get("introduction")),
        path=f"articles/article-{article.id}/index.html",
    )


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("ufabc_science.publisher", "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["safe_url"] = safe_url
    return env


class SiteWriter:
    """Escreve páginas com caminhos relativos e proteção de diretório."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.env = _environment()
        self.written: list[str] = []

    def prepare(self) -> None:
        if self.output_dir.exists():
            entries = list(self.output_dir.iterdir())
            if entries and not (self.output_dir / SITE_MARKER).exists():
                raise RuntimeError(
                    f"{self.output_dir} não está vazio e não foi gerado pelo UFABC Science; "
                    "recusando-se a apagar."
                )
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True)
        (self.output_dir / SITE_MARKER).write_text("gerado por ufabc_science\n", encoding="utf-8")
        assets = resources.files("ufabc_science.publisher").joinpath("assets")
        for sub in ("css", "js"):
            target = self.output_dir / "assets" / sub
            target.mkdir(parents=True, exist_ok=True)
            for entry in sorted(assets.joinpath(sub).iterdir(), key=lambda e: e.name):
                if entry.is_file():
                    (target / entry.name).write_bytes(entry.read_bytes())

    def page(self, relative: str, template: str, **context: Any) -> None:
        target = safe_child(self.output_dir, relative)
        depth = relative.count("/")
        root = "../" * depth
        html = self.env.get_template(template).render(
            root=root, disclaimer=DISCLAIMER, page_path=relative, **context
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="\n")
        self.written.append(relative)


@dataclass
class BuildResult:
    output_dir: Path
    pages: list[str]
    editions: list[int]
    errors: list[str] = field(default_factory=list)


def _edition_view(
    session: Session,
    edition: NewsletterEdition,
    tz: ZoneInfo,
    *,
    preview: bool,
) -> EditionView:
    names = category_names(session)
    groups: list[tuple[str, str, list[ArticleView]]] = []
    blocked: list[str] = []
    for section, items in group_by_section(list(edition.items)):
        views = []
        for item in items:
            review = latest_approval(item.article) if preview else item.review
            if review is None or review.status is not EditorialStatus.APPROVED:
                blocked.append(f"Artigo {item.article_id}: sem aprovação — omitido.")
                continue
            view = article_view(item.article, review, section, names, tz)
            view.edition_slug = edition.slug
            views.append(view)
        if views:
            groups.append((section, names.get(section, section), views))
    intro = edition.introduction if edition.introduction_status is EditorialStatus.APPROVED else ""
    if preview and not intro:
        blocked.append("Introdução editorial ainda não aprovada.")
    return EditionView(
        number=edition.edition_number,
        title=edition.title,
        slug=edition.slug,
        period=f"{_fmt_date(edition.start_date, tz)} a {_fmt_date(edition.end_date, tz)}",
        published=_fmt_date(edition.published_at, tz),
        introduction=render_markdown(intro),
        groups=groups,
        blocked=blocked,
    )


def _write_edition(writer: SiteWriter, view: EditionView, *, preview: bool) -> None:
    writer.page(
        f"editions/{view.slug}/index.html", "newsletter.html", edition=view, preview=preview
    )
    for article in view.articles:
        writer.page(article.path, "article.html", article=article, edition=view, preview=preview)


def build_site(session: Session, output_dir: Path, *, timezone_name: str) -> BuildResult:
    """Gera o site público com todas as edições publicadas."""
    tz = ZoneInfo(timezone_name)
    editions = list(
        session.scalars(
            select(NewsletterEdition)
            .where(NewsletterEdition.status.in_([EditionStatus.PUBLISHED, EditionStatus.ARCHIVED]))
            .order_by(NewsletterEdition.edition_number.desc())
        )
    )
    writer = SiteWriter(output_dir)
    writer.prepare()
    views = []
    errors = []
    for edition in editions:
        view = _edition_view(session, edition, tz, preview=False)
        errors += [f"Edição {edition.edition_number}: {b}" for b in view.blocked]
        views.append(view)
    # Um artigo publicado em mais de uma edição recebe uma única página (a mais recente).
    written_articles: set[int] = set()
    for view in views:
        writer.page(
            f"editions/{view.slug}/index.html", "newsletter.html", edition=view, preview=False
        )
        for article in view.articles:
            if article.id in written_articles:
                continue
            written_articles.add(article.id)
            writer.page(article.path, "article.html", article=article, edition=view, preview=False)
    names = category_names(session)
    writer.page(
        "index.html",
        "home.html",
        latest=views[0] if views else None,
        categories=[(slug, names.get(slug, slug)) for slug in _category_order(names)],
        preview=False,
    )
    writer.page("archive/index.html", "archive.html", editions=views, preview=False)
    return BuildResult(output_dir, sorted(writer.written), [v.number for v in views], errors=errors)


def build_preview(
    session: Session, number: int, preview_dir: Path, *, timezone_name: str
) -> BuildResult:
    """Pré-visualização local de uma edição (qualquer estado). Não publica nada."""
    tz = ZoneInfo(timezone_name)
    edition = get_edition(session, number)
    output = safe_child(preview_dir, edition.slug)
    writer = SiteWriter(output)
    writer.prepare()
    view = _edition_view(session, edition, tz, preview=True)
    _write_edition(writer, view, preview=True)
    names = category_names(session)
    writer.page(
        "index.html",
        "home.html",
        latest=view,
        categories=[(slug, names.get(slug, slug)) for slug in _category_order(names)],
        preview=True,
    )
    writer.page("archive/index.html", "archive.html", editions=[view], preview=True)
    return BuildResult(output, sorted(writer.written), [number], errors=view.blocked)


def _category_order(names: dict[str, str]) -> list[str]:
    from ufabc_science.editorial.edition import CATEGORY_ORDER

    return [slug for slug in CATEGORY_ORDER if slug in names]
