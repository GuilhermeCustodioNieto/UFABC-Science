"""Publicação automática: só rascunhos de IA real com verificação PASSED e sem avisos."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from tests.conftest import FakeApis, Workspace
from ufabc_science.collectors.service import collect_articles
from ufabc_science.domain.enums import EditionStatus, EditorialStatus
from ufabc_science.domain.models import EditorialReview, NewsletterEdition
from ufabc_science.editorial.approval import latest_approval
from ufabc_science.editorial.autopublish import AUTO_REVIEWER, AutoPublishReport, auto_publish
from ufabc_science.editorial.markdown import find_article_files, read_document
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.intelligence.base import AIProvider
from ufabc_science.intelligence.generation import generate_contents
from ufabc_science.intelligence.provider import MockProvider
from ufabc_science.main import main
from ufabc_science.processing.classification import classify_articles, load_rules
from ufabc_science.processing.relevance import score_articles
from ufabc_science.publisher.html import AI_NOTICE, build_site

MONDAY = date(2026, 11, 9)


class CleanProvider(MockProvider):
    """Simula um modelo real: mesmo conteúdo do mock, sem as marcas de rascunho mock."""

    name = "test_llm"
    model = "test-model"

    @staticmethod
    def _draft(payload: dict[str, Any]) -> dict[str, Any]:
        draft = MockProvider._draft(payload)
        # Título e frases curtas, como pede a política editorial (o mock copia o abstract).
        draft["headline"] = draft["headline"].replace("[Rascunho mock] ", "").replace(":", ",")
        note = "Trata-se de um preprint, ainda não revisado por pares; os resultados podem mudar."
        for name in ("discovery", "how_it_works", "why_it_matters", "limitations"):
            words = draft[name].replace(note, "").split()[:110]
            draft[name] = " ".join(
                " ".join(words[i : i + 16]).rstrip(".") + "." for i in range(0, len(words), 16)
            )
        if payload.get("revisao_por_pares") == "preprint":
            draft["limitations"] += " " + note
        draft["uncertainty_notes"] = []
        return draft


def prepare(ws: Workspace, fake_apis: FakeApis, provider: AIProvider) -> None:
    collect_articles(
        ws.settings,
        ws.factory,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 8),
        query="teste",
        max_articles=10,
        transport=fake_apis.transport(),
    )
    with session_scope(ws.factory) as session:
        classify_articles(session, rules=load_rules(), min_confidence=0.35, uncertain_below=0.5)
        score_articles(session, today=MONDAY)
    generate_contents(
        ws.factory,
        provider,
        editorial_dir=ws.editorial,
        limit=10,
        min_abstract_words=40,
        min_score=0,  # a curadoria tem testes próprios (tests/unit/test_curation.py)
        require_ai_curation=False,
    )


def statuses(ws: Workspace) -> dict[int, str]:
    result = {}
    for path in find_article_files(ws.editorial):
        doc = read_document(path)
        result[doc.article_id] = doc.metadata["verification_status"]
    return result


def run(ws: Workspace, today: date = MONDAY, **kwargs: Any) -> AutoPublishReport:
    with session_scope(ws.factory) as session:
        return auto_publish(
            session,
            editorial_dir=ws.editorial,
            editions_dir=ws.settings.editions_dir,
            today=today,
            min_abstract_words=40,
            **kwargs,
        )


@pytest.fixture
def llm_drafts(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    prepare(workspace, fake_apis, CleanProvider())
    return workspace


def test_only_passed_drafts_are_approved_and_published(llm_drafts: Workspace) -> None:
    ws = llm_drafts
    by_status = statuses(ws)
    passed = {i for i, s in by_status.items() if s == "passed"}
    not_passed = set(by_status) - passed
    assert passed and not_passed  # o cenário cobre os dois casos

    report = run(ws)

    assert set(report.approved) == passed
    assert set(report.skipped) == not_passed
    assert all("WARNING" in reason for reason in report.skipped.values())
    assert report.published and set(report.edition_articles) == passed
    with session_scope(ws.factory) as session:
        edition = session.scalars(select(NewsletterEdition)).one()
        assert edition.status is EditionStatus.PUBLISHED
        assert edition.week == "2026-W46"
        assert edition.published_by == AUTO_REVIEWER
        assert "Não houve revisão humana" in (edition.introduction or "")
        for item in edition.items:
            assert item.review is not None and item.review.reviewer == AUTO_REVIEWER
            assert item.review.content_snapshot  # mesmo registro auditável da aprovação humana
    # Rascunhos com aviso continuam pendentes para eventual revisão humana.
    for path in find_article_files(ws.editorial):
        doc = read_document(path)
        expected = "approved" if doc.article_id in passed else "pending"
        assert path.parent.name == expected


def test_site_shows_ai_notice_for_automatic_editions(llm_drafts: Workspace) -> None:
    run(llm_drafts)
    with llm_drafts.factory() as session:
        result = build_site(session, llm_drafts.settings.output_dir, timezone_name="UTC")
    assert not result.errors
    home = (llm_drafts.settings.output_dir / "index.html").read_text(encoding="utf-8")
    assert AI_NOTICE in home


def test_human_site_has_no_ai_notice(workspace: Workspace) -> None:
    with workspace.factory() as session:
        build_site(session, workspace.settings.output_dir, timezone_name="UTC")
    home = (workspace.settings.output_dir / "index.html").read_text(encoding="utf-8")
    assert AI_NOTICE not in home


def test_mock_drafts_are_never_auto_approved(workspace: Workspace, fake_apis: FakeApis) -> None:
    prepare(workspace, fake_apis, MockProvider())
    report = run(workspace)
    assert report.approved == []
    assert all(reason == "gerado pelo provedor mock" for reason in report.skipped.values())
    assert not report.published
    with workspace.factory() as session:
        assert session.scalars(select(NewsletterEdition)).first() is None


def test_manually_edited_draft_waits_for_human(llm_drafts: Workspace) -> None:
    ws = llm_drafts
    passed = sorted(i for i, s in statuses(ws).items() if s == "passed")
    name = f"article-{passed[0]}.md"
    target = next(p for p in find_article_files(ws.editorial) if p.name == name)
    text = target.read_text(encoding="utf-8")
    edited = text.replace("## A descoberta\n\n", "## A descoberta\n\nTexto editado. ", 1)
    assert edited != text
    target.write_text(edited, encoding="utf-8")

    report = run(ws)

    assert passed[0] not in report.approved
    assert "editado manualmente" in report.skipped[passed[0]]


def test_same_week_is_not_published_twice_and_articles_are_not_repeated(
    llm_drafts: Workspace,
) -> None:
    first = run(llm_drafts)
    assert first.published
    again = run(llm_drafts)
    assert not again.published and "já foi publicada" in again.message
    # Semana seguinte sem rascunhos novos: nenhum artigo é republicado.
    next_week = run(llm_drafts, today=date(2026, 11, 16))
    assert not next_week.published and next_week.edition_number is None
    with llm_drafts.factory() as session:
        assert len(session.scalars(select(NewsletterEdition)).all()) == 1


def test_max_articles_limits_the_edition(llm_drafts: Workspace) -> None:
    report = run(llm_drafts, max_articles=2)
    assert report.published and len(report.edition_articles) == 2
    # Os demais aprovados ficam para a próxima semana.
    later = run(llm_drafts, today=date(2026, 11, 16))
    assert later.published
    assert set(later.edition_articles).isdisjoint(report.edition_articles)


def test_auto_approval_is_recorded_like_a_human_review(llm_drafts: Workspace) -> None:
    report = run(llm_drafts)
    with llm_drafts.factory() as session:
        reviews = session.scalars(
            select(EditorialReview).where(EditorialReview.status == EditorialStatus.APPROVED)
        ).all()
        assert {r.article_id for r in reviews} == set(report.approved)
        for review in reviews:
            assert review.reviewer == AUTO_REVIEWER
            assert latest_approval(review.article) is review


def test_cli_requires_explicit_opt_in(
    llm_drafts: Workspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = llm_drafts.settings
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DATA_DIR", settings.data_dir.as_posix())
    monkeypatch.setenv("EDITIONS_DIR", settings.editions_dir.as_posix())
    assert main(["autopublish", "--date", "2026-11-09"]) == 1
    with llm_drafts.factory() as session:
        assert session.scalars(select(NewsletterEdition)).first() is None

    output = tmp_path / "github_output"
    monkeypatch.setenv("AUTO_PUBLISH", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", output.as_posix())
    assert main(["autopublish", "--date", "2026-11-09"]) == 0
    assert "published=true" in output.read_text(encoding="utf-8")
