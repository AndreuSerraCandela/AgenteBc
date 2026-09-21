from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


_OBSOLETE_PLACEHOLDERS = {
    "AGENTEBC_ODATA_BASE_URL": "https://servidor/instancia/ODataV4",
    "AGENTEBC_COMPANY": "Nombre de la empresa",
    "AGENTEBC_SOURCE_PATH": r"C:\Ruta\A\Fuentes\BC",
    "AGENTEBC_ALPACKAGES_PATH": r"C:\Ruta\A\Fuentes\BC\Funciones\.alpackages",
    "AGENTEBC_SQL_ENV_FILE": r"C:\Ruta\A\db.local.env",
}


def _migrate_obsolete_placeholders(env_file: Path) -> None:
    """Vacía valores ficticios copiados por instaladores anteriores."""
    if not env_file.is_file():
        return

    try:
        lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return

    changed = False
    migrated: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            migrated.append(raw_line)
            continue
        name, value = stripped.split("=", 1)
        if _OBSOLETE_PLACEHOLDERS.get(name.strip()) == value.strip():
            migrated.append(f"{name.strip()}=")
            changed = True
        else:
            migrated.append(raw_line)

    values = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in migrated
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    if (
        values.get("AGENTEBC_BC_AGENT_URL") == "http://192.168.10.238:5051"
        and not values.get("AGENTEBC_BC_AGENT_TOKEN")
    ):
        migrated = [
            "AGENTEBC_BC_AGENT_URL="
            if line.strip() == "AGENTEBC_BC_AGENT_URL=http://192.168.10.238:5051"
            else line
            for line in migrated
        ]
        changed = True

    if changed:
        env_file.write_text("\n".join(migrated) + "\n", encoding="utf-8")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_desktop_mode() -> bool:
    return os.getenv("AGENTEBC_APP_MODE", "").strip().lower() == "desktop" or is_frozen()


def default_user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AgenteBC"
    return Path.home() / ".agentebc"


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def development_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AppPaths:
    bundle_root: Path
    user_root: Path
    development_root: Path

    @classmethod
    def resolve(cls) -> AppPaths:
        bundle = bundle_root()
        dev = development_root()
        if is_desktop_mode():
            return cls(
                bundle_root=bundle,
                user_root=default_user_data_dir(),
                development_root=dev,
            )
        return cls(
            bundle_root=dev,
            user_root=dev,
            development_root=dev,
        )

    @property
    def env_file(self) -> Path:
        if is_desktop_mode():
            return self.user_root / ".env"
        return self.development_root / ".env"

    @property
    def env_example_file(self) -> Path:
        candidates = (
            self.bundle_root / ".env.example",
            self.development_root / ".env.example",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return self.development_root / ".env.example"

    @property
    def document_types_file(self) -> Path:
        user_copy = self.user_root / "config" / "document_types.json"
        if user_copy.is_file():
            return user_copy
        bundled = self.bundle_root / "config" / "document_types.json"
        if bundled.is_file():
            return bundled
        return self.development_root / "config" / "document_types.json"

    @property
    def reports_dir(self) -> Path:
        if is_desktop_mode():
            return self.user_root / "reports"
        return self.development_root / "reports"

    @property
    def logs_dir(self) -> Path:
        if is_desktop_mode():
            return self.user_root / "logs"
        return self.development_root / "logs"

    @property
    def config_dir(self) -> Path:
        if is_desktop_mode():
            return self.user_root / "config"
        return self.development_root / "config"

    @property
    def app_icon_file(self) -> Path | None:
        candidates = (
            self.bundle_root / "agentebc.ico",
            self.development_root / "packaging" / "agentebc.ico",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def ensure_user_setup(self) -> None:
        if not is_desktop_mode():
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            return

        self.user_root.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        bundled_types = self.bundle_root / "config" / "document_types.json"
        user_types = self.config_dir / "document_types.json"
        if bundled_types.is_file() and not user_types.is_file():
            shutil.copy2(bundled_types, user_types)

        if not self.env_file.is_file() and self.env_example_file.is_file():
            shutil.copy2(self.env_example_file, self.env_file)
        _migrate_obsolete_placeholders(self.env_file)

    def summary(self) -> dict[str, str]:
        return {
            "mode": "desktop" if is_desktop_mode() else "development",
            "frozen": str(is_frozen()),
            "user_root": str(self.user_root),
            "env_file": str(self.env_file),
            "document_types_file": str(self.document_types_file),
            "reports_dir": str(self.reports_dir),
            "logs_dir": str(self.logs_dir),
        }


def configure_desktop_environment() -> AppPaths:
    os.environ.setdefault("AGENTEBC_APP_MODE", "desktop")
    paths = AppPaths.resolve()
    paths.ensure_user_setup()
    os.environ.setdefault("AGENTEBC_ENV_FILE", str(paths.env_file))
    return paths
