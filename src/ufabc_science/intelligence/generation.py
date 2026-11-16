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
import math
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
    EDITORIAL_REVIEW_PROMPT,
    EVIDENCE_GUIDANCE,
    HEADLINE_RULES,
    untrusted_block,
)
from ufabc_science.intelligence.schemas import (
    APPEAL_CRITERIA,
    DEFAULT_WORD_LIMITS,
    LANGUAGE_CRITERIA,
    PRECISION_CRITERIA,
    SECTION_FIELDS,
    SECTION_TITLES,
    AIArticleDraft,
    AIEditorialReview,
    GeneratedArticleContent,
)
from ufabc_science.intelligence.verification import (
    ContentUnderReview,
    VerificationReport,
    build_reference,
    source_url_for,
    verify_content,
)
from ufabc_science.processing.classification import primary_category
from ufabc_science.processing.curation import (
    CONSIDER_SCORE,
    PRIORITY_SCORE,
    REJECT,
    effective_assessment,
    explain_record,
    infer_evidence_level,
    is_ai_assessment,
)
from ufabc_science.processing.normalization import strip_accents, word_count

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


def curation_hints(article: Article) -> dict[str, Any] | None:
    """Descoberta central, nível de evidência e conexões vindos da curadoria por IA."""
    record = effective_assessment(article)
    if record is None or not is_ai_assessment(record):
        return None
    return {
        "descoberta_central": record.central_discovery,
        "nivel_de_evidencia": record.evidence_level,
        "conexoes_entre_areas": (record.justification or {}).get("interdisciplinary_links"),
    }


def generation_payload(article: Article) -> dict[str, Any]:
    """Dados (e somente eles) enviados ao modelo."""
    categories = sorted(link.category.slug for link in article.categories)
    payload = {
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
    hints = curation_hints(article)
    if hints:
        payload["curadoria"] = hints
    return payload


def compute_input_hash(payload: dict[str, Any], limits: dict[str, tuple[int, int]]) -> str:
    material = json.dumps(
        {
            "payload": payload,
            "prompt": ARTICLE_GENERATION_PROMPT.identifier,
            "review": EDITORIAL_REVIEW_PROMPT.identifier,
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
    primary: str | None = None


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


def _diverse(candidates: list[Candidate], limit: int) -> tuple[list[Candidate], list[Candidate]]:
    """Evita que uma editoria domine a edição sem forçar distribuição artificial.

    Nenhuma editoria passa de metade das vagas, exceto com descoberta de prioridade máxima
    (nota 85+). Vagas que sobrarem são preenchidas pela ordem de nota, sem cota.
    """
    cap = max(2, math.ceil(limit / 2))
    chosen: list[Candidate] = []
    held: list[Candidate] = []
    per_section: dict[str | None, int] = {}
    for candidate in candidates:
        if len(chosen) >= limit:
            held.append(candidate)
            continue
        count = per_section.get(candidate.primary, 0)
        if count >= cap and (candidate.score or 0) < PRIORITY_SCORE:
            held.append(candidate)
            continue
        per_section[candidate.primary] = count + 1
        chosen.append(candidate)
    while len(chosen) < limit and held:
        chosen.append(held.pop(0))
    chosen.sort(key=lambda c: c.score or 0.0, reverse=True)
    return chosen, held


def select_for_generation(
    session: Session,
    *,
    limit: int,
    min_abstract_words: int,
    word_limits: dict[str, tuple[int, int]],
    article_ids: list[int] | None = None,
    force: bool = False,
    min_score: float = CONSIDER_SCORE,
    require_ai_curation: bool = False,
) -> SelectionResult:
    """Escolhe as melhores descobertas para redação.

    Só entram artigos que a curadoria não rejeitou e com nota final >= ``min_score``
    (padrão 65). Com IA configurada (``require_ai_curation``), só artigos já avaliados pela
    curadoria por IA. Pertencer a uma editoria nunca basta. ``article_ids`` com ``force``
    ignora o corte (decisão explícita do editor).
    """
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
        assessment = effective_assessment(article)
        explicit = bool(article_ids) and force
        if not explicit:
            if assessment is None or assessment.decision is None:
                result.skip("sem_avaliacao_editorial", article.id)
                continue
            if require_ai_curation and not is_ai_assessment(assessment):
                result.skip("aguardando_curadoria", article.id)
                continue
            # Rejeição por regra (atualização menor, opinião, área sem editoria...) vale
            # sempre; nota baixa é tratada pelo corte ``min_score``.
            rejected_by_rule = bool(assessment.rejection_flags) or (
                assessment.decision == REJECT and assessment.final_score >= CONSIDER_SCORE
            )
            if rejected_by_rule:
                result.skip("rejeitado_pela_curadoria", article.id)
                continue
            if assessment.final_score < min_score:
                result.skip("abaixo_do_corte_editorial", article.id)
                continue
        input_hash = compute_input_hash(generation_payload(article), word_limits)
        content = latest_content(article)
        if content is not None and content.input_hash == input_hash and not force:
            if content.verification_status is VerificationStatus.FAILED:
                result.skip("bloqueado_por_verificacao", article.id)
            else:
                result.skip("sem_alteracoes", article.id)
            continue
        candidates.append(
            Candidate(
                article,
                assessment.final_score if assessment else None,
                input_hash,
                primary_category(list(article.categories)),
            )
        )
    candidates.sort(
        key=lambda c: (
            c.score is not None,
            c.score or 0.0,
            c.article.publication_date.toordinal() if c.article.publication_date else 0,
        ),
        reverse=True,
    )
    result.selected, extra = _diverse(candidates, limit)
    for candidate in extra:
        result.skip("limite_de_processamento", candidate.article.id)
    return result


# --- Redação ----------------------------------------------------------------------------


def _limits_text(limits: dict[str, tuple[int, int]]) -> str:
    return ", ".join(f"{name}: {low}-{high}" for name, (low, high) in limits.items())


def evidence_guidance(article: Article) -> str:
    record = effective_assessment(article)
    level = (record.evidence_level if record else None) or infer_evidence_level(article)
    return EVIDENCE_GUIDANCE.get(level, EVIDENCE_GUIDANCE["outro"])


def request_draft(
    provider: AIProvider,
    article: Article,
    limits: dict[str, tuple[int, int]],
    max_attempts: int,
    *,
    feedback: str = "",
) -> tuple[AIArticleDraft, dict[str, Any], str | None]:
    """Pede a matéria ao provedor; repete (limitado) se a resposta for inválida.

    ``feedback`` traz as instruções da revisão editorial quando se pede uma nova versão.
    """
    prompt = ARTICLE_GENERATION_PROMPT.render(
        orientacao_tipo=evidence_guidance(article),
        revisao=article.peer_review_status.value,
        titulos=HEADLINE_RULES,
        limites=_limits_text(limits),
        revisao_anterior=(
            "\nA versão anterior foi devolvida pela revisão editorial. Reescreva a matéria "
            "inteira corrigindo estes pontos:\n" + feedback[:2500] + "\n"
            if feedback
            else ""
        ),
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
        _add_usage(usage, response.usage)
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


def _add_usage(total: dict[str, Any], usage: dict[str, Any]) -> None:
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value


# --- Revisão editorial ------------------------------------------------------------------

MIN_REVIEW_SCORE = 7


def _draft_text(draft: AIArticleDraft) -> str:
    return "\n\n".join(
        [
            f"# {draft.headline}",
            f"> {draft.subtitle}",
            *[f"## {SECTION_TITLES[name]}\n\n{getattr(draft, name)}" for name in SECTION_FIELDS],
        ]
    )


def review_draft(
    provider: AIProvider, article: Article, draft: AIArticleDraft, max_attempts: int = 2
) -> tuple[AIEditorialReview | None, dict[str, Any]]:
    """Revisão de linguagem e de fidelidade. ``None`` se a resposta for inválida."""
    payload = generation_payload(article)
    payload.pop("curadoria", None)
    prompt = EDITORIAL_REVIEW_PROMPT.render(
        materia=untrusted_block({"materia": _draft_text(draft)}),
        dados=untrusted_block(payload),
    )
    usage: dict[str, Any] = {}
    schema = AIEditorialReview.model_json_schema()
    for _ in range(max_attempts):
        response = provider.generate_structured(
            prompt, schema, system=EDITORIAL_REVIEW_PROMPT.system
        )
        _add_usage(usage, response.usage)
        try:
            return AIEditorialReview.model_validate(response.data), usage
        except ValidationError as exc:
            logger.warning("Artigo %s: revisão editorial inválida: %s", article.id, exc)
    return None, usage


def assess_review(review: AIEditorialReview) -> tuple[bool, list[str], str]:
    """Aprovação da revisão e, se reprovada, o tipo de correção e as instruções."""
    scores = review.scores()
    low = {name for name, value in scores.items() if value < MIN_REVIEW_SCORE}
    if not low:
        return True, [], ""
    kinds = []
    lines = []
    if low & set(LANGUAGE_CRITERIA):
        kinds.append("simplificar")
        lines.append(
            "O texto está técnico ou pouco natural: reescreva de forma mais simples e direta, "
            "explicando os termos e cortando o jargão, sem perder precisão."
        )
    if low & set(PRECISION_CRITERIA):
        kinds.append("precisao")
        lines.append(
            "Há problemas de precisão ou fidelidade: corrija o que não está no estudo, "
            "deixe clara a diferença entre fato e hipótese e a maturidade do resultado."
        )
    if low & set(APPEAL_CRITERIA):
        kinds.append("interesse")
        lines.append(
            "O título ou a abertura não despertam interesse ou não batem com o texto: comece "
            "pela descoberta e escreva um título concreto e fiel."
        )
    detail = [f"Notas abaixo de {MIN_REVIEW_SCORE}: " + ", ".join(sorted(low)) + "."]
    detail += [f"- {p}" for p in review.problems]
    if review.instructions:
        detail.append(review.instructions)
    return False, kinds, "\n".join(lines + detail)


def complete_markdown(content: GeneratedArticleContent) -> str:
    return render_body(
        content.headline,
        content.sections(),
        content.reference,
        content.source_url,
        subtitle=content.subtitle,
    )


def generate_content(
    session: Session,
    provider: AIProvider,
    candidate: Candidate,
    *,
    limits: dict[str, tuple[int, int]],
    max_attempts: int,
    min_abstract_words: int,
    review_rounds: int = 1,
) -> tuple[GeneratedContent, VerificationReport]:
    """Redige, revisa (e reescreve, se preciso), verifica e persiste uma nova versão.

    A primeira resposta do modelo não é aceita automaticamente: a revisão editorial avalia
    linguagem e fidelidade e pode pedir até ``review_rounds`` novas versões. O resultado da
    última revisão fica gravado; se ela reprovar, a verificação marca WARNING e a matéria
    não é publicada automaticamente.
    """
    article = candidate.article
    source_url = source_url_for(article)
    if source_url is None:
        raise InsufficientInformationError("Artigo sem link original verificável.")
    draft, usage, model_name = request_draft(provider, article, limits, max_attempts)
    review_log: dict[str, Any] = {"prompt_version": EDITORIAL_REVIEW_PROMPT.version, "rounds": []}
    if provider.name == "mock":
        review_log["skipped"] = "provedor mock: sem revisão editorial"
    else:
        for round_number in range(review_rounds + 1):
            review, review_usage = review_draft(provider, article, draft)
            _add_usage(usage, review_usage)
            if review is None:
                review_log["approved"] = False
                review_log["rounds"].append({"error": "revisão editorial inválida"})
                break
            approved, kinds, feedback = assess_review(review)
            review_log["rounds"].append(
                {"scores": review.scores(), "problems": review.problems, "rewrite": kinds}
            )
            review_log["approved"] = approved
            if approved or round_number >= review_rounds:
                break
            logger.info("Artigo %s: revisão pediu nova versão (%s)", article.id, ", ".join(kinds))
            draft, rewrite_usage, model_name = request_draft(
                provider, article, limits, max_attempts, feedback=feedback
            )
            _add_usage(usage, rewrite_usage)
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
            subtitle=content.subtitle,
            editorial_review=review_log,
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
        subtitle=content.subtitle,
        discovery=content.discovery,
        how_it_works=content.how_it_works,
        why_it_matters=content.why_it_matters,
        limitations=content.limitations,
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
        editorial_review=review_log,
        verification_status=report.status,
        verification_report=report.as_dict(),
        verified_at=utcnow(),
        generated_at=utcnow(),
    )
    session.add(record)
    session.flush()
    return record, report


def content_under_review(record: GeneratedContent) -> ContentUnderReview:
    if record.discovery is None and record.how_it_works is None:
        sections = {  # conteúdo da primeira versão
            "introduction": record.introduction or "",
            "context": record.context or "",
            "research_question": record.research_question or "",
            "methodology": record.methodology or "",
            "findings": record.findings or "",
            "limitations": record.limitations or "",
            "ufabc_relevance": record.relevance or "",
        }
    else:
        sections = {
            "discovery": record.discovery or "",
            "how_it_works": record.how_it_works or "",
            "why_it_matters": record.why_it_matters or "",
            "limitations": record.limitations or "",
        }
    return ContentUnderReview(
        headline=record.headline or "",
        original_title=record.original_title or "",
        sections=sections,
        reference=record.reference or "",
        source_url=record.source_url or "",
        uncertainty_notes=tuple(record.uncertainty_notes or ()),
        subtitle=record.subtitle or "",
        editorial_review=record.editorial_review,
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


def _curation_summary(article: Article) -> str | None:
    record = effective_assessment(article)
    return explain_record(record) if record is not None else None


def _review_summary(review: dict[str, Any] | None) -> str | None:
    if not review:
        return None
    if review.get("skipped"):
        return str(review["skipped"])
    rounds = review.get("rounds") or []
    last = rounds[-1] if rounds else {}
    status = "aprovada" if review.get("approved") else "REPROVADA (não publicar sem revisão)"
    scores = ", ".join(f"{k}={v}" for k, v in (last.get("scores") or {}).items())
    return f"{status} após {len(rounds)} rodada(s). {scores}".strip()


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
    primary = primary_category(list(article.categories))
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
        "curation": _curation_summary(article),
        "editorial_review": _review_summary(record.editorial_review),
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
    min_score: float = CONSIDER_SCORE,
    require_ai_curation: bool | None = None,
    review_rounds: int = 1,
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
            min_score=min_score,
            require_ai_curation=(
                provider.name != "mock" if require_ai_curation is None else require_ai_curation
            ),
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
                    review_rounds=review_rounds,
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
