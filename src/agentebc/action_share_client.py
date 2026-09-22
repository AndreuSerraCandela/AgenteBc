from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .action_share import ActionShareError, recipe_for_share
from .config import Settings
from .document_types import ActionDefinition, DocumentTypeDefinition

_DEFAULT_SHARE_URL = "https://agentebc.malla.es"


class ActionShareClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "ActionShareClient":
        token = (settings.share_token or "").strip()
        if not token:
            raise ActionShareError(
                "Falta el token de compartir. Configúralo en Configuración general."
            )
        return cls(
            base_url=settings.share_url or _DEFAULT_SHARE_URL,
            token=token,
            timeout_seconds=min(settings.request_timeout_seconds, 30.0),
        )

    def share(
        self,
        definition: DocumentTypeDefinition,
        action: ActionDefinition,
        *,
        from_user: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        type_payload, action_payload = recipe_for_share(definition, action)
        return self._request(
            "POST",
            "/api/actions/share",
            {
                "document_type": type_payload,
                "action": action_payload,
                "from_user": from_user,
                "note": note,
            },
        )

    def inbox(
        self,
        *,
        status: str = "pending",
        for_user: str = "",
    ) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "status": status,
                "for_user": for_user,
            },
            quote_via=urllib.parse.quote,
        )
        payload = self._request("GET", f"/api/actions/inbox?{query}")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ActionShareError("El buzón no devolvió una lista de acciones")
        return [item for item in items if isinstance(item, dict)]

    def pending_count(self, *, for_user: str = "") -> int:
        return len(self.inbox(status="pending", for_user=for_user))

    def get(self, share_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/actions/{share_id}")

    def ack(
        self,
        share_id: str,
        *,
        status: str,
        acked_by: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/actions/{share_id}/ack",
            {"status": status, "acked_by": acked_by},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "X-AgenteBc-Share-Token": self.token,
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ActionShareError(_http_error_message(exc)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ActionShareError(
                f"No se pudo contactar con el portal de acciones: {exc}"
            ) from exc
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ActionShareError(
                "El portal de acciones no devolvió JSON válido"
            ) from exc
        if not isinstance(parsed, dict):
            raise ActionShareError("El portal de acciones no devolvió un objeto")
        return parsed


def share_sender_name(settings: Settings) -> str:
    return (
        (settings.share_user or "").strip()
        or os.getenv("USERNAME", "").strip()
        or "consultor"
    )


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        if isinstance(payload, dict):
            detail = str(payload.get("error") or "").strip()
    except Exception:
        detail = ""
    if exc.code == 401:
        return detail or "Token de compartir no válido"
    if exc.code == 404:
        return detail or "Acción compartida no encontrada"
    if exc.code == 409:
        return detail or "Este usuario ya procesó esta acción"
    if exc.code == 503:
        return detail or "El portal no tiene el token de compartir configurado"
    return detail or f"El portal de acciones respondió HTTP {exc.code}"
