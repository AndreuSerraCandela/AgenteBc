"""Correo SMTP del informe, guardado en el .env del usuario."""
from __future__ import annotations

from pathlib import Path

from agentebc.config import Settings
from agentebc.env_store import read_env_values, write_env_values

_TRUE = {"1", "true", "yes", "si", "sí"}


def mail_form_from_env(path: Path) -> dict[str, str]:
    values = read_env_values(path) if path.is_file() else {}
    host = values.get("AGENTEBC_SMTP_HOST") or values.get("MAIL_SERVER") or ""
    port = values.get("AGENTEBC_SMTP_PORT") or values.get("MAIL_PORT") or "587"
    user = values.get("AGENTEBC_SMTP_USER") or values.get("MAIL_USERNAME") or ""
    sender = (
        values.get("AGENTEBC_SMTP_FROM")
        or values.get("MAIL_DEFAULT_SENDER")
        or user
    )
    use_ssl = (values.get("MAIL_USE_SSL") or "").strip().lower() in _TRUE
    password_set = bool(
        values.get("AGENTEBC_SMTP_PASSWORD") or values.get("MAIL_PASSWORD")
    )
    return {
        "host": host,
        "port": port,
        "user": user,
        "sender": sender,
        "security": "ssl" if use_ssl else "tls",
        "password_set": "1" if password_set else "",
    }


def save_worker_mail_settings(path: Path, form: dict[str, str]) -> None:
    host = form.get("host", "").strip()
    user = form.get("user", "").strip()
    sender = form.get("sender", "").strip() or user
    security = form.get("security", "tls").strip().lower()
    if security not in {"tls", "ssl"}:
        security = "tls"
    port = form.get("port", "").strip() or ("465" if security == "ssl" else "587")
    if not port.isdigit():
        raise ValueError("El puerto SMTP debe ser numérico")
    updates = {
        "AGENTEBC_SMTP_HOST": host,
        "AGENTEBC_SMTP_PORT": port,
        "AGENTEBC_SMTP_USER": user,
        "AGENTEBC_SMTP_FROM": sender,
        "AGENTEBC_SMTP_TLS": "false" if security == "ssl" else "true",
        "MAIL_USE_SSL": "true" if security == "ssl" else "false",
    }
    password = form.get("password", "").strip()
    if password:
        updates["AGENTEBC_SMTP_PASSWORD"] = password
    write_env_values(path, updates)
    Settings.load_fresh(path)
