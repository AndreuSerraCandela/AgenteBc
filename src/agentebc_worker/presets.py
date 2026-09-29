from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .job_spec import WorkerJobSpec

_PRESET_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,49}$")


@dataclass(frozen=True, slots=True)
class WorkerPreset:
    id: str
    label: str
    spec: WorkerJobSpec

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkerPreset:
        preset_id = str(value.get("id", "")).strip()
        label = str(value.get("label", "")).strip()
        if not _PRESET_ID_PATTERN.fullmatch(preset_id):
            raise ValueError(f"id de preset no válido: {preset_id!r}")
        if not label:
            raise ValueError("label es obligatorio en un preset")
        spec_payload = value.get("spec")
        if not isinstance(spec_payload, dict):
            raise ValueError("spec debe ser un objeto")
        spec = WorkerJobSpec.from_dict(spec_payload, require_company=False)
        if spec.company:
            raise ValueError(
                "Los presets guardados no deben incluir company; "
                "indíquela al hacer preview o ejecutar"
            )
        return cls(id=preset_id, label=label, spec=spec)

    def validate_template(self) -> None:
        if self.spec.company.strip():
            raise ValueError("El preset no debe fijar company")

    def as_dict(self) -> dict[str, Any]:
        spec_dict = self.spec.as_dict()
        spec_dict.pop("company", None)
        return {
            "id": self.id,
            "label": self.label,
            "spec": spec_dict,
        }


class PresetStore:
    def __init__(self, path: Path, *, bundled: Path | None = None) -> None:
        self._path = path
        self._bundled = bundled

    def all(self) -> list[WorkerPreset]:
        merged: dict[str, WorkerPreset] = {}
        for source in (self._bundled, self._path):
            if source is None or not source.is_file():
                continue
            raw = json.loads(source.read_text(encoding="utf-8"))
            items = raw.get("presets", raw) if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                raise ValueError(f"Formato de presets inválido en {source}")
            for item in items:
                if not isinstance(item, dict):
                    continue
                preset = WorkerPreset.from_dict(item)
                merged[preset.id] = preset
        return sorted(merged.values(), key=lambda p: p.label.casefold())

    def get(self, preset_id: str) -> WorkerPreset:
        for preset in self.all():
            if preset.id == preset_id:
                return preset
        raise KeyError(f"Preset no encontrado: {preset_id}")

    def save(self, preset: WorkerPreset) -> None:
        preset.validate_template()
        user_presets = self._load_user_only()
        user_presets = [p for p in user_presets if p.id != preset.id]
        user_presets.append(preset)
        self._write(user_presets)

    def delete(self, preset_id: str) -> None:
        user_presets = self._load_user_only()
        filtered = [p for p in user_presets if p.id != preset_id]
        if len(filtered) == len(user_presets):
            raise KeyError(f"Preset no encontrado en presets guardados: {preset_id}")
        self._write(filtered)

    def _load_user_only(self) -> list[WorkerPreset]:
        if not self._path.is_file():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        items = raw.get("presets", [])
        if not isinstance(items, list):
            raise ValueError(f"Formato de presets inválido en {self._path}")
        return [WorkerPreset.from_dict(item) for item in items if isinstance(item, dict)]

    def _write(self, presets: list[WorkerPreset]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"presets": [p.as_dict() for p in sorted(presets, key=lambda x: x.id)]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def merge_preset_with_company(preset: WorkerPreset, company: str) -> WorkerJobSpec:
    company = company.strip()
    if not company:
        raise ValueError("company es obligatorio")
    base = preset.spec.as_dict()
    base["company"] = company
    return WorkerJobSpec.from_dict(base)


def new_preset_id(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")[:40]
    if not slug or not _PRESET_ID_PATTERN.fullmatch(slug):
        slug = "preset"
    suffix = uuid.uuid4().hex[:8]
    candidate = f"{slug}_{suffix}"[:50]
    if not _PRESET_ID_PATTERN.fullmatch(candidate):
        candidate = f"p_{suffix}"
    return candidate
