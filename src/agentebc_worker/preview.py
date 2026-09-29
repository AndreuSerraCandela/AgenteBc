from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from agentebc.bc_client import BusinessCentralReadClient, BusinessCentralReadError
from agentebc.document_types import DocumentTypeDefinition, DocumentTypeRegistry

from .dynamic_filters import resolve_dynamic_filter
from .job_spec import (
    WorkerJobSpec,
    resolve_date_filter,
    resolve_odata_key_field,
    resolve_odata_service,
    uses_custom_odata_service,
)
from .list_documents import list_documents_for_job


@dataclass(frozen=True, slots=True)
class JobPreview:
    spec: WorkerJobSpec
    type_label: str
    action_label: str
    resolved_dates: dict[str, str | None] | None
    document_count: int | None
    sample_numbers: tuple[str, ...]
    truncated: bool
    odata_list_error: str | None
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.as_dict(),
            "type_label": self.type_label,
            "action_label": self.action_label,
            "resolved_dates": self.resolved_dates,
            "document_count": self.document_count,
            "sample_numbers": list(self.sample_numbers),
            "truncated": self.truncated,
            "odata_list_error": self.odata_list_error,
            "summary": self.summary,
        }


def build_job_preview(
    registry: DocumentTypeRegistry,
    spec: WorkerJobSpec,
    *,
    client: BusinessCentralReadClient | None = None,
    reference_date: date | None = None,
    sample_size: int = 10,
) -> JobPreview:
    spec.validate_against_registry(registry)
    definition = registry.get(spec.type_id)
    action = definition.action(spec.action_id)

    resolved_dates = None
    if spec.date_filter:
        if spec.date_filter.dynamic:
            resolved = resolve_dynamic_filter(
                spec.date_filter.dynamic,
                reference=reference_date,
            )
            resolved_dates = resolved.as_dict()
        else:
            date_from, date_to = resolve_date_filter(
                spec.date_filter,
                reference=reference_date,
            )
            resolved_dates = {
                "dynamic": None,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            }

    document_count: int | None = None
    sample_numbers: tuple[str, ...] = ()
    truncated = False
    odata_error: str | None = None

    if client is not None:
        try:
            listing = list_documents_for_job(
                client,
                definition,
                spec,
                reference_date=reference_date,
            )
            document_count = len(listing.documents)
            truncated = listing.truncated
            sample_numbers = tuple(
                doc.number for doc in listing.documents[:sample_size]
            )
        except (BusinessCentralReadError, ValueError, RuntimeError) as exc:
            odata_error = str(exc)

    summary = _format_summary(
        definition=definition,
        action_label=action.label,
        spec=spec,
        resolved_dates=resolved_dates,
        document_count=document_count,
        truncated=truncated,
        odata_error=odata_error,
    )

    return JobPreview(
        spec=spec,
        type_label=definition.label,
        action_label=action.label,
        resolved_dates=resolved_dates,
        document_count=document_count,
        sample_numbers=sample_numbers,
        truncated=truncated,
        odata_list_error=odata_error,
        summary=summary,
    )


def _format_summary(
    *,
    definition: DocumentTypeDefinition,
    action_label: str,
    spec: WorkerJobSpec,
    resolved_dates: dict[str, str | None] | None,
    document_count: int | None,
    truncated: bool,
    odata_error: str | None,
) -> str:
    odata_service = resolve_odata_service(spec, definition)
    lines = [
        f"Empresa: {spec.company}",
        f"Tipo: {definition.label} ({spec.type_id})",
        f"Servicio OData: {odata_service}",
    ]
    if uses_custom_odata_service(spec, definition):
        lines.append(
            f"Campo clave OData: {resolve_odata_key_field(spec, definition)}"
        )
    lines.extend([
        f"Acción: {action_label} ({spec.action_id})",
        f"Modo: {'solo simulación (dry_run)' if spec.dry_run else 'ejecución real'}",
        f"Límite: {spec.limit} documentos",
    ])
    if resolved_dates:
        dynamic = resolved_dates.get("dynamic")
        if dynamic:
            lines.append(
                f"Fechas ({spec.date_filter.field if spec.date_filter else '?'}): "
                f"filtro dinámico «{dynamic}» → "
                f"{resolved_dates['from']} … {resolved_dates['to']}"
            )
        else:
            lines.append(
                f"Fechas ({spec.date_filter.field if spec.date_filter else '?'}): "
                f"{resolved_dates['from']} … {resolved_dates['to']}"
            )
    if odata_error:
        lines.append(f"Listado OData: no disponible ({odata_error})")
    elif document_count is not None:
        suffix = " (hay más; aumente limit o acote filtros)" if truncated else ""
        lines.append(f"Documentos que coinciden: {document_count}{suffix}")
        if document_count == 0:
            lines.append("Revise empresa, fechas y filtros antes de confirmar.")
    else:
        lines.append("Listado OData: no consultado (sin cliente BC).")
    return "\n".join(lines)
