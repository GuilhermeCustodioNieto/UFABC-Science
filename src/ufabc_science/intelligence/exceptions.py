"""Exceções da camada de inteligência artificial."""

from __future__ import annotations


class AIError(RuntimeError):
    """Erro genérico da camada de IA."""


class AIProviderError(AIError):
    """Falha de comunicação ou resposta HTTP inválida do provedor."""


class AIResponseValidationError(AIError):
    """A resposta do modelo não respeitou o esquema esperado (após as tentativas)."""


class InsufficientInformationError(AIError):
    """Os dados de origem não são suficientes para produzir conteúdo sem especulação."""
