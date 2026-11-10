"""Interface independente de provedor para modelos de IA (Etapa 3, seção 5)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AIResponse:
    """Resposta estruturada de um provedor.

    ``data`` é o objeto JSON devolvido pelo modelo (ainda não validado pelo
    domínio). ``usage`` traz dados de consumo quando o provedor os informa
    (tokens), permitindo controle de custos.
    """

    data: dict[str, Any]
    provider: str
    model: str | None
    usage: dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    """Contrato de qualquer provedor de IA.

    A lógica editorial depende apenas desta interface; trocar de provedor não
    exige alterar geração, classificação ou verificação.
    """

    name: str = "abstract"
    model: str | None = None

    @abstractmethod
    def generate_structured(
        self, prompt: str, response_schema: dict[str, Any], *, system: str | None = None
    ) -> AIResponse:
        """Envia ``prompt`` e devolve um objeto JSON compatível com ``response_schema``.

        Implementações devem aplicar timeout e tratar erros de rede lançando
        ``AIProviderError``. A validação semântica é feita por quem chama.
        """
