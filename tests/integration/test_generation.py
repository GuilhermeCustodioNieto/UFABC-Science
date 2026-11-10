"""Seleção, geração, versionamento, verificação e exportação Markdown (Etapa 3)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select

from tests.conftest import FakeApis, Workspace
from ufabc_science.collectors.service import collect_articles
from ufabc_science.domain.enums import EditorialStatus, VerificationStatus
from ufabc_science.domain.models import Article, EditorialReview, GeneratedContent
from ufabc_science.editorial.markdown import find_article_files, read_document
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.intelligence import generation
from ufabc_science.intelligence.base import AIProvider, AIResponse
from ufabc_science.intelligence.generation import generate_contents, select_for_generation
from ufabc_science.intelligence.provider import MockProvider
from ufabc_science.intelligence.schemas import DEFAULT_WORD_LIMITS
from ufabc_science.processing.classification import classify_articles, load_rules
from ufabc_science.processing.relevance import latest_assessment, score_articles


@pytest.fixture
def prepared(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    collect_articles(
        workspace.settings,
        workspace.factory,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 8),
        query="teste",
        max_articles=10,
        transport=fake_apis.transport(),
    )
    with session_scope(workspace.factory) as session:
        classify_articles(session, rules=load_rules(), min_confidence=0.35, uncertain_below=0.5)
        score_articles(session, today=date(2026, 11, 9))
    return workspace


def run(ws: Workspace, provider: AIProvider | None = None, **kwargs: Any):
    params: dict[str, Any] = {
        "editorial_dir": ws.editorial,
        "limit": 3,
        "min_abstract_words": 40,
        "max_attempts": 3,
    }
    params.update(kwargs)
    return generate_contents(ws.factory, provider or MockProvider(), **params)


def test_generation_creates_pending_markdown_and_never_approves(prepared: Workspace) -> None:
    summary = run(prepared)

    assert summary.generated == 3
    files = find_article_files(prepared.editorial)
    assert len(files) == 3
    for path in files:
        assert path.parent.name == "pending"
        doc = read_document(path)
        assert doc.status == EditorialStatus.PENDING_REVIEW.value
        assert doc.metadata["model_provider"] == "mock"
        assert doc.metadata["verification_status"] in {"passed", "warning", "failed"}
        assert not doc.manually_edited
        assert doc.source_link == doc.metadata["source_url"]
    with prepared.factory() as session:
        approved = session.scalar(
            select(func.count())
            .select_from(EditorialReview)
            .where(EditorialReview.status == EditorialStatus.APPROVED)
        )
        assert approved == 0
        record = session.scalars(select(GeneratedContent)).first()
        assert record is not None
        assert record.input_hash and len(record.input_hash) == 64
        assert record.prompt_version == generation.ARTICLE_GENERATION_PROMPT.version
        assert record.reference and record.source_url


def test_selection_prioritizes_relevance(prepared: Workspace) -> None:
    with prepared.factory() as session:
        selection = select_for_generation(
            session, limit=3, min_abstract_words=40, word_limits=DEFAULT_WORD_LIMITS
        )
        scores = [c.score for c in selection.selected]
        others = [
            latest_assessment(session.get(Article, i)).final_score
            for i in selection.skipped.get("limite_de_processamento", [])
        ]
    assert scores == sorted(scores, reverse=True)
    assert min(scores) >= max(others)


def test_unchanged_articles_are_not_regenerated(prepared: Workspace) -> None:
    first = run(prepared, limit=20)
    second = run(prepared, limit=20)

    assert first.generated > 0
    assert second.generated == 0
    assert len(second.skipped["sem_alteracoes"]) == first.generated


def test_input_change_creates_new_version_and_preserves_history(
    prepared: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(prepared, limit=1)
    with prepared.factory() as session:
        article_id = session.scalars(select(GeneratedContent.article_id)).one()

    # Mudar a versão do prompt muda o hash de entrada -> nova versão permitida.
    newer = generation.ARTICLE_GENERATION_PROMPT.__class__(
        **{**generation.ARTICLE_GENERATION_PROMPT.__dict__, "version": "2099-01-v9"}
    )
    monkeypatch.setattr(generation, "ARTICLE_GENERATION_PROMPT", newer)
    summary = run(prepared, article_ids=[article_id])

    assert summary.generated == 1
    with prepared.factory() as session:
        versions = session.scalars(
            select(GeneratedContent.version)
            .where(GeneratedContent.article_id == article_id)
            .order_by(GeneratedContent.version)
        ).all()
        hashes = set(session.scalars(select(GeneratedContent.input_hash)))
    assert versions == [1, 2]
    assert len(hashes) == 2


def test_force_regenerates_same_input(prepared: Workspace) -> None:
    run(prepared, limit=1)
    with prepared.factory() as session:
        article_id = session.scalars(select(GeneratedContent.article_id)).one()
    assert run(prepared, article_ids=[article_id]).generated == 0
    assert run(prepared, article_ids=[article_id], force=True).generated == 1
    history = list((prepared.editorial / "history").glob(f"article-{article_id}.v1.md"))
    assert history, "a versão anterior do Markdown deve ser arquivada"


class FlakyProvider(MockProvider):
    """Primeira resposta inválida (JSON incompleto), depois válida."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def generate_structured(self, prompt, response_schema, *, system=None) -> AIResponse:
        self.calls += 1
        if self.calls <= self.failures:
            return AIResponse({"headline": "x"}, "flaky", "f", {"total_tokens": 7})
        return super().generate_structured(prompt, response_schema, system=system)


def test_invalid_ai_response_is_retried(prepared: Workspace) -> None:
    provider = FlakyProvider(failures=1)
    summary = run(prepared, provider, limit=1)
    assert summary.generated == 1
    with prepared.factory() as session:
        record = session.scalars(select(GeneratedContent)).one()
        assert record.usage["attempts"] == 2


def test_invalid_ai_response_is_never_persisted(prepared: Workspace) -> None:
    provider = FlakyProvider(failures=99)
    summary = run(prepared, provider, limit=1, max_attempts=2)
    assert summary.generated == 0
    assert summary.errors and "inválida" in summary.errors[0]
    assert provider.calls == 2  # tentativas limitadas
    with prepared.factory() as session:
        assert session.scalar(select(func.count()).select_from(GeneratedContent)) == 0
    assert find_article_files(prepared.editorial) == []


class InventingProvider(MockProvider):
    """Simula um modelo que inventa estatísticas."""

    def generate_structured(self, prompt, response_schema, *, system=None) -> AIResponse:
        response = super().generate_structured(prompt, response_schema, system=system)
        data = dict(response.data)
        data["findings"] = "O tratamento curou 97,3% dos 12.345 participantes avaliados."
        return AIResponse(data, "inventor", "x", {})


def test_failed_verification_blocks_content(prepared: Workspace) -> None:
    summary = run(prepared, InventingProvider(), limit=1)
    assert summary.failed == 1
    path = find_article_files(prepared.editorial)[0]
    doc = read_document(path)
    assert doc.metadata["verification_status"] == "failed"
    assert any("Números sem correspondência" in m for m in doc.metadata["verification_messages"])

    again = run(prepared, InventingProvider(), limit=10)
    assert doc.article_id in again.skipped["bloqueado_por_verificacao"]


def test_articles_with_insufficient_information_are_not_sent_to_ai(
    prepared: Workspace,
) -> None:
    with session_scope(prepared.factory) as session:
        article = session.scalars(select(Article)).first()
        article.abstract = "Resumo curto."
        target = article.id
    summary = run(prepared, limit=20)
    assert target in summary.skipped["informacao_insuficiente"]


def test_manually_edited_markdown_is_never_overwritten(prepared: Workspace) -> None:
    run(prepared, limit=1)
    path = find_article_files(prepared.editorial)[0]
    edited = path.read_text(encoding="utf-8").replace("## Introdução\n", "## Introdução\n\nNota.\n")
    path.write_text(edited, encoding="utf-8")
    article_id = read_document(path).article_id

    run(prepared, article_ids=[article_id], force=False)
    with session_scope(prepared.factory) as session:
        session.get(Article, article_id).abstract += " Additional sentence added later by source."
    run(prepared, article_ids=[article_id])

    assert path.read_text(encoding="utf-8") == edited
    proposed = list((prepared.editorial / "history").glob(f"article-{article_id}.v2.proposed.md"))
    assert proposed


def test_verify_command_reverifies_latest_versions(prepared: Workspace) -> None:
    run(prepared, limit=2)
    summary = generation.verify_contents(prepared.factory, min_abstract_words=40)
    assert summary.verified == 2
    with prepared.factory() as session:
        statuses = set(session.scalars(select(GeneratedContent.verification_status)))
    assert statuses <= set(VerificationStatus)
