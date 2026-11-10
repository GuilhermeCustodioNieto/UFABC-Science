"""Seleção, geração, verificação e exportação de rascunhos (Etapa 3, seções 6, 7, 11 e 12).

Garantias:

* a IA recebe somente dados coletados, dentro de um bloco "não confiável";
* respostas inválidas não são persistidas (validação Pydantic com novas
  tentativas limitadas);
* referência, título original e link são montados a partir dos metadados;
* cada geração cria uma nova versão (histórico preservado) e registra
  provedor, modelo, versão do prompt e hash dos dados de entrada;
* nenhum conteúdo é aprovado automaticamente: o Markdown sai como
  ``pending_review``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ufabc_science.domain.enums import (
    ArticleType,
    EditorialStatus,
    PeerReviewStatus,
    VerificationStatus,
)
from ufabc_science.domain.models import Article, EditorialReview, GeneratedContent, utcnow
from ufabc_science.editorial.markdown import (
    SCHEMA_ID,
    STATUS_DIRS,
    article_filename,
    body_hash,
    dump_document,
    find_article_files,
    read_document,
    render_body,
    safe_child,
    write_text_atomic,
)
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.intelligence.base import AIProvider
from ufabc_science.intelligence.exceptions import (
    AIError,
    AIResponseValidationError,
    InsufficientInformationError,
)
from ufabc_science.intelligence.prompts import (
    ARTICLE_GENERATION_PROMPT,
    STUDY_TYPE_GUIDANCE,
    untrusted_block,
)
from ufabc_science.intelligence.schemas import (
    DEFAULT_WORD_LIMITS,
    SECTION_FIELDS,
    AIArticleDraft,
    GeneratedArticleContent,
)
from ufabc_science.intelligence.verification import (
    ContentUnderReview,
    VerificationReport,
    build_reference,
    source_url_for,
    verify_content,
)
from ufabc_science.processing.normalization import strip_accents, word_count
from ufabc_science.processing.relevance import latest_assessment

logger = logging.getLogger(__name__)


# --- Tipo de estudo ---------------------------------------------------------------------

_STUDY_CUES = (
    ("meta_analysis", r"meta-analys"),
    ("systematic_review", r"systematic review|scoping review|prisma"),
    ("simulation", r"\bsimulat|monte carlo|in silico"),
    ("observational", r"cohort|cross-sectional|observational|case-control|survey|registry"),
    ("experimental", r"randomi[sz]ed|experiment|trial|we measured|in vivo|in vitro|knockdown"),
    ("theoretical", r"theorem|we prove|analytical(ly)? deriv|theoretical framework"),
    ("computational", r"machine learning|deep learning|algorithm|benchmark|neural network"),
)


def infer_study_type(article: Article) -> str:
    """Tipo de estudo inferido de forma conservadora a partir de tipo e abstract."""
    text = strip_accents(f"{article.title} {article.abstract or ''}").casefold()
    for name, pattern in _STUDY_CUES:
        if re.search(pattern, text):
            return name
    if article.article_type is ArticleType.REVIEW:
        return "narrative_review"
    if article.peer_review_status is PeerReviewStatus.PREPRINT:
        return "preprint"
    return "unknown"


# --- Entrada e hash ---------------------------------------------------------------------


def generation_payload(article: Article) -> dict[str, Any]:
    """Dados (e somente eles) enviados ao modelo."""
    categories = sorted(link.category.slug for link in article.categories)
    return {
        "titulo_original": article.title,
        "abstract": article.abstract,
        "autores": [a.get("name") for a in article.authors or [] if a.get("name")][:20],
        "periodico": article.journal,
        "editora": article.publisher,
        "data_publicacao": article.publication_date.isoformat()
        if article.publication_date
        else None,
        "tipo_publicacao": article.article_type.value,
        "revisao_por_pares": article.peer_review_status.value,
        "categorias": categories,
        "palavras_chave": list(article.keywords or [])[:25],
    }


def compute_input_hash(payload: dict[str, Any], limits: dict[str, tuple[int, int]]) -> str:
    material = json.dumps(
        {
            "payload": payload,
            "prompt": ARTICLE_GENERATION_PROMPT.identifier,
            "limits": {k: list(v) for k, v in sorted(limits.items())},
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --- Seleção ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    article: Article
    score: float | None
    input_hash: str


@dataclass
class SelectionResult:
    selected: list[Candidate] = field(default_factory=list)
    skipped: dict[str, list[int]] = field(default_factory=dict)

    def skip(self, reason: str, article_id: int) -> None:
        self.skipped.setdefault(reason, []).append(article_id)


def latest_review(article: Article) -> EditorialReview | None:
    return article.editorial_reviews[-1] if article.editorial_reviews else None


def latest_content(article: Article) -> GeneratedContent | None:
    return article.generated_contents[-1] if article.generated_contents else None


def select_for_generation(
    session: Session,
    *,
    limit: int,
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]],
    article_ids: list[int] | None = None,
    force: bool = False,
) -> SelectionResult:
    """Escolhe artigos para geração, priorizando maior relevância editorial."""
    result = SelectionResult()
    query = select(Article).order_by(Article.id)
    if article_ids:
        query = query.where(Article.id.in_(article_ids))
    candidates: list[Candidate] = []
    for article in session.scalars(query).all():
        if not (article.title or "").strip():
            result.skip("titulo_invalido", article.id)
            continue
        if not article.sources:
            result.skip("sem_fonte", article.id)
            continue
        if word_count(article.abstract) < min_abstract_words:
            # Aviso de insuficiência: não se gera notícia especulativa.
            result.skip("informacao_insuficiente", article.id)
            continue
        review = latest_review(article)
        if review is not None and review.status is EditorialStatus.REJECTED and not force:
            result.skip("rejeitado", article.id)
            continue
        if review is not None and review.status is EditorialStatus.APPROVED and not force:
            result.skip("ja_aprovado", article.id)
            continue
        input_hash = compute_input_hash(generation_payload(article), word_limits)
        content = latest_content(article)
        if content is not None and content.input_hash == input_hash and not force:
            if content.verification_status is VerificationStatus.FAILED:
                result.skip("bloqueado_por_verificacao", article.id)
            else:
                result.skip("sem_alteracoes", article.id)
            continue
        assessment = latest_assessment(article)
        candidates.append(
            Candidate(article, assessment.final_score if assessment else None, input_hash)
        )
    candidates.sort(
        key=lambda c: (
            c.score is not None,
            c.score or 0.0,
            c.article.publication_date.toordinal() if c.article.publication_date else 0,
        ),
        reverse=True,
    )
    result.selected = candidates[:limit]
    for extra in candidates[limit:]:
        result.skip("limite_de_processamento", extra.article.id)
    return result


# --- Geração ----------------------------------------------------------------------------


def _limits_text(limits: dict[str, tuple[int, int]]) -> str:
    return ", ".join(f"{name}: {low}-{high}" for name, (low, high) in limits.items())


def request_draft(
    provider: AIProvider, article: Article, limits: dict[str, tuple[int, int]], max_attempts: int
) -> tuple[AIArticleDraft, dict[str, Any], str | None]:
    """Pede o rascunho ao provedor; repete (limitado) se a resposta for inválida."""
    study_type = infer_study_type(article)
    prompt = ARTICLE_GENERATION_PROMPT.render(
        tipo_estudo=study_type,
        orientacao_tipo=STUDY_TYPE_GUIDANCE.get(study_type, STUDY_TYPE_GUIDANCE["unknown"]),
        revisao=article.peer_review_status.value,
        limites=_limits_text(limits),
        dados=untrusted_block(generation_payload(article)),
    )
    schema = AIArticleDraft.model_json_schema()
    errors: list[str] = []
    usage: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        attempt_prompt = prompt
        if errors:
            attempt_prompt += (
                "\n\nA resposta anterior foi rejeitada pela validação: "
                + errors[-1][:800]
                + "\nCorrija e devolva apenas o JSON."
            )
        response = provider.generate_structured(
            attempt_prompt, schema, system=ARTICLE_GENERATION_PROMPT.system
        )
        for key, value in response.usage.items():
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + value
        usage["attempts"] = attempt
        try:
            return AIArticleDraft.model_validate(response.data), usage, response.model
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10]
            )
            errors.append(message)
            logger.warning(
                "Artigo %s: resposta inválida da IA (tentativa %d/%d): %s",
                article.id,
                attempt,
                max_attempts,
                message,
            )
    raise AIResponseValidationError(
        f"Resposta inválida após {max_attempts} tentativa(s): {errors[-1] if errors else ''}"
    )


def complete_markdown(content: GeneratedArticleContent) -> str:
    return render_body(content.headline, content.sections(), content.reference, content.source_url)


def generate_content(
    session: Session,
    provider: AIProvider,
    candidate: Candidate,
    *,
    limits: dict[str, tuple[int, int]],
    max_attempts: int,
    min_abstract_words: int,
) -> tuple[GeneratedContent, VerificationReport]:
    """Gera, valida, verifica e persiste uma nova versão de conteúdo."""
    article = candidate.article
    source_url = source_url_for(article)
    if source_url is None:
        raise InsufficientInformationError("Artigo sem link original verificável.")
    draft, usage, model_name = request_draft(provider, article, limits, max_attempts)
    content = GeneratedArticleContent(
        **draft.model_dump(),
        original_title=article.title,
        reference=build_reference(article),
        source_url=source_url,
    )
    report = verify_content(
        article,
        ContentUnderReview(
            headline=content.headline,
            original_title=content.original_title,
            sections=content.sections(),
            reference=content.reference,
            source_url=content.source_url,
            uncertainty_notes=tuple(content.uncertainty_notes),
        ),
        min_abstract_words=min_abstract_words,
        word_limits=limits,
    )
    version = (
        session.scalar(
            select(func.max(GeneratedContent.version)).where(
                GeneratedContent.article_id == article.id
            )
        )
        or 0
    ) + 1
    record = GeneratedContent(
        article=article,
        version=version,
        headline=content.headline,
        original_title=content.original_title,
        introduction=content.introduction,
        context=content.context,
        research_question=content.research_question,
        methodology=content.methodology,
        findings=content.findings,
        limitations=content.limitations,
        relevance=content.ufabc_relevance,
        complete_content=complete_markdown(content),
        reference=content.reference,
        source_url=content.source_url,
        uncertainty_notes=list(content.uncertainty_notes),
        study_type=infer_study_type(article),
        model_provider=provider.name,
        model_name=model_name or provider.model,
        prompt_version=ARTICLE_GENERATION_PROMPT.version,
        input_hash=candidate.input_hash,
        usage=usage,
        verification_status=report.status,
        verification_report=report.as_dict(),
        verified_at=utcnow(),
        generated_at=utcnow(),
    )
    session.add(record)
    session.flush()
    return record, report


def content_under_review(record: GeneratedContent) -> ContentUnderReview:
    return ContentUnderReview(
        headline=record.headline or "",
        original_title=record.original_title or "",
        sections={
            "introduction": record.introduction or "",
            "context": record.context or "",
            "research_question": record.research_question or "",
            "methodology": record.methodology or "",
            "findings": record.findings or "",
            "limitations": record.limitations or "",
            "ufabc_relevance": record.relevance or "",
        },
        reference=record.reference or "",
        source_url=record.source_url or "",
        uncertainty_notes=tuple(record.uncertainty_notes or ()),
    )


def reverify(
    session: Session, record: GeneratedContent, *, min_abstract_words: int, limits: dict
) -> VerificationReport:
    """Executa novamente a verificação determinística de uma versão existente."""
    report = verify_content(
        record.article,
        content_under_review(record),
        min_abstract_words=min_abstract_words,
        word_limits=limits,
    )
    record.verification_status = report.status
    record.verification_report = report.as_dict()
    record.verified_at = utcnow()
    return report


# --- Exportação Markdown ----------------------------------------------------------------


class ExportOutcome(str, Enum):
    WRITTEN = "written"
    REPLACED = "replaced"
    PRESERVED = "preserved"


def _messages(report: dict[str, Any]) -> list[str]:
    return [
        f"{c['status'].upper()}: {c['message']}"
        + (f" ({'; '.join(map(str, c['details'][:5]))})" if c.get("details") else "")
        for c in report.get("checks", [])
        if c["status"] != VerificationStatus.PASSED.value
    ]


def export_markdown(
    record: GeneratedContent, editorial_dir: Path, *, overwrite_edited: bool = False
) -> tuple[ExportOutcome, Path]:
    """Grava ``pending/article-<id>.md`` para revisão humana.

    Se já existir um arquivo do artigo editado manualmente ou já revisado, ele é
    preservado e a nova versão vai para ``history/`` (a menos que
    ``overwrite_edited``, que arquiva o atual antes de substituir).
    """
    article = record.article
    name = article_filename(article.id)
    body = record.complete_content or ""
    primary = None
    if article.categories:
        primary = max(article.categories, key=lambda link: link.confidence).category.slug
    metadata: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "article_id": article.id,
        "content_id": record.id,
        "content_version": record.version,
        "status": EditorialStatus.PENDING_REVIEW.value,
        "categories": sorted(link.category.slug for link in article.categories),
        "primary_category": primary,
        "source_url": record.source_url,
        "doi": article.doi,
        "peer_review_status": article.peer_review_status.value,
        "article_type": article.article_type.value,
        "original_title": record.original_title,
        "generated_at": record.generated_at.isoformat(timespec="seconds"),
        "model_provider": record.model_provider,
        "model_name": record.model_name,
        "prompt_version": record.prompt_version,
        "verification_status": record.verification_status.value
        if record.verification_status
        else None,
        "verification_messages": _messages(record.verification_report or {}),
        "generated_body_hash": body_hash(body),
        "reviewer": None,
        "reviewed_at": None,
        "editorial_notes": None,
        "warning_justification": None,
        "edition_slug": None,
    }
    text = dump_document(metadata, body)
    history_dir = editorial_dir / "history"
    existing = [p for p in find_article_files(editorial_dir) if p.name == name]
    target = safe_child(editorial_dir / STATUS_DIRS[EditorialStatus.PENDING_REVIEW], name)
    if existing:
        current = existing[0]
        try:
            document = read_document(current)
            untouched = (
                not document.manually_edited
                and document.status == EditorialStatus.PENDING_REVIEW.value
            )
            old_version = document.metadata.get("content_version", "x")
        except Exception:
            untouched, old_version = False, "x"
        if not untouched and not overwrite_edited:
            proposed = safe_child(
                history_dir, f"article-{article.id}.v{record.version}.proposed.md"
            )
            write_text_atomic(proposed, text)
            logger.warning(
                "%s foi editado ou revisado: preservado. Nova versão salva em %s",
                current,
                proposed,
            )
            return ExportOutcome.PRESERVED, proposed
        archived = safe_child(history_dir, f"article-{article.id}.v{old_version}.md")
        history_dir.mkdir(parents=True, exist_ok=True)
        archived.write_text(current.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        current.unlink()
        write_text_atomic(target, text)
        return ExportOutcome.REPLACED, target
    write_text_atomic(target, text)
    return ExportOutcome.WRITTEN, target


# --- Serviço ----------------------------------------------------------------------------


@dataclass
class GenerationSummary:
    selected: int = 0
    generated: int = 0
    passed: int = 0
    warnings: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: dict[str, list[int]] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "generated": self.generated,
            "passed": self.passed,
            "warnings": self.warnings,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": {k: len(v) for k, v in self.skipped.items()},
        }


def generate_contents(
    factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    editorial_dir: Path,
    limit: int,
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]] | None = None,
    max_attempts: int = 3,
    article_ids: list[int] | None = None,
    force: bool = False,
) -> GenerationSummary:
    """Seleciona, gera, verifica e exporta rascunhos. Um artigo por transação."""
    limits = {**DEFAULT_WORD_LIMITS, **(word_limits or {})}
    summary = GenerationSummary()
    with session_scope(factory) as session:
        selection = select_for_generation(
            session,
            limit=limit,
            min_abstract_words=min_abstract_words,
            word_limits=limits,
            article_ids=article_ids,
            force=force,
        )
        chosen = [(c.article.id, c.input_hash, c.score) for c in selection.selected]
        summary.skipped = selection.skipped
    if summary.skipped.get("informacao_insuficiente"):
        logger.warning(
            "Aviso de insuficiência: %d artigo(s) sem abstract suficiente não foram enviados "
            "à IA (ids: %s)",
            len(summary.skipped["informacao_insuficiente"]),
            summary.skipped["informacao_insuficiente"][:20],
        )
    summary.selected = len(chosen)
    for article_id, input_hash, score in chosen:
        try:
            with session_scope(factory) as session:
                article = session.get(Article, article_id)
                assert article is not None
                record, report = generate_content(
                    session,
                    provider,
                    Candidate(article, score, input_hash),
                    limits=limits,
                    max_attempts=max_attempts,
                    min_abstract_words=min_abstract_words,
                )
                _, path = export_markdown(record, editorial_dir, overwrite_edited=force)
                summary.files.append(path.as_posix())
        except (AIError, InsufficientInformationError) as exc:
            summary.errors.append(f"artigo {article_id}: {exc}")
            logger.error("Artigo %s: geração falhou: %s", article_id, exc)
            continue
        summary.generated += 1
        if report.status is VerificationStatus.PASSED:
            summary.passed += 1
        elif report.status is VerificationStatus.WARNING:
            summary.warnings += 1
        else:
            summary.failed += 1
        logger.info(
            "Artigo %s: versão %d gerada (%s) -> %s",
            article_id,
            record.version,
            report.status.value.upper(),
            path,
        )
    return summary


@dataclass
class VerifySummary:
    verified: int = 0
    passed: int = 0
    warnings: int = 0
    failed: int = 0


def verify_contents(
    factory: sessionmaker[Session],
    *,
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]] | None = None,
    article_ids: list[int] | None = None,
) -> VerifySummary:
    """Reexecuta a verificação da versão mais recente de cada artigo."""
    limits = {**DEFAULT_WORD_LIMITS, **(word_limits or {})}
    summary = VerifySummary()
    with session_scope(factory) as session:
        query = select(Article).order_by(Article.id)
        if article_ids:
            query = query.where(Article.id.in_(article_ids))
        for article in session.scalars(query):
            record = latest_content(article)
            if record is None:
                continue
            report = reverify(session, record, min_abstract_words=min_abstract_words, limits=limits)
            summary.verified += 1
            if report.status is VerificationStatus.PASSED:
                summary.passed += 1
            elif report.status is VerificationStatus.WARNING:
                summary.warnings += 1
            else:
                summary.failed += 1
    return summary


__all__ = [
    "SECTION_FIELDS",
    "Candidate",
    "GenerationSummary",
    "export_markdown",
    "generate_contents",
    "infer_study_type",
    "select_for_generation",
    "verify_contents",
]
