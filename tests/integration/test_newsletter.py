"""Newsletter por e-mail: renderização, agendamento no Kit (simulado) e envio único."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from tests.conftest import FakeApis, Workspace
from tests.integration.test_autopublish import CleanProvider, prepare, run
from ufabc_science.config.settings import Settings
from ufabc_science.main import main
from ufabc_science.newsletter.kit import KitClient, NewsletterError
from ufabc_science.newsletter.service import (
    latest_published,
    render_newsletter,
    send_newsletter,
    sent_marker,
)
from ufabc_science.publisher.html import AI_NOTICE, build_site

SITE = "https://exemplo.github.io/UFABC-Science/"


class FakeKit:
    def __init__(self, status: int = 201, draft: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.draft = draft

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json={"errors": ["The access token is invalid"]})
        body = json.loads(request.content)
        send_at = None if self.draft else body["send_at"]
        return httpx.Response(
            201,
            json={
                "broadcast": {
                    "id": 42,
                    "send_at": send_at,
                    "status": "draft" if self.draft else "scheduled",
                }
            },
        )

    def client(self) -> KitClient:
        return KitClient("chave-secreta", transport=httpx.MockTransport(self))

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def published(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    prepare(workspace, fake_apis, CleanProvider())
    assert run(workspace).published
    return workspace


def configured(ws: Workspace, **overrides: object) -> Settings:
    values = {"kit_api_key": "chave-secreta", "site_url": SITE, **overrides}
    return ws.settings.model_copy(update=values)


def test_email_links_to_site_and_declares_ai(published: Workspace) -> None:
    with published.factory() as session:
        email = render_newsletter(
            session, latest_published(session), site_url=SITE, timezone_name="UTC"
        )
    assert email.subject.startswith("☕ ")
    for html in (email.body, email.html):
        assert "Bom dia!" in html and "Nesta edição" in html
        assert f"{SITE}articles/article-" in html
        assert f"{SITE}editions/edicao-001/index.html" in html
        assert AI_NOTICE in html
    # O corpo enviado ao Kit é um fragmento (o template do Kit adiciona o descadastro).
    assert "<html" not in email.body and "<html" in email.html


def test_send_to_all_subscribers_once(published: Workspace) -> None:
    settings = configured(published)
    kit = FakeKit()
    with published.factory() as session:
        result = send_newsletter(session, settings, client=kit.client())
    assert result.sent and result.broadcast_id == 42
    (request,) = kit.requests
    assert request.url.path == "/v4/broadcasts"
    assert request.headers["X-Kit-Api-Key"] == "chave-secreta"
    body = kit.bodies()[0]
    assert body["subscriber_filter"] == []  # todos os assinantes
    assert body["public"] is True and body["send_at"] and body["content"]
    assert not body["subject"].startswith("[TESTE]")
    marker = sent_marker(settings.editions_dir, "edicao-001")
    assert json.loads(marker.read_text(encoding="utf-8"))["broadcast_id"] == 42

    with published.factory() as session:
        again = send_newsletter(session, settings, client=kit.client())
    assert not again.sent and "já foi enviada" in again.message
    assert len(kit.requests) == 1  # nada novo foi enviado


def test_test_send_targets_tag_and_records_nothing(published: Workspace) -> None:
    settings = configured(published, kit_test_tag_id=5)
    kit = FakeKit()
    with published.factory() as session:
        result = send_newsletter(session, settings, test=True, client=kit.client())
    assert result.sent and result.test
    body = kit.bodies()[0]
    assert body["subscriber_filter"] == [
        {"all": [{"type": "tag", "ids": [5]}], "any": None, "none": None}
    ]
    assert body["subject"].startswith("[TESTE] ") and body["public"] is False
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_schedule_is_a_few_minutes_ahead() -> None:
    kit = FakeKit()
    now = datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)
    kit.client().schedule_broadcast(
        subject="s", preview_text="p", description="d", html="<p>x</p>", public=True, now=now
    )
    body = kit.bodies()[0]
    assert body["published_at"] == "2026-11-16T11:00:00Z"
    assert body["send_at"] == "2026-11-16T11:02:00Z"


def test_draft_response_is_an_error(published: Workspace) -> None:
    settings = configured(published)
    with published.factory() as session, pytest.raises(NewsletterError, match="rascunho"):
        send_newsletter(session, settings, client=FakeKit(draft=True).client())
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_missing_configuration_is_reported(published: Workspace) -> None:
    with published.factory() as session, pytest.raises(NewsletterError) as error:
        send_newsletter(session, published.settings, test=True)
    message = str(error.value)
    assert "KIT_API_KEY" in message and "SITE_URL" in message and "KIT_TEST_TAG_ID" in message


def test_kit_error_does_not_leak_key_or_mark_as_sent(published: Workspace) -> None:
    settings = configured(published)
    with published.factory() as session, pytest.raises(NewsletterError) as error:
        send_newsletter(session, settings, client=FakeKit(status=401).client())
    assert "401" in str(error.value) and "chave-secreta" not in str(error.value)
    assert not sent_marker(settings.editions_dir, "edicao-001").exists()


def test_nothing_published_means_nothing_to_send(workspace: Workspace) -> None:
    with workspace.factory() as session, pytest.raises(NewsletterError):
        send_newsletter(session, configured(workspace), client=FakeKit().client())


def test_site_shows_subscribe_button_only_when_configured(published: Workspace) -> None:
    out = published.settings.output_dir
    with published.factory() as session:
        build_site(session, out, timezone_name="UTC")
    assert "Assinar a newsletter" not in (out / "index.html").read_text(encoding="utf-8")
    url = "https://ufabc-science.kit.com/assinar"
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


def test_cli_skips_quietly_without_key(
    published: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", published.settings.database_url)
    assert main(["newsletter", "send", "--skip-if-unconfigured"]) == 0
    assert "não configurada" in capsys.readouterr().out
    assert main(["newsletter", "send"]) == 1  # sem a opção, a falta de chave é um erro
