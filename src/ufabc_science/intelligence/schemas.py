"""Esquemas Pydantic de saída da IA (Etapa 3, seção 8; curadoria editorial).

``AIArticleDraft`` é o que o modelo pode produzir. Título original, referência
bibliográfica e link **não** fazem parte da resposta do modelo: são montados
pelo sistema a partir dos metadados coletados (``GeneratedArticleContent``),
eliminando a possibilidade de referências ou DOIs inventados.

Estrutura da matéria (política editorial, seção 6): título, subtítulo, "A descoberta",
"Como funciona", "Por que isso importa?", "Limitações e próximos passos" e referências.
Conteúdos gerados antes dessa estrutura (``LEGACY_SECTION_FIELDS``) continuam legíveis,
verificáveis e publicáveis.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SECTION_CHARS = 2500
MAX_HEADLINE_CHARS = 140

SECTION_FIELDS = ("discovery", "how_it_works", "why_it_matters", "limitations")

SECTION_TITLES = {
    "discovery": "A descoberta",
    "how_it_works": "Como funciona",
    "why_it_matters": "Por que isso importa?",
    "limitations": "Limitações e próximos passos",
}

SUBTITLE_TITLE = "Subtítulo"

# Estrutura da primeira versão (antes da curadoria editorial).
LEGACY_SECTION_FIELDS = (
    "introduction",
    "context",
    "research_question",
    "methodology",
    "findings",
    "limitations",
    "ufabc_relevance",
)

LEGACY_SECTION_TITLES = {
    "introduction": "Introdução",
    "context": "Contexto científico",
    "research_question": "O que foi investigado?",
    "methodology": "Como a pesquisa foi realizada?",
    "findings": "Principais resultados",
    "limitations": "Limitações",
    "ufabc_relevance": "Por que isso importa?",
}

# Campos que só existem no formato antigo: sua presença identifica um conteúdo legado.
_LEGACY_ONLY = frozenset(LEGACY_SECTION_FIELDS) - frozenset(SECTION_FIELDS)

DEFAULT_WORD_LIMITS: dict[str, tuple[int, int]] = {
    "subtitle": (10, 35),
    "discovery": (60, 140),
    "how_it_works": (80, 200),
    "why_it_matters": (50, 130),
    "limitations": (40, 110),
    "total": (300, 650),
}


def is_legacy(sections: dict[str, str]) -> bool:
    """Indica se as seções seguem a estrutura antiga (sete seções)."""
    return any((sections.get(name) or "").strip() for name in _LEGACY_ONLY) and not any(
        (sections.get(name) or "").strip() for name in ("discovery", "how_it_works")
    )


def section_layout(sections: dict[str, str]) -> tuple[tuple[str, ...], dict[str, str]]:
    """Campos e títulos esperados para estas seções (estrutura atual ou antiga)."""
    if is_legacy(sections):
        return LEGACY_SECTION_FIELDS, LEGACY_SECTION_TITLES
    return SECTION_FIELDS, SECTION_TITLES


def _strip_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()) if "\n" not in value else value.strip()
    return value


class AIArticleDraft(BaseModel):
    """Resposta JSON esperada do modelo para a redação da matéria."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    headline: str = Field(min_length=5, max_length=MAX_HEADLINE_CHARS)
    subtitle: str = Field(min_length=20, max_length=400)
    discovery: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    how_it_works: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    why_it_matters: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    limitations: str = Field(min_length=10, max_length=MAX_SECTION_CHARS)
    uncertainty_notes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return _strip_text(value)

    @field_validator("uncertainty_notes")
    @classmethod
    def _notes(cls, value: list[str]) -> list[str]:
        return [note.strip()[:500] for note in value if note and note.strip()]


class GeneratedArticleContent(AIArticleDraft):
    """Conteúdo completo: rascunho da IA + campos montados pelo sistema."""

    original_title: str = Field(min_length=1)
    reference: str = Field(min_length=10)
    source_url: str = Field(min_length=8)

    def sections(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in SECTION_FIELDS}


# --- Curadoria (descoberta + avaliação) -----------------------------------------------------

EvidenceLevel = Literal[
    "ensaio_clinico",
    "estudo_observacional",
    "experimento_laboratorial",
    "estudo_em_animais",
    "demonstracao_de_conceito",
    "estudo_computacional",
    "observacao_astronomica",
    "revisao_ou_meta_analise",
    "teoria_ou_hipotese",
    "estudo_qualitativo_ou_teorico",
    "outro",
]

RejectionFlag = Literal[
    "atualizacao_menor",
    "resultado_trivial",
    "especifico_demais",
    "sem_novidade",
    "noticia_empresarial",
    "opiniao_como_descoberta",
    "sem_fonte_verificavel",
    "pesquisa_antiga",
    "sensacionalista",
    "correlacao_como_causa",
    "hipotese_como_fato",
]


class CriterionScore(BaseModel):
    score: int = Field(ge=0, le=100)
    justification: str = Field(min_length=3, max_length=600)


class AICurationScores(BaseModel):
    curiosity: CriterionScore
    scientific_relevance: CriterionScore
    novelty: CriterionScore
    impact: CriterionScore
    evidence_quality: CriterionScore


class AICurationOutput(BaseModel):
    """Identificação da descoberta central e avaliação editorial de um candidato."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    central_discovery: str = Field(min_length=10, max_length=600)
    evidence_level: EvidenceLevel
    editorias: list[str] = Field(default_factory=list, max_length=4)
    interdisciplinary_links: list[str] = Field(default_factory=list, max_length=5)
    scores: AICurationScores
    rejection_flags: list[RejectionFlag] = Field(default_factory=list)
    decision_justification: str = Field(min_length=10, max_length=1200)


# --- Revisão editorial da matéria -----------------------------------------------------------

REVIEW_CRITERIA = (
    "clarity",
    "naturalness",
    "scientific_accuracy",
    "interest",
    "headline_quality",
    "jargon_free",
    "headline_body_coherence",
    "fidelity",
    "fact_vs_hypothesis",
)

# Critérios que, abaixo do mínimo, pedem uma versão mais simples ou mais precisa.
LANGUAGE_CRITERIA = ("clarity", "naturalness", "jargon_free")
PRECISION_CRITERIA = ("scientific_accuracy", "fidelity", "fact_vs_hypothesis")
APPEAL_CRITERIA = ("interest", "headline_quality", "headline_body_coherence")


class AIEditorialReview(BaseModel):
    """Notas de 0 a 10 por critério e instruções concretas de correção."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    clarity: int = Field(ge=0, le=10)
    naturalness: int = Field(ge=0, le=10)
    scientific_accuracy: int = Field(ge=0, le=10)
    interest: int = Field(ge=0, le=10)
    headline_quality: int = Field(ge=0, le=10)
    jargon_free: int = Field(ge=0, le=10)
    headline_body_coherence: int = Field(ge=0, le=10)
    fidelity: int = Field(ge=0, le=10)
    fact_vs_hypothesis: int = Field(ge=0, le=10)
    problems: list[str] = Field(default_factory=list, max_length=12)
    instructions: str = Field(default="", max_length=1500)

    def scores(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in REVIEW_CRITERIA}
