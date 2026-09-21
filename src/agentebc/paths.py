from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


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

        bundled_types = self.bundle_root / "config" / "document_types.json"
        user_types = self.config_dir / "document_types.json"
        if bundled_types.is_file() and not user_types.is_file():
            shutil.copy2(bundled_types, user_types)

        if not self.env_file.is_file() and self.env_example_file.is_file():
            shutil.copy2(self.env_example_file, self.env_file)

    def summary(self) -> dict[str, str]:
        return {
            "mode": "desktop" if is_desktop_mode() else "development",
            "frozen": str(is_frozen()),
            "user_root": str(self.user_root),
            "env_file": str(self.env_file),
            "document_types_file": str(self.document_types_file),
            "reports_dir": str(self.reports_dir),
        }


def configure_desktop_environment() -> AppPaths:
    os.environ.setdefault("AGENTEBC_APP_MODE", "desktop")
    paths = AppPaths.resolve()
    paths.ensure_user_setup()
    os.environ.setdefault("AGENTEBC_ENV_FILE", str(paths.env_file))
    return paths
