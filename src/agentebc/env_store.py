from __future__ import annotations

import re
from pathlib import Path

from .config import ConfigurationError, Settings

_PASSWORD_KEYS = frozenset({"AGENTEBC_PASSWORD", "AGENTEBC_DEEPSEEK_API_KEY", "AGENTEBC_BC_AGENT_TOKEN"})
_SECRET_PLACEHOLDER = "********"

_SETUP_KEYS = (
    "AGENTEBC_ODATA_BASE_URL",
    "AGENTEBC_AUTH_MODE",
    "AGENTEBC_USERNAME",
    "AGENTEBC_PASSWORD",
    "AGENTEBC_COMPANY",
    "AGENTEBC_TLS_VERIFY",
    "AGENTEBC_BC_AGENT_URL",
    "AGENTEBC_BC_AGENT_TOKEN",
    "AGENTEBC_SOURCE_PATH",
    "AGENTEBC_ALPACKAGES_PATH",
    "AGENTEBC_SQL_ENV_FILE",
    "AGENTEBC_REQUEST_TIMEOUT",
    "AGENTEBC_BROWSER_CHANNEL",
    "AGENTEBC_BROWSER_HEADLESS",
    "AGENTEBC_AI_PROVIDER",
    "AGENTEBC_LM_STUDIO_URL",
    "AGENTEBC_LM_STUDIO_MODEL",
    "AGENTEBC_DEEPSEEK_API_KEY",
    "AGENTEBC_DEEPSEEK_MODEL",
    "AGENTEBC_DEEPSEEK_URL",
    "AGENTEBC_DEEPSEEK_WEB_URL",
    "AGENTEBC_DEEPSEEK_WEB_CDP_URL",
    "AGENTEBC_AI_WEB_CDP_URL",
    "AGENTEBC_GOOGLE_AI_WEB_URL",
    "AGENTEBC_LICENSE_URL",
    "AGENTEBC_LICENSE_TOKEN",
    "AGENTEBC_LICENSE_CLIENT",
)

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def read_env_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        match = _ENV_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def mask_secret_values(values: dict[str, str]) -> dict[str, str]:
    masked = dict(values)
    for key in _PASSWORD_KEYS:
        if masked.get(key):
            masked[key] = _SECRET_PLACEHOLDER
    return masked


def write_env_values(
    path: Path,
    updates: dict[str, str],
    *,
    preserve_if_empty: frozenset[str] = _PASSWORD_KEYS,
) -> None:
    existing = read_env_values(path) if path.is_file() else {}
    merged = dict(existing)
    for key, value in updates.items():
        stripped = value.strip()
        if key in preserve_if_empty and not stripped:
            continue
        merged[key] = stripped

    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("export "):
                stripped = stripped[7:].lstrip()
            match = _ENV_LINE.match(stripped) if stripped and not stripped.startswith("#") else None
            if match:
                name = match.group(1)
                if name in merged:
                    lines.append(f"{name}={merged[name]}")
                    seen.add(name)
                    continue
            lines.append(raw_line)

    for key in _SETUP_KEYS:
        if key in merged and key not in seen:
            lines.append(f"{key}={merged[key]}")
            seen.add(key)

    for key, value in merged.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_setup_complete(settings: Settings) -> bool:
    if not settings.odata_base_url or not settings.company:
        return False
    if settings.auth_mode == "basic" and not (settings.username and settings.password):
        return False
    return True


def collect_setup_updates(form: object) -> dict[str, str]:
    updates: dict[str, str] = {}
    for key in _SETUP_KEYS:
        if key in form:
            updates[key] = str(form.get(key, "")).strip()
    return updates


def apply_env_updates(path: Path, updates: dict[str, str]) -> Settings:
    write_env_values(path, updates)
    return Settings.load_fresh(path)
