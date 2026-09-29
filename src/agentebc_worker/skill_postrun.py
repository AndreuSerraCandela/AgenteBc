from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from agentebc.config import Settings

from .batch_llm import add_per_invoice_ai_conclusions
from .batch_report import (
    SkillBatchReport,
    build_skill_batch_report,
    format_report_plain_text,
    save_batch_report,
)
from .mailer import SmtpSettings, send_plain_email
from .runner import BatchRunResult
from .skills import WorkerSkill


def finalize_skill_batch(
    settings: Settings,
    skill: WorkerSkill,
    result: BatchRunResult,
    *,
    reports_dir: Path,
    field_values_by_number: dict[str, dict[str, str]] | None = None,
    send_email: bool = True,
    run_llm: bool = True,
) -> SkillBatchReport:
    report = build_skill_batch_report(
        skill,
        result,
        field_values_by_number=field_values_by_number,
    )
    llm_error: str | None = None
    if run_llm:
        report, llm_error = add_per_invoice_ai_conclusions(settings, skill, report)
        has_ai = any(
            row.get("ai_conclusion")
            for row in report.rows
            if row.get("outcome") == "error"
        )
        if has_ai:
            report = replace(report, llm_summary=None)
        elif llm_error:
            report = replace(
                report,
                llm_summary=f"(Aviso IA: {llm_error})",
            )

    path = save_batch_report(report, reports_dir)
    report = replace(report, report_path=str(path))

    email_status = _maybe_send_email(
        report,
        send_email=send_email,
        dry_run=result.dry_run,
    )
    report = replace(report, email_status=email_status)
    path.write_text(report.to_json() + "\n", encoding="utf-8")
    return report


def _maybe_send_email(
    report: SkillBatchReport,
    *,
    send_email: bool,
    dry_run: bool,
) -> str:
    if not send_email:
        return "Correo no solicitado"
    if not report.notify_emails:
        return "Skill sin destinatarios de correo"
    if dry_run:
        return "Simulación: no se envía correo (solo registro real)"
    smtp = SmtpSettings.from_environment()
    if smtp is None:
        return "SMTP no configurado (AGENTEBC_SMTP_HOST / FROM)"
    ok = report.totals.get("success", 0)
    err = report.totals.get("error", 0)
    subject = (
        f"[AgenteBc Worker] {report.skill_label} — "
        f"{ok} OK, {err} error(es)"
    )
    body = format_report_plain_text(report)
    try:
        send_plain_email(
            smtp=smtp,
            recipients=report.notify_emails,
            subject=subject,
            body=body,
        )
    except Exception as exc:
        return f"Error al enviar correo: {exc}"
    return f"Enviado a {', '.join(report.notify_emails)}"


def postrun_summary(report: SkillBatchReport) -> str:
    parts = [
        f"Informe guardado: {report.report_path}",
        f"Errores: {report.totals.get('error', 0)}",
    ]
    if any(row.get("ai_conclusion") for row in report.rows):
        parts.append("Conclusiones IA en facturas con error.")
    elif report.llm_summary:
        parts.append("Aviso IA en informe.")
    if report.email_status:
        parts.append(report.email_status)
    return " · ".join(parts)


def field_map_from_listing(documents) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for doc in documents:
        mapping[doc.number] = dict(doc.extra_fields)
    return mapping
