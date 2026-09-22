from __future__ import annotations

import hmac
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .document_types import ActionDefinition, DocumentTypeDefinition, DocumentTypeRegistry

SHARE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
VALID_STATUSES = frozenset({"pending", "closed"})
_ACK_STATUSES = frozenset({"accepted", "rejected"})
_LEGACY_SHARE_STATUSES = frozenset({"accepted", "rejected"})
_DEFAULT_ACTIONS_DIR = Path(__file__).resolve().parents[2] / "packaging" / "actions"
_OBSOLETE_IIS_ACTIONS_DIR = Path(r"C:\inetpub\data\AgenteBc\actions")
_MAX_NOTE = 500
_MAX_NAME = 80


class ActionShareError(ValueError):
    """Receta compartida inválida o almacén inconsistente."""


class ActionShareConflict(ActionShareError):
    """El usuario ya registró un acuse para esta acción."""


@dataclass(frozen=True, slots=True)
class SharedAction:
    id: str
    created_at: str
    from_user: str
    note: str
    status: str
    document_type: dict[str, Any]
    action: dict[str, Any]
    acks: dict[str, dict[str, str]]

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "from_user": self.from_user,
            "note": self.note,
            "status": self.status,
            "type_id": self.document_type.get("id"),
            "type_label": self.document_type.get("label"),
            "action_id": self.action.get("id"),
            "action_label": self.action.get("label"),
            "safety": self.action.get("safety"),
            "acks": dict(self.acks),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "from_user": self.from_user,
            "note": self.note,
            "status": self.status,
            "document_type": self.document_type,
            "action": self.action,
            "acks": dict(self.acks),
        }

    def ack_for(self, user: str) -> dict[str, str] | None:
        key = _clip(user, _MAX_NAME)
        if not key:
            return None
        entry = self.acks.get(key)
        return dict(entry) if entry else None

    def pending_for(self, user: str) -> bool:
        if self.status != "pending":
            return False
        return self.ack_for(user) is None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SharedAction":
        document_type, action = validate_share_recipe(
            payload.get("document_type"),
            payload.get("action"),
        )
        status, acks = _load_share_status_and_acks(payload)
        share_id = str(payload.get("id") or "").strip()
        if not SHARE_ID_PATTERN.fullmatch(share_id):
            raise ActionShareError("El id de la acción compartida no es válido")
        return cls(
            id=share_id,
            created_at=str(payload.get("created_at") or "").strip(),
            from_user=_clip(payload.get("from_user"), _MAX_NAME) or "consultor",
            note=_clip(payload.get("note"), _MAX_NOTE),
            status=status,
            document_type=document_type,
            action=action,
            acks=acks,
        )


class ActionShareStore:
    def __init__(self, path: Path | None = None) -> None:
        self._fixed_path = path

    @property
    def path(self) -> Path:
        return self._fixed_path or actions_dir()

    def share(
        self,
        *,
        document_type: dict[str, Any] | DocumentTypeDefinition,
        action: dict[str, Any] | ActionDefinition,
        from_user: str = "",
        note: str = "",
    ) -> SharedAction:
        type_payload, action_payload = validate_share_recipe(document_type, action)
        item = SharedAction(
            id=str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            from_user=_clip(from_user, _MAX_NAME) or "consultor",
            note=_clip(note, _MAX_NOTE),
            status="pending",
            document_type=type_payload,
            action=action_payload,
            acks={},
        )
        try:
            self._write(item)
        except OSError as exc:
            raise ActionShareError(
                f"No se pudo guardar la acción compartida en {self.path}: {exc}"
            ) from exc
        return item

    def get(self, share_id: str) -> SharedAction:
        path = self._item_path(share_id)
        if not path.is_file():
            raise KeyError(f"Acción compartida no encontrada: {share_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ActionShareError("El fichero compartido no es un objeto JSON")
        return SharedAction.from_dict(payload)

    def list(
        self,
        *,
        status: str | None = "pending",
        for_user: str | None = None,
    ) -> list[SharedAction]:
        if status and status != "all" and status not in VALID_STATUSES:
            raise ActionShareError("El filtro de estado no es válido")
        user_filter = _clip(for_user, _MAX_NAME) if for_user else ""
        items: list[SharedAction] = []
        if not self.path.is_dir():
            return items
        for path in self.path.glob("*.json"):
            if path.name.endswith(".tmp"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                item = SharedAction.from_dict(payload)
            except (OSError, json.JSONDecodeError, ActionShareError, ValueError):
                continue
            if status and status != "all" and item.status != status:
                continue
            if user_filter and not item.pending_for(user_filter):
                continue
            items.append(item)
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def ack(
        self,
        share_id: str,
        *,
        status: str,
        acked_by: str = "",
    ) -> SharedAction:
        if status not in _ACK_STATUSES:
            raise ActionShareError("El acuse debe ser accepted o rejected")
        user = _clip(acked_by, _MAX_NAME)
        if not user:
            raise ActionShareError("Falta el usuario del acuse")
        current = self.get(share_id)
        if current.status != "pending":
            raise ActionShareConflict("Esta acción compartida ya está cerrada")
        if current.ack_for(user) is not None:
            raise ActionShareConflict("Este usuario ya procesó esta acción")
        acks = dict(current.acks)
        acks[user] = {
            "status": status,
            "at": datetime.now(UTC).isoformat(),
        }
        updated = SharedAction(
            id=current.id,
            created_at=current.created_at,
            from_user=current.from_user,
            note=current.note,
            status=current.status,
            document_type=current.document_type,
            action=current.action,
            acks=acks,
        )
        self._write(updated)
        return updated

    def _item_path(self, share_id: str) -> Path:
        if not SHARE_ID_PATTERN.fullmatch(share_id):
            raise ActionShareError("El id de la acción compartida no es válido")
        return self.path / f"{share_id}.json"

    def _write(self, item: SharedAction) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        path = self._item_path(item.id)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(item.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def actions_dir() -> Path:
    configured = os.getenv("AGENTEBC_ACTIONS_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if path != _OBSOLETE_IIS_ACTIONS_DIR:
            return path
    if (Path.cwd() / "wsgi.py").is_file():
        return (Path.cwd() / "data" / "actions").resolve()
    return _DEFAULT_ACTIONS_DIR.resolve()


def share_token() -> str:
    return os.getenv("AGENTEBC_SHARE_TOKEN", "").strip()


def recipe_for_share(
    definition: DocumentTypeDefinition,
    action: ActionDefinition,
) -> tuple[dict[str, Any], dict[str, Any]]:
    action.validate()
    type_payload = asdict(definition)
    type_payload["actions"] = [asdict(action)]
    return validate_share_recipe(type_payload, asdict(action))


def validate_share_recipe(
    document_type: Any,
    action: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(action, ActionDefinition):
        action_obj = action
    elif isinstance(action, dict):
        action_obj = ActionDefinition.from_dict(action)
    else:
        raise ActionShareError("Falta la receta de la acción")
    if isinstance(document_type, DocumentTypeDefinition):
        type_data = asdict(document_type)
    elif isinstance(document_type, dict):
        type_data = dict(document_type)
    else:
        raise ActionShareError("Falta el tipo de documento de la acción")
    type_data["actions"] = [asdict(action_obj)]
    type_obj = DocumentTypeDefinition.from_dict(type_data)
    return asdict(type_obj), asdict(action_obj)


def install_shared_action(
    registry: DocumentTypeRegistry,
    payload: dict[str, Any] | SharedAction,
) -> tuple[DocumentTypeDefinition, ActionDefinition]:
    data = payload.as_dict() if isinstance(payload, SharedAction) else payload
    _type_payload, action_payload = validate_share_recipe(
        data.get("document_type"),
        data.get("action"),
    )
    action = ActionDefinition.from_dict(action_payload)
    type_data = dict(data.get("document_type") or {})
    type_data["actions"] = []
    incoming_type = DocumentTypeDefinition.from_dict(type_data)
    try:
        registry.get(incoming_type.id)
    except KeyError:
        registry.save_document_type(incoming_type)
    registry.save_action(incoming_type.id, action)
    return registry.get(incoming_type.id), action


def register_action_share_routes(app: Flask) -> None:
    store = ActionShareStore()

    @app.post("/api/actions/share")
    def share_action():
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("El cuerpo debe ser un objeto JSON", 400)
        try:
            item = store.share(
                document_type=payload.get("document_type"),
                action=payload.get("action"),
                from_user=str(payload.get("from_user") or ""),
                note=str(payload.get("note") or ""),
            )
        except (ActionShareError, ValueError, TypeError, KeyError) as exc:
            return _json_error(str(exc), 400)
        except OSError as exc:
            return _json_error(f"No se pudo guardar la acción: {exc}", 500)
        return jsonify(item.as_dict()), 201

    @app.get("/api/actions/inbox")
    def action_inbox():
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        status = (request.args.get("status") or "pending").strip()
        for_user = str(request.args.get("for_user") or "").strip()
        try:
            items = store.list(
                status=status,
                for_user=for_user or None,
            )
        except ActionShareError as exc:
            return _json_error(str(exc), 400)
        return jsonify(
            {
                "items": [item.as_dict() for item in items],
                "count": len(items),
            }
        )

    @app.get("/api/actions/<share_id>")
    def get_shared_action(share_id: str):
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        try:
            return jsonify(store.get(share_id).as_dict())
        except ActionShareError as exc:
            return _json_error(str(exc), 400)
        except KeyError:
            return _json_error("Acción compartida no encontrada", 404)

    @app.post("/api/actions/<share_id>/ack")
    def ack_shared_action(share_id: str):
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("El cuerpo debe ser un objeto JSON", 400)
        status = str(payload.get("status") or "").strip()
        try:
            item = store.ack(
                share_id,
                status=status,
                acked_by=str(payload.get("acked_by") or ""),
            )
        except ActionShareConflict as exc:
            return _json_error(str(exc), 409)
        except ActionShareError as exc:
            return _json_error(str(exc), 400)
        except KeyError:
            return _json_error("Acción compartida no encontrada", 404)
        return jsonify(item.as_dict())


def _auth_error():
    expected = share_token()
    if not expected:
        return _json_error(
            "El portal no tiene AGENTEBC_SHARE_TOKEN configurado",
            503,
        )
    provided = (
        request.headers.get("X-AgenteBc-Share-Token")
        or _bearer_token(request.headers.get("Authorization"))
        or ""
    ).strip()
    if not provided or not hmac.compare_digest(provided, expected):
        return _json_error("Token de compartir no válido", 401)
    return None


def _bearer_token(value: str | None) -> str:
    text = (value or "").strip()
    prefix = "Bearer "
    if text.lower().startswith(prefix.lower()):
        return text[len(prefix) :].strip()
    return ""


def _json_error(message: str, status: int):
    return jsonify({"error": message}), status


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_acks(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, str]] = {}
    for user, entry in raw.items():
        user_key = _clip(user, _MAX_NAME)
        if not user_key or not isinstance(entry, dict):
            continue
        ack_status = str(entry.get("status") or "").strip()
        if ack_status not in _ACK_STATUSES:
            continue
        ack_at = _optional_text(entry.get("at")) or datetime.now(UTC).isoformat()
        parsed[user_key] = {"status": ack_status, "at": ack_at}
    return parsed


def _load_share_status_and_acks(
    payload: dict[str, Any],
) -> tuple[str, dict[str, dict[str, str]]]:
    acks = _parse_acks(payload.get("acks"))
    status = str(payload.get("status") or "pending").strip()
    if status in _LEGACY_SHARE_STATUSES:
        legacy_user = _clip(payload.get("acked_by"), _MAX_NAME)
        legacy_at = _optional_text(payload.get("acked_at"))
        if legacy_user and legacy_user not in acks:
            acks[legacy_user] = {
                "status": status,
                "at": legacy_at or datetime.now(UTC).isoformat(),
            }
        status = "pending"
    if status not in VALID_STATUSES:
        raise ActionShareError("El estado de la acción compartida no es válido")
    return status, acks
