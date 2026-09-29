from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentebc.config import Settings
from agentebc.document_types import DocumentTypeRegistry
from agentebc.web_preview import PreviewActionStalledError, PreviewResult
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.runner import run_job


@dataclass
class _FakePreview:
    calls: list[str]

    def run(self, document, definition, action) -> PreviewResult:
        self.calls.append(document.number)
        if len(self.calls) == 1:
            raise PreviewActionStalledError("sin respuesta")
        return PreviewResult(
            outcome="completed",
            title="",
            messages=(),
            raw_rows=(),
            screenshot_path=Path("x.png"),
        )


def test_retries_same_document_on_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_types_file = (
        Path(__file__).resolve().parents[1] / "config" / "document_types.json"
    )
    registry = DocumentTypeRegistry(document_types_file)
    spec = WorkerJobSpec.from_dict(
        {
            "company": "CRONUS",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "odata_service": "FacturaVenta",
            "odata_key_field": "No",
            "limit": 1,
            "dry_run": False,
        }
    )
    fake = _FakePreview(calls=[])
    monkeypatch.setattr(
        "agentebc_worker.runner.BusinessCentralWebPreview",
        lambda *a, **k: fake,
    )
    monkeypatch.setattr(
        "agentebc_worker.runner.build_job_preview",
        lambda *a, **k: MagicMock(
            document_count=1,
            summary="test",
            odata_list_error=None,
        ),
    )
    doc = MagicMock(number="INV001", extra_fields={})
    monkeypatch.setattr(
        "agentebc_worker.runner.list_documents_for_job",
        lambda *a, **k: MagicMock(documents=(doc,)),
    )
    monkeypatch.setattr(
        "agentebc_worker.runner._confirm_removed_from_pending_list",
        lambda *a, **k: len(fake.calls) >= 2,
    )
    monkeypatch.setattr(
        "agentebc_worker.runner.is_registered_for_posting_job",
        lambda *a, **k: len(fake.calls) >= 2,
    )
    settings = MagicMock(spec=Settings)
    settings.web_action_max_attempts = 2

    result = run_job(settings, registry, spec)

    assert fake.calls == ["INV001", "INV001"]
    assert len(result.outcomes) == 1
    assert result.outcomes[0].outcome == "success"
    assert result.outcomes[0].attempts == 2


def test_false_web_success_still_in_odata_retries_then_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_types_file = (
        Path(__file__).resolve().parents[1] / "config" / "document_types.json"
    )
    registry = DocumentTypeRegistry(document_types_file)
    spec = WorkerJobSpec.from_dict(
        {
            "company": "CRONUS",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "odata_service": "FacturaVenta",
            "odata_key_field": "No",
            "limit": 1,
            "dry_run": False,
        }
    )

    class _AlwaysCompleted:
        def run(self, document, definition, action) -> PreviewResult:
            return PreviewResult(
                outcome="completed",
                title="",
                messages=(),
                raw_rows=(),
                screenshot_path=Path("x.png"),
            )

    monkeypatch.setattr(
        "agentebc_worker.runner.BusinessCentralWebPreview",
        lambda *a, **k: _AlwaysCompleted(),
    )
    monkeypatch.setattr(
        "agentebc_worker.runner.build_job_preview",
        lambda *a, **k: MagicMock(
            document_count=1,
            summary="test",
            odata_list_error=None,
        ),
    )
    doc = MagicMock(number="ML257397", extra_fields={})
    monkeypatch.setattr(
        "agentebc_worker.runner.list_documents_for_job",
        lambda *a, **k: MagicMock(documents=(doc,)),
    )
    monkeypatch.setattr(
        "agentebc_worker.runner._confirm_removed_from_pending_list",
        lambda *a, **k: False,
    )
    def _not_registered(*_a, **_k) -> bool:
        return False

    monkeypatch.setattr(
        "agentebc_worker.runner.is_registered_for_posting_job",
        _not_registered,
    )
    monkeypatch.setattr(
        "agentebc_worker.odata_posting.is_registered_for_posting_job",
        _not_registered,
    )
    settings = MagicMock(spec=Settings)
    settings.web_action_max_attempts = 2

    result = run_job(settings, registry, spec)

    assert len(result.outcomes) == 1
    assert result.outcomes[0].outcome == "error"
    assert result.outcomes[0].number == "ML257397"
    assert "OData" in (result.outcomes[0].error or "")
    assert result.outcomes[0].attempts == 2
