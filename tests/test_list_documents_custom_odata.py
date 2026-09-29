from __future__ import annotations

from datetime import date
from pathlib import Path

from agentebc.document_types import DocumentTypeRegistry

from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.list_documents import list_documents_for_job


class CaptureClient:
    def __init__(self) -> None:
        self.last_endpoint = ""

    def get(self, endpoint: str):
        self.last_endpoint = endpoint
        return {
            "value": [
                {
                    "No": "FV-001",
                    "Posting_Date": "2026-09-15",
                    "N_x00BA__Contrato": "C-99",
                }
            ]
        }


def test_custom_odata_service_skips_catalog_document_type_filter() -> None:
    document_types_file = Path(__file__).resolve().parents[1] / "config" / "document_types.json"
    registry = DocumentTypeRegistry(document_types_file)
    definition = registry.get("sales_invoice")
    spec = WorkerJobSpec.from_dict(
        {
            "company": "Malla Publicidad",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "odata_service": "FacturaVenta",
            "odata_key_field": "No",
            "date_filter": {"field": "Posting_Date", "dynamic": "current_month"},
            "extra_odata_filters": {"Esperar_Orden_Cliente": False},
            "report_odata_fields": {
                "number": "No",
                "contract": "N_x00BA__Contrato",
            },
            "limit": 10,
        }
    )
    client = CaptureClient()
    result = list_documents_for_job(
        client,
        definition,
        spec,
        reference_date=date(2026, 9, 28),
    )
    assert "documentType" not in client.last_endpoint
    assert "number" not in client.last_endpoint.split("$select=")[-1].split("&")[0]
    assert "No" in client.last_endpoint
    assert "FacturaVenta" in client.last_endpoint
    assert len(result.documents) == 1
    assert result.documents[0].number == "FV-001"
    extras = dict(result.documents[0].extra_fields)
    assert extras.get("contract") == "C-99"
