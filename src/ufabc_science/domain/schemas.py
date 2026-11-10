"""Esquemas Pydantic do domínio: editorias e artigo normalizado.

Os esquemas de saída da IA ficam em ``ufabc_science.intelligence.schemas``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.processing.normalization import clean_text, is_http_url, normalize_doi


class CategoryDefinition(BaseModel):
    """Definição de uma editoria, usada para popular a tabela ``categories``."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=1)


DEFAULT_CATEGORIES: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        name="Neurociência",
        slug="neurociencia",
        description=(
            "Cérebro, cognição, comportamento, neurobiologia, neurotecnologia e saúde neural."
        ),
    ),
    CategoryDefinition(
        name="Computação e Tecnologia",
        slug="computacao-e-tecnologia",
        description=(
            "Inteligência artificial, ciência de dados, algoritmos, software, segurança, "
            "computação quântica e sistemas."
        ),
    ),
    CategoryDefinition(
        name="Engenharias",
        slug="engenharias",
        description=(
            "Engenharia de materiais, energia, mecânica, aeroespacial, biomédica, robótica, "
            "química e áreas correlatas."
        ),
    ),
    CategoryDefinition(
        name="Ciências Biológicas",
        slug="ciencias-biologicas",
        description=(
            "Genética, biologia molecular, microbiologia, evolução, ecologia, biotecnologia "
            "e pesquisas biomédicas."
        ),
    ),
    CategoryDefinition(
        name="Ciências e STEM",
        slug="ciencias-e-stem",
        description=(
            "Física, química, matemática, astronomia, ciências ambientais e pesquisas "
            "interdisciplinares."
        ),
    ),
)


# --- Etapa 2: estrutura interna única produzida por todos os coletores ---------------


class NormalizedInstitution(BaseModel):
    """Instituição associada a um artigo (sem juízo de prestígio)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=500)
    ror: str | None = None
    country: str | None = Field(default=None, max_length=8)


class NormalizedAuthor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=300)
    orcid: str | None = None
    affiliations: tuple[str, ...] = ()


class NormalizedArticle(BaseModel):
    """Artigo normalizado, independente da API de origem.

    ``source`` e ``external_id`` preservam a rastreabilidade; ``raw_data_path``
    aponta para a resposta bruta salva em ``data/raw/``.
    """

    source: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    abstract: str | None = None
    doi: str | None = None
    url: str | None = None
    publication_date: date | None = None
    journal: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    authors: list[NormalizedAuthor] = Field(default_factory=list)
    institutions: list[NormalizedInstitution] = Field(default_factory=list)
    article_type: ArticleType = ArticleType.UNKNOWN
    peer_review_status: PeerReviewStatus = PeerReviewStatus.UNKNOWN
    open_access: bool | None = None
    language: str | None = None
    keywords: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_data_path: str | None = None

    @field_validator("doi")
    @classmethod
    def _doi_must_be_normalized(cls, value: str | None) -> str | None:
        normalized = normalize_doi(value)
        if value and normalized is None:
            # DOI malformado: descartado, mas nunca "corrigido" por suposição.
            return None
        return normalized

    @field_validator("url")
    @classmethod
    def _url_must_be_http(cls, value: str | None) -> str | None:
        return value.strip() if is_http_url(value) else None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("Título vazio.")
        return cleaned

    @field_validator("keywords")
    @classmethod
    def _dedupe_keywords(cls, value: list[str]) -> list[str]:
        seen: dict[str, str] = {}
        for item in value:
            text = (item or "").strip()
            if text and text.casefold() not in seen:
                seen[text.casefold()] = text
        return list(seen.values())

    @property
    def external_key(self) -> str:
        return f"{self.source}:{self.external_id}"
