"""Verificação determinística de fidelidade (SPECIFICATION.md, seção 12; Etapa 3, seção 10).

Independe da IA: usa apenas regras sobre o texto gerado e os metadados
coletados. **Não comprova a veracidade científica**; aponta inconsistências
que exigem revisão humana.

Estados: ``PASSED`` (nenhuma inconsistência encontrada), ``WARNING`` (pontos
que exigem atenção humana) e ``FAILED`` (inconsistência crítica ou conteúdo
insuficiente — bloqueia a aprovação normal).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus, VerificationStatus
from ufabc_science.domain.models import Article
from ufabc_science.intelligence.schemas import (
    DEFAULT_WORD_LIMITS,
    MAX_HEADLINE_CHARS,
    SUBTITLE_TITLE,
    is_legacy,
    section_layout,
)
from ufabc_science.processing.normalization import (
    doi_url,
    is_http_url,
    is_valid_doi,
    normalize_doi,
    normalize_title,
    normalize_url,
    strip_accents,
    word_count,
)

_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?:\s?%)?")
_DOI_IN_TEXT = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>)\]]+", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
_CITATION = re.compile(
    r"\(\s*[A-ZÀ-Ý][\w'’-]+(?:\s+(?:et al\.?|e colaboradores|and|e|&)\s*[A-ZÀ-Ý]?"  # noqa: RUF001
    r"[\w'’-]*)?,?\s+(?:19|20)\d{2}[a-z]?\s*\)"  # noqa: RUF001
)
_ET_AL = re.compile(r"\b([A-ZÀ-Ý][\w'’-]+)\s+(?:et al\.?|e colaboradores)")  # noqa: RUF001
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z][a-z0-9-]{4,}")
# Siglas e termos técnicos curtos (NAMs, 3Rs, LLM, fMRI) são preservados entre idiomas.
_ACRONYM = re.compile(r"\b(?=[A-Za-z0-9-]*[A-Z][A-Za-z0-9-]*[A-Z0-9])[A-Za-z0-9-]{2,12}\b")
LENGTH_TOLERANCE = 1.25

SENSATIONAL = (
    r"provaram",
    r"prova(?:m)? que",
    r"comprov(?:a|ou|aram|am)",
    r"\bcura(?:r|m)?\b",
    r"revolucion",
    r"milagr",
    r"definitivamente",
    r"sem precedentes",
    r"descoberta historica",
    r"garante(?:m)? que",
    r"de uma vez por todas",
)
CLINICAL_ADVICE = (
    r"pacientes devem",
    r"deve(?:m)? (?:tomar|usar|ingerir|suspender)",
    r"recomenda-se (?:o uso|a ingestao|tomar|que pacientes|o tratamento)",
    r"substitu(?:i|ir|a) o tratamento",
    r"tratamento recomendado",
)
_LIMITATION_CUES = re.compile(
    r"\b(limitation|limited by|small sample|preliminary|caveat|further (?:work|studies)|"
    r"future (?:work|research)|however)",
    re.IGNORECASE,
)
_NOT_AVAILABLE = re.compile(r"nao (?:foram|foi|estao|esta) (?:informad|disponive|detalhad)")
_PEER_REVIEW_CLAIM = re.compile(r"revisad[oa]s? por pares|revisao por pares")
_NEGATION = re.compile(r"\b(nao|ainda nao|sem|antes da)\b")

# Fórmulas típicas de texto gerado ou acadêmico que a política editorial proíbe.
CLICHES = (
    r"neste artigo",
    r"imagine que",
    r"voce ja se perguntou",
    r"no mundo atual",
    r"na busca incessante",
    r"em um avanco significativo",
    r"pesquisadores tem se dedicado",
    r"e importante ressaltar",
    r"vale (?:destacar|ressaltar)",
    r"\bem suma\b",
    r"\bem resumo\b",
    r"\bdesvend",
    r"abre caminho",
    r"um passo importante",
)
# Resultado de laboratório ou em animais apresentado como tratamento disponível.
MATURITY_OVERCLAIM = (
    r"ja (?:esta|estao) disponive",
    r"ja pode(?:m)? ser usad",
    r"pode(?:m)? ser usad[oa]s? (?:em|por) pacientes",
    r"tratamento eficaz",
    r"(?:eficacia|seguranca) comprovada",
    r"cura (?:para|da|do)\b",
    r"novo tratamento para",
)
_ANIMAL_STUDY = re.compile(r"\bmice\b|\bmouse\b|\brats?\b|murine|zebrafish|primates?\b|in vivo")
_ANIMAL_MENTION = re.compile(r"camundong|\bratos?\b|animais|animal|peixe-zebra|primatas|murino")
_LAB_STUDY = re.compile(r"in vitro|cell lines?|organoid")
_LAB_MENTION = re.compile(
    r"laboratorio|celulas|in vitro|organoide|cultura|tecido|ainda nao (?:foi )?testad"
)
MAX_AVG_SENTENCE_WORDS = 30
MAX_SENTENCE_WORDS = 50
# Frases sobre a publicação (não sobre o resultado) não entram na checagem de afirmações.
_META_SENTENCE = re.compile(
    r"preprint|revis(?:ao|ad[oa]s?) por pares|foi (?:registrad|publicad)|periodico|"
    r"rascunho|editor"
)


@dataclass
class Check:
    code: str
    status: VerificationStatus
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class Claim:
    text: str
    supported: bool
    evidence: list[str]


@dataclass
class VerificationReport:
    status: VerificationStatus
    checks: list[Check]
    claims: list[Claim]
    verified_at: str

    @property
    def warnings(self) -> list[str]:
        return [c.message for c in self.checks if c.status is VerificationStatus.WARNING]

    @property
    def failures(self) -> list[str]:
        return [c.message for c in self.checks if c.status is VerificationStatus.FAILED]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        for check in data["checks"]:
            check["status"] = check["status"].value
        return data


@dataclass(frozen=True)
class ContentUnderReview:
    """Texto a verificar: rascunho da IA ou versão editada em Markdown."""

    headline: str
    original_title: str
    sections: dict[str, str]
    reference: str
    source_url: str
    uncertainty_notes: tuple[str, ...] = ()
    subtitle: str = ""
    # Resultado da revisão editorial por IA (``None`` em textos editados à mão).
    editorial_review: dict[str, Any] | None = None


def _plain(text: str) -> str:
    return strip_accents(text).casefold()


def _number_variants(raw: str) -> set[str]:
    value = raw.replace(" ", "").rstrip("%")
    variants = {value, value.replace(",", ".")}
    # "1.000" / "1,000" como separador de milhar; "0,5" como decimal.
    variants.add(value.replace(".", "").replace(",", ""))
    if re.fullmatch(r"\d+[.,]0+", value):
        variants.add(re.split(r"[.,]", value)[0])
    return {v.lstrip("0") or "0" for v in variants}


def _source_numbers(article: Article) -> set[str]:
    parts = [article.title or "", article.abstract or "", article.journal or ""]
    if article.publication_date:
        d = article.publication_date
        parts += [str(d.year), str(d.day), str(d.month)]
    numbers: set[str] = set()
    for text in parts:
        for match in _NUMBER.findall(text):
            numbers |= _number_variants(match)
    return numbers


def _anchor_tokens(text: str) -> set[str]:
    """Termos para vincular afirmações à fonte, tolerando a diferença de idioma.

    Inclui siglas e o prefixo de 5 letras de palavras longas, que aproxima cognatos
    português/inglês (certificado/certified, instâncias/instances, energia/energy).
    """
    acronyms = {a.casefold() for a in _ACRONYM.findall(text)}
    tokens = set(_TOKEN.findall(_plain(text)))
    stems = {f"{t[:5]}~" for t in tokens if len(t) >= 6}
    return tokens | stems | acronyms


def build_reference(article: Article) -> str:
    """Referência bibliográfica a partir dos metadados (nunca gerada pela IA)."""
    authors = [a.get("name") for a in article.authors or [] if a.get("name")]
    if len(authors) > 3:
        author_text = ", ".join(authors[:3]) + " et al."
    else:
        author_text = ", ".join(authors) or "Autoria não informada"
    year = str(article.publication_date.year) if article.publication_date else "s.d."
    venue = article.journal or article.publisher or "Fonte não informada"
    title = article.title.rstrip(".")
    reference = f"{author_text.rstrip('.')}. {title}. {venue}. {year}."
    if author_text.endswith("et al."):
        reference = f"{author_text} {title}. {venue}. {year}."
    if article.doi:
        reference += f" DOI: {article.doi}."
    if article.peer_review_status is PeerReviewStatus.PREPRINT:
        reference += " (Preprint, sem revisão por pares confirmada.)"
    return reference


def source_url_for(article: Article) -> str | None:
    """Link original: DOI quando disponível; senão a URL coletada da fonte."""
    if article.doi and is_valid_doi(article.doi):
        return doi_url(article.doi)
    for candidate in [article.canonical_url, *[s.original_url for s in article.sources]]:
        if is_http_url(candidate):
            return candidate
    return None


def _allowed_urls(article: Article) -> set[str]:
    urls = {normalize_url(article.canonical_url)}
    urls |= {normalize_url(s.original_url) for s in article.sources}
    if article.doi:
        urls.add(normalize_url(doi_url(article.doi)))
    return {u for u in urls if u}


def verify_content(
    article: Article,
    content: ContentUnderReview,
    *,
    min_abstract_words: int = 40,
    word_limits: dict[str, tuple[int, int]] | None = None,
) -> VerificationReport:
    limits = {**DEFAULT_WORD_LIMITS, **(word_limits or {})}
    checks: list[Check] = []
    fail, warn, ok = (
        VerificationStatus.FAILED,
        VerificationStatus.WARNING,
        VerificationStatus.PASSED,
    )

    def add(code: str, status: VerificationStatus, message: str, details: list[str] | None = None):
        checks.append(Check(code, status, message, details or []))

    fields, titles = section_layout(content.sections)
    legacy = is_legacy(content.sections)
    body = " ".join([content.headline, content.subtitle, *content.sections.values()])
    plain_body = _plain(body)

    # 1. Informação de origem suficiente.
    abstract_words = word_count(article.abstract)
    if abstract_words < min_abstract_words:
        add(
            "insufficient_source",
            fail,
            f"Informação insuficiente na fonte: abstract com {abstract_words} palavra(s) "
            f"(mínimo {min_abstract_words}). Não publicar conteúdo especulativo.",
        )

    # 1b. Fonte atípica: depósito sem triagem ou "abstract" que é na verdade outro texto.
    from ufabc_science.processing.relevance import (
        MAX_TYPICAL_ABSTRACT_WORDS,
        unmoderated_repository,
    )

    source_notes = []
    repository = unmoderated_repository(article)
    if repository:
        source_notes.append(f"depositado em repositório sem triagem editorial ({repository})")
    if abstract_words > MAX_TYPICAL_ABSTRACT_WORDS:
        source_notes.append(f"abstract atípico com {abstract_words} palavras")
    if source_notes:
        add(
            "source_quality",
            warn,
            "Fonte atípica: confirme que se trata de pesquisa científica antes de aprovar.",
            source_notes,
        )

    # 2. Título original e título editorial.
    if normalize_title(content.original_title) != normalize_title(article.title):
        add("title_mismatch", fail, "O título original não corresponde ao registro coletado.")
    else:
        add("title_match", ok, "Título original corresponde ao registro coletado.")
    if not content.headline.strip():
        add("headline_missing", fail, "Título editorial ausente.")

    # 3. Seções obrigatórias.
    empty = [titles[name] for name in fields if not content.sections.get(name)]
    if not legacy and not content.subtitle.strip():
        empty.insert(0, SUBTITLE_TITLE)
    if empty:
        add("sections_missing", fail, "Seções obrigatórias vazias.", empty)

    # 4. DOI e link original.
    if article.doi:
        if not is_valid_doi(article.doi):
            add("doi_invalid", fail, f"DOI mal formatado no registro: {article.doi}")
        elif article.doi not in content.reference:
            add("doi_reference", fail, "A referência não contém o DOI do registro coletado.")
        else:
            add("doi_ok", ok, "DOI presente e bem formatado.")
    else:
        add("doi_absent", warn, "Registro sem DOI: confirme a fonte pelo link original.")
    foreign_dois = sorted(
        {
            d
            for d in (normalize_doi(m) for m in _DOI_IN_TEXT.findall(body))
            if d and d != article.doi
        }
    )
    if foreign_dois:
        add("doi_foreign", fail, "O texto menciona DOI que não pertence ao registro.", foreign_dois)

    if not is_http_url(content.source_url):
        add("source_url_invalid", fail, "Link original ausente ou inválido.")
    elif normalize_url(content.source_url) not in _allowed_urls(article):
        add("source_url_mismatch", fail, "Link original não corresponde às fontes coletadas.")
    else:
        add("source_url_ok", ok, "Link original corresponde ao registro.")
    foreign_urls = sorted(
        {u for u in _URL_IN_TEXT.findall(body) if normalize_url(u) not in _allowed_urls(article)}
    )
    if foreign_urls:
        add("url_foreign", fail, "O texto contém links não associados ao registro.", foreign_urls)

    # 5. Autores.
    surnames = {
        _plain(name.split()[-1])
        for name in (a.get("name", "") for a in article.authors or [])
        if name.strip()
    }
    if not surnames:
        add("authors_missing", warn, "Autores não disponíveis nos metadados.")
    else:
        unknown = sorted({name for name in _ET_AL.findall(body) if _plain(name) not in surnames})
        if unknown:
            add(
                "authors_mismatch",
                fail,
                "O texto atribui o trabalho a autores ausentes dos metadados.",
                unknown,
            )
        else:
            add("authors_ok", ok, "Autores citados correspondem aos metadados.")

    # 6. Citações bibliográficas inventadas.
    citations = _CITATION.findall(body)
    if citations:
        add("citations", fail, "O texto contém citações bibliográficas não fornecidas.", citations)

    # 7. Data e tipo de publicação.
    if article.publication_date is None:
        add("date_missing", warn, "Data de publicação não disponível.")
    if article.article_type is ArticleType.UNKNOWN:
        add("type_unknown", warn, "Tipo de publicação não identificado.")

    # 8. Números e estatísticas sem correspondência na fonte.
    allowed_numbers = _source_numbers(article)
    unmatched = []
    numbered = " ".join([*content.sections.values(), content.headline, content.subtitle])
    for match in _NUMBER.findall(numbered):
        if not (_number_variants(match) & allowed_numbers):
            unmatched.append(match.strip())
    if unmatched:
        add(
            "numbers_unmatched",
            fail,
            "Números sem correspondência no título/abstract coletados.",
            sorted(set(unmatched)),
        )
    else:
        add("numbers_ok", ok, "Todos os números do texto aparecem na fonte.")

    # 9. Afirmações dos resultados vinculadas a evidências da fonte.
    source_tokens = _anchor_tokens(f"{article.title} {article.abstract or ''}")
    claims: list[Claim] = []
    findings = (
        content.sections.get("findings", "")
        if legacy
        else " ".join([content.sections.get("discovery", ""), content.subtitle])
    )
    for sentence in _SENTENCE.split(findings):
        if len(sentence.split()) < 4 or _META_SENTENCE.search(_plain(sentence)):
            continue
        evidence = sorted(_anchor_tokens(sentence) & source_tokens)[:6]
        numbers = [n for n in _NUMBER.findall(sentence) if _number_variants(n) & allowed_numbers]
        supported = len(evidence) >= 2 or bool(numbers)
        claims.append(Claim(sentence.strip(), supported, evidence + numbers))
    unsupported = [c.text for c in claims if not c.supported]
    if unsupported:
        add(
            "claims_unsupported",
            warn,
            "Afirmações de resultados sem evidência vinculável ao abstract (verificar).",
            unsupported,
        )

    # 10. Limitações preservadas.
    limitations = _plain(content.sections.get("limitations", ""))
    if _LIMITATION_CUES.search(article.abstract or "") and _NOT_AVAILABLE.search(limitations):
        add(
            "limitations_omitted",
            warn,
            "O abstract menciona limitações, mas o texto diz que elas não foram informadas.",
        )

    # 11. Preprints e revisão por pares.
    status = article.peer_review_status
    mentions_preprint = "preprint" in plain_body or "revisao por pares" in plain_body
    if status is PeerReviewStatus.PREPRINT and not mentions_preprint:
        add("preprint_unlabeled", fail, "Preprint não identificado como tal no texto.")
    elif status is PeerReviewStatus.PREPRINT:
        add("preprint_labeled", ok, "Preprint identificado no texto.")
    if status is not PeerReviewStatus.VERIFIED:
        for sentence in _SENTENCE.split(plain_body):
            if _PEER_REVIEW_CLAIM.search(sentence) and not _NEGATION.search(sentence):
                add(
                    "peer_review_claim",
                    fail,
                    "O texto afirma revisão por pares sem confirmação nos metadados.",
                    [sentence[:200]],
                )
                break

    # 12. Sensacionalismo, causalidade indevida e aconselhamento clínico.
    sensational = [p for p in SENSATIONAL if re.search(p, plain_body)]
    if sensational:
        add(
            "sensationalism",
            warn,
            "Linguagem sensacionalista ou causal sem sustentação (revisar).",
            [p.replace("\\b", "") for p in sensational],
        )
    clinical = [p for p in CLINICAL_ADVICE if re.search(p, plain_body)]
    if clinical:
        add("clinical_advice", fail, "O texto contém aconselhamento clínico indevido.", clinical)

    # 13. Extensão (referência configurável). Texto curto não gera aviso: a especificação
    # proíbe aumentar artificialmente o texto quando a fonte tem pouca informação.
    too_long = []
    sized = {name: content.sections.get(name) for name in fields}
    if not legacy:
        sized["subtitle"] = content.subtitle
    for name, text in sized.items():
        _, high = limits.get(name, (0, 10_000))
        words = word_count(text)
        if words > high * LENGTH_TOLERANCE:
            label = titles.get(name, SUBTITLE_TITLE)
            too_long.append(f"{label}: {words} palavras (ref. até {high})")
    total = sum(word_count(t) for t in content.sections.values())
    _, high = limits.get("total", (0, 10_000))
    if total > high * LENGTH_TOLERANCE:
        too_long.append(f"Total: {total} palavras (ref. até {high})")
    if too_long:
        add("length", warn, "Texto mais longo que a referência configurada.", too_long)

    # 15. Estilo editorial: clichês, travessões, título e frases longas demais.
    if not legacy:
        style = [p.replace("\\b", "") for p in CLICHES if re.search(p, plain_body)]
        if "—" in body:
            style.append("travessão (—)")
        if style:
            add("style", warn, "Fórmulas proibidas pela política editorial (reescrever).", style)
        headline_issues = []
        if len(content.headline) > MAX_HEADLINE_CHARS:
            headline_issues.append(f"{len(content.headline)} caracteres")
        if content.headline.rstrip().endswith("?"):
            headline_issues.append("título em forma de pergunta")
        if ":" in content.headline:
            headline_issues.append("título com dois-pontos (estilo acadêmico)")
        if headline_issues:
            add("headline_style", warn, "Título fora do padrão editorial.", headline_issues)
        sentences = [s for s in _SENTENCE.split(" ".join(content.sections.values())) if s.strip()]
        if sentences:
            lengths = [len(s.split()) for s in sentences]
            average = sum(lengths) / len(lengths)
            if average > MAX_AVG_SENTENCE_WORDS or max(lengths) > MAX_SENTENCE_WORDS:
                add(
                    "readability",
                    warn,
                    f"Frases longas demais (média de {average:.0f} e máximo de {max(lengths)} "
                    "palavras): simplificar.",
                )

    # 16. Maturidade científica: laboratório e animais não são tratamento disponível.
    overclaim = [p for p in MATURITY_OVERCLAIM if re.search(p, plain_body)]
    if overclaim:
        add(
            "maturity_overclaim",
            warn,
            "O texto pode apresentar resultado preliminar como tratamento ou eficácia comprovada.",
            [p.replace("\\b", "") for p in overclaim],
        )
    source_text = _plain(f"{article.title} {article.abstract or ''}")
    if not legacy:
        if _ANIMAL_STUDY.search(source_text) and not _ANIMAL_MENTION.search(plain_body):
            add("maturity_unstated", warn, "Estudo em animais, mas o texto não diz isso ao leitor.")
        elif _LAB_STUDY.search(source_text) and not _LAB_MENTION.search(plain_body):
            add(
                "maturity_unstated",
                warn,
                "Experimento de laboratório, mas o texto não diz isso ao leitor.",
            )

    # 17. Revisão editorial por IA (linguagem e fidelidade).
    review = content.editorial_review
    if review and not review.get("skipped") and not review.get("approved"):
        rounds = review.get("rounds") or []
        problems = list((rounds[-1] if rounds else {}).get("problems") or [])
        add(
            "editorial_review",
            warn,
            "A revisão editorial não aprovou o texto após as reescritas.",
            problems[:8],
        )

    # 14. Pontos de incerteza informados pelo gerador.
    if content.uncertainty_notes:
        add(
            "uncertainty_notes",
            warn,
            "O gerador indicou pontos para verificação humana.",
            list(content.uncertainty_notes),
        )

    statuses = {c.status for c in checks}
    overall = fail if fail in statuses else warn if warn in statuses else ok
    return VerificationReport(
        status=overall,
        checks=checks,
        claims=claims,
        verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
