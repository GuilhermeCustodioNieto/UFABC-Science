"""Pipeline automatizado (Etapa 5): coleta → enriquecimento → classificação →
relevância → seleção/geração/verificação → exportação Markdown.

A rotina **nunca** aprova, cria edição final ou publica. Cada execução é
registrada em ``pipeline_runs`` e em ``data/runs/<run_id>.json``. Todas as
etapas são idempotentes, então reexecutar após uma falha continua de onde parou.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science.collectors.service import (
    collect_articles,
    collection_window,
    enrich_with_crossref,
)
from ufabc_science.config.settings import Settings
from ufabc_science.domain.enums import RunStatus
from ufabc_science.domain.models import PipelineRun, utcnow
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.intelligence.base import AIProvider
from ufabc_science.intelligence.generation import generate_contents
from ufabc_science.intelligence.provider import build_provider
from ufabc_science.pipeline.lock import PipelineLock
from ufabc_science.processing.classification import classify_articles, load_rules
from ufabc_science.processing.relevance import score_articles

logger = logging.getLogger(__name__)

ALL_STEPS = ("collect", "enrich", "classify", "score", "generate")
PROCESS_STEPS = ("classify", "score", "generate")


@dataclass
class RunParameters:
    days: int
    sources: list[str]
    max_articles: int | None = None
    generation_limit: int = 10
    steps: tuple[str, ...] = ALL_STEPS
    trigger: str = "local"
    start_date: date | None = None
    end_date: date | None = None
    use_ai_classification: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "sources": self.sources,
            "max_articles": self.max_articles,
            "generation_limit": self.generation_limit,
            "steps": list(self.steps),
            "trigger": self.trigger,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }


@dataclass
class RunSummary:
    run_id: str
    status: RunStatus
    started_at: datetime
    duration_seconds: float
    parameters: dict[str, Any]
    stats: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "duration_seconds": round(self.duration_seconds, 2),
            "parameters": self.parameters,
            "stats": self.stats,
            "errors": self.errors,
            "messages": self.messages,
        }

    def to_markdown(self) -> str:
        s = self.stats
        rows = [
            ("Status", self.status.value.upper()),
            ("Fontes consultadas", ", ".join(s.get("sources_consulted", [])) or "-"),
            ("Artigos encontrados", s.get("articles_found", 0)),
            ("Artigos novos", s.get("articles_new", 0)),
            ("Artigos duplicados (já existentes)", s.get("articles_duplicate", 0)),
            ("Possíveis duplicatas sinalizadas", s.get("possible_duplicates", 0)),
            ("Artigos classificados", s.get("articles_classified", 0)),
            ("Artigos selecionados", s.get("articles_selected", 0)),
            ("Conteúdos gerados", s.get("contents_generated", 0)),
            ("Conteúdos com falha de verificação", s.get("verification_failed", 0)),
            ("Erros de coleta", s.get("collection_errors", 0)),
            ("Duração total", f"{self.duration_seconds:.1f} s"),
        ]
        lines = [
            f"## UFABC Science — execução `{self.run_id}`",
            "",
            "| Item | Valor |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in rows],
            "",
            "> Nenhum conteúdo foi aprovado ou publicado por esta execução. "
            + (
                "Revise os novos rascunhos em `data/editorial/pending/`."
                if s.get("contents_generated")
                else "Nenhum rascunho foi gerado nesta execução"
                + (
                    " (etapa de geração não executada: configure um provedor de IA ou gere "
                    "localmente com `python -m ufabc_science generate`)."
                    if "generate" not in self.parameters.get("steps", [])
                    else "."
                )
            ),
        ]
        if self.errors:
            lines += ["", "### Erros", "", *[f"- {e}" for e in self.errors]]
        return "\n".join(lines) + "\n"


MAX_GAP_DAYS = 60


def last_collected_until(
    factory: sessionmaker[Session], *, exclude: str | None = None
) -> date | None:
    """Data final da última janela de coleta concluída (SUCCESS ou PARTIAL_SUCCESS)."""
    with factory() as session:
        runs = session.scalars(
            select(PipelineRun)
            .where(PipelineRun.status.in_([RunStatus.SUCCESS, RunStatus.PARTIAL_SUCCESS]))
            .order_by(PipelineRun.started_at.desc())
        )
        for run in runs:
            window = (run.stats or {}).get("collection_window")
            if run.id != exclude and window:
                return date.fromisoformat(window[1])
    return None


def recover_interrupted_runs(factory: sessionmaker[Session], stale_after: timedelta) -> int:
    """Marca como ``FAILED`` execuções ``RUNNING`` abandonadas (processo interrompido)."""
    recovered = 0
    limit = datetime.now(timezone.utc) - stale_after
    with session_scope(factory) as session:
        for run in session.scalars(
            select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)
        ):
            if run.started_at < limit:
                run.status = RunStatus.FAILED
                run.finished_at = utcnow()
                run.errors = [*(run.errors or []), "Execução interrompida (recuperada depois)."]
                recovered += 1
    return recovered


def _running_elsewhere(
    factory: sessionmaker[Session], stale_after: timedelta
) -> PipelineRun | None:
    limit = datetime.now(timezone.utc) - stale_after
    with factory() as session:
        for run in session.scalars(
            select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)
        ):
            if run.started_at >= limit:
                return run
    return None


def run_pipeline(
    settings: Settings,
    factory: sessionmaker[Session],
    params: RunParameters,
    *,
    provider: AIProvider | None = None,
    transport: httpx.BaseTransport | None = None,
    today: date | None = None,
) -> RunSummary:
    """Executa o pipeline com trava exclusiva e registro completo."""
    from ufabc_science.pipeline.lock import ConcurrentRunError

    run_id = uuid.uuid4().hex[:12]
    stale_after = timedelta(hours=settings.pipeline_lock_stale_hours)
    lock = PipelineLock(settings.lock_path, run_id=run_id, stale_after=stale_after)
    lock.acquire()
    try:
        recovered = recover_interrupted_runs(factory, stale_after)
        other = _running_elsewhere(factory, stale_after)
        if other is not None:
            raise ConcurrentRunError(
                f"A execução {other.id} consta como em andamento desde {other.started_at}."
            )
        return _execute(
            settings, factory, params, run_id, recovered, provider=provider,
            transport=transport, today=today,
        )  # fmt: skip
    finally:
        lock.release()


def _execute(
    settings: Settings,
    factory: sessionmaker[Session],
    params: RunParameters,
    run_id: str,
    recovered: int,
    *,
    provider: AIProvider | None,
    transport: httpx.BaseTransport | None,
    today: date | None,
) -> RunSummary:
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    with session_scope(factory) as session:
        session.add(
            PipelineRun(
                id=run_id,
                trigger=params.trigger,
                status=RunStatus.RUNNING,
                started_at=started,
                parameters=params.as_dict(),
            )
        )
    stats: dict[str, Any] = {"sources_consulted": []}
    errors: list[str] = []
    messages: list[str] = []
    if recovered:
        messages.append(f"{recovered} execução(ões) interrompida(s) marcada(s) como FAILED.")
    step_failures = 0
    executed = 0

    def step(name: str, func: Any) -> None:
        nonlocal step_failures, executed
        if name not in params.steps:
            return
        executed += 1
        logger.info("[%s] etapa %s", run_id, name)
        try:
            func()
        except Exception as exc:
            step_failures += 1
            errors.append(f"etapa {name}: {type(exc).__name__}: {exc}")
            logger.exception("[%s] etapa %s falhou", run_id, name)

    def do_collect() -> None:
        if params.start_date and params.end_date:
            start, end = params.start_date, params.end_date
        else:
            start, end = collection_window(params.days, today)
            last_end = last_collected_until(factory, exclude=run_id)
            if last_end is not None and last_end < start:
                # Coleta incremental: cobre a lacuna desde a última coleta bem-sucedida.
                gap_start = max(last_end, end - timedelta(days=MAX_GAP_DAYS))
                messages.append(
                    f"Lacuna desde a última coleta ({last_end.isoformat()}): janela ampliada "
                    f"para começar em {gap_start.isoformat()}."
                )
                start = gap_start
        summary = collect_articles(
            settings,
            factory,
            start_date=start,
            end_date=end,
            sources=params.sources,
            max_articles=params.max_articles,
            transport=transport,
        )
        stats["sources_consulted"] = [s.source for s in summary.sources]
        stats["collection_window"] = [start.isoformat(), end.isoformat()]
        stats["articles_found"] = summary.total("collected")
        stats["articles_new"] = summary.total("inserted")
        stats["articles_duplicate"] = summary.total("updated") + summary.total("ignored")
        stats["possible_duplicates"] = summary.total("flagged_duplicates")
        stats["collection_errors"] = len(summary.errors)
        stats["failed_sources"] = summary.failed_sources
        stats["per_source"] = summary.as_dict()["sources"]
        errors.extend(summary.errors)

    def do_enrich() -> None:
        if "crossref" not in params.sources:
            messages.append("Enriquecimento Crossref ignorado (fonte desabilitada).")
            return
        result = enrich_with_crossref(settings, factory, transport=transport)
        stats["crossref_checked"] = result.checked
        stats["crossref_confirmed"] = result.confirmed
        errors.extend(result.errors)

    ai = provider or build_provider(settings)

    def do_classify() -> None:
        with session_scope(factory) as session:
            summary = classify_articles(
                session,
                rules=load_rules(
                    str(settings.classification_rules_path)
                    if settings.classification_rules_path
                    else None
                ),
                min_confidence=settings.classification_min_confidence,
                uncertain_below=settings.classification_uncertain_below,
                provider=ai if params.use_ai_classification and settings.ai_enabled else None,
            )
        stats["articles_classified"] = summary.classified
        stats["articles_without_category"] = summary.without_category
        stats["classification_uncertain"] = summary.uncertain

    def do_score() -> None:
        with session_scope(factory) as session:
            summary = score_articles(session, today=today)
        stats["articles_scored"] = summary.assessed

    def do_generate() -> None:
        summary = generate_contents(
            factory,
            ai,
            editorial_dir=settings.editorial_dir,
            limit=params.generation_limit,
            min_abstract_words=settings.min_abstract_words,
            word_limits=settings.generation_word_limits,
            max_attempts=settings.ai_max_retries + 1,
        )
        stats["ai_provider"] = ai.name
        stats["articles_selected"] = summary.selected
        stats["contents_generated"] = summary.generated
        stats["verification_passed"] = summary.passed
        stats["verification_warning"] = summary.warnings
        stats["verification_failed"] = summary.failed
        stats["generation_skipped"] = {k: len(v) for k, v in summary.skipped.items()}
        stats["markdown_files"] = summary.files
        errors.extend(summary.errors)
        if ai.name == "mock":
            messages.append(
                "Provedor de IA 'mock': rascunhos extrativos para desenvolvimento, "
                "não textos editoriais."
            )

    try:
        step("collect", do_collect)
        step("enrich", do_enrich)
        step("classify", do_classify)
        step("score", do_score)
        step("generate", do_generate)
    except BaseException as exc:  # interrupcao (Ctrl+C, sinal): registra antes de propagar
        with session_scope(factory) as session:
            run = session.get(PipelineRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.finished_at = utcnow()
                run.duration_seconds = round(time.monotonic() - clock, 2)
                run.stats = stats
                run.errors = [*errors, f"Execucao interrompida: {type(exc).__name__}"]
        raise

    if executed and step_failures == executed:
        status = RunStatus.FAILED
    elif errors:
        status = RunStatus.PARTIAL_SUCCESS
    else:
        status = RunStatus.SUCCESS
    duration = time.monotonic() - clock
    summary = RunSummary(
        run_id=run_id,
        status=status,
        started_at=started,
        duration_seconds=duration,
        parameters=params.as_dict(),
        stats=stats,
        errors=errors,
        messages=messages,
    )
    with session_scope(factory) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.status = status
        run.finished_at = utcnow()
        run.duration_seconds = round(duration, 2)
        run.stats = stats
        run.errors = errors
        run.messages = messages
    write_run_report(settings.runs_dir, summary)
    return summary


def write_run_report(runs_dir: Path, summary: RunSummary) -> Path:
    """Grava o relatório JSON e, no GitHub Actions, o resumo da execução."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = runs_dir / f"{stamp}-{summary.run_id}.json"
    path.write_text(
        json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary.to_markdown())
    return path
