from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agentebc.document_types import DocumentTypeRegistry

from agentebc_worker.dynamic_filters import resolve_dynamic_filter
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.presets import PresetStore, WorkerPreset, merge_preset_with_company
from agentebc_worker.natural_language import compile_phrase
from agentebc_worker.preview import build_job_preview


def test_resolve_current_month() -> None:
    resolved = resolve_dynamic_filter("current_month", reference=date(2026, 9, 15))
    assert resolved.date_from == date(2026, 9, 1)
    assert resolved.date_to == date(2026, 9, 30)


def test_resolve_current_year() -> None:
    resolved = resolve_dynamic_filter("current_year", reference=date(2026, 9, 15))
    assert resolved.date_from == date(2026, 1, 1)
    assert resolved.date_to == date(2026, 12, 31)


def test_job_spec_dynamic_date_validation(
    document_types_file: Path,
) -> None:
    registry = DocumentTypeRegistry(document_types_file)
    spec = WorkerJobSpec.from_dict(
        {
            "company": "CRONUS",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "date_filter": {"field": "posting_date", "dynamic": "current_month"},
        }
    )
    spec.validate_against_registry(registry)
    preview = build_job_preview(
        registry,
        spec,
        client=None,
        reference_date=date(2026, 9, 1),
    )
    assert preview.document_count is None
    assert "2026-09-01" in preview.summary
    assert preview.resolved_dates is not None
    assert preview.resolved_dates["dynamic"] == "current_month"


def test_bundled_presets_merge(tmp_path: Path, document_types_file: Path) -> None:
    bundled = tmp_path / "bundled.json"
    bundled.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "id": "demo_month",
                        "label": "Demo mes",
                        "spec": {
                            "type_id": "sales_invoice",
                            "action_id": "registrar_factura",
                            "date_filter": {
                                "field": "posting_date",
                                "dynamic": "current_month",
                            },
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    user_file = tmp_path / "user.json"
    store = PresetStore(user_file, bundled=bundled)
    presets = store.all()
    assert len(presets) == 1
    spec = merge_preset_with_company(presets[0], "Malla Publicidad")
    assert spec.company == "Malla Publicidad"
    assert spec.type_id == "sales_invoice"


def test_save_preset_strips_company(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "presets.json")
    spec = WorkerJobSpec.from_dict(
        {
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "date_filter": {"field": "posting_date", "dynamic": "current_year"},
        },
        require_company=False,
    )
    preset = WorkerPreset(id="saved_year", label="Ventas año", spec=spec)
    store.save(preset)
    loaded = store.get("saved_year")
    assert loaded.spec.as_dict().get("company") in ("", None)


def test_compile_phrase_rules_september(document_types_file: Path) -> None:
    registry = DocumentTypeRegistry(document_types_file)
    companies = ("Malla Publicidad", "CRONUS")
    result = compile_phrase(
        "Registrar las facturas de venta de Malla Publicidad de septiembre de 2026",
        registry,
        companies=companies,
        reference_date=date(2026, 9, 28),
    )
    assert result.method == "rules"
    assert result.spec.company == "Malla Publicidad"
    assert result.spec.type_id == "sales_invoice"
    assert result.spec.action_id == "registrar_factura"
    assert result.spec.date_filter is not None
    assert result.spec.date_filter.date_from == date(2026, 9, 1)
    assert result.spec.date_filter.date_to == date(2026, 9, 30)


def test_compile_phrase_mentions(document_types_file: Path) -> None:
    registry = DocumentTypeRegistry(document_types_file)
    result = compile_phrase(
        "@registrar_factura @sales_invoice mes en curso",
        registry,
        companies=("CRONUS",),
        settings=None,
        reference_date=date(2026, 3, 10),
    )
    assert result.spec.type_id == "sales_invoice"
    assert result.spec.action_id == "registrar_factura"
    assert result.spec.date_filter is not None
    assert result.spec.date_filter.dynamic == "current_month"


@pytest.fixture
def document_types_file() -> Path:
    root = Path(__file__).resolve().parents[1]
    path = root / "config" / "document_types.json"
    if not path.is_file():
        pytest.skip("config/document_types.json no disponible")
    return path
