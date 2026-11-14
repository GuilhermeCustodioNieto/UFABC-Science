"""Cliente mínimo da API do Brevo (https://developers.brevo.com/).

Usa apenas três chamadas:

* ``POST /emailCampaigns`` + ``POST /emailCampaigns/{id}/sendNow``: envio da edição para
  a lista de assinantes (o Brevo cuida de inscrição, confirmação e descadastro);
* ``POST /smtp/email``: envio transacional de teste para um único endereço.

A chave nunca é registrada em logs nem incluída em mensagens de erro.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.brevo.com/v3"
UNSUBSCRIBE_TAG = "{{ unsubscribe }}"


class NewsletterError(RuntimeError):
    """Falha ao enviar a newsletter."""


class BrevoClient:
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
            headers={"api-key": api_key, "accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BrevoClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TransportError as exc:
            raise NewsletterError(f"Brevo indisponível: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = f": {body.get('code', '')} {body.get('message', '')}".rstrip()
            except ValueError:
                pass
            raise NewsletterError(f"Brevo respondeu HTTP {response.status_code}{detail}")
        if not response.content:
            return {}
        try:
            return dict(response.json())
        except ValueError:
            return {}

    def send_campaign(
        self,
        *,
        name: str,
        subject: str,
        preheader: str,
        sender_name: str,
        sender_email: str,
        html: str,
        list_id: int,
    ) -> int:
        """Cria a campanha para a lista e a envia imediatamente. Retorna o id da campanha."""
        created = self._post(
            "/emailCampaigns",
            {
                "name": name,
                "subject": subject,
                "previewText": preheader,
                "sender": {"name": sender_name, "email": sender_email},
                "htmlContent": html,
                "recipients": {"listIds": [list_id]},
                "inlineImageActivation": False,
            },
        )
        campaign_id = created.get("id")
        if not isinstance(campaign_id, int):
            raise NewsletterError("Brevo não devolveu o id da campanha criada.")
        self._post(f"/emailCampaigns/{campaign_id}/sendNow")
        logger.info("Campanha %s enviada para a lista %s.", campaign_id, list_id)
        return campaign_id

    def send_test(
        self, *, to: str, subject: str, sender_name: str, sender_email: str, html: str
    ) -> str | None:
        """Envio transacional para um único endereço (não usa a lista de assinantes)."""
        result = self._post(
            "/smtp/email",
            {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": html,
            },
        )
        return result.get("messageId")
