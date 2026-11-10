"""Interface comum dos coletores e utilitários HTTP compartilhados.

Requisitos atendidos (SPECIFICATION.md, seção 6.5): timeout configurável,
tratamento de erros HTTP, retry com backoff para falhas transitórias, intervalo
mínimo entre requisições (sem chamadas simultâneas), identificação da fonte,
logs e persistência das respostas brutas.
"""

from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from ufabc_science import __version__
from ufabc_science.domain.enums import SourceType
from ufabc_science.domain.schemas import NormalizedArticle

logger = logging.getLogger(__name__)

TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _sleep(seconds: float) -> None:
    # Resolvido em tempo de chamada para permitir substituicao em testes.
    time.sleep(seconds)


class CollectorError(RuntimeError):
    """Falha definitiva ao consultar uma fonte."""


@dataclass
class CollectionResult:
    """Resultado de uma coleta em uma fonte."""

    source: str
    articles: list[NormalizedArticle] = field(default_factory=list)
    requests: int = 0
    raw_files: list[str] = field(default_factory=list)
    invalid_records: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class RawStore:
    """Grava respostas brutas em ``<raiz>/<fonte>/<AAAA-MM-DD>/``.

    O nome do arquivo deriva do SHA-256 do conteúdo: gravar a mesma resposta duas
    vezes não cria arquivos duplicados (idempotência).
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, source: str, label: str, content: bytes, extension: str) -> str:
        digest = hashlib.sha256(content).hexdigest()[:16]
        day = datetime.now(timezone.utc).date().isoformat()
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)[:60]
        directory = self.root / source / day
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_label}-{digest}.{extension}"
        if not path.exists():
            path.write_bytes(content)
        return path.as_posix()


class RateLimitedClient:
    """Cliente HTTP síncrono com intervalo mínimo entre chamadas e retry com backoff.

    Requisições são sempre sequenciais; nunca há chamadas simultâneas a uma fonte.
    """

    def __init__(
        self,
        *,
        source: str,
        timeout: float,
        max_retries: int,
        backoff_seconds: float,
        min_interval: float,
        contact_email: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        user_agent = f"UFABC-Science/{__version__} (curadoria cientifica sem fins lucrativos"
        user_agent += f"; mailto:{contact_email})" if contact_email else ")"
        self.source = source
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_interval = min_interval
        self.requests = 0
        self._sleep = sleep or _sleep
        self._last_request: float | None = None
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RateLimitedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _wait_interval(self) -> None:
        if self._last_request is None or self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            self._sleep(self.min_interval - elapsed)

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and "Retry-After" in response.headers:
            value = response.headers["Retry-After"]
            try:
                return min(float(value), 120.0)
            except ValueError:
                try:
                    delta = parsedate_to_datetime(value) - datetime.now(timezone.utc)
                    return max(0.0, min(delta.total_seconds(), 120.0))
                except (TypeError, ValueError):
                    pass
        return self.backoff_seconds * (2**attempt)

    def get(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        """GET com retry para erros transitórios. Lança ``CollectorError`` se falhar."""
        last_error = "erro desconhecido"
        for attempt in range(self.max_retries + 1):
            self._wait_interval()
            response: httpx.Response | None = None
            try:
                self.requests += 1
                response = self._client.get(url, params=params)
                self._last_request = time.monotonic()
            except httpx.TransportError as exc:  # timeout, conexão recusada, DNS...
                self._last_request = time.monotonic()
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in TRANSIENT_STATUS:
                    raise CollectorError(f"{self.source}: {last_error} em {response.url}")
            if attempt < self.max_retries:
                delay = self._retry_delay(attempt, response)
                logger.warning(
                    "%s: falha transitória (%s); nova tentativa %d/%d em %.1fs",
                    self.source,
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                self._sleep(delay)
        raise CollectorError(
            f"{self.source}: {last_error} após {self.max_retries + 1} tentativa(s)"
        )


@dataclass(frozen=True)
class CollectorConfig:
    """Parâmetros comuns a todos os coletores (derivados de ``Settings``)."""

    max_articles: int = 100
    timeout: float = 30.0
    max_retries: int = 3
    backoff_seconds: float = 1.0
    contact_email: str | None = None
    api_key: str | None = None
    raw_store: RawStore | None = None
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] | None = None


class BaseCollector(ABC):
    """Contrato de todos os coletores: ``collect(query, start_date, end_date)``.

    Implementações devem devolver ``NormalizedArticle`` (mesma estrutura para
    qualquer fonte), registrar respostas brutas e nunca lançar exceção por um
    registro inválido isolado — ele é contado e ignorado.
    """

    name: str
    base_url: str
    source_type: SourceType = SourceType.API
    min_interval: float = 1.0
    default_queries: tuple[str, ...] = ()

    def __init__(self, config: CollectorConfig | None = None) -> None:
        self.config = config or CollectorConfig()

    def _client(self) -> RateLimitedClient:
        return RateLimitedClient(
            source=self.name,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
            backoff_seconds=self.config.backoff_seconds,
            min_interval=self.min_interval,
            contact_email=self.config.contact_email,
            transport=self.config.transport,
            sleep=self.config.sleep,
        )

    def _save_raw(self, result: CollectionResult, label: str, content: bytes, ext: str) -> str:
        if self.config.raw_store is None:
            return ""
        path = self.config.raw_store.save(self.name, label, content, ext)
        if path not in result.raw_files:
            result.raw_files.append(path)
        return path

    def _build(self, result: CollectionResult, data: dict[str, Any]) -> NormalizedArticle | None:
        """Valida um registro normalizado; registros inválidos são contados e ignorados."""
        try:
            return NormalizedArticle(source=self.name, **data)
        except ValidationError as exc:
            result.invalid_records += 1
            logger.debug("%s: registro inválido ignorado: %s", self.name, exc)
            return None

    def collect(self, query: str | None, start_date: date, end_date: date) -> CollectionResult:
        """Coleta artigos publicados em ``[start_date, end_date]``.

        ``query=None`` usa as consultas padrão da fonte (``default_queries``).
        """
        if end_date < start_date:
            raise ValueError("end_date deve ser posterior a start_date.")
        result = CollectionResult(source=self.name)
        queries = [query] if query else list(self.default_queries)
        seen: set[str] = set()
        per_query = max(1, self.config.max_articles // max(1, len(queries)))
        with self._client() as client:
            for item in queries:
                remaining = self.config.max_articles - len(result.articles)
                if remaining <= 0:
                    break
                try:
                    articles = self._collect_query(
                        client, result, item, start_date, end_date, min(per_query, remaining)
                    )
                except CollectorError as exc:
                    result.errors.append(str(exc))
                    logger.error("%s: consulta %r falhou: %s", self.name, item, exc)
                    continue
                for article in articles:
                    if article.external_id not in seen:
                        seen.add(article.external_id)
                        result.articles.append(article)
            result.requests = client.requests
        logger.info(
            "%s: %d artigo(s) coletado(s) em %d requisição(ões); %d inválido(s); %d erro(s)",
            self.name,
            len(result.articles),
            result.requests,
            result.invalid_records,
            len(result.errors),
        )
        return result

    @abstractmethod
    def _collect_query(
        self,
        client: RateLimitedClient,
        result: CollectionResult,
        query: str,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[NormalizedArticle]:
        """Executa uma consulta paginada e devolve artigos normalizados."""
