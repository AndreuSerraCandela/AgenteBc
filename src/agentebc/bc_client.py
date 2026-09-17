from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

from .config import Settings


class BusinessCentralReadError(RuntimeError):
    """Una consulta de solo lectura a Business Central ha fallado."""


class BusinessCentralReadClient:
    """Cliente HTTP que expone exclusivamente operaciones GET."""

    def __init__(self, settings: Settings) -> None:
        if not settings.odata_base_url:
            raise ValueError("Falta AGENTEBC_ODATA_BASE_URL")
        self._base_url = settings.odata_base_url.rstrip("/")
        self._verify = settings.tls_verify
        self._timeout = settings.request_timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "AgenteBC-Diagnostico/0.1",
            }
        )
        self._session.auth = _build_auth(settings)

    def get(self, endpoint: str) -> dict[str, Any] | list[Any]:
        url = self._safe_url(endpoint)
        try:
            response = self._session.get(
                url,
                timeout=self._timeout,
                verify=self._verify,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            detail = f" (HTTP {status})" if status else ""
            raise BusinessCentralReadError(
                f"No se pudo consultar Business Central{detail}"
            ) from exc

        try:
            data = response.json()
        except requests.JSONDecodeError as exc:
            raise BusinessCentralReadError(
                "Business Central no devolvió una respuesta JSON"
            ) from exc
        if not isinstance(data, (dict, list)):
            raise BusinessCentralReadError("La respuesta JSON tiene un formato inesperado")
        return data

    def _safe_url(self, endpoint: str) -> str:
        endpoint = endpoint.strip()
        parsed = urlparse(endpoint)
        if not endpoint or parsed.scheme or parsed.netloc:
            raise ValueError("El endpoint debe ser una ruta relativa no vacía")
        if ".." in endpoint.split("/"):
            raise ValueError("El endpoint no puede contener '..'")
        return f"{self._base_url}/{endpoint.lstrip('/')}"


def _build_auth(settings: Settings):
    if settings.auth_mode == "basic":
        if not settings.username or not settings.password:
            raise ValueError(
                "El modo basic requiere AGENTEBC_USERNAME y AGENTEBC_PASSWORD"
            )
        return HTTPBasicAuth(settings.username, settings.password)

    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
    except ImportError as exc:
        raise RuntimeError(
            "La autenticación Windows requiere instalar "
            "'agente-bc[windows-auth]'"
        ) from exc
    return HttpNegotiateAuth()
