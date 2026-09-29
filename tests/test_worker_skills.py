from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from agentebc_worker.dynamic_filters import resolve_dynamic_filter
from agentebc_worker.list_documents import _odata_equals
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.skills import (
    SkillReport,
    SkillReportField,
    SkillStore,
    WorkerSkill,
    parse_email_list,
    parse_report_fields_lines,
    skill_from_builder_form,
)


def test_month_to_today_filter() -> None:
    resolved = resolve_dynamic_filter("month_to_today", reference=date(2026, 9, 28))
    assert resolved.date_from == date(2026, 9, 1)
    assert resolved.date_to == date(2026, 9, 28)


def test_odata_equals_boolean() -> None:
    assert _odata_equals("esperarOrdenCliente", False) == "esperarOrdenCliente eq false"


def test_parse_report_fields_lines() -> None:
    fields = parse_report_fields_lines(
        "Nº contrato | contract | N_x00BA__Contrato\nCliente | customerName"
    )
    keys = [f.key for f in fields]
    assert keys[0] == "number"
    assert "contract" in keys
    assert any(f.odata == "customerName" for f in fields)


def test_skill_form_report_fields_not_only_contract() -> None:
    class Form:
        def get(self, name, default=""):
            data = {
                "label": "Test",
                "skill_id": "test_skill",
                "company": "CRONUS",
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
                "date_dynamic": "current_month",
                "odata_service": "FacturaVenta",
                "document_key_odata": "No",
                "date_odata_field": "Posting_Date",
                "report_fields_lines": "Nº contrato | contract | N_x00BA__Contrato",
                "extra_filter_lines": "Esperar_Orden_Cliente | No",
                "limit": "10",
            }
            return data.get(name, default)

        def getlist(self, name):
            return []

    skill = skill_from_builder_form(Form())
    assert skill.spec.odata_service == "FacturaVenta"
    assert skill.spec.odata_key_field == "No"
    assert skill.spec.date_filter is not None
    assert skill.spec.date_filter.field == "Posting_Date"
    assert skill.report_odata_fields().get("number") == "No"
    assert skill.report_odata_fields().get("contract") == "N_x00BA__Contrato"
    assert skill.spec.extra_odata_filters["Esperar_Orden_Cliente"] == "No"


def test_report_odata_fields_omits_after_action_only_columns() -> None:
    skill = WorkerSkill(
        id="t",
        label="T",
        spec=WorkerJobSpec.from_dict(
            {
                "company": "C",
                "type_id": "sales_invoice",
                "action_id": "registrar_factura",
                "limit": 1,
            }
        ),
        report=SkillReport(
            fields=(
                SkillReportField(key="number", label="Nº", odata="No"),
                SkillReportField(
                    key="no_factura_registrada",
                    label="Nº registrada",
                    odata=None,
                ),
            )
        ),
    )
    mapping = skill.report_odata_fields()
    assert "no_factura_registrada" not in mapping
    assert mapping.get("number") == "No"


def test_parse_email_list() -> None:
    emails = parse_email_list("a@x.es; b@y.es, c@z.es")
    assert emails == ("a@x.es", "b@y.es", "c@z.es")


def test_load_malla_skill_from_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    bundled = root / "config" / "skills"
    store = SkillStore(root / "tests" / "_unused_skills_user", bundled_dirs=(bundled,))
    skill = store.get("malla_publicidad_facturar_ventas")
    assert skill.spec.company == "Malla Publicidad"
    assert skill.spec.extra_odata_filters.get("esperarOrdenCliente") is False
    assert skill.spec.date_filter is not None
    assert skill.spec.date_filter.dynamic == "month_to_today"
    spec = skill.to_job_spec()
    assert spec.report_odata_fields.get("contract") == "contractNo"
    assert "andreuserra@malla.es" in skill.report.notify_emails


def test_skill_store_save_roundtrip(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    bundled = root / "config" / "skills"
    user = tmp_path / "skills"
    store = SkillStore(user, bundled_dirs=(bundled,))
    skill = store.get("malla_publicidad_facturar_ventas")
    saved = store.save(skill)
    reloaded = WorkerSkill.from_dict(json.loads(saved.read_text(encoding="utf-8")))
    assert reloaded.id == skill.id
    assert reloaded.spec.company == skill.spec.company
