"""Trava de execução exclusiva do pipeline (arquivo criado atomicamente).

Impede duas execuções simultâneas sobre o mesmo banco no mesmo diretório de
dados. No GitHub Actions, ``concurrency`` no workflow complementa esta proteção.
Uma trava mais antiga que o limite configurado é considerada abandonada
(processo interrompido) e removida com aviso.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class ConcurrentRunError(RuntimeError):
    """Outra execução do pipeline está em andamento."""


class PipelineLock:
    def __init__(self, path: Path, *, run_id: str, stale_after: timedelta) -> None:
        self.path = path
        self.run_id = run_id
        self.stale_after = stale_after
        self.acquired = False

    def _read(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _is_stale(self) -> bool:
        info = self._read()
        try:
            started = datetime.fromisoformat(info["started_at"])
        except (KeyError, ValueError):
            started = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - started > self.stale_after

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "run_id": self.run_id,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._is_stale():
                    logger.warning(
                        "Trava abandonada encontrada (%s); removendo.", self._read() or self.path
                    )
                    self.path.unlink(missing_ok=True)
                    continue
                info = self._read()
                raise ConcurrentRunError(
                    "Outra execução do pipeline está em andamento "
                    f"(run_id={info.get('run_id', '?')}, desde {info.get('started_at', '?')}). "
                    f"Se tiver certeza de que ela não existe mais, remova {self.path}."
                ) from None
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            self.acquired = True
            return
        raise ConcurrentRunError(f"Não foi possível obter a trava {self.path}.")

    def release(self) -> None:
        if self.acquired and self._read().get("run_id") == self.run_id:
            self.path.unlink(missing_ok=True)
        self.acquired = False

    def __enter__(self) -> PipelineLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
