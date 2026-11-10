"""Ponto de entrada da aplicação."""

from __future__ import annotations

from collections.abc import Sequence

from ufabc_science.cli import run_cli


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a CLI e devolve o código de saída do processo."""
    return run_cli(argv)
