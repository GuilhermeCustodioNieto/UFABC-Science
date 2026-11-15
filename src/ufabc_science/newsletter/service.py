"""Renderização e envio da edição publicada por e-mail, direto pelo SMTP do projeto.

* Só edições ``PUBLISHED``/``ARCHIVED`` são enviadas, com o mesmo texto aprovado do site.
* Assinantes vêm do secret ``NEWSLETTER_RECIPIENTS`` (lista pequena, mantida à mão).
* Cada edição é enviada aos assinantes **uma única vez**: o envio grava
  ``editions/sent/<slug>.json`` (persistido na branch ``data``), só com contagens, nunca
  endereços. Envios de teste vão para ``NEWSLETTER_TEST_EMAIL`` (ou o próprio remetente) e
  não gravam marca.
* Os links apontam para o site público (``SITE_URL``).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.config.settings import Settings
from ufabc_science.domain.enums import EditionStatus
from ufabc_science.domain.models import NewsletterEdition, utcnow
from ufabc_science.editorial.autopublish import is_automatic
from ufabc_science.editorial.edition import get_edition
from ufabc_science.editorial.markdown import safe_child, write_text_atomic
from ufabc_science.newsletter.mailer import Mailer, NewsletterError, SmtpMailer, build_message
from ufabc_science.publisher.html import AI_NOTICE, DISCLAIMER, _edition_view, _environment

PUBLISHED = (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED)
_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


@dataclass
class RenderedEmail:
    edition_number: int
    slug: str
    subject: str
    preheader: str
    html: str
    text: str


@dataclass
class SendResult:
    edition_number: int
    sent: bool
    test: bool
    message: str
    delivered: int = 0
    failed: int = 0


def parse_recipients(raw: str | None) -> list[str]:
    """Endereços únicos (sem diferenciar maiúsculas), na ordem em que aparecem."""
    seen: dict[str, str] = {}
    for part in re.split(r"[,;\s]+", raw or ""):
        address = part.strip()
        if address and _ADDRESS.match(address):
            seen.setdefault(address.casefold(), address)
    return list(seen.values())


def latest_published(session: Session) -> NewsletterEdition:
    edition = session.scalars(
        select(NewsletterEdition)
        .where(NewsletterEdition.status.in_(PUBLISHED))
        .order_by(NewsletterEdition.edition_number.desc())
    ).first()
    if edition is None:
        raise NewsletterError("Nenhuma edição publicada para enviar.")
    return edition


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_newsletter(
    session: Session,
    edition: NewsletterEdition,
    *,
    site_url: str,
    timezone_name: str,
    test: bool = False,
    unsubscribe_url: str | None = None,
) -> RenderedEmail:
    if edition.status not in PUBLISHED:
        raise NewsletterError(f"A edição {edition.edition_number} não está publicada.")
    view = _edition_view(session, edition, ZoneInfo(timezone_name), preview=False)
    articles = view.articles
    if not articles:
        raise NewsletterError(f"A edição {edition.edition_number} não tem artigos publicados.")
    site = site_url if site_url.endswith("/") else site_url + "/"
    words = len(view.introduction.striptags().split()) + sum(
        len(a.summary.striptags().split()) + len(a.headline.split()) for a in articles
    )
    subject = _truncate(("[TESTE] " if test else "") + f"☕ {articles[0].headline}", 110)
    others = [a.headline for a in articles[1:]]
    preheader = _truncate(
        ("Também nesta edição: " + "; ".join(others)) if others else view.title, 150
    )
    ai_notice = AI_NOTICE if is_automatic(edition) else None
    html = (
        _environment()
        .get_template("email/newsletter.html")
        .render(
            edition=view,
            subject=subject,
            preheader=preheader,
            site_url=site,
            reading_minutes=max(1, math.ceil(words / 200)),
            ai_notice=ai_notice,
            disclaimer=DISCLAIMER,
            test=test,
            unsubscribe_url=unsubscribe_url,
        )
    )
    lines = [f"UFABC Science — Edição {view.number:03d}", "", "Bom dia!", ""]
    if view.introduction:
        lines += [view.introduction.striptags(), ""]
    for _, name, items in view.groups:
        lines += [name.upper(), ""]
        for article in items:
            lines += [article.headline, article.summary.striptags(), f"{site}{article.path}", ""]
    if ai_notice:
        lines += [ai_notice, ""]
    lines.append(DISCLAIMER)
    if unsubscribe_url and not test:
        lines.append(f"Cancelar inscrição: {unsubscribe_url}")
    return RenderedEmail(
        edition.edition_number, edition.slug, subject, preheader, html, "\n".join(lines) + "\n"
    )


def sent_marker(editions_dir: Path, slug: str) -> Path:
    return safe_child(editions_dir / "sent", f"{slug}.json")


def _default_mailer(settings: Settings) -> Mailer:
    assert settings.sender_address and settings.smtp_password
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.sender_address,
        password=settings.smtp_password.get_secret_value(),
    )


def send_newsletter(
    session: Session,
    settings: Settings,
    *,
    edition_number: int | None = None,
    test: bool = False,
    mailer: Mailer | None = None,
) -> SendResult:
    """Envia a edição (padrão: a mais recente publicada) aos assinantes ou um teste."""
    missing = [
        name
        for name, value in (
            ("SMTP_PASSWORD", settings.smtp_password),
            ("SMTP_USERNAME ou CONTACT_EMAIL", settings.sender_address),
            ("SITE_URL", settings.site_url),
        )
        if not value
    ]
    if missing:
        raise NewsletterError("Configuração ausente para a newsletter: " + ", ".join(missing))
    assert settings.site_url and settings.sender_address

    if test:
        recipients = [settings.newsletter_test_email or settings.sender_address]
    else:
        recipients = parse_recipients(
            settings.newsletter_recipients.get_secret_value()
            if settings.newsletter_recipients
            else None
        )
        if not recipients:
            raise NewsletterError("NEWSLETTER_RECIPIENTS está vazio: não há assinantes.")

    edition = (
        get_edition(session, edition_number)
        if edition_number is not None
        else latest_published(session)
    )
    marker = sent_marker(settings.editions_dir, edition.slug)
    if not test and marker.exists():
        return SendResult(
            edition.edition_number, False, False, f"edição {edition.slug} já foi enviada"
        )
    email = render_newsletter(
        session,
        edition,
        site_url=settings.site_url,
        timezone_name=settings.timezone,
        test=test,
        unsubscribe_url=settings.unsubscribe_link,
    )
    owns = mailer is None
    mailer = mailer or _default_mailer(settings)
    delivered = failed = 0
    try:
        for address in recipients:
            message = build_message(
                sender_name=settings.newsletter_sender_name,
                sender=settings.sender_address,
                to=address,
                subject=email.subject,
                html=email.html,
                text=email.text,
                unsubscribe=None if test else settings.unsubscribe_link,
            )
            try:
                mailer.send(message)
            except NewsletterError:
                failed += 1
            else:
                delivered += 1
    finally:
        if owns:
            mailer.close()

    if test:
        if failed:
            raise NewsletterError("O e-mail de teste não pôde ser enviado.")
        return SendResult(edition.edition_number, True, True, "e-mail de teste enviado", 1, 0)
    if delivered == 0:
        raise NewsletterError(f"Nenhum e-mail foi entregue ({failed} falha(s)).")
    # Registrado mesmo com falhas parciais, para que ninguém receba a edição em dobro.
    write_text_atomic(
        marker,
        json.dumps(
            {
                "schema": "ufabc-science/newsletter-send@1",
                "edition_number": edition.edition_number,
                "slug": edition.slug,
                "delivered": delivered,
                "failed": failed,
                "sent_at": utcnow().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    message = f"enviada a {delivered} assinante(s)"
    if failed:
        message += f"; {failed} falha(s)"
    return SendResult(edition.edition_number, True, False, message, delivered, failed)


__all__ = [
    "RenderedEmail",
    "SendResult",
    "latest_published",
    "parse_recipients",
    "render_newsletter",
    "send_newsletter",
]
