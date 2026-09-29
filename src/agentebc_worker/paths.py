from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentebc.paths import AppPaths


@dataclass(frozen=True, slots=True)
class WorkerPaths:
    app: AppPaths

    @classmethod
    def resolve(cls) -> WorkerPaths:
        app = AppPaths.resolve()
        return cls(app=app)

    @property
    def worker_dir(self) -> Path:
        return self.app.user_root / "worker"

    @property
    def presets_file(self) -> Path:
        return self.worker_dir / "presets.json"

    @property
    def bundled_presets_file(self) -> Path:
        candidates = (
            self.app.bundle_root / "config" / "worker_presets.json",
            self.app.development_root / "config" / "worker_presets.json",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return self.app.development_root / "config" / "worker_presets.json"

    @property
    def pending_preview_file(self) -> Path:
        return self.worker_dir / "pending_preview.json"

    @property
    def user_skills_dir(self) -> Path:
        return self.worker_dir / "skills"

    @property
    def bundled_skills_dirs(self) -> tuple[Path, ...]:
        candidates = (
            self.app.bundle_root / "config" / "skills",
            self.app.development_root / "config" / "skills",
        )
        seen: list[Path] = []
        for path in candidates:
            if path.is_dir() and path not in seen:
                seen.append(path)
        return tuple(seen)

    @property
    def batch_reports_dir(self) -> Path:
        return self.worker_dir / "reports"

    def ensure_dirs(self) -> None:
        self.worker_dir.mkdir(parents=True, exist_ok=True)
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)
        self.batch_reports_dir.mkdir(parents=True, exist_ok=True)
