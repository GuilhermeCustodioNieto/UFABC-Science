"""Implementações de ``AIProvider``.

* ``MockProvider`` — determinístico, sem rede, para desenvolvimento e testes.
  Produz rascunhos **extrativos** (reorganiza trechos do abstract) claramente
  marcados como mock; não é um gerador de texto editorial.
* ``OpenAICompatibleProvider`` — adaptador HTTP para qualquer serviço com API
  compatível com ``/v1/chat/completions`` (ex.: Ollama ou LM Studio locais, sem
  custo; ou serviços hospedados). Ver ``docs/AI_PROVIDERS.md`` para condições,
  limites e custos antes de configurar um serviço externo.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from ufabc_science.config.settings import Settings
from ufabc_science.intelligence.base import AIProvider, AIResponse
from ufabc_science.intelligence.exceptions import AIProviderError
from ufabc_science.intelligence.prompts import UNTRUSTED_TAG

logger = logging.getLogger(__name__)

_BLOCK = re.compile(rf"<{UNTRUSTED_TAG}>\n(?P<body>.*)\n</{UNTRUSTED_TAG}>", re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_METHOD = re.compile(
    r"\b(we (used|developed|analy[sz]ed|measured|trained|conducted|performed|propose|present)|"
    r"using|method|approach|dataset|participants|cohort|sample|simulat|model)",
    re.IGNORECASE,
)
_RESULT = re.compile(
    r"\b(results?|we (found|show|observed|demonstrate)|shows?|revealed?|indicates?|"
    r"suggests?|outperform|improv|increase|decrease|reduc)",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\b(limitation|however|although|small sample|preliminary|future work)", re.I)


def extract_payload(prompt: str) -> dict[str, Any]:
    """Recupera os dados do bloco não confiável de um prompt (uso do mock)."""
    match = _BLOCK.search(prompt)
    if not match:
        return {}
    try:
        return json.loads(match.group("body"))
    except json.JSONDecodeError:
        return {}


def _sentences(text: str | None) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


class MockProvider(AIProvider):
    """Provedor determinístico para desenvolvimento. Nunca acessa a rede."""

    name = "mock"
    model = "mock-extractive-v1"

    def generate_structured(
        self, prompt: str, response_schema: dict[str, Any], *, system: str | None = None
    ) -> AIResponse:
        title = response_schema.get("title")
        payload = extract_payload(prompt)
        if title == "AIClassificationOutput":
            data: dict[str, Any] = {"categories": []}
        elif title == "AIArticleDraft":
            data = self._draft(payload)
        else:
            raise AIProviderError(f"MockProvider não suporta o esquema {title!r}")
        return AIResponse(
            data=data, provider=self.name, model=self.model, usage={"prompt_chars": len(prompt)}
        )

    @staticmethod
    def _draft(payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("titulo_original") or "pesquisa sem título"
        sentences = _sentences(payload.get("abstract"))
        methods = [s for s in sentences if _METHOD.search(s)][:2]
        results = [s for s in sentences if _RESULT.search(s) and s not in methods][:3]
        limits = [s for s in sentences if _LIMIT.search(s)][:2]
        categories = ", ".join(payload.get("categorias") or []) or "áreas ainda não classificadas"
        venue = payload.get("periodico") or payload.get("editora") or "fonte não informada"
        is_preprint = payload.get("revisao_por_pares") == "preprint"
        preprint_note = (
            " Trata-se de um preprint, ainda não revisado por pares; os resultados podem mudar."
            if is_preprint
            else ""
        )

        def quote(items: list[str], fallback: str) -> str:
            if not items:
                return fallback
            return "Trechos do resumo original (traduzir e revisar): " + " ".join(
                f"“{s}”" for s in items
            )

        return {
            "headline": f"[Rascunho mock] {title}"[:200],
            "introduction": (
                "Rascunho produzido pelo provedor mock, sem modelo de linguagem, apenas para "
                f"desenvolvimento e testes. O trabalho “{title}” foi registrado em {venue}."
                + preprint_note
            ),
            "context": (
                f"O estudo foi associado às editorias: {categories}. Os termos técnicos do "
                "resumo original devem ser explicados pelo editor antes da publicação."
            ),
            "research_question": quote(
                sentences[:1], "A pergunta de pesquisa não está disponível nos dados da fonte."
            ),
            "methodology": quote(
                methods, "A metodologia não está detalhada nos dados disponíveis na fonte."
            ),
            "findings": quote(
                results or sentences[-2:],
                "Os resultados não estão descritos nos dados disponíveis na fonte.",
            ),
            "limitations": quote(
                limits,
                "As limitações não foram informadas nos dados disponíveis na fonte."
                + preprint_note,
            ),
            "ufabc_relevance": (
                f"A pesquisa dialoga com {categories}, temas presentes nos cursos "
                "interdisciplinares da UFABC. O editor deve avaliar a relevância antes de publicar."
            ),
            "uncertainty_notes": [
                "Conteúdo gerado pelo provedor mock: requer redação humana completa.",
            ],
        }


class OpenAICompatibleProvider(AIProvider):
    """Adaptador para APIs no formato ``POST {base_url}/chat/completions``."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        temperature: float | None = 0.2,
        max_tokens: int | None = 2000,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _body(self, prompt: str, schema: dict[str, Any], system: str | None) -> dict[str, Any]:
        user = (
            f"{prompt}\n\nResponda com um único objeto JSON compatível com este esquema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        messages = [{"role": "user", "content": user}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        return body

    @staticmethod
    def _parse_content(content: str) -> dict[str, Any]:
        text = content.strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"Resposta não é JSON válido: {exc}") from exc
        if not isinstance(data, dict):
            raise AIProviderError("Resposta JSON não é um objeto.")
        return data

    def generate_structured(
        self, prompt: str, response_schema: dict[str, Any], *, system: str | None = None
    ) -> AIResponse:
        body = self._body(prompt, response_schema, system)
        last_error = "erro desconhecido"
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    try:
                        payload = response.json()
                        content = payload["choices"][0]["message"]["content"]
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise AIProviderError(f"Formato de resposta inesperado: {exc}") from exc
                    return AIResponse(
                        data=self._parse_content(content or ""),
                        provider=self.name,
                        model=payload.get("model") or self.model,
                        usage=dict(payload.get("usage") or {}),
                    )
                # Nunca registrar o corpo da requisição ou cabeçalhos (contém a chave).
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in (408, 429, 500, 502, 503, 504):
                    raise AIProviderError(f"Provedor respondeu {last_error}")
            if attempt < self.max_retries:
                delay = 2.0 * (2**attempt)
                logger.warning(
                    "IA: falha transitória (%s); nova tentativa em %.0fs", last_error, delay
                )
                self._sleep(delay)
        raise AIProviderError(f"Provedor indisponível: {last_error}")


def build_provider(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> AIProvider:
    """Cria o provedor configurado. Sem configuração, usa o ``MockProvider``."""
    if settings.ai_provider == "mock":
        return MockProvider()
    assert settings.ai_base_url and settings.ai_model  # garantido por Settings
    return OpenAICompatibleProvider(
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        api_key=settings.ai_api_key.get_secret_value() if settings.ai_api_key else None,
        timeout=settings.ai_timeout,
        max_retries=settings.ai_max_retries,
        temperature=settings.ai_temperature,
        max_tokens=settings.ai_max_tokens,
        transport=transport,
    )
