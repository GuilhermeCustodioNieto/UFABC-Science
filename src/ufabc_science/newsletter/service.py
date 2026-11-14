"""Renderização e envio da edição publicada por e-mail.

* Só edições ``PUBLISHED``/``ARCHIVED`` são enviadas, com o mesmo texto aprovado do site.
* Cada edição é enviada aos assinantes **uma única vez**: o envio grava
  ``editions/sent/<slug>.json`` (persistido na branch ``data``). Envios de teste não
  gravam marca e não usam a lista.
* Os links apontam para o site público (``SITE_URL``).
"""

from __future__ import annotations

import json
import math
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
from ufabc_science.newsletter.brevo import UNSUBSCRIBE_TAG, BrevoClient, NewsletterError
from ufabc_science.publisher.html import AI_NOTICE, DISCLAIMER, _edition_view, _environment

PUBLISHED = (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED)


@dataclass
class RenderedEmail:
    edition_number: int
    slug: str
    subject: str
    preheader: str
    html: str


@dataclass
class SendResult:
    edition_number: int
    sent: bool
    test: bool
    message: str
    campaign_id: int | None = None


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
    for_subscribers: bool,
) -> RenderedEmail:
    if edition.status not in PUBLISHED:
        raise NewsletterError(f"A edição {edition.edition_number} não está publicada.")
    view = _edition_view(session, edition, ZoneInfo(timezone_name), preview=False)
    articles = view.articles
    if not articles:
        raise NewsletterError(f"A edição {edition.edition_number} não tem artigos publicados.")
    words = len(view.introduction.striptags().split()) + sum(
        len(a.summary.striptags().split()) + len(a.headline.split()) for a in articles
    )
    subject = _truncate(f"☕ {articles[0].headline}", 110)
    others = [a.headline for a in articles[1:]]
    preheader = _truncate(
        ("Também nesta edição: " + "; ".join(others)) if others else view.title, 150
    )
    html = (
        _environment()
        .get_template("email/newsletter.html")
        .render(
            edition=view,
            subject=subject,
            preheader=preheader,
            site_url=site_url if site_url.endswith("/") else site_url + "/",
            reading_minutes=max(1, math.ceil(words / 200)),
            ai_notice=AI_NOTICE if is_automatic(edition) else None,
            disclaimer=DISCLAIMER,
            unsubscribe_url=UNSUBSCRIBE_TAG if for_subscribers else None,
        )
    )
    return RenderedEmail(edition.edition_number, edition.slug, subject, preheader, html)


def sent_marker(editions_dir: Path, slug: str) -> Path:
    return safe_child(editions_dir / "sent", f"{slug}.json")


def send_newsletter(
    session: Session,
    settings: Settings,
    *,
    edition_number: int | None = None,
    test_to: str | None = None,
    client: BrevoClient | None = None,
) -> SendResult:
    """Envia a edição (padrão: a mais recente publicada) aos assinantes ou a um teste."""
    missing = [
        name
        for name, value in (
            ("BREVO_API_KEY", settings.brevo_api_key),
            ("SITE_URL", settings.site_url),
            ("NEWSLETTER_SENDER_EMAIL ou CONTACT_EMAIL", settings.sender_email),
        )
        if not value
    ]
    if test_to is None and settings.brevo_list_id is None:
        missing.append("BREVO_LIST_ID")
    if missing:
        raise NewsletterError("Configuração ausente para a newsletter: " + ", ".join(missing))
    assert settings.site_url and settings.sender_email and settings.brevo_api_key

    edition = (
        get_edition(session, edition_number)
        if edition_number is not None
        else latest_published(session)
    )
    test = test_to is not None
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
        for_subscribers=not test,
    )
    owns_client = client is None
    client = client or BrevoClient(settings.brevo_api_key.get_secret_value())
    try:
        if test:
            assert test_to is not None
            client.send_test(
                to=test_to,
                subject="[TESTE] " + email.subject,
                sender_name=settings.newsletter_sender_name,
                sender_email=settings.sender_email,
                html=email.html,
            )
            return SendResult(edition.edition_number, True, True, "e-mail de teste enviado")
        assert settings.brevo_list_id is not None
        campaign_id = client.send_campaign(
            name=f"UFABC Science — {edition.slug}",
            subject=email.subject,
            preheader=email.preheader,
            sender_name=settings.newsletter_sender_name,
            sender_email=settings.sender_email,
            html=email.html,
            list_id=settings.brevo_list_id,
        )
    finally:
        if owns_client:
            client.close()
    write_text_atomic(
        marker,
        json.dumps(
            {
                "schema": "ufabc-science/newsletter-send@1",
                "edition_number": edition.edition_number,
                "slug": edition.slug,
                "campaign_id": campaign_id,
                "list_id": settings.brevo_list_id,
                "sent_at": utcnow().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return SendResult(
        edition.edition_number, True, False, "enviada aos assinantes", campaign_id=campaign_id
    )


__all__ = [
    "RenderedEmail",
    "SendResult",
    "latest_published",
    "render_newsletter",
    "send_newsletter",
]
