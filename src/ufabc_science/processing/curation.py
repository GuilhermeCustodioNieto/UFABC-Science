"""Curadoria editorial: o que merece virar matéria (política editorial, seções 3 e 4).

O pipeline procura primeiro descobertas interessantes e só depois as classifica. Cada
candidato recebe cinco notas de 0 a 100 e uma decisão justificada:

============================  =====
Critério                      Peso
============================  =====
Potencial de curiosidade      30
Relevância científica         25
Grau de novidade              20
Potencial de impacto          15
Qualidade das evidências      10
============================  =====

Faixas: 85-100 prioridade máxima, 75-84 publicar, 65-74 avaliar se houver espaço,
abaixo de 65 rejeitar. Qualquer regra de rejeição (atualização menor, opinião, notícia
empresarial, pesquisa antiga...) rejeita, independentemente da nota.

Há dois avaliadores com a mesma saída:

* **heurístico** (sem IA, determinístico): roda sobre todos os artigos e serve de
  pré-filtro barato. Regras de rejeição verificáveis por padrão de texto são aplicadas
  aqui. Sem IA configurada, é ele quem decide.
* **IA** (``CURATION_PROMPT``): roda só na lista curta do heurístico. Identifica a
  descoberta central, o nível de evidência, as editorias e as conexões entre áreas, e
  dá as notas. O código, não o modelo, calcula a nota final e a decisão; as notas de
  evidência são limitadas pelos metadados (um preprint nunca tem evidência de artigo
  revisado) e as rejeições determinísticas continuam valendo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ufabc_science.domain.enums import ArticleType, ClassificationMethod, PeerReviewStatus
from ufabc_science.domain.models import (
    Article,
    ArticleCategory,
    Category,
    RelevanceAssessment,
    utcnow,
)
from ufabc_science.domain.schemas import EXCEPTIONAL_ONLY_CATEGORY, INTERDISCIPLINARY_CATEGORY
from ufabc_science.intelligence.base import AIProvider
from ufabc_science.intelligence.exceptions import AIError
from ufabc_science.processing.normalization import strip_accents, word_count

logger = logging.getLogger(__name__)

HEURISTIC_VERSION = "curation-heuristic-v1"
AI_METHOD_PREFIX = "curation-ai"

WEIGHTS = {
    "curiosity": 0.30,
    "scientific_relevance": 0.25,
    "novelty": 0.20,
    "impact": 0.15,
    "evidence_quality": 0.10,
}
CRITERIA_LABELS = {
    "curiosity": "Potencial de curiosidade",
    "scientific_relevance": "Relevância científica",
    "novelty": "Grau de novidade",
    "impact": "Potencial de impacto",
    "evidence_quality": "Qualidade das evidências",
}

PRIORITY, PUBLISH, CONSIDER, REJECT = "priority", "publish", "consider", "reject"
DECISION_LABELS = {
    PRIORITY: "prioridade máxima",
    PUBLISH: "publicar",
    CONSIDER: "avaliar se houver espaço",
    REJECT: "rejeitar",
}
PRIORITY_SCORE, PUBLISH_SCORE, CONSIDER_SCORE = 85.0, 75.0, 65.0

# Mesma lista de ``RejectionFlag`` (intelligence/schemas.py), com a explicação ao leitor.
REJECTION_REASONS = {
    "atualizacao_menor": "anuncia apenas uma atualização pequena (versão, lançamento, ajuste)",
    "resultado_trivial": "resultado trivial ou esperado",
    "especifico_demais": "específico demais e sem implicações interessantes",
    "sem_novidade": "não apresenta novidade relevante",
    "noticia_empresarial": "notícia empresarial ou de mercado sem contribuição científica",
    "opiniao_como_descoberta": "opinião, comentário ou editorial apresentado como descoberta",
    "sem_fonte_verificavel": "não tem fonte verificável",
    "pesquisa_antiga": "reproduz pesquisa antiga sem desenvolvimento novo",
    "sensacionalista": "abordagem sensacionalista",
    "correlacao_como_causa": "apresenta correlação como causalidade",
    "hipotese_como_fato": "transforma hipótese em fato comprovado",
    # Regra interna (não é sugerida pela IA): sem dados, só daria para especular.
    "informacao_insuficiente": "informação insuficiente na fonte para escrever sem especular",
}

OLD_RESEARCH_DAYS = 540
# Abstracts reais raramente passam disso; acima, é texto completo ou registro atípico.
MAX_TYPICAL_ABSTRACT_WORDS = 600

# --- Fontes ------------------------------------------------------------------------------

# Repositórios de depósito livre, sem triagem editorial. Servidores de preprint com
# moderação (arXiv, bioRxiv, medRxiv...) não entram aqui.
UNMODERATED_REPOSITORIES = {
    "zenodo": "Zenodo",
    "osf preprints": "OSF Preprints",
    "figshare": "Figshare",
    "researchgate": "ResearchGate",
    "academia.edu": "Academia.edu",
}
_UNMODERATED_DOI_PREFIXES = {"10.5281/": "Zenodo", "10.6084/": "Figshare", "10.31219/": "OSF"}

PREPRINT_SERVERS = (
    "arxiv",
    "biorxiv",
    "medrxiv",
    "chemrxiv",
    "psyarxiv",
    "socarxiv",
    "ssrn",
    "research square",
    "preprints.org",
    "scielo preprints",
)

# Periódicos e anais reconhecidos por área (lista aberta, seção 4 da política editorial).
# Indicam fonte confiável com revisão rigorosa; não substituem a avaliação do conteúdo.
RECOGNIZED_VENUES = frozenset(
    {
        "nature",
        "science",
        "cell",
        "the lancet",
        "lancet",
        "new england journal of medicine",
        "the new england journal of medicine",
        "jama",
        "bmj",
        "the bmj",
        "proceedings of the national academy of sciences",
        "proceedings of the national academy of sciences of the united states of america",
        "pnas",
        "science advances",
        "science robotics",
        "science translational medicine",
        "science immunology",
        "elife",
        "plos biology",
        "plos medicine",
        "neuron",
        "brain",
        "current biology",
        "psychological science",
        "trends in cognitive sciences",
        "the astrophysical journal",
        "astrophysical journal",
        "the astrophysical journal letters",
        "astronomy & astrophysics",
        "astronomy and astrophysics",
        "monthly notices of the royal astronomical society",
        "the astronomical journal",
        "icarus",
        "aiaa journal",
        "journal of propulsion and power",
        "acta astronautica",
        "journal of spacecraft and rockets",
        "american economic review",
        "the quarterly journal of economics",
        "quarterly journal of economics",
        "econometrica",
        "journal of political economy",
        "the review of economic studies",
        "review of economic studies",
        "american sociological review",
        "american journal of sociology",
        "mind",
        "the philosophical review",
        "noûs",
        "nous",
        "the journal of philosophy",
        "journal of the acm",
        "communications of the acm",
        "advances in neural information processing systems",
        "international conference on machine learning",
        "international conference on learning representations",
    }
)
RECOGNIZED_PREFIXES = (
    "nature ",
    "the lancet ",
    "lancet ",
    "jama ",
    "cell ",
    "physical review",
    "ieee transactions on",
    "ieee journal of",
    "acm transactions on",
    "proceedings of the acm",
    "proceedings of the ieee",
    "annual review of",
)


def unmoderated_repository(article: Article) -> str | None:
    """Nome do repositório genérico sem triagem em que o registro foi depositado, se houver."""
    venue = (article.journal or "").casefold()
    for key, name in UNMODERATED_REPOSITORIES.items():
        if key in venue:
            return name
    for prefix, name in _UNMODERATED_DOI_PREFIXES.items():
        if (article.doi or "").startswith(prefix):
            return name
    return None


def source_tier(article: Article) -> tuple[str, str]:
    """Confiabilidade da fonte: ``A`` reconhecida, ``B`` revisada, ``C`` preprint, ``D`` sem
    triagem, ``U`` desconhecida. Volta também a explicação."""
    repository = unmoderated_repository(article)
    if repository:
        return "D", f"repositório sem triagem editorial ({repository})"
    venue = " ".join((article.journal or "").casefold().split())
    if article.peer_review_status is PeerReviewStatus.PREPRINT or any(
        server in venue for server in PREPRINT_SERVERS
    ):
        return "C", "preprint em servidor moderado, sem revisão por pares"
    if venue in RECOGNIZED_VENUES or venue.startswith(RECOGNIZED_PREFIXES):
        return "A", f"periódico/anais reconhecido ({article.journal})"
    if article.peer_review_status is PeerReviewStatus.VERIFIED:
        return "B", "publicação revisada por pares"
    return "U", "revisão por pares não confirmada"


# --- Sinais de texto ---------------------------------------------------------------------


def _label(pattern: str) -> str:
    """Rótulo legível de um padrão (primeira alternativa, sem metacaracteres)."""
    text = re.sub(r"\[([^\]])[^\]]*\]", r"\1", pattern)  # [sz] -> s
    text = re.sub(r"\(\?:([^|)]*)[^)]*\)\??", r"\1", text)  # (?:ed|ations?) -> ed
    first = text.split("|")[0]
    return re.sub(r"[\\()?*+:]", "", first).strip()


def _find(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [_label(p) for p in patterns if re.search(rf"(?<!\w)(?:{p})", text)]


_SURPRISE = (
    r"for the first time",
    r"first (?:direct |ever |known )?(?:evidence|detection|observation|demonstration|images?)",
    r"unexpected",
    r"surpris",
    r"counterintuitive|counter-intuitive",
    r"contrary to",
    r"paradox",
    r"never before",
    r"previously unknown",
    r"discover",
    r"reveal",
    r"challeng(?:es|ed|ing) (?:the|long|current|common)",
    r"overturn",
    r"mystery|puzzl",
    r"record[- ]breaking",
    r"largest|smallest|oldest|earliest|fastest|most distant|coldest|hottest",
    r"unprecedented",
    r"long-standing",
    r"were expected|was expected|than predicted|than expected",
    r"but not (?:in|for|of|among)",
    r"restor(?:e|es|ed|ing) (?:hearing|vision|sight|movement|memory|function)",
)
_FASCINATING_TOPICS = (
    r"black holes?",
    r"exoplanet",
    r"dark matter|dark energy",
    r"early universe|big bang",
    r"supernova",
    r"gravitational waves?",
    r"james webb|jwst",
    r"habitab|biosignature",
    r"atmospheres?",
    r"origin of life",
    r"consciousness",
    r"dreams?",
    r"memor(?:y|ies)|forgett",
    r"sleep",
    r"learn(?:s|ing)? (?:faster|new)|learns",
    r"brain.computer|neural implant|neuroprosthe",
    r"gene therap",
    r"gene editing|crispr",
    r"vaccine",
    r"cancer|tumou?r",
    r"regenerat",
    r"antibiotic|superbug|drug-resistant",
    r"deaf|hearing|blind|paraly",
    r"alzheimer",
    r"aging|ageing|longevity",
    r"placebo",
    r"quantum computer|qubit",
    r"large language model|generative ai|foundation model|artificial intelligence",
    r"neuromorphic",
    r"robot",
    r"rocket|propulsion|spacecraft|lander|rover",
    r"mars|lunar|moon|asteroid|comet",
    r"fossil|extinct|ancient dna",
    r"superconduct|metamaterial",
    r"decision[- ]making|cooperation|altruism|creativity",
    r"inequality",
    r"productivity",
)
_DULL = (
    r"case study",
    r"case report",
    r"a comparative (?:study|analysis|performance)",
    r"performance evaluation",
    r"we evaluate",
    r"improv(?:e|es|ed|ing) the (?:accuracy|performance|efficiency)",
    r"state-of-the-art (?:results|performance) on",
    r"bibliometric",
    r"scoping review",
    r"literature review",
    r"psychometric",
    r"validation of (?:the|a)",
    r"questionnaire",
    r"optimi[sz]ation (?:of|strateg)",
    r"parameter (?:tuning|estimation|optimi)",
    r"a framework for",
    r"municipalit",
    r"province of",
    r"in the context of",
    r"teaching|curriculum",
    r"routine",
    r"practical guidance",
)
_METHOD = (
    r"randomi[sz]ed",
    r"cohort",
    r"meta-analys",
    r"systematic review",
    r"experiments?",
    r"participants",
    r"sample of",
    r"observ(?:ed|ations?)",
    r"longitudinal",
    r"preregistered|replicated",
    r"n ?= ?\d",
    r"simulation",
    r"we (?:show|demonstrate|find|found|measured|delivered|trained|treated|tested|screened)",
    r"in mice|in vivo|in vitro",
    r"we (?:study|analy[sz]e|estimate|exploit|observed)",
    r"natural experiment|staggered|difference-in-differences|instrumental variable",
)
_NOVELTY = (
    r"novel",
    r"first",
    r"new (?:approach|method|class|mechanism|material|type|kind|way)",
    r"we propose|we introduce|we present",
    r"previously unknown",
    r"unprecedented",
    r"challeng(?:es|ed|ing) (?:the|long|current|common)",
    r"contrary to",
    r"unexpected|surpris",
    r"no (?:treatment|cure)|has no",
)
_IMPACT = (
    r"therap",
    r"treatment|cure",
    r"diagnos",
    r"vaccine",
    r"clinical",
    r"public health",
    r"polic(?:y|ies)",
    r"climate",
    r"energy",
    r"sustainab",
    r"could (?:enable|lead|help|transform)|path toward",
    r"models? of|understanding of|explain",
    r"inequality",
    r"labou?r markets?",
    r"productivity",
    r"training|education",
    r"resistan",
    r"restor|recover",
    r"exploration",
)
_PRELIMINARY = (r"preliminary", r"pilot", r"exploratory", r"feasibility")

# Regras de rejeição verificáveis por padrão de texto (sobretudo no título).
_TITLE_REJECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        r"^(?:erratum|corrigendum|correction(?: to)?|retraction|retracted|expression of concern)\b",
        "sem_novidade",
        "aviso de correção ou retratação, não uma pesquisa nova",
    ),
    (
        r"^(?:editorial|commentary|comment on|perspective|viewpoint|opinion|letter to the editor|"
        r"reply to|response to|in memoriam|obituary|book review)\b",
        "opiniao_como_descoberta",
        "editorial, comentário ou opinião",
    ),
    (
        r"\b(?:version \d+(?:\.\d+)+|v\d+\.\d+(?:\.\d+)?|release notes|changelog|software update|"
        r"new release)\b",
        "atualizacao_menor",
        "anúncio de versão ou atualização de software",
    ),
    (
        r"\b(?:study protocol|trial protocol|protocol for a)\b",
        "sem_novidade",
        "protocolo de estudo, ainda sem resultados",
    ),
    (
        r"\b(?:stock (?:price|market)|share price|quarterly earnings|market outlook|ipo|"
        r"press release|product launch)\b",
        "noticia_empresarial",
        "notícia empresarial ou de mercado",
    ),
    (
        r"\b(?:call for papers|conference report|workshop summary|meeting abstracts?|"
        r"proceedings of the)\b",
        "sem_novidade",
        "anúncio ou relatório de evento, não uma pesquisa",
    ),
)

_EVIDENCE_LEVELS: tuple[tuple[str, str], ...] = (
    ("revisao_ou_meta_analise", r"meta-analys|systematic review"),
    (
        "ensaio_clinico",
        r"clinical trial|randomi[sz]ed controlled|placebo-controlled|"
        r"phase (?:i|ii|iii|1|2|3) trial",
    ),
    (
        "estudo_em_animais",
        r"\bmice\b|\bmouse\b|\brats?\b|murine|zebrafish|in vivo|animal model|primates?\b",
    ),
    ("experimento_laboratorial", r"in vitro|cell lines?|organoid|cultured"),
    (
        "observacao_astronomica",
        r"telescope|james webb|jwst|we observed|observations of|spectroscop|light curve",
    ),
    (
        "estudo_observacional",
        r"cohort|cross-sectional|observational|registry|case-control|survey data|panel data",
    ),
    ("demonstracao_de_conceito", r"proof[- ]of[- ]concept|prototype|we demonstrate"),
    (
        "estudo_computacional",
        r"simulation|deep learning|machine learning|algorithm|benchmark|neural network|model",
    ),
    ("teoria_ou_hipotese", r"theorem|we prove|hypothes|theoretical"),
    ("estudo_qualitativo_ou_teorico", r"interview|qualitative|ethnograph|philosoph|we argue"),
)

EVIDENCE_LEVEL_LABELS = {
    "ensaio_clinico": "ensaio clínico",
    "estudo_observacional": "estudo observacional",
    "experimento_laboratorial": "experimento de laboratório",
    "estudo_em_animais": "estudo em animais",
    "demonstracao_de_conceito": "demonstração de conceito",
    "estudo_computacional": "estudo computacional",
    "observacao_astronomica": "observação astronômica",
    "revisao_ou_meta_analise": "revisão ou meta-análise",
    "teoria_ou_hipotese": "teoria ou hipótese",
    "estudo_qualitativo_ou_teorico": "estudo qualitativo ou teórico",
    "outro": "outro",
}


_NEGATED = re.compile(r"\b(?:not|no|yet|future|needed|will be)\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def infer_evidence_level(article: Article) -> str:
    """Nível de evidência pelo que o estudo fez. Frases negadas ou sobre o futuro ("ensaios
    em humanos ainda não foram feitos") não contam."""
    text = " ".join(s for s in _SENTENCE_END.split(_text(article)) if not _NEGATED.search(s))
    for level, pattern in _EVIDENCE_LEVELS:
        if re.search(pattern, text):
            return level
    return "outro"


def _text(article: Article) -> str:
    return strip_accents(f"{article.title} {article.abstract or ''}").casefold()


# --- Resultado ---------------------------------------------------------------------------


def compute_editorial_score(scores: dict[str, int]) -> float:
    """Nota final ponderada (0-100). Cada critério deve estar entre 0 e 100."""
    for name in WEIGHTS:
        value = scores[name]
        if not 0 <= value <= 100:
            raise ValueError(f"{name} fora do intervalo 0-100: {value}")
    return round(sum(scores[name] * weight for name, weight in WEIGHTS.items()), 2)


def decide(score: float, flags: list[str], categories: list[str]) -> tuple[str, list[str]]:
    """Decisão editorial e seus motivos, a partir da nota e das regras de rejeição."""
    reasons: list[str] = []
    if flags:
        reasons += [f"Rejeitado: {REJECTION_REASONS.get(f, f)}." for f in dict.fromkeys(flags)]
        return REJECT, reasons
    only_other = bool(categories) and set(categories) <= {EXCEPTIONAL_ONLY_CATEGORY}
    if only_other and score < PRIORITY_SCORE:
        reasons.append(
            f"Rejeitado: área sem editoria própria só entra com descoberta excepcional "
            f"(nota {score:.0f} < {PRIORITY_SCORE:.0f})."
        )
        return REJECT, reasons
    if score >= PRIORITY_SCORE:
        decision = PRIORITY
    elif score >= PUBLISH_SCORE:
        decision = PUBLISH
    elif score >= CONSIDER_SCORE:
        decision = CONSIDER
    else:
        reasons.append(
            f"Rejeitado: nota {score:.0f} abaixo do corte editorial ({CONSIDER_SCORE:.0f})."
        )
        return REJECT, reasons
    reasons.append(f"Nota {score:.0f}: {DECISION_LABELS[decision]}.")
    return decision, reasons


@dataclass
class CurationAssessment:
    scores: dict[str, int]
    justification: dict[str, str]
    method_version: str
    evidence_level: str
    flags: list[str] = field(default_factory=list)
    central_discovery: str | None = None
    editorias: list[str] = field(default_factory=list)
    interdisciplinary_links: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    decision: str = REJECT
    reasons: list[str] = field(default_factory=list)

    @property
    def final_score(self) -> float:
        return compute_editorial_score(self.scores)

    def finalize(self) -> CurationAssessment:
        decision, reasons = decide(self.final_score, self.flags, self.categories)
        self.decision = decision
        self.reasons = reasons + [r for r in self.reasons if r not in reasons]
        return self

    def explain(self) -> str:
        parts = [f"{DECISION_LABELS[self.decision].upper()} ({self.final_score:.1f})"]
        parts += self.reasons
        for name, label in CRITERIA_LABELS.items():
            parts.append(f"{label}: {self.scores[name]} — {self.justification.get(name, '')}")
        return "\n".join(parts)

    def to_record(self, article: Article) -> RelevanceAssessment:
        justification = dict(self.justification)
        if self.interdisciplinary_links:
            justification["interdisciplinary_links"] = "; ".join(self.interdisciplinary_links)
        if self.editorias:
            justification["editorias"] = ", ".join(self.editorias)
        categories = len(set(self.categories) - {INTERDISCIPLINARY_CATEGORY})
        return RelevanceAssessment(
            article=article,
            scientific_relevance=self.scores["scientific_relevance"],
            originality=self.scores["novelty"],
            potential_impact=self.scores["impact"],
            interdisciplinarity={0: 15, 1: 30, 2: 65, 3: 80}.get(categories, 90),
            # Coluna da primeira versão; passa a espelhar o potencial de curiosidade.
            ufabc_interest=self.scores["curiosity"],
            curiosity=self.scores["curiosity"],
            evidence_quality=self.scores["evidence_quality"],
            final_score=self.final_score,
            justification=justification,
            method_version=self.method_version,
            decision=self.decision,
            decision_reasons=self.reasons,
            rejection_flags=list(dict.fromkeys(self.flags)),
            central_discovery=self.central_discovery,
            evidence_level=self.evidence_level,
            assessed_at=utcnow(),
        )


# --- Avaliador heurístico ----------------------------------------------------------------


def deterministic_flags(
    article: Article, *, today: date, source_available: bool = True
) -> tuple[list[str], list[str]]:
    """Regras de rejeição verificáveis sem IA. Volta (códigos, explicações)."""
    title = strip_accents(article.title or "").casefold().strip()
    flags: list[str] = []
    notes: list[str] = []
    for pattern, flag, note in _TITLE_REJECTIONS:
        if re.search(pattern, title):
            flags.append(flag)
            notes.append(note)
    if article.article_type is ArticleType.OTHER and re.search(
        r"^(?:editorial|news|comment)", title
    ):
        flags.append("opiniao_como_descoberta")
        notes.append("texto não científico")
    if not source_available:
        flags.append("sem_fonte_verificavel")
        notes.append("sem DOI nem link original verificável")
    if article.publication_date and (today - article.publication_date).days > OLD_RESEARCH_DAYS:
        flags.append("pesquisa_antiga")
        notes.append(f"publicada há {(today - article.publication_date).days} dias")
    return flags, notes


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def heuristic_curation(
    article: Article,
    *,
    today: date | None = None,
    categories: list[str] | None = None,
    min_abstract_words: int = 40,
) -> CurationAssessment:
    """Avaliação determinística, usada como pré-filtro (e como decisão quando não há IA)."""
    from ufabc_science.intelligence.verification import source_url_for

    today = today or datetime.now(timezone.utc).date()
    text = _text(article)
    title = strip_accents(article.title or "").casefold()
    words = word_count(article.abstract)
    if categories is None:
        categories = [link.category.slug for link in article.categories if not link.is_uncertain]
    just: dict[str, str] = {}

    # A. Curiosidade: sinais de surpresa e temas que despertam perguntas; pesa contra o
    # estudo burocrático, incremental ou excessivamente específico.
    surprise = _find(text, _SURPRISE)
    topics = _find(text, _FASCINATING_TOPICS)
    dull = _find(text, _DULL)
    title_words = len(title.split())
    cur = 35 + min(36, 9 * len(surprise)) + min(21, 7 * len(topics)) - min(40, 10 * len(dull))
    notes = []
    if surprise:
        notes.append("sinais de surpresa (" + ", ".join(surprise[:3]) + ")")
    if topics:
        notes.append("tema que desperta curiosidade (" + ", ".join(topics[:3]) + ")")
    if dull:
        notes.append("sinais de estudo incremental ou burocrático (" + ", ".join(dull[:3]) + ")")
    if title_words > 20:
        cur -= 5
        notes.append(f"título técnico e longo ({title_words} palavras)")
    just["curiosity"] = "; ".join(notes) or "sem sinais claros de curiosidade"

    # B. Relevância científica: pesquisa real e descrita, em fonte confiável.
    tier, tier_note = source_tier(article)
    sci = 30
    notes = []
    if words > MAX_TYPICAL_ABSTRACT_WORDS:
        sci += 5
        notes.append(
            f"texto atípico para um abstract ({words} palavras): possível texto completo ou "
            "registro não padronizado, conferir"
        )
    elif words >= 150:
        sci += 20
        notes.append("abstract detalhado")
    elif words >= 60:
        sci += 10
        notes.append("abstract moderado")
    else:
        notes.append("pouca informação no abstract")
    methods = _find(text, _METHOD)
    if methods:
        sci += min(25, 8 * len(methods))
        notes.append("método e resultados descritos (" + ", ".join(methods[:3]) + ")")
    sci += {"A": 15, "B": 5, "C": 0, "U": 0, "D": -20}[tier]
    notes.append(tier_note)
    just["scientific_relevance"] = "; ".join(notes)

    # C. Novidade.
    novelty = _find(text, _NOVELTY)
    nov = 35 + min(40, 10 * len(novelty))
    notes = ["sinais de novidade (" + ", ".join(novelty[:3]) + ")"] if novelty else []
    if not novelty:
        notes.append("sem sinais explícitos de novidade")
    if article.publication_date:
        age = (today - article.publication_date).days
        if age <= 30:
            nov += 10
            notes.append(f"publicação recente ({age} dias)")
        elif age > 180:
            nov -= 15
            notes.append(f"publicação de {age} dias atrás")
    just["novelty"] = "; ".join(notes)

    # D. Impacto potencial (não comprovado).
    impact = _find(text, _IMPACT)
    imp = 30 + min(45, 9 * len(impact))
    just["impact"] = (
        "consequências possíveis (" + ", ".join(impact[:4]) + ")"
        if impact
        else "consequências não descritas"
    ) + " — potencial, não impacto comprovado"

    # E. Qualidade das evidências: maturidade científica e fonte.
    level = infer_evidence_level(article)
    ev = {"A": 85, "B": 65, "C": 40, "U": 50, "D": 15}[tier]
    notes = [tier_note, f"nível de evidência: {EVIDENCE_LEVEL_LABELS[level]}"]
    ev += {
        "ensaio_clinico": 10,
        "revisao_ou_meta_analise": 10,
        "observacao_astronomica": 5,
        "estudo_em_animais": -10,
        "experimento_laboratorial": -5,
        "teoria_ou_hipotese": -10,
        "demonstracao_de_conceito": -5,
    }.get(level, 0)
    preliminary = _find(text, _PRELIMINARY)
    if preliminary:
        ev -= 10
        notes.append("estudo preliminar (" + ", ".join(preliminary) + ")")
    just["evidence_quality"] = "; ".join(notes)

    flags, flag_notes = deterministic_flags(
        article, today=today, source_available=source_url_for(article) is not None
    )
    if words < min_abstract_words:
        flags.append("informacao_insuficiente")
        flag_notes.append(f"abstract com {words} palavra(s) (mínimo {min_abstract_words})")
    assessment = CurationAssessment(
        scores={
            "curiosity": _clamp(cur),
            "scientific_relevance": _clamp(sci),
            "novelty": _clamp(nov),
            "impact": _clamp(imp),
            "evidence_quality": _clamp(ev),
        },
        justification=just,
        method_version=HEURISTIC_VERSION,
        evidence_level=level,
        flags=flags,
        categories=list(categories),
        reasons=[f"Regra: {n}." for n in flag_notes],
    )
    return assessment.finalize()


# --- Avaliador por IA --------------------------------------------------------------------


def evidence_cap(article: Article) -> tuple[int, str] | None:
    """Teto da nota de evidências imposto pelos metadados (o modelo não pode ultrapassá-lo)."""
    tier, note = source_tier(article)
    if tier == "D":
        return 30, note
    if tier == "C":
        return 60, "preprint: evidência ainda sem revisão por pares"
    if tier == "U":
        return 75, note
    return None


def curation_payload(article: Article, heuristic: CurationAssessment) -> dict[str, Any]:
    tier, tier_note = source_tier(article)
    return {
        "titulo": article.title,
        "abstract": article.abstract,
        "palavras_chave": list(article.keywords or [])[:25],
        "periodico_ou_servidor": article.journal or article.publisher,
        "data_publicacao": article.publication_date.isoformat()
        if article.publication_date
        else None,
        "tipo_publicacao": article.article_type.value,
        "revisao_por_pares": article.peer_review_status.value,
        "confiabilidade_da_fonte": f"{tier}: {tier_note}",
        "editorias_por_regras": heuristic.categories,
        "nivel_de_evidencia_estimado": heuristic.evidence_level,
    }


def ai_curation(
    provider: AIProvider,
    article: Article,
    heuristic: CurationAssessment,
    allowed_categories: dict[str, str],
    *,
    max_attempts: int = 2,
) -> CurationAssessment:
    """Descoberta central + avaliação pela IA, com as travas determinísticas aplicadas."""
    from ufabc_science.intelligence.prompts import CURATION_PROMPT, untrusted_block
    from ufabc_science.intelligence.schemas import AICurationOutput

    prompt = CURATION_PROMPT.render(
        editorias="\n".join(f"- {slug}: {desc}" for slug, desc in allowed_categories.items()),
        dados=untrusted_block(curation_payload(article, heuristic)),
    )
    schema = AICurationOutput.model_json_schema()
    error = ""
    output: AICurationOutput | None = None
    for _ in range(max_attempts):
        attempt = prompt
        if error:
            attempt += f"\n\nA resposta anterior foi rejeitada pela validação: {error[:600]}"
        response = provider.generate_structured(attempt, schema, system=CURATION_PROMPT.system)
        try:
            output = AICurationOutput.model_validate(response.data)
            break
        except ValidationError as exc:
            error = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:8]
            )
    if output is None:
        raise AIError(f"Curadoria: resposta inválida da IA ({error})")

    scores = {name: getattr(output.scores, name).score for name in WEIGHTS}
    just = {name: getattr(output.scores, name).justification for name in WEIGHTS}
    reasons: list[str] = [f"IA: {output.decision_justification}"]
    cap = evidence_cap(article)
    if cap and scores["evidence_quality"] > cap[0]:
        reasons.append(
            f"Evidências limitadas a {cap[0]} pelos metadados ({cap[1]}); a IA deu "
            f"{scores['evidence_quality']}."
        )
        scores["evidence_quality"] = cap[0]
    editorias = [s for s in dict.fromkeys(output.editorias) if s in allowed_categories]
    links = [link for link in output.interdisciplinary_links if link.strip()]
    categories = list(dict.fromkeys([*heuristic.categories, *editorias]))
    if len(set(categories) - {INTERDISCIPLINARY_CATEGORY, EXCEPTIONAL_ONLY_CATEGORY}) >= 2 and (
        links or INTERDISCIPLINARY_CATEGORY in editorias
    ):
        categories.append(INTERDISCIPLINARY_CATEGORY)
    assessment = CurationAssessment(
        scores=scores,
        justification=just,
        method_version=f"{AI_METHOD_PREFIX}-{CURATION_PROMPT.version}",
        evidence_level=output.evidence_level,
        flags=[*heuristic.flags, *output.rejection_flags],
        central_discovery=output.central_discovery,
        editorias=editorias,
        interdisciplinary_links=links,
        categories=list(dict.fromkeys(categories)),
        reasons=[r for r in heuristic.reasons if r.startswith("Regra")] + reasons,
    )
    return assessment.finalize()


# --- Persistência e consulta -------------------------------------------------------------


def is_ai_assessment(record: RelevanceAssessment | None) -> bool:
    return bool(record and (record.method_version or "").startswith(AI_METHOD_PREFIX))


def effective_assessment(article: Article) -> RelevanceAssessment | None:
    """Avaliação que vale para a seleção: a curadoria por IA mais recente, se houver;
    senão, a avaliação mais recente."""
    records = article.relevance_assessments or []
    for record in reversed(records):
        if is_ai_assessment(record):
            return record
    return records[-1] if records else None


def apply_categories(session: Session, article: Article, assessment: CurationAssessment) -> int:
    """Grava as editorias indicadas pela curadoria que as regras não encontraram.

    Não remove nem rebaixa categorias existentes. Volta quantas foram adicionadas.
    """
    current = {link.category.slug for link in article.categories}
    wanted = [slug for slug in assessment.categories if slug not in current]
    if not wanted:
        return 0
    categories = {
        c.slug: c
        for c in session.scalars(select(Category).where(Category.slug.in_(wanted), Category.active))
    }
    added = 0
    for slug in wanted:
        if slug not in categories:
            continue
        interdisciplinary = slug == INTERDISCIPLINARY_CATEGORY
        session.add(
            ArticleCategory(
                article_id=article.id,
                category_id=categories[slug].id,
                confidence=0.9 if interdisciplinary else 0.7,
                classification_method=ClassificationMethod.AI_ASSISTED,
                justification=(
                    "Curadoria: conecta "
                    + ("; ".join(assessment.interdisciplinary_links) or "várias áreas")
                    if interdisciplinary
                    else f"Curadoria ({assessment.method_version}): editoria indicada pela IA."
                ),
                is_uncertain=False,
                classified_at=utcnow(),
            )
        )
        added += 1
    session.flush()
    session.expire(article, ["categories"])
    return added


@dataclass
class CurationSummary:
    assessed: int = 0
    decisions: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    explanations: dict[int, str] = field(default_factory=dict)

    def count(self, decision: str) -> None:
        self.decisions[decision] = self.decisions.get(decision, 0) + 1


def shortlist_for_ai(
    session: Session, *, limit: int, max_age_days: int, today: date | None = None
) -> list[Article]:
    """Candidatos à curadoria por IA: sem rejeição determinística, ainda sem avaliação por IA,
    ordenados pela nota heurística."""
    from ufabc_science.domain.enums import EditorialStatus

    today = today or datetime.now(timezone.utc).date()
    candidates: list[tuple[float, int, Article]] = []
    for article in session.scalars(select(Article).order_by(Article.id)):
        record = effective_assessment(article)
        if record is None or is_ai_assessment(record):
            continue
        if record.rejection_flags:
            continue
        if article.publication_date and (today - article.publication_date).days > max_age_days:
            continue
        review = article.editorial_reviews[-1] if article.editorial_reviews else None
        if review is not None and review.status in (
            EditorialStatus.APPROVED,
            EditorialStatus.REJECTED,
        ):
            continue
        published = article.publication_date.toordinal() if article.publication_date else 0
        candidates.append((record.final_score, published, article))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return [article for _, _, article in candidates[:limit]]


def curate_articles(
    session: Session,
    provider: AIProvider,
    *,
    limit: int,
    max_age_days: int = 60,
    min_abstract_words: int = 40,
    article_ids: list[int] | None = None,
    today: date | None = None,
) -> CurationSummary:
    """Curadoria por IA da lista curta. Cada avaliação é um novo registro (histórico)."""
    summary = CurationSummary()
    today = today or datetime.now(timezone.utc).date()
    allowed = {
        c.slug: c.description or c.name
        for c in session.scalars(select(Category).where(Category.active).order_by(Category.id))
    }
    if article_ids:
        articles = list(session.scalars(select(Article).where(Article.id.in_(article_ids))))
    else:
        articles = shortlist_for_ai(session, limit=limit, max_age_days=max_age_days, today=today)
    for article in articles:
        heuristic = heuristic_curation(article, today=today, min_abstract_words=min_abstract_words)
        try:
            assessment = ai_curation(provider, article, heuristic, allowed)
        except AIError as exc:
            summary.errors.append(f"artigo {article.id}: {exc}")
            logger.error("Curadoria do artigo %s falhou: %s", article.id, exc)
            continue
        session.add(assessment.to_record(article))
        if assessment.decision != REJECT:
            apply_categories(session, article, assessment)
        session.flush()
        summary.assessed += 1
        summary.count(assessment.decision)
        summary.explanations[article.id] = assessment.explain()
        logger.info(
            "Curadoria do artigo %s: %s (%.1f)", article.id, assessment.decision,
            assessment.final_score,
        )  # fmt: skip
    return summary


def explain_record(record: RelevanceAssessment) -> str:
    """Explicação legível de uma decisão gravada."""
    decision = record.decision or "?"
    lines = [
        f"{DECISION_LABELS.get(decision, decision).upper()} ({record.final_score:.1f}) "
        f"[{record.method_version}]"
    ]
    if record.central_discovery:
        lines.append(f"Descoberta central: {record.central_discovery}")
    if record.evidence_level:
        lines.append(
            "Nível de evidência: "
            + EVIDENCE_LEVEL_LABELS.get(record.evidence_level, record.evidence_level)
        )
    lines += list(record.decision_reasons or [])
    columns = {
        "curiosity": record.curiosity,
        "scientific_relevance": record.scientific_relevance,
        "novelty": record.originality,
        "impact": record.potential_impact,
        "evidence_quality": record.evidence_quality,
    }
    for name, label in CRITERIA_LABELS.items():
        value = columns[name]
        note = (record.justification or {}).get(name, "")
        lines.append(f"  {label}: {value if value is not None else '-'} — {note}")
    links = (record.justification or {}).get("interdisciplinary_links")
    if links:
        lines.append(f"Conexões entre áreas: {links}")
    return "\n".join(lines)
