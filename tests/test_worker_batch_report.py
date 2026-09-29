from __future__ import annotations

from agentebc_worker.batch_report import build_skill_batch_report, format_report_plain_text
from agentebc_worker.runner import BatchRunResult, DocumentRunOutcome
from agentebc_worker.skills import SkillStore
from pathlib import Path


def test_batch_report_includes_fields_and_errors() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = SkillStore(
        root / "tests" / "_unused",
        bundled_dirs=(root / "config" / "skills",),
    ).get("malla_publicidad_facturar_ventas")
    result = BatchRunResult(
        preview_summary="Empresa: Malla Publicidad",
        dry_run=False,
        outcomes=(
            DocumentRunOutcome(
                number="FV-1",
                outcome="error",
                error="Proyecto obligatorio",
                fields={"contract": "C-99"},
            ),
            DocumentRunOutcome(
                number="FV-2",
                outcome="success",
                fields={"contract": "C-100"},
            ),
        ),
    )
    report = build_skill_batch_report(skill, result)
    assert report.totals["error"] == 1
    text = format_report_plain_text(report)
    assert "FV-1" in text
    assert "Proyecto obligatorio" in text
    assert "C-99" in text
