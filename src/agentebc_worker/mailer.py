from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    mail_from: str
    use_tls: bool
    use_ssl: bool

    @classmethod
    def from_environment(cls) -> SmtpSettings | None:
        host = (
            os.getenv("AGENTEBC_SMTP_HOST", "").strip()
            or os.getenv("MAIL_SERVER", "").strip()
        )
        if not host:
            return None
        port_text = (
            os.getenv("AGENTEBC_SMTP_PORT", "").strip()
            or os.getenv("MAIL_PORT", "587").strip()
        )
        try:
            port = int(port_text)
        except ValueError:
            port = 587
        mail_from = (
            os.getenv("AGENTEBC_SMTP_FROM", "").strip()
            or os.getenv("MAIL_DEFAULT_SENDER", "").strip()
            or os.getenv("AGENTEBC_SMTP_USER", "").strip()
            or os.getenv("MAIL_USERNAME", "").strip()
        )
        if not mail_from:
            return None
        use_ssl = os.getenv("MAIL_USE_SSL", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "si",
            "sí",
        }
        use_tls = os.getenv("AGENTEBC_SMTP_TLS", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "si",
            "sí",
        }
        if os.getenv("MAIL_USE_TLS") is not None:
            use_tls = True
        username = (
            os.getenv("AGENTEBC_SMTP_USER", "").strip()
            or os.getenv("MAIL_USERNAME", "").strip()
            or None
        )
        password = (
            os.getenv("AGENTEBC_SMTP_PASSWORD", "").strip()
            or os.getenv("MAIL_PASSWORD", "").strip()
            or None
        )
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            mail_from=mail_from,
            use_tls=use_tls and not use_ssl,
            use_ssl=use_ssl,
        )


def send_plain_email(
    *,
    smtp: SmtpSettings,
    recipients: tuple[str, ...],
    subject: str,
    body: str,
) -> None:
    if not recipients:
        raise ValueError("No hay destinatarios")
    message = EmailMessage()
    message["From"] = smtp.mail_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    if smtp.use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=60, context=context) as server:
            if smtp.username and smtp.password:
                server.login(smtp.username, smtp.password)
            server.send_message(message)
        return
    with smtplib.SMTP(smtp.host, smtp.port, timeout=60) as server:
        server.ehlo()
        if smtp.use_tls:
            context = ssl.create_default_context()
            server.starttls(context=context)
            server.ehlo()
        if smtp.username and smtp.password:
            server.login(smtp.username, smtp.password)
        server.send_message(message)
