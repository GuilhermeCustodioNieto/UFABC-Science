"""Cliente mínimo da API v4 do Kit (https://developers.kit.com/).

Usa apenas ``POST /v4/broadcasts``: cria a newsletter com o nosso HTML como corpo e a agenda
para daqui a poucos minutos. O template padrão (Classic) do Kit envolve o corpo e adiciona o
link de descadastro e o endereço exigidos por lei; inscrição, confirmação e descadastro
ficam todos no Kit.

``subscriber_filter`` vazio significa "todos os assinantes" (documentação da API). Para testes,
o filtro usa uma tag (``KIT_TEST_TAG_ID``).

A chave nunca é registrada em logs nem incluída em mensagens de erro.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.kit.com"
SEND_DELAY = timedelta(minutes=2)


class NewsletterError(RuntimeError):
    """Falha ao enviar a newsletter."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class KitClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"X-Kit-Api-Key": api_key, "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TransportError as exc:
            raise NewsletterError(f"Kit indisponível: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                errors = response.json().get("errors")
                if errors:
                    detail = ": " + "; ".join(str(e) for e in errors)[:300]
            except (ValueError, AttributeError):
                pass
            raise NewsletterError(f"Kit respondeu HTTP {response.status_code}{detail}")
        try:
            return dict(response.json())
        except ValueError as exc:
            raise NewsletterError("Resposta do Kit não é JSON.") from exc

    def schedule_broadcast(
        self,
        *,
        subject: str,
        preview_text: str,
        description: str,
        html: str,
        public: bool,
        tag_id: int | None = None,
        email_address: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Cria a newsletter e a agenda para envio em ``SEND_DELAY``. Retorna o id."""
        moment = now or datetime.now(timezone.utc)
        subscriber_filter: list[dict[str, Any]] = []
        if tag_id is not None:
            subscriber_filter = [
                {"all": [{"type": "tag", "ids": [tag_id]}], "any": None, "none": None}
            ]
        payload: dict[str, Any] = {
            "subject": subject,
            "preview_text": preview_text,
            "description": description,
            "content": html,
            "public": public,
            "published_at": _iso(moment),
            "send_at": _iso(moment + SEND_DELAY),
            "subscriber_filter": subscriber_filter,
        }
        if email_address:
            payload["email_address"] = email_address
        broadcast = self._post("/v4/broadcasts", payload).get("broadcast") or {}
        broadcast_id = broadcast.get("id")
        if not isinstance(broadcast_id, int):
            raise NewsletterError("Kit não devolveu o id da newsletter criada.")
        if broadcast.get("send_at") is None or broadcast.get("status") == "draft":
            raise NewsletterError(
                f"Kit salvou a newsletter {broadcast_id} como rascunho em vez de agendá-la; "
                "confira-a no painel do Kit."
            )
        logger.info("Newsletter %s agendada no Kit para %s.", broadcast_id, broadcast["send_at"])
        return broadcast_id
