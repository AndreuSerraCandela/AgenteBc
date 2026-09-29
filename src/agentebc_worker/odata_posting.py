"""Comprobación OData de facturas abiertas vs registradas (FacturaVenta)."""
from __future__ import annotations

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.document_types import DocumentTypeDefinition
from agentebc.documents import bc_urlencode, _odata_literal

from .after_action import evaluate_after_action_steps
from .job_spec import (
    WorkerJobSpec,
    resolve_odata_key_field,
    resolve_odata_service,
    uses_custom_odata_service,
)
from .list_documents import (
    _row_still_open_for_posting,
    document_still_listed_for_job,
)

POSTING_ACTION_IDS = frozenset({"registrar_factura", "registrar_factura_compra"})


def posting_action_requires_odata_check(
    spec: WorkerJobSpec,
    definition: DocumentTypeDefinition,
) -> bool:
    if spec.action_id in POSTING_ACTION_IDS:
        return True
    return uses_custom_odata_service(spec, definition)


def document_still_open_by_number(
    client: BusinessCentralReadClient,
    company: str,
    service: str,
    number: str,
    *,
    key_field: str = "No",
) -> bool:
    """True si el documento sigue en el servicio OData como borrador abierto."""
    query = bc_urlencode(
        {
            "company": company,
            "$filter": f"{key_field} eq {_odata_literal(number)}",
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
    return _row_still_open_for_posting(row)


def registration_check_for_posting_job(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    number: str,
) -> tuple[bool, dict[str, str]]:
    """(registrada, campos extra para informe desde pasos después de acción)."""
    if document_still_listed_for_job(client, definition, spec, number):
        return False, {}
    after = evaluate_after_action_steps(
        client,
        company=spec.company,
        steps=spec.after_action_steps,
        number=number,
    )
    if after.used_after_steps:
        return after.registered, dict(after.fields)
    if uses_custom_odata_service(spec, definition):
        return True, {}
    service = resolve_odata_service(spec, definition)
    key_field = resolve_odata_key_field(spec, definition)
    if document_still_open_by_number(
        client,
        spec.company,
        service,
        number,
        key_field=key_field,
    ):
        return False, {}
    return True, {}


def is_registered_for_posting_job(
    client: BusinessCentralReadClient,
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    number: str,
) -> bool:
    registered, _ = registration_check_for_posting_job(
        client,
        definition,
        spec,
        number,
    )
    return registered
