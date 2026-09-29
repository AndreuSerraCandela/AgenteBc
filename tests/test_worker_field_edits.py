from __future__ import annotations

from datetime import date
from pathlib import Path

from agentebc.document_types import DocumentTypeRegistry
from agentebc_worker.field_edits import (
    materialize_action_for_job,
    resolve_field_edit_value,
)
from agentebc_worker.job_spec import WorkerJobSpec


def test_resolve_posting_date_today() -> None:
    assert resolve_field_edit_value("today", reference=date(2026, 9, 28)) == "28/09/2026"


def test_resolve_posting_date_end_of_month() -> None:
    assert (
        resolve_field_edit_value("end_of_month", reference=date(2026, 9, 5))
        == "30/09/2026"
    )


def test_materialize_action_adds_skill_field_edits() -> None:
    registry = DocumentTypeRegistry(
        Path(__file__).resolve().parents[1] / "config" / "document_types.json",
    )
    definition = registry.get("sales_invoice")
    spec = WorkerJobSpec.from_dict(
        {
            "company": "X",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "before_action_field_edits": [
                {"field_label": "Fecha registro", "value": "today"},
            ],
        }
    )
    action = materialize_action_for_job(
        definition,
        spec,
        reference_date=date(2026, 9, 28),
    )
    assert len(action.field_edits) == 1
    assert action.field_edits[0].field_label == "Fecha registro"
    assert action.field_edits[0].value == "28/09/2026"
