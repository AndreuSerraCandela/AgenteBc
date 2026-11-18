"""Valida cambios de ficha con InformesPyTableReader_ValidateChanges. No registra."""
from __future__ import annotations

import json
import re
from datetime import date

from agentebc.bc_client import BusinessCentralReadClient, BusinessCentralReadError
from agentebc.document_types import DocumentTypeDefinition
from agentebc.documents import DocumentReference, bc_urlencode

from .field_edits import resolve_before_action_field_edits
from .job_spec import WorkerJobSpec

_SERVICE = "InformesPyTableReader"
_ACTION = "ValidateChanges"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BC_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def validation_errors_for_job(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    documents: tuple[DocumentReference, ...],
    *,
    reference_date: date | None = None,
) -> dict[str, str]:
    """Número de documento → texto de error. Vacío si no hay nada que validar."""
    if not spec.validate_via_odata or not spec.before_action_field_edits:
        return {}
    if not documents:
        return {}
    payload = build_validation_request(
        definition,
        spec,
        documents,
        reference_date=reference_date,
    )
    response = invoke_validate_changes(client, spec.company, payload)
    return errors_by_document(response)


def build_validation_request(
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    documents: tuple[DocumentReference, ...],
    *,
    reference_date: date | None = None,
) -> dict[str, object]:
    edits = resolve_before_action_field_edits(spec, reference_date=reference_date)
    fields = [
        {"caption": step.field_label, "value": _value_for_bc(step.value)}
        for step in edits
    ]
    records = []
    for document in documents:
        keys = [
            {"caption": caption, "value": value}
            for caption, value in definition.page_filters.items()
        ]
        keys.append({"name": "No.", "value": document.number})
        records.append(
            {
                "id": document.number,
                "tableName": definition.source_table,
                "company": spec.company,
                "keys": keys,
                "fields": fields,
            }
        )
    return {"records": records}


def invoke_validate_changes(
    client: BusinessCentralReadClient,
    company: str,
    request: dict[str, object],
) -> dict[str, object]:
    query = bc_urlencode({"company": company})
    endpoint = f"{_SERVICE}_{_ACTION}?{query}"
    try:
        raw = client.post_json(
            endpoint,
            {"jsonText": json.dumps(request, ensure_ascii=False)},
        )
    except BusinessCentralReadError as exc:
        raise BusinessCentralReadError(
            f"{exc}. Publique la codeunit InformesPy Table Reader "
            f"como servicio OData {_SERVICE} con la acción {_ACTION}."
        ) from exc
    parsed = _unwrap_odata_text(raw)
    if not isinstance(parsed, dict):
        raise BusinessCentralReadError("ValidateChanges no devolvió un objeto JSON")
    return parsed


def errors_by_document(response: dict[str, object]) -> dict[str, str]:
    raw_errors = response.get("errors") or []
    if not isinstance(raw_errors, list):
        return {}
    grouped: dict[str, list[str]] = {}
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        number = str(item.get("id") or "").strip()
        field = str(item.get("field") or "").strip()
        message = str(item.get("message") or "").strip()
        if not number or not message:
            continue
        text = f"{field}: {message}" if field else message
        grouped.setdefault(number, []).append(text)
    return {
        number: "Validación OData: " + " | ".join(parts)
        for number, parts in grouped.items()
    }


def _unwrap_odata_text(data: object) -> object:
    if isinstance(data, dict) and isinstance(data.get("value"), str):
        raw = str(data["value"]).strip()
        if raw.startswith("{") or raw.startswith("["):
            return json.loads(raw)
    return data


def _value_for_bc(value: str) -> str:
    match = _BC_DATE.match(value.strip())
    if match and not _ISO_DATE.match(value.strip()):
        day, month, year = match.groups()
        return f"{year}-{month}-{day}"
    return value.strip()
