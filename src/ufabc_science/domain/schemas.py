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
        name="Computação e IA",
        slug="computacao-e-ia",
        description=(
            "Novos modelos e arquiteturas de IA, aprendizado de máquina, IA generativa, robótica "
            "e sistemas autônomos, computação quântica, novos algoritmos, interfaces "
            "cérebro-computador, interação humano-máquina, hardware e semicondutores. Não inclui "
            "atualizações de software, lançamentos comerciais ou melhorias incrementais."
        ),
    ),
    CategoryDefinition(
        name="Engenharia Aeroespacial",
        slug="engenharia-aeroespacial",
        description=(
            "Propulsão, foguetes e motores experimentais, exploração espacial, materiais "
            "aeroespaciais, aeronaves experimentais, engenharia de voo, pouso e lançamento, "
            "satélites e tecnologias para explorar outros planetas."
        ),
    ),
    CategoryDefinition(
        name="Astronomia e Universo",
        slug="astronomia-e-universo",
        description=(
            "Exoplanetas, buracos negros, galáxias, matéria e energia escuras, origem e evolução "
            "do universo, observações de telescópios (como o James Webb), astrobiologia e "
            "formação de estrelas e planetas."
        ),
    ),
    CategoryDefinition(
        name="Medicina e Biotecnologia",
        slug="medicina-e-biotecnologia",
        description=(
            "Novos medicamentos e tratamentos, terapias genéticas, vacinas, oncologia, engenharia "
            "de tecidos, medicina regenerativa, cirurgias, diagnóstico, descobertas sobre doenças "
            "e biotecnologia aplicada à saúde. Não inclui conselhos de saúde sem descoberta."
        ),
    ),
    CategoryDefinition(
        name="Neurociência e Psicologia",
        slug="neurociencia-e-psicologia",
        description=(
            "Funcionamento do cérebro, consciência, memória, sonhos, cognição, emoções, "
            "comportamento, neuroplasticidade, transtornos neurológicos e psicológicos, "
            "aprendizagem e experimentos psicológicos."
        ),
    ),
    CategoryDefinition(
        name="Filosofia, Sociologia e Arte",
        slug="filosofia-sociologia-e-arte",
        description=(
            "Pesquisas sociológicas, comportamento coletivo, filosofia da mente e da ciência, "
            "ética e tecnologia, cultura, psicologia social, história das ideias, arte e "
            "tecnologia, criatividade, percepção e estética. Exige fundamentação acadêmica, não "
            "opinião."
        ),
    ),
    CategoryDefinition(
        name="Economia",
        slug="economia",
        description=(
            "Economia comportamental, comportamento econômico, IA e economia, automação e "
            "trabalho, desigualdade, desenvolvimento, economia da inovação e novas teorias. Não "
            "inclui cotações, especulação de mercado ou notícias empresariais."
        ),
    ),
    CategoryDefinition(
        name="Intersecções Científicas",
        slug="interseccoes-cientificas",
        description=(
            "Pesquisas que conectam duas ou mais áreas: IA na descoberta de medicamentos, "
            "neurociência computacional, astrobiologia, química quântica, bioinformática, "
            "neuroeconomia, filosofia da IA, nanomedicina e outras conexões."
        ),
    ),
    CategoryDefinition(
        name="Outras Ciências",
        slug="outras-ciencias",
        description=(
            "Matemática, física, química, biologia, geologia e outras áreas, somente quando a "
            "descoberta tem potencial excepcional de interesse."
        ),
    ),
)

# Editorias da primeira versão. Continuam no banco (inativas) porque edições já publicadas
# apontam para elas; novos artigos nunca são classificados nelas.
LEGACY_CATEGORY_SLUGS: tuple[str, ...] = (
    "neurociencia",
    "computacao-e-tecnologia",
    "engenharias",
    "ciencias-biologicas",
    "ciencias-e-stem",
)

# Editoria que só recebe descobertas excepcionais (seção 2.9 da política editorial).
EXCEPTIONAL_ONLY_CATEGORY = "outras-ciencias"
INTERDISCIPLINARY_CATEGORY = "interseccoes-cientificas"


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
