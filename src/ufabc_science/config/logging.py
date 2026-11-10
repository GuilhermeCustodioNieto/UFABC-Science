"""Configuração de logs legíveis para a CLI."""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """Configura o logger raiz para escrever em ``stderr``.

    Pode ser chamada várias vezes: os handlers anteriores são substituídos.
    """
    logging.basicConfig(
        level=level.upper(),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stderr,
        force=True,
    )
    # Alembic e SQLAlchemy são verbosos em INFO; fora do modo DEBUG mantemos apenas avisos.
    library_level = logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    for name in ("alembic", "sqlalchemy"):
        logging.getLogger(name).setLevel(library_level)
