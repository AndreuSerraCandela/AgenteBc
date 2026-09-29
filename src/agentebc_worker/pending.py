from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .preview import JobPreview
from .job_spec import WorkerJobSpec


def write_pending_preview(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_pending_raw(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def load_pending_preview(path: Path) -> JobPreview | None:
    data = read_pending_raw(path)
    if not data or "spec" not in data:
        return None
    spec = WorkerJobSpec.from_dict(data["spec"])
    return JobPreview(
        spec=spec,
        type_label=str(data.get("type_label", "")),
        action_label=str(data.get("action_label", "")),
        resolved_dates=data.get("resolved_dates"),
        document_count=data.get("document_count"),
        sample_numbers=tuple(data.get("sample_numbers") or ()),
        truncated=bool(data.get("truncated")),
        odata_list_error=data.get("odata_list_error"),
        summary=str(data.get("summary", "")),
    )


def pending_skill_id(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    skill_id = str(data.get("skill_id", "")).strip()
    return skill_id or None
