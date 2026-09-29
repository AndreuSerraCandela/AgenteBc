from __future__ import annotations

from pathlib import Path

from agentebc.document_types import DocumentTypeRegistry
from agentebc_worker.after_action import (
    AfterActionOdataQueryStep,
    evaluate_after_action_steps,
    resolve_template_value,
    validate_save_for_report_keys,
)
from agentebc_worker.batch_report import build_skill_batch_report
from agentebc_worker.job_spec import WorkerJobSpec
from agentebc_worker.odata_posting import is_registered_for_posting_job
from agentebc_worker.runner import BatchRunResult, DocumentRunOutcome
from agentebc_worker.skills import SkillReport, SkillReportField, WorkerSkill


def test_after_step_from_dict_aliases_field() -> None:
    step = AfterActionOdataQueryStep.from_dict(
        {
            "kind": "odata_query",
            "service": "FacturasRegistradas",
            "field": "Preassigned_No",
            "filter_value": "{number}",
            "extra_filters": {"Document_Type": "Invoice"},
        }
    )
    assert step is not None
    assert step.service == "FacturasRegistradas"
    assert step.filter_field == "Preassigned_No"


def test_legacy_odata_confirmation_migrates_to_after_steps() -> None:
    spec = WorkerJobSpec.from_dict(
        {
            "company": "X",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "limit": 1,
            "odata_confirmation": {
                "service": "FacturasRegistradas",
                "filter_field": "Preassigned_No",
            },
        }
    )
    assert len(spec.after_action_steps) == 1
    assert spec.after_action_steps[0].service == "FacturasRegistradas"


def test_resolve_template_value() -> None:
    assert resolve_template_value("{number}", number="ML99") == "ML99"
    assert resolve_template_value("X-{document_no}-Y", number="ML1") == "X-ML1-Y"


def test_evaluate_after_action_saves_report_field() -> None:
    step = AfterActionOdataQueryStep.from_dict(
        {
            "kind": "odata_query",
            "service": "FacturasRegistradas",
            "filter_field": "Preassigned_No",
            "save_for_report": {
                "odata_field": "No",
                "report_key": "posted_no",
            },
        }
    )
    assert step is not None

    class Client:
        def get(self, endpoint: str):
            if "FacturasRegistradas" in endpoint and "ML42" in endpoint:
                return {"value": [{"No": "FV-900"}]}
            return {"value": []}

    result = evaluate_after_action_steps(
        Client(),
        company="Malla Publicidad",
        steps=(step,),
        number="ML42",
    )
    assert result.registered is True
    assert result.fields == {"posted_no": "FV-900"}


def test_validate_report_key_must_exist() -> None:
    step = AfterActionOdataQueryStep.from_dict(
        {
            "kind": "odata_query",
            "service": "S",
            "filter_field": "F",
            "save_for_report": {"odata_field": "No", "report_key": "missing"},
        }
    )
    assert step is not None
    try:
        validate_save_for_report_keys((step,), frozenset({"contract"}))
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "missing" in str(exc)


def test_is_registered_requires_after_step_row() -> None:
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
            "limit": 1,
            "after_action_steps": [
                {
                    "kind": "odata_query",
                    "service": "FacturasRegistradas",
                    "filter_field": "Preassigned_No",
                    "expect": "at_least_one_row",
                }
            ],
        }
    )

    class Client:
        def get(self, endpoint: str):
            if "FacturasRegistradas" in endpoint:
                return {"value": []}
            return {"value": []}

    assert is_registered_for_posting_job(Client(), definition, spec, "ML1") is False


def test_batch_report_includes_after_action_field() -> None:
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
                    key="posted_no",
                    label="Nº registrada",
                    odata=None,
                ),
            )
        ),
    )
    result = BatchRunResult(
        preview_summary="",
        dry_run=False,
        outcomes=(
            DocumentRunOutcome(
                number="ML1",
                outcome="success",
                fields={"posted_no": "FV-1"},
            ),
        ),
    )
    report = build_skill_batch_report(skill, result)
    row = report.rows[0]
    assert row["Nº registrada"] == "FV-1"
