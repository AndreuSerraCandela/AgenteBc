from __future__ import annotations

from dataclasses import replace
from typing import Any

from agentebc.config import Settings
from agentebc.diagnosis import build_diagnostic_service
from agentebc.documents import DocumentReference
from agentebc.license_catalog import ExtensionCatalog
from agentebc.llm_conclusions import build_conclusion_prompt
from agentebc.models import DiagnosticReport, Incident
from agentebc.web_preview import PreviewMessage, primary_preview_message

from .batch_report import SkillBatchReport
from .error_reporting import format_error_detail_text, preview_message_from_dict
from .skills import WorkerSkill
from .worker_ai import build_worker_llm_client, worker_ai_enabled

_SYSTEM = (
    "Eres un consultor experto en Microsoft Dynamics 365 Business Central. "
    "Responde de forma práctica y concreta en español."
)

def add_per_invoice_ai_conclusions(
    settings: Settings,
    skill: WorkerSkill,
    report: SkillBatchReport,
) -> tuple[SkillBatchReport, str | None]:
    """Una llamada IA por cada factura con error. Devuelve (informe, error_global)."""
    if not worker_ai_enabled(settings):
        return report, (
            "IA del worker no configurada. Use AGENTEBC_WORKER_AI_PROVIDER=lm_studio "
            "y AGENTEBC_WORKER_LM_STUDIO_URL (o AGENTEBC_LM_STUDIO_URL)."
        )
    try:
        client = build_worker_llm_client(settings)
    except ValueError as exc:
        return report, str(exc)

    catalog = _extension_catalog(settings)
    diagnostic_service = build_diagnostic_service(settings, catalog)
    case_label = f"{skill.label} ({skill.id})"
    new_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for row in report.rows:
        outcome = str(row.get("outcome") or "")
        if outcome != "error":
            new_rows.append(dict(row))
            continue
        number = str(row.get("number") or "?")
        try:
            text = _conclude_single_row(
                client,
                diagnostic_service=diagnostic_service,
                skill=skill,
                case_label=case_label,
                row=row,
            )
            updated = dict(row)
            updated["ai_conclusion"] = text
            new_rows.append(updated)
        except Exception as exc:
            errors.append(f"{number}: {exc}")
            updated = dict(row)
            updated["ai_conclusion"] = f"(IA no disponible para esta factura: {exc})"
            new_rows.append(updated)

    global_error = "; ".join(errors) if errors else None
    return replace(report, rows=tuple(new_rows)), global_error


def _conclude_single_row(
    client,
    *,
    diagnostic_service,
    skill: WorkerSkill,
    case_label: str,
    row: dict[str, Any],
) -> str:
    number = str(row.get("number") or "")
    company = skill.spec.company

    document = DocumentReference(
        company=company,
        kind=skill.spec.type_id,
        number=number,
        document_type="",
        status="",
        system_id="",
        posting_date=None,
        extra_fields=(),
    )

    detail = row.get("error_detail")
    message = _primary_message_from_row(row, detail)
    incident = Incident(
        error_text=message.description,
        document_number=number,
        company=company,
        call_stack=message.call_stack,
        metadata={
            "document_kind": skill.spec.type_id,
            "context": message.context,
            "context_field": message.context_field,
            "source": message.source,
            "source_field": message.source_field,
            "error_detail_text": format_error_detail_text(detail),
        },
    )
    try:
        diagnosis = diagnostic_service.diagnose(incident)
    except Exception:
        diagnosis = _fallback_diagnosis(incident)

    user_prompt = build_conclusion_prompt(
        case_label=f"{case_label} — {number}",
        document=document,
        message=message,
        diagnosis=diagnosis,
        enrichments=(),
    )
    extra_block = format_error_detail_text(detail)
    if extra_block:
        user_prompt = (
            f"{user_prompt}\n\n"
            "## Detalle completo capturado en BC (worker)\n"
            f"{extra_block}\n"
        )
    return client.complete(user_prompt, _SYSTEM).strip()


def _primary_message_from_row(
    row: dict[str, Any],
    detail: dict[str, Any] | None,
) -> PreviewMessage:
    messages_raw = []
    if isinstance(detail, dict):
        messages_raw = detail.get("messages") or []
    parsed = [
        preview_message_from_dict(item)
        for item in messages_raw
        if isinstance(item, dict)
    ]
    if parsed:
        return primary_preview_message(tuple(parsed))
    description = str(row.get("error") or "Error de registro sin detalle")
    return PreviewMessage(
        message_type="worker",
        description=description,
        context=None,
        context_field=None,
        source=None,
        source_field=None,
        additional_information=format_error_detail_text(detail) or None,
        call_stack=None,
    )


def _fallback_diagnosis(incident: Incident) -> DiagnosticReport:
    return DiagnosticReport(
        incident=incident,
        summary=(
            "Diagnóstico automático de código no disponible en este informe; "
            "use el error de BC y la pila de llamadas."
        ),
        confidence="baja",
        evidence=(),
        source_matches=(),
        proposed_solutions=(),
        limitations=("Informe generado por worker en lote",),
    )


def _extension_catalog(settings: Settings) -> ExtensionCatalog | None:
    if settings.source_path is None or not settings.license_client:
        return None
    return ExtensionCatalog(
        settings.source_path,
        license_url=settings.license_url,
        license_token=settings.license_token,
        license_client=settings.license_client,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
