"""Newsletter por e-mail: renderização, envio pelo Brevo (simulado) e envio único."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tests.conftest import FakeApis, Workspace
from tests.integration.test_autopublish import CleanProvider, prepare, run
from ufabc_science.config.settings import Settings
from ufabc_science.main import main
from ufabc_science.newsletter.brevo import UNSUBSCRIBE_TAG, BrevoClient, NewsletterError
from ufabc_science.newsletter.service import (
    latest_published,
    render_newsletter,
    send_newsletter,
    sent_marker,
)
from ufabc_science.publisher.html import AI_NOTICE, build_site

SITE = "https://exemplo.github.io/UFABC-Science/"


class FakeBrevo:
    def __init__(self, status: int = 201) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json={"code": "unauthorized", "message": "Key"})
        if request.url.path.endswith("/emailCampaigns"):
            return httpx.Response(201, json={"id": 42})
        if request.url.path.endswith("/sendNow"):
            return httpx.Response(204)
        if request.url.path.endswith("/smtp/email"):
            return httpx.Response(201, json={"messageId": "<abc@brevo>"})
        return httpx.Response(404)

    def client(self) -> BrevoClient:
        return BrevoClient("chave-secreta", transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) if r.content else {} for r in self.requests]


@pytest.fixture
def published(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    prepare(workspace, fake_apis, CleanProvider())
    assert run(workspace).published
    return workspace


def configured(ws: Workspace, **overrides: object) -> Settings:
    values = {
        "brevo_api_key": "chave-secreta",
        "brevo_list_id": 7,
        "site_url": SITE,
        "contact_email": "projeto@exemplo.org",
        **overrides,
    }
    return ws.settings.model_copy(update=values)


def test_email_links_to_site_and_has_unsubscribe(published: Workspace) -> None:
    with published.factory() as session:
        edition = latest_published(session)
        email = render_newsletter(
            session, edition, site_url=SITE, timezone_name="UTC", for_subscribers=True
        )
        headlines = [i.review.content_snapshot.splitlines()[0][2:] for i in edition.items]
    assert email.subject.startswith("☕ ")
    assert "Bom dia!" in email.html and "Nesta edição" in email.html
    assert f"{SITE}articles/article-" in email.html
    assert f"{SITE}editions/{edition.slug}/index.html" in email.html
    assert UNSUBSCRIBE_TAG in email.html
    assert AI_NOTICE in email.html  # edição automática declara ausência de revisão humana
    for headline in headlines:
        assert headline.replace("'", "&#39;") in email.html or headline in email.html


def test_send_to_subscribers_once(published: Workspace) -> None:
    settings = configured(published)
    brevo = FakeBrevo()
    with published.factory() as session:
        result = send_newsletter(session, settings, client=brevo.client())
    assert result.sent and result.campaign_id == 42
    create, send_now = brevo.requests
    assert create.headers["api-key"] == "chave-secreta"
    body = brevo.bodies()[0]
    assert body["recipients"] == {"listIds": [7]}
    assert body["sender"]["email"] == "projeto@exemplo.org"
    assert UNSUBSCRIBE_TAG in body["htmlContent"]
    assert send_now.url.path == "/v3/emailCampaigns/42/sendNow"
    marker = sent_marker(settings.editions_dir, "edicao-001")
    assert json.loads(marker.read_text(encoding="utf-8"))["campaign_id"] == 42

    with published.factory() as session:
        again = send_newsletter(session, settings, client=brevo.client())
    assert not again.sent and "já foi enviada" in again.message
    assert len(brevo.requests) == 2  # nada novo foi enviado


def test_test_send_goes_to_one_address_and_records_nothing(published: Workspace) -> None:
    settings = configured(published, brevo_list_id=None)
    brevo = FakeBrevo()
    with published.factory() as session:
        result = send_newsletter(session, settings, test_to="eu@exemplo.org", client=brevo.client())
    assert result.sent and result.test
    (request,) = brevo.requests
    assert request.url.path == "/v3/smtp/email"
    body = brevo.bodies()[0]
    assert body["to"] == [{"email": "eu@exemplo.org"}]
    assert body["subject"].startswith("[TESTE] ")
    assert UNSUBSCRIBE_TAG not in body["htmlContent"]
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_missing_configuration_is_reported(published: Workspace) -> None:
    with published.factory() as session, pytest.raises(NewsletterError) as error:
        send_newsletter(session, published.settings)
    assert "BREVO_API_KEY" in str(error.value) and "BREVO_LIST_ID" in str(error.value)


def test_brevo_error_does_not_leak_key_or_mark_as_sent(published: Workspace) -> None:
    settings = configured(published)
    brevo = FakeBrevo(status=401)
    with published.factory() as session, pytest.raises(NewsletterError) as error:
        send_newsletter(session, settings, client=brevo.client())
    assert "401" in str(error.value) and "chave-secreta" not in str(error.value)
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_nothing_published_means_nothing_to_send(workspace: Workspace) -> None:
    with workspace.factory() as session, pytest.raises(NewsletterError):
        send_newsletter(session, configured(workspace), client=FakeBrevo().client())


def test_site_shows_subscribe_button_only_when_configured(published: Workspace) -> None:
    out = published.settings.output_dir
    with published.factory() as session:
        build_site(session, out, timezone_name="UTC")
    assert "Assinar a newsletter" not in (out / "index.html").read_text(encoding="utf-8")
    url = "https://sibforms.com/serve/abc"
    with published.factory() as session:
        build_site(session, out, timezone_name="UTC", subscribe_url=url)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Assinar a newsletter" in home and url in home
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


def test_cli_test_send_requires_address(
    published: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", published.settings.database_url)
    assert main(["newsletter", "send", "--test"]) == 1
