"""Pipeline automatizado (Etapa 5): execução, idempotência, falhas e salvaguardas."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tests.conftest import FakeApis, Workspace
from ufabc_science.domain.enums import EditionStatus, EditorialStatus, RunStatus
from ufabc_science.domain.models import (
    Article,
    EditorialReview,
    GeneratedContent,
    NewsletterEdition,
    PipelineRun,
    utcnow,
)
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.pipeline.lock import ConcurrentRunError, PipelineLock
from ufabc_science.pipeline.runner import ALL_STEPS, RunParameters, run_pipeline

TODAY = date(2026, 11, 9)


def params(**kwargs: object) -> RunParameters:
    data: dict[str, object] = {
        "days": 7,
        "sources": ["openalex", "pubmed", "arxiv", "crossref"],
        "max_articles": 10,
        "generation_limit": 3,
        "steps": ALL_STEPS,
    }
    data.update(kwargs)
    return RunParameters(**data)  # type: ignore[arg-type]


def run(ws: Workspace, apis: FakeApis, **kwargs: object):
    return run_pipeline(
        ws.settings, ws.factory, params(**kwargs), transport=apis.transport(), today=TODAY
    )


def count(ws: Workspace, model) -> int:
    with ws.factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_full_run_without_credentials(workspace: Workspace, fake_apis: FakeApis) -> None:
    summary = run(workspace, fake_apis)

    assert summary.status is RunStatus.SUCCESS, summary.errors
    stats = summary.stats
    assert stats["sources_consulted"] == ["openalex", "pubmed", "arxiv", "crossref"]
    assert stats["articles_found"] == 8 and stats["articles_new"] == 8
    assert stats["articles_classified"] > 0
    assert stats["contents_generated"] == 3
    assert stats["ai_provider"] == "mock"
    assert len(list((workspace.editorial / "pending").glob("article-*.md"))) == 3
    with workspace.factory() as session:
        record = session.get(PipelineRun, summary.run_id)
        assert record is not None and record.status is RunStatus.SUCCESS
        assert record.finished_at is not None and record.duration_seconds is not None
    report = next(workspace.settings.runs_dir.glob(f"*-{summary.run_id}.json"))
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "success"


def test_pipeline_never_approves_or_publishes(workspace: Workspace, fake_apis: FakeApis) -> None:
    run(workspace, fake_apis)
    run(workspace, fake_apis)
    with workspace.factory() as session:
        approved = session.scalar(
            select(func.count())
            .select_from(EditorialReview)
            .where(EditorialReview.status == EditorialStatus.APPROVED)
        )
        published = session.scalar(
            select(func.count())
            .select_from(NewsletterEdition)
            .where(NewsletterEdition.status == EditionStatus.PUBLISHED)
        )
    assert approved == 0 and published == 0
    assert not workspace.settings.output_dir.exists()
    for path in workspace.editorial.rglob("article-*.md"):
        assert "status: approved" not in path.read_text(encoding="utf-8")


def test_second_run_is_idempotent(workspace: Workspace, fake_apis: FakeApis) -> None:
    run(workspace, fake_apis, generation_limit=20)
    articles, contents = count(workspace, Article), count(workspace, GeneratedContent)

    second = run(workspace, fake_apis, generation_limit=20)

    assert second.stats["articles_new"] == 0
    assert second.stats["articles_duplicate"] == 8
    assert second.stats["contents_generated"] == 0
    assert (count(workspace, Article), count(workspace, GeneratedContent)) == (articles, contents)


def test_partial_failure_of_one_source(workspace: Workspace) -> None:
    summary = run(workspace, FakeApis(fail={"crossref"}))

    assert summary.status is RunStatus.PARTIAL_SUCCESS
    assert summary.stats["failed_sources"] == ["crossref"]
    assert summary.stats["articles_new"] == 6
    assert summary.stats["contents_generated"] == 3  # demais etapas continuaram


def test_partial_steps(workspace: Workspace, fake_apis: FakeApis) -> None:
    summary = run(workspace, fake_apis, steps=("collect", "classify"))
    assert summary.status is RunStatus.SUCCESS
    assert "contents_generated" not in summary.stats
    assert count(workspace, GeneratedContent) == 0

    process = run(workspace, fake_apis, steps=("score", "generate"))
    assert process.stats["contents_generated"] == 3
    assert "articles_found" not in process.stats


def test_failure_when_every_step_fails(workspace: Workspace, monkeypatch) -> None:
    import ufabc_science.pipeline.runner as runner

    def boom(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(runner, "collect_articles", boom)
    summary = run(workspace, FakeApis(), steps=("collect",))
    assert summary.status is RunStatus.FAILED
    assert "falha simulada" in summary.errors[0]


def test_concurrent_runs_are_blocked(workspace: Workspace, fake_apis: FakeApis) -> None:
    lock = PipelineLock(
        workspace.settings.lock_path, run_id="outra", stale_after=timedelta(hours=6)
    )
    with lock, pytest.raises(ConcurrentRunError):
        run(workspace, fake_apis)
    assert count(workspace, PipelineRun) == 0


def test_running_record_blocks_and_stale_record_is_recovered(
    workspace: Workspace, fake_apis: FakeApis
) -> None:
    with session_scope(workspace.factory) as session:
        session.add(PipelineRun(id="ativa", status=RunStatus.RUNNING, started_at=utcnow()))
    with pytest.raises(ConcurrentRunError):
        run(workspace, fake_apis)

    with session_scope(workspace.factory) as session:
        session.get(PipelineRun, "ativa").started_at = utcnow() - timedelta(hours=12)
    summary = run(workspace, fake_apis)

    assert summary.status is RunStatus.SUCCESS
    assert any("interrompida" in m for m in summary.messages)
    with workspace.factory() as session:
        assert session.get(PipelineRun, "ativa").status is RunStatus.FAILED


def test_recovery_after_interrupted_generation(
    workspace: Workspace, fake_apis: FakeApis, monkeypatch
) -> None:
    import ufabc_science.pipeline.runner as runner

    original = runner.generate_contents

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "generate_contents", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(workspace, fake_apis)
    assert not workspace.settings.lock_path.exists()  # trava liberada mesmo com interrupção
    assert count(workspace, Article) == 8  # coleta já persistida

    with workspace.factory() as session:
        interrupted_run = session.scalars(select(PipelineRun)).one()
        assert interrupted_run.status is RunStatus.FAILED
        assert "interrompida" in interrupted_run.errors[-1]

    monkeypatch.setattr(runner, "generate_contents", original)
    summary = run(workspace, fake_apis)
    assert summary.status is RunStatus.SUCCESS
    assert summary.stats["articles_new"] == 0
    assert summary.stats["contents_generated"] == 3


def test_github_step_summary_is_written(
    workspace: Workspace, fake_apis: FakeApis, monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    summary = run(workspace, fake_apis, steps=("collect",))
    text = target.read_text(encoding="utf-8")
    assert summary.run_id in text
    assert "Nenhum conteúdo foi aprovado ou publicado" in text
    assert "Artigos novos | 8" in text


def test_summary_explains_when_no_draft_was_generated(
    workspace: Workspace, fake_apis: FakeApis
) -> None:
    summary = run(workspace, fake_apis, steps=("collect", "classify", "score"))
    text = summary.to_markdown()
    assert "Nenhum rascunho foi gerado" in text
    assert "configure um provedor de IA" in text
    assert "Revise os novos rascunhos" not in text


def test_collection_window_covers_gap_since_last_successful_collection(
    workspace: Workspace, fake_apis: FakeApis
) -> None:
    with session_scope(workspace.factory) as session:
        session.add(
            PipelineRun(
                id="antiga",
                status=RunStatus.SUCCESS,
                started_at=utcnow() - timedelta(days=20),
                stats={"collection_window": ["2026-10-13", "2026-10-20"]},
            )
        )
    summary = run(workspace, fake_apis, steps=("collect",))
    assert summary.stats["collection_window"] == ["2026-10-20", TODAY.isoformat()]
    assert any("Lacuna" in m for m in summary.messages)

    # Sem lacuna, a janela padrão (days) é usada.
    again = run(workspace, fake_apis, steps=("collect",))
    assert again.stats["collection_window"] == ["2026-11-02", TODAY.isoformat()]
