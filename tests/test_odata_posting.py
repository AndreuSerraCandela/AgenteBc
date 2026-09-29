from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agentebc.document_types import DocumentTypeRegistry
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.odata_posting import (
    is_registered_for_posting_job,
    posting_action_requires_odata_check,
)


def test_registrar_factura_requires_odata_check() -> None:
    registry = DocumentTypeRegistry(
        Path(__file__).resolve().parents[1] / "config" / "document_types.json",
    )
    definition = registry.get("sales_invoice")
    spec = WorkerJobSpec.from_dict(
        {
            "company": "X",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "limit": 1,
        }
    )
    assert posting_action_requires_odata_check(spec, definition)


def test_is_registered_when_not_open_by_number() -> None:
    registry = DocumentTypeRegistry(
        Path(__file__).resolve().parents[1] / "config" / "document_types.json",
    )
    definition = registry.get("sales_invoice")
    spec = WorkerJobSpec.from_dict(
        {
            "company": "Malla Publicidad",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "odata_service": "FacturaVenta",
            "odata_key_field": "No",
            "extra_odata_filters": {"Status": "Open"},
            "limit": 1,
        }
    )

    class Client:
        def get(self, endpoint: str):
            if "$filter" in endpoint and "Status eq 'Open'" in endpoint:
                return {"value": []}
            if "No eq 'ML1'" in endpoint:
                return {"value": []}
            return {"value": []}

    assert is_registered_for_posting_job(
        Client(),
        definition,
        spec,
        "ML1",
    )
