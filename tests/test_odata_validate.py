from datetime import date

from agentebc.document_types import DocumentTypeDefinition
from agentebc.documents import DocumentReference
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.odata_validate import (
    build_validation_request,
    errors_by_document,
    _value_for_bc,
)


def _definition() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.from_dict(
        {
            "id": "sales_invoice",
            "label": "Factura de venta",
            "page_id": 43,
            "source_table": "Sales Header",
            "odata_service": "salesDocuments",
            "odata_key_field": "number",
            "page_filters": {"Document Type": "Invoice"},
        }
    )


def _spec(**extra: object) -> WorkerJobSpec:
    payload = {
        "company": "Malla Publicidad",
        "type_id": "sales_invoice",
        "action_id": "registrar_factura",
        "before_action_field_edits": [
            {"field_label": "Fecha registro", "value": "today"}
        ],
        "validate_via_odata": True,
    }
    payload.update(extra)
    return WorkerJobSpec.from_dict(payload)


def test_build_validation_request_uses_table_and_keys() -> None:
    document = DocumentReference(
        company="Malla Publicidad",
        kind="sales_invoice",
        number="ML268669",
        document_type="Invoice",
        status="",
        system_id="",
        posting_date=None,
    )
    request = build_validation_request(
        _definition(),
        _spec(),
        (document,),
        reference_date=date(2026, 11, 18),
    )
    record = request["records"][0]
    assert record["id"] == "ML268669"
    assert record["tableName"] == "Sales Header"
    assert {"name": "No.", "value": "ML268669"} in record["keys"]
    assert record["fields"] == [
        {"caption": "Fecha registro", "value": "2026-11-18"}
    ]


def test_errors_by_document_groups_messages() -> None:
    grouped = errors_by_document(
        {
            "errors": [
                {
                    "id": "ML1",
                    "field": "Fecha registro",
                    "message": "fecha no permitida",
                }
            ]
        }
    )
    assert "fecha no permitida" in grouped["ML1"]
    assert grouped["ML1"].startswith("Validación OData:")


def test_validate_flag_defaults_false() -> None:
    spec = WorkerJobSpec.from_dict(
        {
            "company": "A",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
        }
    )
    assert spec.validate_via_odata is False


def test_bc_date_becomes_iso() -> None:
    assert _value_for_bc("18/11/2026") == "2026-11-18"
