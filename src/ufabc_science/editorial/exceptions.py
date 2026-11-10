"""Exceções do fluxo editorial."""

from __future__ import annotations


class EditorialError(RuntimeError):
    """Erro de regra editorial (mensagem destinada ao editor)."""


class EditionError(EditorialError):
    """Operação inválida sobre uma edição."""


class PublicationBlockedError(EditionError):
    """A edição não atende aos requisitos de publicação."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []
