from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .error_reporting import format_error_detail_text
from .runner import BatchRunResult, DocumentRunOutcome
from .skills import SkillReportField, WorkerSkill

REPORT_FORMAT_VERSION = 2


@dataclass(frozen=True, slots=True)
class SkillBatchReport:
    skill_id: str
    skill_label: str
    generated_at: str
    dry_run: bool
    preview_summary: str
    totals: dict[str, int]
    field_labels: dict[str, str]
    rows: tuple[dict[str, Any], ...]
    notify_emails: tuple[str, ...] = ()
    llm_summary: str | None = None
    email_status: str | None = None
    report_path: str | None = None
    report_format_version: int = REPORT_FORMAT_VERSION

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["report_format_version"] = REPORT_FORMAT_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillBatchReport:
        rows = data.get("rows", [])
        return cls(
            skill_id=str(data["skill_id"]),
            skill_label=str(data["skill_label"]),
            generated_at=str(data["generated_at"]),
            dry_run=bool(data["dry_run"]),
            preview_summary=str(data["preview_summary"]),
            totals=dict(data["totals"]),
            field_labels=dict(data["field_labels"]),
            rows=tuple(rows if isinstance(rows, list) else ()),
            notify_emails=tuple(data.get("notify_emails") or ()),
            llm_summary=data.get("llm_summary"),
            email_status=data.get("email_status"),
            report_path=data.get("report_path"),
            report_format_version=int(
                data.get("report_format_version") or REPORT_FORMAT_VERSION
            ),
        )

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)


def build_skill_batch_report(
    skill: WorkerSkill,
    result: BatchRunResult,
    *,
    field_values_by_number: dict[str, dict[str, str]] | None = None,
) -> SkillBatchReport:
    labels = _field_labels(skill.report.fields)
    extras = field_values_by_number or {}
    rows: list[dict[str, Any]] = []
    totals = {
        "success": 0,
        "error": 0,
        "skipped": 0,
        "dry_run_skipped": 0,
        "other": 0,
    }

    for outcome in result.outcomes:
        bucket = outcome.outcome
        if bucket in totals:
            totals[bucket] += 1
        else:
            totals["other"] += 1
        row: dict[str, Any] = {
            "number": outcome.number,
            "outcome": outcome.outcome,
            "error": outcome.error,
            "attempts": outcome.attempts,
            "error_detail": outcome.error_detail,
        }
        merged = dict(outcome.fields)
        merged.update(extras.get(outcome.number, {}))
        for key, label in labels.items():
            if key == "number":
                row[label] = outcome.number
            elif key in merged:
                row[label] = merged[key]
        rows.append(row)

    return SkillBatchReport(
        skill_id=skill.id,
        skill_label=skill.label,
        generated_at=datetime.now(UTC).isoformat(),
        dry_run=result.dry_run,
        preview_summary=result.preview_summary,
        totals=totals,
        field_labels=labels,
        rows=tuple(rows),
        notify_emails=skill.report.notify_emails,
    )


def save_batch_report(report: SkillBatchReport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.replace(":", "").replace("-", "")[:15]
    path = directory / f"batch-{report.skill_id}-{stamp}.json"
    path.write_text(report.to_json() + "\n", encoding="utf-8")
    return path


def format_report_plain_text(report: SkillBatchReport) -> str:
    lines = [
        f"Informe skill: {report.skill_label} ({report.skill_id})",
        f"Formato informe: v{report.report_format_version}",
        f"Generado: {report.generated_at}",
        "Modo: simulación (dry run)" if report.dry_run else "Modo: registro real en BC",
        "",
        report.preview_summary,
        "",
        (
            f"Totales — OK: {report.totals.get('success', 0)}, "
            f"Errores: {report.totals.get('error', 0)}, "
            f"Omitidas: {report.totals.get('skipped', 0)}, "
            f"Simulados: {report.totals.get('dry_run_skipped', 0)}"
        ),
        "",
        "=" * 72,
        f"FACTURAS REGISTRADAS CORRECTAMENTE ({len(_rows_by_outcome(report, 'success'))})",
        "=" * 72,
    ]
    successes = _rows_by_outcome(report, "success")
    if successes:
        for row in successes:
            lines.extend(_format_row_header(row, report))
            lines.append("")
    else:
        lines.append("(Ninguna en este lote.)")
        lines.append("")

    lines.extend(
        [
            "=" * 72,
            f"FACTURAS NO REGISTRADAS ({len(_rows_by_outcome(report, 'error'))})",
            "=" * 72,
            "",
        ]
    )
    errors = _rows_by_outcome(report, "error")
    if errors:
        for row in errors:
            lines.extend(_format_row_header(row, report))
            if row.get("error"):
                lines.append(f"Resumen: {row['error']}")
            detail_text = format_error_detail_text(row.get("error_detail"))
            if detail_text:
                lines.append("")
                lines.append("Detalle completo del error (BC):")
                lines.append(detail_text)
            lines.append("")
    else:
        lines.append("No hay errores de registro en este lote.")
        lines.append("")

    skipped = _rows_by_outcome(report, "skipped")
    if skipped:
        lines.extend(
            [
                "=" * 72,
                f"OMITIDAS ({len(skipped)})",
                "=" * 72,
                "",
            ]
        )
        for row in skipped:
            lines.extend(_format_row_header(row, report))
            if row.get("error"):
                lines.append(f"Motivo: {row['error']}")
            lines.append("")

    ai_rows = [
        row
        for row in report.rows
        if row.get("ai_conclusion") and row.get("outcome") == "error"
    ]
    lines.extend(
        [
            "=" * 72,
            "CONCLUSIONES IA (SOLO FACTURAS CON ERROR, UNA POR FACTURA)",
            "=" * 72,
            "",
        ]
    )
    if ai_rows:
        for row in ai_rows:
            lines.append(f"### {row.get('number', '?')}")
            lines.extend(_format_row_header(row, report, bullet=False))
            lines.append(str(row.get("ai_conclusion", "")).strip())
            lines.append("")
    elif report.llm_summary and str(report.llm_summary).startswith("(Aviso IA:"):
        lines.append(report.llm_summary)
        lines.append("")
    elif report.llm_summary:
        lines.append(
            "(Este informe tiene un resumen IA antiguo global. "
            "Regenera conclusiones por factura con "
            "scripts/enrich_batch_report_ai.py <informe.json> --mail.)"
        )
        lines.append("")
    else:
        lines.append("(Sin conclusiones IA en este informe.)")
        lines.append("")

    if report.email_status:
        lines.extend(["", f"Correo: {report.email_status}"])
    return "\n".join(lines)


def _rows_by_outcome(report: SkillBatchReport, outcome: str) -> list[dict[str, Any]]:
    return [row for row in report.rows if row.get("outcome") == outcome]


def _format_row_header(
    row: dict[str, Any],
    report: SkillBatchReport,
    *,
    bullet: bool = True,
) -> list[str]:
    prefix = "  • " if bullet else ""
    parts = [f"{prefix}{row.get('number', '?')}"]
    for label in report.field_labels.values():
        if label in row and label not in {"Nº documento"}:
            parts.append(f"{label}={row[label]}")
    if row.get("attempts", 1) > 1:
        parts.append(f"intentos={row['attempts']}")
    return [" ".join(parts)]


def _field_labels(fields: tuple[SkillReportField, ...]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in fields:
        labels[item.key] = item.label
    if "number" not in labels:
        labels["number"] = "Nº documento"
    return labels
