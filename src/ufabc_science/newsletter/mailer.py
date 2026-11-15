"""Envio por SMTP (biblioteca padrão do Python), pensado para o Gmail do projeto.

Gmail: ``smtp.gmail.com``, porta 465 (SSL), usuário = endereço do Gmail e senha = **senha de
app** (exige verificação em duas etapas na conta). Cada assinante recebe uma mensagem
individual, então ninguém vê o endereço dos outros. Senha e endereços nunca vão para os logs.
"""

from __future__ import annotations

import contextlib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol


class NewsletterError(RuntimeError):
    """Falha ao enviar a newsletter."""


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> None: ...

    def close(self) -> None: ...


def build_message(
    *,
    sender_name: str,
    sender: str,
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe: str | None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    if unsubscribe:
        message["List-Unsubscribe"] = f"<{unsubscribe}>"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


class SmtpMailer:
    """Uma conexão SMTP autenticada, reutilizada para todas as mensagens do envio."""

    def __init__(
        self, *, host: str, port: int, username: str, password: str, timeout: float = 30.0
    ) -> None:
        context = ssl.create_default_context()
        try:
            if port == 465:
                self._smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                    host, port, timeout=timeout, context=context
                )
            else:
                self._smtp = smtplib.SMTP(host, port, timeout=timeout)
                self._smtp.starttls(context=context)
            self._smtp.login(username, password)
        except smtplib.SMTPAuthenticationError as exc:
            raise NewsletterError(
                "Login SMTP recusado: confira SMTP_USERNAME e a senha de app (SMTP_PASSWORD)."
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise NewsletterError(f"Falha ao conectar ao SMTP: {type(exc).__name__}") from exc

    def send(self, message: EmailMessage) -> None:
        try:
            self._smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise NewsletterError(f"Falha no envio SMTP: {type(exc).__name__}") from exc

    def close(self) -> None:
        with contextlib.suppress(smtplib.SMTPException, OSError):
            self._smtp.quit()
