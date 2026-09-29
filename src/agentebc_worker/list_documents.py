from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from agentebc.bc_client import BusinessCentralReadClient
from agentebc.documents import bc_urlencode
from agentebc.document_types import DocumentTypeDefinition
from agentebc.documents import DocumentReference, _odata_literal

from .job_spec import (
    WorkerJobSpec,
    odata_date_field,
    resolve_date_filter,
    resolve_odata_key_field,
    resolve_odata_service,
    uses_custom_odata_service,
)

_ODATA_POSTING_STATUS_FIELD = "Status"
_ODATA_POSTING_NO_FIELD = "Posting_No"


@dataclass(frozen=True, slots=True)
class DocumentListResult:
    documents: tuple[DocumentReference, ...]
    truncated: bool


def list_documents_for_job(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    *,
    reference_date: date | None = None,
) -> DocumentListResult:
    service = resolve_odata_service(spec, definition)
    custom_service = uses_custom_odata_service(spec, definition)
    key_field = resolve_odata_key_field(spec, definition)

    filters: list[str] = []
    if not custom_service:
        filters.extend(
            f"{field} eq {_odata_literal(value)}"
            for field, value in definition.odata_filters.items()
        )
    filters.extend(
        _odata_equals(field, value)
        for field, value in spec.extra_odata_filters.items()
    )
    if spec.date_filter:
        odata_field = odata_date_field(
            definition,
            spec.date_filter,
            custom_odata_service=custom_service,
        )
        date_from, date_to = resolve_date_filter(
            spec.date_filter,
            reference=reference_date,
        )
        filters.append(f"{odata_field} ge {_odata_date_literal(date_from)}")
        filters.append(f"{odata_field} le {_odata_date_literal(date_to)}")

    if custom_service:
        selected_fields: set[str] = {key_field}
        if spec.date_filter:
            selected_fields.add(
                odata_date_field(
                    definition,
                    spec.date_filter,
                    custom_odata_service=True,
                )
            )
        for odata_name in spec.report_odata_fields.values():
            if odata_name == "number" and key_field != "number":
                continue
            selected_fields.add(odata_name)
        selected_fields.update(spec.extra_odata_filters.keys())
    else:
        selected_fields = set(definition.odata_select_fields.values())
        selected_fields.add(key_field)
        selected_fields.update(spec.report_odata_fields.values())
    parts = [
        ("company", spec.company),
        ("$select", ",".join(sorted(selected_fields))),
        ("$orderby", f"{key_field} asc"),
        ("$top", str(spec.limit + 1)),
    ]
    if filters:
        parts.insert(1, ("$filter", " and ".join(filters)))
    query = bc_urlencode(dict(parts))

    data = client.get(f"{service}?{query}")
    rows = data.get("value", []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        rows = []

    truncated = len(rows) > spec.limit
    rows = rows[: spec.limit]
    fields = definition.odata_select_fields

    def row_value(row: dict[str, object], name: str, default: str = "") -> str:
        field_name = fields.get(name)
        raw = row.get(field_name) if field_name else None
        if raw is None:
            raw = row.get(name)
        return str(raw) if raw is not None else default

    date_odata = (
        odata_date_field(
            definition,
            spec.date_filter,
            custom_odata_service=custom_service,
        )
        if spec.date_filter
        else None
    )

    documents = tuple(
        DocumentReference(
            company=spec.company,
            kind=definition.id,
            number=str(row.get(key_field, "") or ""),
            document_type=row_value(row, "document_type"),
            status=row_value(row, "status"),
            system_id=row_value(row, "system_id"),
            posting_date=(
                str(row.get(date_odata, "")) if date_odata and row.get(date_odata) is not None
                else row_value(row, "posting_date") or None
            ),
            extra_fields=_report_extra_fields(row, spec.report_odata_fields, key_field),
        )
        for row in rows
        if isinstance(row, dict)
    )
    return DocumentListResult(documents=documents, truncated=truncated)


def document_still_listed_for_job(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    number: str,
    *,
    reference_date: date | None = None,
) -> bool:
    """True si el número sigue apareciendo con los mismos filtros OData del job."""
    service = resolve_odata_service(spec, definition)
    custom_service = uses_custom_odata_service(spec, definition)
    key_field = resolve_odata_key_field(spec, definition)

    filters: list[str] = []
    if not custom_service:
        filters.extend(
            f"{field} eq {_odata_literal(value)}"
            for field, value in definition.odata_filters.items()
        )
    filters.extend(
        _odata_equals(field, value)
        for field, value in spec.extra_odata_filters.items()
    )
    if spec.date_filter:
        odata_field = odata_date_field(
            definition,
            spec.date_filter,
            custom_odata_service=custom_service,
        )
        date_from, date_to = resolve_date_filter(
            spec.date_filter,
            reference=reference_date,
        )
        filters.append(f"{odata_field} ge {_odata_date_literal(date_from)}")
        filters.append(f"{odata_field} le {_odata_date_literal(date_to)}")
    filters.append(f"{key_field} eq {_odata_literal(number)}")

    select_fields = {key_field}
    query = bc_urlencode(
        {
            "company": spec.company,
            "$filter": " and ".join(filters),
            "$select": ",".join(sorted(select_fields)),
            "$top": "1",
        }
    )
    data = client.get(f"{service}?{query}")
    rows = data.get("value", []) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        return False
    row = rows[0]
    if not isinstance(row, dict):
        return False
    return True


def _row_still_open_for_posting(row: dict[str, object]) -> bool:
    """Comprobación OData tras registrar: sigue en el servicio sin nº registro."""
    posting_no = str(row.get(_ODATA_POSTING_NO_FIELD, "") or "").strip()
    if posting_no:
        return False
    return True


def _odata_date_literal(value: date) -> str:
    return value.isoformat()


def _odata_equals(field: str, value: str | bool) -> str:
    if isinstance(value, bool):
        return f"{field} eq {str(value).lower()}"
    if value == "":
        return f"{field} eq ''"
    return f"{field} eq {_odata_literal(value)}"


def _report_extra_fields(
    row: dict[str, object],
    report_fields: dict[str, str],
    key_field: str,
) -> tuple[tuple[str, str], ...]:
    if not report_fields:
        return ()
    items: list[tuple[str, str]] = []
    for key, odata_name in report_fields.items():
        if key == "number" and odata_name in {key_field, "number"}:
            continue
        if odata_name == "number" and key_field != "number":
            continue
        raw = row.get(odata_name)
        if raw is not None:
            items.append((key, str(raw)))
    return tuple(items)
