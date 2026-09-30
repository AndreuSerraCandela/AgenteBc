"""Buzón de skills (mismo patrón que acciones compartidas del consultor)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .skills import WorkerSkill

_SHARE_ID_PATTERN = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_share_env_loaded = False
_last_portal_inbox_error: str | None = None


class SkillShareError(ValueError):
    pass


def format_share_timestamp(iso: str) -> str:
    """ISO UTC → fecha y hora locales (dd/mm/aaaa HH:MM)."""
    raw = (iso or "").strip()
    if not raw:
        return ""
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


@dataclass(frozen=True, slots=True)
class SharedSkill:
    id: str
    created_at: str
    from_user: str
    note: str
    status: str
    skill: dict[str, Any]

    def formatted_created_at(self) -> str:
        return format_share_timestamp(self.created_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "from_user": self.from_user,
            "note": self.note,
            "status": self.status,
            "skill": self.skill,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SharedSkill:
        share_id = str(payload.get("id") or "").strip()
        if not _SHARE_ID_PATTERN.fullmatch(share_id):
            raise SkillShareError("Id de skill compartido no válido")
        skill = payload.get("skill")
        if not isinstance(skill, dict):
            raise SkillShareError("Falta el objeto skill")
        WorkerSkill.from_dict(skill)
        status = str(payload.get("status") or "pending").strip()
        if status not in {"pending", "closed"}:
            raise SkillShareError("Estado no válido")
        return cls(
            id=share_id,
            created_at=str(payload.get("created_at") or ""),
            from_user=str(payload.get("from_user") or "consultor").strip()[:80],
            note=str(payload.get("note") or "").strip()[:500],
            status=status,
            skill=skill,
        )


class SkillShareStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path or skills_share_dir()

    def share(
        self,
        skill: WorkerSkill,
        *,
        from_user: str = "",
        note: str = "",
    ) -> SharedSkill:
        item = SharedSkill(
            id=str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            from_user=from_user.strip()[:80] or "consultor",
            note=note.strip()[:500],
            status="pending",
            skill=skill.as_dict(),
        )
        self._write(item)
        return item

    def list_pending(self) -> tuple[SharedSkill, ...]:
        items: list[SharedSkill] = []
        directory = self.path
        if not directory.is_dir():
            return ()
        for path in directory.glob("*.json"):
            if path.name.endswith(".tmp"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                item = SharedSkill.from_dict(payload)
            except (OSError, json.JSONDecodeError, SkillShareError, ValueError):
                continue
            if item.status == "pending":
                items.append(item)
        items.sort(key=lambda row: row.created_at, reverse=True)
        return tuple(items)

    def close(self, share_id: str) -> SharedSkill:
        item = self.get(share_id)
        closed = SharedSkill(
            id=item.id,
            created_at=item.created_at,
            from_user=item.from_user,
            note=item.note,
            status="closed",
            skill=item.skill,
        )
        self._write(closed)
        return closed

    def get(self, share_id: str) -> SharedSkill:
        path = self._item_path(share_id)
        if not path.is_file():
            raise KeyError(share_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SkillShareError("JSON inválido")
        return SharedSkill.from_dict(payload)

    def _item_path(self, share_id: str) -> Path:
        if not _SHARE_ID_PATTERN.fullmatch(share_id):
            raise SkillShareError("Id no válido")
        return self.path / f"{share_id}.json"

    def _write(self, item: SharedSkill) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        path = self._item_path(item.id)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(item.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


def ensure_share_env_loaded() -> None:
    """Carga %LOCALAPPDATA%\\AgenteBC\\.env (AGENTEBC_ENV_FILE) en os.environ."""
    global _share_env_loaded
    if _share_env_loaded:
        return
    from agentebc.config import Settings

    Settings._load_all_env_files(override=False)
    _share_env_loaded = True


def skills_share_dir() -> Path:
    ensure_share_env_loaded()
    configured = os.getenv("AGENTEBC_WORKER_SKILLS_SHARE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    from agentebc.paths import development_root, is_desktop_mode

    if is_desktop_mode():
        from .paths import WorkerPaths

        return WorkerPaths.resolve().worker_dir / "skills-share"
    releases = os.getenv("AGENTEBC_RELEASES_DIR", "").strip()
    if releases:
        return (Path(releases).expanduser().resolve().parent / "skills-share").resolve()
    return (development_root() / "data" / "skills-share").resolve()


def portal_base_url() -> str | None:
    ensure_share_env_loaded()
    url = (
        os.getenv("AGENTEBC_SHARE_URL", "").strip()
        or os.getenv("AGENTEBC_PORTAL_URL", "").strip()
    )
    return url.rstrip("/") if url else None


def _portal_share_token() -> str:
    ensure_share_env_loaded()
    return os.getenv("AGENTEBC_SHARE_TOKEN", "").strip()


def portal_inbox_fetch_error() -> str | None:
    """Último error al consultar /api/skills/inbox (p. ej. token incorrecto)."""
    return _last_portal_inbox_error


def share_portal_configured() -> bool:
    """True si el Worker puede leer el buzón de skills en agentebc.malla.es."""
    return bool(portal_base_url() and _portal_share_token())


def share_skill_via_portal(
    skill: WorkerSkill,
    *,
    note: str = "",
    from_user: str = "",
) -> SharedSkill | None:
    """POST /api/skills/share si hay URL y token; si no, None (usar buzón local)."""
    import json
    import urllib.error
    import urllib.request

    base = portal_base_url()
    token = _portal_share_token()
    if not base or not token:
        return None
    body = json.dumps(
        {
            "skill": skill.as_dict(),
            "note": note,
            "from_user": from_user or "consultor",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/api/skills/share",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-AgenteBc-Share-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and parsed.get("error"):
                detail = str(parsed["error"])
        except json.JSONDecodeError:
            pass
        message = detail or f"HTTP {exc.code}"
        raise SkillShareError(
            f"No se pudo publicar el skill en el portal: {message}"
        ) from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SkillShareError(f"No se pudo publicar el skill en el portal: {exc}") from exc
    if not isinstance(payload, dict):
        raise SkillShareError("Respuesta del portal no válida")
    return SharedSkill.from_dict(payload)


def list_pending_from_portal() -> tuple[SharedSkill, ...]:
    import json
    import urllib.error
    import urllib.request

    global _last_portal_inbox_error
    _last_portal_inbox_error = None

    base = portal_base_url()
    token = _portal_share_token()
    if not base or not token:
        return ()
    request = urllib.request.Request(
        f"{base}/api/skills/inbox?status=pending",
        headers={
            "Accept": "application/json",
            "X-AgenteBc-Share-Token": token,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        _last_portal_inbox_error = (
            f"El portal respondió {exc.code}"
            + (f": {detail}" if detail else "")
        )
        return ()
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        _last_portal_inbox_error = str(exc)
        return ()
    if not isinstance(payload, dict):
        return ()
    items_raw = payload.get("items")
    if not isinstance(items_raw, list):
        return ()
    items: list[SharedSkill] = []
    for raw in items_raw:
        if isinstance(raw, dict):
            try:
                items.append(SharedSkill.from_dict(raw))
            except (SkillShareError, ValueError):
                continue
    return tuple(items)


def merge_pending_skills(
    local: tuple[SharedSkill, ...],
    remote: tuple[SharedSkill, ...],
) -> tuple[SharedSkill, ...]:
    seen = {item.id for item in local}
    merged = list(local)
    for item in remote:
        if item.id not in seen:
            merged.append(item)
            seen.add(item.id)
    merged.sort(key=lambda row: row.created_at, reverse=True)
    return tuple(merged)


def merged_pending_count(local_store: SkillShareStore | None = None) -> int:
    store = local_store or SkillShareStore()
    return len(
        merge_pending_skills(store.list_pending(), list_pending_from_portal())
    )


def get_shared_skill_from_portal(share_id: str) -> SharedSkill | None:
    import json
    import urllib.error
    import urllib.request

    if not _SHARE_ID_PATTERN.fullmatch(share_id):
        return None
    base = portal_base_url()
    token = _portal_share_token()
    if not base or not token:
        return None
    request = urllib.request.Request(
        f"{base}/api/skills/{share_id}",
        headers={
            "Accept": "application/json",
            "X-AgenteBc-Share-Token": token,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return SharedSkill.from_dict(payload)
    except (SkillShareError, ValueError):
        return None


def close_shared_skill_on_portal(share_id: str) -> bool:
    import urllib.error
    import urllib.request

    if not _SHARE_ID_PATTERN.fullmatch(share_id):
        return False
    base = portal_base_url()
    token = _portal_share_token()
    if not base or not token:
        return False
    request = urllib.request.Request(
        f"{base}/api/skills/{share_id}/close",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-AgenteBc-Share-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def resolve_shared_skill(
    share_id: str,
    local_store: SkillShareStore,
) -> tuple[SharedSkill, bool]:
    """Devuelve (item, from_portal)."""
    try:
        return local_store.get(share_id), False
    except KeyError:
        remote = get_shared_skill_from_portal(share_id)
        if remote is None:
            raise KeyError(share_id) from None
        return remote, True
