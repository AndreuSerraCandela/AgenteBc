"""Sube un skill al portal (POST /api/skills/share)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import urllib.error
import urllib.request

_DEFAULT_PORTAL = "https://agentebc.malla.es"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _share_token() -> str:
    token = os.getenv("AGENTEBC_SHARE_TOKEN", "").strip()
    if token:
        return token
    localapp = os.getenv("LOCALAPPDATA", "").strip()
    for path in (
        [Path(localapp) / "AgenteBC" / ".env"] if localapp else []
    ) + [Path.cwd() / ".env"]:
        token = _read_env_file(path).get("AGENTEBC_SHARE_TOKEN", "").strip()
        if token:
            return token
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publica un skill en el portal")
    parser.add_argument("skill", type=Path, help="Ruta al .skill.json")
    parser.add_argument("--note", default="", help="Nota para el buzón")
    parser.add_argument("--from-user", default="", help="Nombre del consultor")
    parser.add_argument(
        "--portal",
        default=os.getenv("AGENTEBC_SHARE_URL", _DEFAULT_PORTAL).strip()
        or _DEFAULT_PORTAL,
    )
    args = parser.parse_args(argv)
    path = args.skill.expanduser().resolve()
    if not path.is_file():
        print(f"No existe: {path}", file=sys.stderr)
        return 1
    token = _share_token()
    if not token:
        print("Falta AGENTEBC_SHARE_TOKEN", file=sys.stderr)
        return 1
    skill = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(skill, dict):
        print("El skill debe ser un objeto JSON", file=sys.stderr)
        return 1
    body = json.dumps(
        {
            "skill": skill,
            "note": args.note,
            "from_user": args.from_user or "consultor",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    url = args.portal.rstrip("/") + "/api/skills/share"
    request = urllib.request.Request(
        url,
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
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"No se pudo conectar: {exc}", file=sys.stderr)
        return 1
    print(f"Skill publicado: {payload.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
