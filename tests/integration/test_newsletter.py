"""Newsletter por e-mail: renderização, envio SMTP (simulado) e envio único."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.conftest import FakeApis, Workspace
from tests.integration.test_autopublish import CleanProvider, prepare, run
from ufabc_science.config.settings import Settings
from ufabc_science.main import main
from ufabc_science.newsletter.mailer import NewsletterError, SmtpMailer
from ufabc_science.newsletter.service import (
    latest_published,
    parse_recipients,
    render_newsletter,
    send_newsletter,
    sent_marker,
)
from ufabc_science.publisher.html import AI_NOTICE, build_site

SITE = "https://exemplo.github.io/UFABC-Science/"
PROJECT = "projeto@gmail.com"


class FakeMailer:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.fail_for = fail_for or set()
        self.closed = False

    def send(self, message: EmailMessage) -> None:
        if message["To"] in self.fail_for:
            raise NewsletterError("Falha no envio SMTP: SMTPRecipientsRefused")
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def published(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    prepare(workspace, fake_apis, CleanProvider())
    assert run(workspace).published
    return workspace


def configured(ws: Workspace, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "smtp_password": "senha-de-app",
        "contact_email": PROJECT,
        "site_url": SITE,
        "newsletter_recipients": "ana@exemplo.org, bia@exemplo.org;\nANA@exemplo.org invalido",
        **overrides,
    }
    for key in ("smtp_password", "newsletter_recipients"):  # como viriam do ambiente
        if isinstance(values[key], str):
            values[key] = SecretStr(str(values[key]))
    return ws.settings.model_copy(update=values)


def html_of(message: EmailMessage) -> str:
    return message.get_body(("html",)).get_content()


def test_parse_recipients_dedupes_and_ignores_invalid() -> None:
    raw = "ana@exemplo.org, bia@exemplo.org;\nANA@exemplo.org  invalido\n\n"
    assert parse_recipients(raw) == ["ana@exemplo.org", "bia@exemplo.org"]
    assert parse_recipients(None) == []


def test_email_links_to_site_and_declares_ai(published: Workspace) -> None:
    with published.factory() as session:
        email = render_newsletter(
            session,
            latest_published(session),
            site_url=SITE,
            timezone_name="UTC",
            unsubscribe_url="mailto:x@exemplo.org?subject=Cancelar",
        )
    assert email.subject.startswith("☕ ")
    assert "Bom dia!" in email.html and "Nesta edição" in email.html
    assert f"{SITE}articles/article-" in email.html
    assert f"{SITE}editions/edicao-001/index.html" in email.html
    assert AI_NOTICE in email.html and "Cancelar inscrição" in email.html
    assert f"{SITE}articles/article-" in email.text and "Cancelar inscrição" in email.text


def test_send_individually_to_each_subscriber_once(published: Workspace) -> None:
    settings = configured(published)
    mailer = FakeMailer()
    with published.factory() as session:
        result = send_newsletter(session, settings, mailer=mailer)
    assert result.sent and result.delivered == 2 and result.failed == 0
    assert [m["To"] for m in mailer.sent] == ["ana@exemplo.org", "bia@exemplo.org"]
    for message in mailer.sent:
        assert PROJECT in message["From"]  # um destinatário por mensagem: ninguém vê os outros
        assert message["List-Unsubscribe"].startswith(f"<mailto:{PROJECT}")
        assert "Bom dia!" in html_of(message)
    marker = sent_marker(settings.editions_dir, "edicao-001")
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["delivered"] == 2
    assert "ana@exemplo.org" not in marker.read_text(encoding="utf-8")  # sem endereços no Git

    with published.factory() as session:
        again = send_newsletter(session, settings, mailer=mailer)
    assert not again.sent and "já foi enviada" in again.message
    assert len(mailer.sent) == 2


def test_partial_failure_is_reported_and_not_resent(published: Workspace) -> None:
    settings = configured(published)
    mailer = FakeMailer(fail_for={"bia@exemplo.org"})
    with published.factory() as session:
        result = send_newsletter(session, settings, mailer=mailer)
    assert result.delivered == 1 and result.failed == 1 and "1 falha" in result.message
    assert sent_marker(settings.editions_dir, "edicao-001").exists()


def test_total_failure_records_nothing(published: Workspace) -> None:
    settings = configured(published)
    mailer = FakeMailer(fail_for={"ana@exemplo.org", "bia@exemplo.org"})
    with published.factory() as session, pytest.raises(NewsletterError):
        send_newsletter(session, settings, mailer=mailer)
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_test_send_goes_to_test_address_or_sender(published: Workspace) -> None:
    mailer = FakeMailer()
    settings = configured(published, newsletter_test_email="eu@exemplo.org")
    with published.factory() as session:
        result = send_newsletter(session, settings, test=True, mailer=mailer)
    with published.factory() as session:  # sem NEWSLETTER_TEST_EMAIL: vai para o remetente
        send_newsletter(session, configured(published), test=True, mailer=mailer)
    assert result.test and [m["To"] for m in mailer.sent] == ["eu@exemplo.org", PROJECT]
    assert all(m["Subject"].startswith("[TESTE] ") for m in mailer.sent)
    assert all(m["List-Unsubscribe"] is None for m in mailer.sent)
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_missing_configuration_is_reported(published: Workspace) -> None:
    with published.factory() as session, pytest.raises(NewsletterError) as error:
        send_newsletter(session, published.settings)
    assert "SMTP_PASSWORD" in str(error.value) and "SITE_URL" in str(error.value)


def test_empty_recipient_list_is_an_error(published: Workspace) -> None:
    settings = configured(published, newsletter_recipients=None)
    with published.factory() as session, pytest.raises(NewsletterError, match="vazio"):
        send_newsletter(session, settings, mailer=FakeMailer())


def test_nothing_published_means_nothing_to_send(workspace: Workspace) -> None:
    with workspace.factory() as session, pytest.raises(NewsletterError):
        send_newsletter(session, configured(workspace), mailer=FakeMailer())


def test_smtp_login_error_has_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class RefusingSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    monkeypatch.setattr(smtplib, "SMTP_SSL", RefusingSMTP)
    with pytest.raises(NewsletterError, match="senha de app") as error:
        SmtpMailer(host="smtp.gmail.com", port=465, username=PROJECT, password="segredo")
    assert "segredo" not in str(error.value)


def test_site_subscribe_button_opens_email_to_project(published: Workspace) -> None:
    out = published.settings.output_dir
    with published.factory() as session:
        build_site(session, out, timezone_name="UTC")
    assert "Assinar a newsletter" not in (out / "index.html").read_text(encoding="utf-8")
    link = configured(published).subscribe_link
    assert link and link.startswith(f"mailto:{PROJECT}?subject=")
    with published.factory() as session:
        build_site(session, out, timezone_name="UTC", subscribe_url=link)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Assinar a newsletter" in home and "é só enviar" in home
    assert "sem revisão humana" in home and "revisado por uma pessoa" not in home


def test_cli_preview_writes_html(
    published: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = published.settings
    monkeypatch.setenv("DATABASE_URL", s.database_url)
    monkeypatch.setenv("EDITIONS_DIR", s.editions_dir.as_posix())
    monkeypatch.setenv("PREVIEW_DIR", s.preview_dir.as_posix())
    monkeypatch.setenv("SITE_URL", SITE)
    assert main(["newsletter", "preview"]) == 0
    target = Path(s.preview_dir) / "newsletter" / "edicao-001.html"
    assert "Bom dia!" in target.read_text(encoding="utf-8")
    assert "nada foi enviado" in capsys.readouterr().out


def test_cli_skips_quietly_without_password(
    published: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", published.settings.database_url)
    assert main(["newsletter", "send", "--skip-if-unconfigured"]) == 0
    assert "não configurada" in capsys.readouterr().out
    assert main(["newsletter", "send"]) == 1
