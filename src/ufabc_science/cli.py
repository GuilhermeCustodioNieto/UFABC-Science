"""Interface de linha de comando (``python -m ufabc_science``).

Códigos de saída:

* ``0`` — sucesso;
* ``1`` — erro de execução ou validação reprovada;
* ``2`` — uso incorreto ou configuração inválida;
* ``3`` — operação bloqueada por outra execução em andamento (trava do pipeline).

Nenhum comando aprova conteúdo: a aprovação é sempre feita por uma pessoa no
arquivo Markdown e registrada por ``editorial sync``. A mudança de estado para
``PUBLISHED`` ocorre somente em ``edition publish --confirm``.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from datetime import date

from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science import __version__
from ufabc_science.config.logging import configure_logging
from ufabc_science.config.settings import KNOWN_SOURCES, Settings
from ufabc_science.domain.enums import EditorialStatus, RunStatus
from ufabc_science.editorial.exceptions import EditorialError, PublicationBlockedError
from ufabc_science.infrastructure.database import (
    create_db_engine,
    create_session_factory,
    current_revision,
    head_revision,
    init_database,
    session_scope,
)
from ufabc_science.pipeline.lock import ConcurrentRunError

logger = logging.getLogger("ufabc_science.cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOCKED = 3

Handler = Callable[[argparse.Namespace, Settings], int]


class CLIError(RuntimeError):
    """Erro com mensagem clara para o usuário."""


# --- Infraestrutura ---------------------------------------------------------------------


def _redact_url(database_url: str) -> str:
    """Oculta a senha da URL nos logs."""
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<URL inválida>"


def open_database(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    """Abre o banco e confirma que o schema está atualizado."""
    engine = create_db_engine(settings.database_url)
    revision = current_revision(engine)
    head = head_revision(settings.database_url)
    if revision != head:
        engine.dispose()
        raise CLIError(
            f"Banco não inicializado ou desatualizado (revisão {revision or 'nenhuma'}, "
            f"esperado {head}). Execute: python -m ufabc_science init-db"
        )
    return engine, create_session_factory(engine)


def _ids(value: str) -> list[int]:
    try:
        ids = [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use números separados por vírgula") from exc
    if not ids or any(i < 1 for i in ids):
        raise argparse.ArgumentTypeError("informe ids positivos")
    return ids


def _sources(value: str) -> list[str]:
    names = [n.strip().lower() for n in value.split(",") if n.strip()]
    unknown = sorted(set(names) - set(KNOWN_SOURCES))
    if unknown:
        raise argparse.ArgumentTypeError(
            f"fontes desconhecidas: {', '.join(unknown)} (disponíveis: {', '.join(KNOWN_SOURCES)})"
        )
    return names


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use AAAA-MM-DD") from exc


def _print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# --- Comandos: base e configuração ------------------------------------------------------


def _cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    database_url = args.database_url or settings.database_url
    logger.info("Inicializando banco de dados: %s", _redact_url(database_url))
    result = init_database(database_url)
    if result.migrated:
        logger.info(
            "Migrações aplicadas: %s -> %s",
            result.previous_revision or "(vazio)",
            result.current_revision,
        )
    else:
        logger.info("Schema já atualizado (revisão %s).", result.current_revision)
    logger.info("Editorias criadas: %d", result.categories_created)
    print(
        f"Banco pronto (revisão {result.current_revision}); "
        f"editorias criadas: {result.categories_created}."
    )
    return EXIT_OK


def _cmd_config_check(args: argparse.Namespace, settings: Settings) -> int:
    """Mostra a configuração efetiva sem revelar segredos."""
    report = {
        "app_env": settings.app_env,
        "database_url": _redact_url(settings.database_url),
        "data_dir": settings.data_dir.as_posix(),
        "editions_dir": settings.editions_dir.as_posix(),
        "output_dir": settings.output_dir.as_posix(),
        "enabled_sources": settings.sources,
        "contact_email": "configurado" if settings.contact_email else "não configurado",
        "openalex_api_key": "configurada" if settings.openalex_api_key else "não configurada",
        "ncbi_api_key": "configurada" if settings.ncbi_api_key else "não configurada",
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
        "ai_base_url": settings.ai_base_url,
        "ai_api_key": "configurada" if settings.ai_api_key else "não configurada",
        "collection_days": settings.collection_days,
        "max_articles_per_source": settings.max_articles_per_source,
        "generation_limit": settings.generation_limit,
        "timezone": settings.timezone,
    }
    _print_json(report)
    warnings = []
    if not settings.contact_email and not settings.openalex_email:
        warnings.append("CONTACT_EMAIL não definido: as APIs recomendam um e-mail de contato.")
    if "openalex" in settings.sources and not settings.openalex_api_key:
        warnings.append(
            "OPENALEX_API_KEY não definida: o OpenAlex usa um orçamento diário compartilhado."
        )
    if not settings.ai_enabled:
        warnings.append("AI_PROVIDER=mock: rascunhos extrativos apenas para desenvolvimento.")
    for warning in warnings:
        logger.warning(warning)
    return EXIT_OK


# --- Etapa 2: coleta --------------------------------------------------------------------


def _cmd_collect(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.collectors.service import (
        collect_articles,
        collection_window,
        enrich_with_crossref,
    )

    if (args.start is None) != (args.end is None):
        raise CLIError("Informe --start e --end juntos.")
    if args.start and args.end:
        start, end = args.start, args.end
        if end < start:
            raise CLIError("--end deve ser posterior a --start.")
    else:
        start, end = collection_window(args.days or settings.collection_days)
    engine, factory = open_database(settings)
    try:
        summary = collect_articles(
            settings,
            factory,
            start_date=start,
            end_date=end,
            sources=args.sources or settings.sources,
            query=args.query,
            max_articles=args.limit,
        )
        data = summary.as_dict()
        if args.enrich and "crossref" in (args.sources or settings.sources):
            enrichment = enrich_with_crossref(settings, factory)
            data["crossref_enrichment"] = enrichment.__dict__
    finally:
        engine.dispose()
    totals = data["totals"]
    print(
        f"Período {start} a {end}: coletados={totals['collected']} inseridos={totals['inserted']} "
        f"atualizados={totals['updated']} ignorados={totals['ignored']} "
        f"possíveis_duplicatas={totals['flagged_duplicates']} inválidos={totals['invalid']}"
    )
    if args.json:
        _print_json(data)
    if summary.errors:
        for error in summary.errors:
            logger.error(error)
        return EXIT_ERROR if len(summary.failed_sources) == len(summary.sources) else EXIT_OK
    return EXIT_OK


def _cmd_enrich(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.collectors.service import enrich_with_crossref

    engine, factory = open_database(settings)
    try:
        result = enrich_with_crossref(settings, factory, limit=args.limit)
    finally:
        engine.dispose()
    print(
        f"Crossref: verificados={result.checked} confirmados={result.confirmed} "
        f"não_encontrados={result.not_found} erros={len(result.errors)}"
    )
    return EXIT_ERROR if result.errors and not result.checked else EXIT_OK


# --- Etapa 3: inteligência editorial ----------------------------------------------------


def _rules(settings: Settings):  # type: ignore[no-untyped-def]
    from ufabc_science.processing.classification import load_rules

    path = settings.classification_rules_path
    return load_rules(str(path) if path else None)


def _cmd_classify(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.intelligence.provider import build_provider
    from ufabc_science.processing.classification import classify_articles

    if args.ai and not settings.ai_enabled:
        raise CLIError("--ai exige um provedor de IA configurado (AI_PROVIDER).")
    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            summary = classify_articles(
                session,
                rules=_rules(settings),
                min_confidence=settings.classification_min_confidence,
                uncertain_below=settings.classification_uncertain_below,
                article_ids=args.article_id,
                reclassify=args.all,
                provider=build_provider(settings) if args.ai else None,
            )
    finally:
        engine.dispose()
    print(
        f"Classificação: processados={summary.processed} classificados={summary.classified} "
        f"sem_categoria={summary.without_category} com_incerteza={summary.uncertain} "
        f"sugestões_ia={summary.ai_assisted}"
    )
    return EXIT_OK


def _cmd_score(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.processing.relevance import score_articles

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            summary = score_articles(session, article_ids=args.article_id, rescore=args.all)
    finally:
        engine.dispose()
    print(f"Relevância: avaliados={summary.assessed} já_avaliados={summary.skipped}")
    return EXIT_OK


def _cmd_shortlist(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.domain.models import Article
    from ufabc_science.processing.normalization import word_count
    from ufabc_science.processing.relevance import (
        MAX_TYPICAL_ABSTRACT_WORDS,
        PriorityBands,
        latest_assessment,
        unmoderated_repository,
    )

    bands = PriorityBands(
        settings.priority_very_high, settings.priority_high, settings.priority_moderate
    )
    engine, factory = open_database(settings)
    try:
        with factory() as session:
            rows = []
            for article in session.scalars(select(Article)):
                assessment = latest_assessment(article)
                if assessment is not None:
                    rows.append((assessment.final_score, article))
            rows.sort(key=lambda r: r[0], reverse=True)
            print(f"{'ID':>6}  {'NOTA':>6}  {'PRIORIDADE':<10} {'REVISÃO':<9} ALERTAS  TÍTULO")
            for score, article in rows[: args.limit]:
                flags = []
                if article.possible_duplicate_of_id:
                    flags.append(f"dup?{article.possible_duplicate_of_id}")
                if unmoderated_repository(article):
                    flags.append("repo")
                if word_count(article.abstract) > MAX_TYPICAL_ABSTRACT_WORDS:
                    flags.append("abs?")
                if article.peer_review_status.value == "preprint":
                    flags.append("pre")
                cats = (
                    ", ".join(sorted(link.category.name for link in article.categories))
                    or "sem editoria"
                )
                print(
                    f"{article.id:>6}  {score:6.2f}  {bands.classify(score).value:<10} "
                    f"{article.peer_review_status.value:<9} {' '.join(flags) or '-':<8} "
                    f"{article.title[:80]}\n{'':>36}{cats}"
                )
            if rows:
                print(
                    "\nAlertas: pre=preprint, repo=repositório sem triagem, "
                    "abs?=abstract atípico, dup?N=possível duplicata do artigo N."
                )
            if not rows:
                print("Nenhum artigo avaliado. Execute: python -m ufabc_science score")
    finally:
        engine.dispose()
    return EXIT_OK


def _cmd_generate(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.intelligence.generation import generate_contents
    from ufabc_science.intelligence.provider import build_provider

    engine, factory = open_database(settings)
    try:
        summary = generate_contents(
            factory,
            build_provider(settings),
            editorial_dir=settings.editorial_dir,
            limit=args.limit or settings.generation_limit,
            min_abstract_words=settings.min_abstract_words,
            word_limits=settings.generation_word_limits,
            max_attempts=settings.ai_max_retries + 1,
            article_ids=args.article_id,
            force=args.force,
        )
    finally:
        engine.dispose()
    print(
        f"Geração: selecionados={summary.selected} gerados={summary.generated} "
        f"PASSED={summary.passed} WARNING={summary.warnings} FAILED={summary.failed} "
        f"erros={len(summary.errors)}"
    )
    for reason, ids in sorted(summary.skipped.items()):
        print(f"  ignorados ({reason}): {len(ids)}")
    for path in summary.files:
        print(f"  -> {path}")
    return EXIT_ERROR if summary.errors and not summary.generated else EXIT_OK


def _cmd_verify(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.intelligence.generation import verify_contents

    engine, factory = open_database(settings)
    try:
        summary = verify_contents(
            factory,
            min_abstract_words=settings.min_abstract_words,
            word_limits=settings.generation_word_limits,
            article_ids=args.article_id,
        )
    finally:
        engine.dispose()
    print(
        f"Verificação: conteúdos={summary.verified} PASSED={summary.passed} "
        f"WARNING={summary.warnings} FAILED={summary.failed}"
    )
    return EXIT_OK


# --- Etapa 4: fluxo editorial -----------------------------------------------------------


def _cmd_editorial_sync(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.approval import sync_editorial

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            report = sync_editorial(
                session,
                settings.editorial_dir,
                min_abstract_words=settings.min_abstract_words,
                word_limits=settings.generation_word_limits,
                dry_run=args.dry_run,
            )
    finally:
        engine.dispose()
    for outcome in report.outcomes:
        print(f"[{outcome.action}] {outcome.path}")
        for message in outcome.messages:
            print(f"    {message}")
    counts = {}
    for outcome in report.outcomes:
        counts[outcome.action] = counts.get(outcome.action, 0) + 1
    print(
        "Resumo: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nenhum arquivo")
    )
    return EXIT_ERROR if report.errors else EXIT_OK


def _cmd_editorial_validate(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.approval import validate_files

    engine, factory = open_database(settings)
    try:
        with factory() as session:
            results = validate_files(
                session,
                settings.editorial_dir,
                min_abstract_words=settings.min_abstract_words,
                word_limits=settings.generation_word_limits,
            )
    finally:
        engine.dispose()
    invalid = 0
    for result in results:
        if result.errors:
            invalid += 1
        status = "OK" if result.valid else "INVÁLIDO"
        print(f"[{status}] {result.path}")
        for line in result.lines():
            print(f"    {line.split(': ', 1)[-1]}")
    print(f"{len(results)} arquivo(s) verificados; {invalid} com erros.")
    return EXIT_ERROR if invalid else EXIT_OK


def _cmd_editorial_list(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.markdown import find_article_files, read_document

    wanted = {
        "pending": {EditorialStatus.PENDING_REVIEW.value, EditorialStatus.NEEDS_REVISION.value},
        "approved": {EditorialStatus.APPROVED.value},
        "rejected": {EditorialStatus.REJECTED.value},
        "needs_revision": {EditorialStatus.NEEDS_REVISION.value},
        "all": {s.value for s in EditorialStatus},
    }[args.status]
    count = 0
    for path in find_article_files(settings.editorial_dir):
        try:
            doc = read_document(path)
        except Exception as exc:
            print(f"[erro] {path.as_posix()}: {exc}")
            continue
        if doc.status not in wanted:
            continue
        count += 1
        print(
            f"{doc.status:<15} {doc.metadata.get('verification_status') or '-':<8} "
            f"{path.as_posix()}  {doc.headline[:70]}"
        )
    print(f"{count} arquivo(s).")
    return EXIT_OK


def _edition_kwargs(settings: Settings) -> dict[str, object]:
    return {
        "editorial_dir": settings.editorial_dir,
        "editions_dir": settings.editions_dir,
        "min_abstract_words": settings.min_abstract_words,
        "word_limits": settings.generation_word_limits,
    }


def _cmd_edition_create(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import create_edition, intro_path

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            edition = create_edition(session, args.week, settings.editions_dir, title=args.title)
            print(
                f"Edição {edition.edition_number} criada ({edition.slug}, {edition.week}: "
                f"{edition.start_date} a {edition.end_date}) em DRAFT."
            )
            print(f"Introdução editorial: {intro_path(settings.editions_dir, edition).as_posix()}")
    finally:
        engine.dispose()
    return EXIT_OK


def _cmd_edition_add(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import add_article

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            item = add_article(
                session,
                args.edition,
                args.article_id,
                settings.editorial_dir,
                section=args.section,
                position=args.position,
            )
            print(
                f"Artigo {item.article_id} adicionado à edição {args.edition} "
                f"(posição {item.position}, seção {item.editorial_section})."
            )
    finally:
        engine.dispose()
    return EXIT_OK


def _cmd_edition_remove(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import remove_article

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            remove_article(session, args.edition, args.article_id)
    finally:
        engine.dispose()
    print(f"Artigo {args.article_id} removido da edição {args.edition}.")
    return EXIT_OK


def _cmd_edition_reorder(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import reorder

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            reorder(session, args.edition, args.order)
    finally:
        engine.dispose()
    print(f"Nova ordem da edição {args.edition}: {', '.join(map(str, args.order))}.")
    return EXIT_OK


def _cmd_edition_section(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import set_section

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            set_section(session, args.edition, args.article_id, args.section)
    finally:
        engine.dispose()
    print(f"Artigo {args.article_id}: seção principal '{args.section}'.")
    return EXIT_OK


def _cmd_edition_validate(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import get_edition, validate_edition

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            result = validate_edition(session, args.edition, **_edition_kwargs(settings))
            status = get_edition(session, args.edition).status.value
    finally:
        engine.dispose()
    for error in result.errors:
        print(f"ERRO: {error}")
    for warning in result.warnings:
        print(f"AVISO: {warning}")
    print(f"Edição {args.edition}: {'VÁLIDA' if result.valid else 'INVÁLIDA'} (estado: {status}).")
    return EXIT_OK if result.valid else EXIT_ERROR


def _cmd_edition_show(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import category_names, get_edition, group_by_section

    engine, factory = open_database(settings)
    try:
        with factory() as session:
            edition = get_edition(session, args.edition)
            print(f"{edition.title} [{edition.status.value}] {edition.week}")
            print(f"Período: {edition.start_date} a {edition.end_date}")
            print(f"Introdução: {edition.introduction_status.value}")
            if edition.published_at:
                print(f"Publicada em {edition.published_at} por {edition.published_by}")
            names = category_names(session)
            for section, items in group_by_section(list(edition.items)):
                print(f"\n## {names.get(section, section)}")
                for item in items:
                    print(f"  {item.position:>2}. [{item.article_id}] {item.article.title[:80]}")
            if not edition.items:
                print("(sem artigos)")
    finally:
        engine.dispose()
    return EXIT_OK


def _cmd_edition_publish(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import publish_edition
    from ufabc_science.publisher.html import build_site

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            edition = publish_edition(
                session,
                args.edition,
                published_by=args.by or "",
                confirm=args.confirm,
                **_edition_kwargs(settings),
            )
            print(f"Edição {edition.edition_number} PUBLICADA em {edition.published_at}.")
        with factory() as session:
            result = build_site(session, settings.output_dir, timezone_name=settings.timezone)
        print(f"Site gerado em {result.output_dir.as_posix()} ({len(result.pages)} páginas).")
    finally:
        engine.dispose()
    return EXIT_OK


def _cmd_edition_archive(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.editorial.edition import archive_edition

    engine, factory = open_database(settings)
    try:
        with session_scope(factory) as session:
            archive_edition(session, args.edition)
    finally:
        engine.dispose()
    print(f"Edição {args.edition} arquivada.")
    return EXIT_OK


def _cmd_publish_preview(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.publisher.html import build_preview

    engine, factory = open_database(settings)
    try:
        with factory() as session:
            result = build_preview(
                session, args.edition, settings.preview_dir, timezone_name=settings.timezone
            )
    finally:
        engine.dispose()
    print(f"Pré-visualização gerada em {result.output_dir.as_posix()} (nada foi publicado).")
    print(f"Abra no navegador: {(result.output_dir / 'index.html').as_posix()}")
    for warning in result.errors:
        print(f"AVISO: {warning}")
    return EXIT_OK


def _cmd_site_build(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.domain.enums import EditionStatus
    from ufabc_science.editorial.edition import get_edition, validate_edition
    from ufabc_science.publisher.html import build_site

    engine, factory = open_database(settings)
    try:
        with factory() as session:
            if args.require_edition is not None:
                edition = get_edition(session, args.require_edition)
                if edition.status not in (EditionStatus.PUBLISHED, EditionStatus.ARCHIVED):
                    raise CLIError(
                        f"A edição {args.require_edition} não está PUBLISHED "
                        f"(estado: {edition.status.value}). Publique-a com "
                        "'edition publish --confirm' antes do deploy."
                    )
                check = validate_edition(
                    session, args.require_edition, mark_ready=False, **_edition_kwargs(settings)
                )
                if not check.valid:
                    raise PublicationBlockedError("Edição publicada inconsistente.", check.errors)
            result = build_site(session, settings.output_dir, timezone_name=settings.timezone)
    finally:
        engine.dispose()
    print(
        f"Site público gerado em {result.output_dir.as_posix()}: {len(result.pages)} páginas, "
        f"edições publicadas: {result.editions or 'nenhuma'}."
    )
    for error in result.errors:
        print(f"ERRO: {error}")
    return EXIT_ERROR if result.errors and args.strict else EXIT_OK


# --- Etapa 5: pipeline ------------------------------------------------------------------


def _steps(value: str) -> tuple[str, ...]:
    from ufabc_science.pipeline.runner import ALL_STEPS

    if value in ("all", "full", "completo"):
        return ALL_STEPS
    if value in ("process", "processamento"):
        return ("classify", "score", "generate")
    steps = tuple(s.strip() for s in value.split(",") if s.strip())
    unknown = sorted(set(steps) - set(ALL_STEPS))
    if unknown or not steps:
        raise argparse.ArgumentTypeError(
            f"etapas inválidas: {', '.join(unknown) or '(vazio)'}; use {', '.join(ALL_STEPS)}"
        )
    return tuple(s for s in ALL_STEPS if s in steps)


def _run(settings: Settings, args: argparse.Namespace, steps: tuple[str, ...]) -> int:
    from ufabc_science.pipeline.runner import RunParameters, run_pipeline

    engine, factory = open_database(settings)
    try:
        summary = run_pipeline(
            settings,
            factory,
            RunParameters(
                days=getattr(args, "days", None) or settings.collection_days,
                sources=getattr(args, "sources", None) or settings.sources,
                max_articles=getattr(args, "max_articles", None),
                generation_limit=getattr(args, "limit", None) or settings.generation_limit,
                steps=steps,
                trigger=getattr(args, "trigger", "local"),
                use_ai_classification=getattr(args, "ai_classification", False),
            ),
        )
    finally:
        engine.dispose()
    print(summary.to_markdown())
    return EXIT_ERROR if summary.status is RunStatus.FAILED else EXIT_OK


def _cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    return _run(settings, args, args.steps)


def _cmd_process(args: argparse.Namespace, settings: Settings) -> int:
    return _run(settings, args, ("classify", "score", "generate"))


def _cmd_runs(args: argparse.Namespace, settings: Settings) -> int:
    from ufabc_science.domain.models import PipelineRun

    engine, factory = open_database(settings)
    try:
        with factory() as session:
            runs = session.scalars(
                select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(args.limit)
            ).all()
            for run in runs:
                print(
                    f"{run.id}  {run.started_at:%Y-%m-%d %H:%M}Z  {run.status.value:<15} "
                    f"{run.trigger:<18} erros={len(run.errors or [])} "
                    f"duração={run.duration_seconds or 0:.0f}s"
                )
            if not runs:
                print("Nenhuma execução registrada.")
    finally:
        engine.dispose()
    return EXIT_OK


# --- Parser -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufabc_science",
        description="UFABC Science — curadoria e divulgação científica.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        type=str.upper,
        help="Sobrescreve LOG_LEVEL.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMANDO")

    p = sub.add_parser("init-db", help="Cria ou atualiza o banco de dados (idempotente).")
    p.add_argument("--database-url", help="Sobrescreve DATABASE_URL.")
    p.set_defaults(handler=_cmd_init_db, needs_settings_only=True)

    p = sub.add_parser("config", help="Configuração.")
    config_sub = p.add_subparsers(dest="config_command", metavar="AÇÃO", required=True)
    c = config_sub.add_parser("check", help="Valida e mostra a configuração (sem segredos).")
    c.set_defaults(handler=_cmd_config_check)

    p = sub.add_parser("collect", help="Coleta artigos das fontes habilitadas.")
    p.add_argument("--days", type=int, help="Janela em dias até hoje (padrão COLLECTION_DAYS).")
    p.add_argument("--start", type=_date, help="Data inicial (AAAA-MM-DD).")
    p.add_argument("--end", type=_date, help="Data final (AAAA-MM-DD).")
    p.add_argument("--sources", type=_sources, help="Ex.: openalex,arxiv")
    p.add_argument("--query", help="Consulta livre (substitui as consultas padrão).")
    p.add_argument("--limit", type=int, help="Máximo de artigos por fonte.")
    p.add_argument(
        "--no-enrich", dest="enrich", action="store_false", help="Não consultar o Crossref por DOI."
    )
    p.add_argument("--json", action="store_true", help="Imprime o relatório completo em JSON.")
    p.set_defaults(handler=_cmd_collect)

    p = sub.add_parser("enrich", help="Confirma metadados por DOI no Crossref.")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(handler=_cmd_enrich)

    p = sub.add_parser("classify", help="Classifica artigos nas editorias.")
    p.add_argument("--article-id", type=_ids, help="Reclassifica os artigos informados.")
    p.add_argument("--all", action="store_true", help="Reclassifica todos os artigos.")
    p.add_argument("--ai", action="store_true", help="Usa IA nos casos ambíguos.")
    p.set_defaults(handler=_cmd_classify)

    p = sub.add_parser("score", help="Calcula a relevância editorial.")
    p.add_argument("--article-id", type=_ids)
    p.add_argument("--all", action="store_true", help="Reavalia todos (preserva histórico).")
    p.set_defaults(handler=_cmd_score)

    p = sub.add_parser("shortlist", help="Lista os artigos prioritários.")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler=_cmd_shortlist)

    p = sub.add_parser("generate", help="Gera rascunhos para revisão humana.")
    p.add_argument("--limit", type=int)
    p.add_argument("--article-id", type=_ids)
    p.add_argument(
        "--force",
        action="store_true",
        help="Gera nova versão mesmo sem mudanças (arquiva o Markdown anterior).",
    )
    p.set_defaults(handler=_cmd_generate)

    p = sub.add_parser("verify", help="Reexecuta a verificação dos conteúdos.")
    p.add_argument("--article-id", type=_ids)
    p.set_defaults(handler=_cmd_verify)

    p = sub.add_parser("process", help="Classificação, relevância, geração e verificação.")
    p.add_argument("--limit", type=int, help="Máximo de rascunhos gerados.")
    p.set_defaults(handler=_cmd_process)

    p = sub.add_parser("editorial", help="Fluxo editorial em Markdown.")
    ed = p.add_subparsers(dest="editorial_command", metavar="AÇÃO", required=True)
    e = ed.add_parser("sync", help="Sincroniza estados dos arquivos com o banco.")
    e.add_argument("--dry-run", action="store_true")
    e.set_defaults(handler=_cmd_editorial_sync)
    e = ed.add_parser("validate", help="Valida os arquivos editoriais (sem alterar nada).")
    e.set_defaults(handler=_cmd_editorial_validate)
    e = ed.add_parser("list", help="Lista arquivos por estado.")
    e.add_argument(
        "--status",
        choices=["pending", "approved", "rejected", "needs_revision", "all"],
        default="pending",
    )
    e.set_defaults(handler=_cmd_editorial_list)

    p = sub.add_parser("edition", help="Edições semanais.")
    eds = p.add_subparsers(dest="edition_command", metavar="AÇÃO", required=True)
    e = eds.add_parser("create", help="Cria edição DRAFT para uma semana ISO.")
    e.add_argument("--week", required=True, help="Ex.: 2026-W46")
    e.add_argument("--title")
    e.set_defaults(handler=_cmd_edition_create)
    for name, func, helptext in (
        ("add", _cmd_edition_add, "Adiciona artigo aprovado."),
        ("remove", _cmd_edition_remove, "Remove artigo."),
        ("section", _cmd_edition_section, "Define a editoria principal do artigo na edição."),
    ):
        e = eds.add_parser(name, help=helptext)
        e.add_argument("--edition", type=int, required=True)
        e.add_argument("--article-id", type=int, required=True)
        if name == "add":
            e.add_argument("--section", help="Editoria principal (slug).")
            e.add_argument("--position", type=int)
        if name == "section":
            e.add_argument("--section", required=True)
        e.set_defaults(handler=func)
    e = eds.add_parser("reorder", help="Define a ordem dos artigos.")
    e.add_argument("--edition", type=int, required=True)
    e.add_argument("--order", type=_ids, required=True, help="Ids na nova ordem: 12,5,9")
    e.set_defaults(handler=_cmd_edition_reorder)
    for name, func, helptext in (
        ("validate", _cmd_edition_validate, "Valida a edição (marca READY se válida)."),
        ("show", _cmd_edition_show, "Mostra a edição."),
        ("archive", _cmd_edition_archive, "Arquiva edição publicada."),
    ):
        e = eds.add_parser(name, help=helptext)
        e.add_argument("--edition", type=int, required=True)
        e.set_defaults(handler=func)
    e = eds.add_parser("publish", help="Publicação explícita e auditável (altera para PUBLISHED).")
    e.add_argument("--edition", type=int, required=True)
    e.add_argument("--by", help="Responsável pela publicação.")
    e.add_argument("--confirm", action="store_true", help="Confirma a publicação.")
    e.set_defaults(handler=_cmd_edition_publish)

    p = sub.add_parser("publish", help="Gera HTML de pré-visualização (não publica).")
    p.add_argument("--edition", type=int, required=True)
    p.set_defaults(handler=_cmd_publish_preview)

    p = sub.add_parser("site", help="Site público estático.")
    site = p.add_subparsers(dest="site_command", metavar="AÇÃO", required=True)
    s = site.add_parser("build", help="Gera dist/ somente com edições publicadas.")
    s.add_argument("--require-edition", type=int, help="Falha se a edição não estiver publicada.")
    s.add_argument("--strict", action="store_true", help="Falha se algum item for omitido.")
    s.set_defaults(handler=_cmd_site_build)

    p = sub.add_parser("run", help="Pipeline até os rascunhos (nunca aprova nem publica).")
    p.add_argument("--days", type=int)
    p.add_argument("--sources", type=_sources)
    p.add_argument("--max-articles", type=int, help="Máximo por fonte.")
    p.add_argument("--limit", type=int, help="Máximo de rascunhos gerados.")
    p.add_argument("--steps", type=_steps, default=_steps("all"), help="all, process ou lista")
    p.add_argument("--trigger", default="local", help="Origem: local, schedule, workflow_dispatch")
    p.add_argument("--ai-classification", action="store_true")
    p.set_defaults(handler=_cmd_run)

    p = sub.add_parser("runs", help="Lista execuções do pipeline.")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(handler=_cmd_runs)

    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        settings = Settings()
    except ValidationError as exc:
        configure_logging("ERROR")
        logger.error("Configuração inválida:\n%s", exc)
        return EXIT_USAGE

    configure_logging(args.log_level or settings.log_level)

    try:
        return handler(args, settings)
    except ConcurrentRunError as exc:
        logger.error("%s", exc)
        return EXIT_LOCKED
    except PublicationBlockedError as exc:
        logger.error("%s", exc)
        for error in exc.errors:
            logger.error("  - %s", error)
        return EXIT_ERROR
    except (CLIError, EditorialError) as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    except SQLAlchemyError as exc:
        logger.error("Erro de banco de dados: %s", exc)
        logger.debug("Detalhes", exc_info=True)
        return EXIT_ERROR
    except KeyboardInterrupt:
        logger.warning("Operação interrompida pelo usuário.")
        return 130
    except Exception as exc:
        logger.error("Erro inesperado: %s", exc)
        logger.debug("Detalhes", exc_info=True)
        return EXIT_ERROR


__all__ = ["build_parser", "run_cli"]
