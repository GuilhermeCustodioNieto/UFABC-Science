"""Esquemas Pydantic de saída da IA (Etapa 3, seção 8).

``AIArticleDraft`` é o que o modelo pode produzir. Título original, referência
bibliográfica e link **não** fazem parte da resposta do modelo: são montados
pelo sistema a partir dos metadados coletados (``GeneratedArticleContent``),
eliminando a possibilidade de referências ou DOIs inventados.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SECTION_CHARS = 2500

SECTION_FIELDS = (
    "introduction",
    "context",
    "research_question",
    "methodology",
    "findings",
    "limitations",
    "ufabc_relevance",
)

SECTION_TITLES = {
    "introduction": "Introdução",
    "context": "Contexto científico",
    "research_question": "O que foi investigado?",
    "methodology": "Como a pesquisa foi realizada?",
    "findings": "Principais resultados",
    "limitations": "Limitações",
    "ufabc_relevance": "Por que isso importa?",
}

DEFAULT_WORD_LIMITS: dict[str, tuple[int, int]] = {
    "introduction": (50, 100),
    "context": (60, 120),
    "research_question": (30, 70),
    "methodology": (50, 100),
    "findings": (80, 150),
    "limitations": (30, 80),
    "ufabc_relevance": (40, 80),
    "total": (350, 650),
}


def _strip_text(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()) if "\n" not in value else value.strip()
    return value


class AIArticleDraft(BaseModel):
    """Resposta JSON esperada do modelo para a geração de artigo."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    headline: str = Field(min_length=5, max_length=200)
    introduction: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    context: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    research_question: str = Field(min_length=10, max_length=MAX_SECTION_CHARS)
    methodology: str = Field(min_length=10, max_length=MAX_SECTION_CHARS)
    findings: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
    limitations: str = Field(min_length=10, max_length=MAX_SECTION_CHARS)
    ufabc_relevance: str = Field(min_length=20, max_length=MAX_SECTION_CHARS)
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
