from __future__ import annotations

from pathlib import Path

from agentebc.document_types import DocumentTypeRegistry

from agentebc_worker.odata_fields import (
    list_odata_field_names,
    suggest_contract_fields,
    suggest_boolean_fields,
)


class FakeClient:
    def get(self, endpoint: str):
        assert "salesDocuments" in endpoint
        return {"value": [{"number": "X", "postingDate": "2026-01-01", "yourReference": "C1"}]}


def test_list_odata_field_names_from_sample_row() -> None:
    path = Path(__file__).resolve().parents[1] / "config" / "document_types.json"
    defn = DocumentTypeRegistry(path).get("sales_invoice")
    fields = list_odata_field_names(FakeClient(), defn, "CRONUS")
    assert "number" in fields
    assert "yourReference" in fields


def test_suggest_helpers() -> None:
    fields = ("number", "yourReference", "quoteNumber", "onHold")
    assert "yourReference" in suggest_contract_fields(fields)
    assert "onHold" in suggest_boolean_fields(fields)
