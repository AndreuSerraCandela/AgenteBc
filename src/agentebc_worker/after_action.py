"""Pasos después de la acción principal (OData, etc.)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.documents import _odata_literal, bc_urlencode


@dataclass(frozen=True, slots=True)
class SaveForReportSpec:
    odata_field: str
    report_key: str

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SaveForReportSpec | None:
        if not value or not isinstance(value, dict):
            return None
        odata_field = str(value.get("odata_field", "")).strip()
        report_key = str(value.get("report_key", "")).strip()
        if not odata_field or not report_key:
            return None
        return cls(odata_field=odata_field, report_key=report_key)

    def as_dict(self) -> dict[str, str]:
        return {"odata_field": self.odata_field, "report_key": self.report_key}


@dataclass(frozen=True, slots=True)
class AfterActionOdataQueryStep:
    service: str
    filter_field: str
    filter_value: str = "{number}"
    extra_filters: dict[str, str | bool] = field(default_factory=dict)
    expect: str = "at_least_one_row"
    save_for_report: SaveForReportSpec | None = None
    kind: str = "odata_query"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AfterActionOdataQueryStep | None:
        if not isinstance(value, dict):
            return None
        kind = str(value.get("kind", "odata_query")).strip() or "odata_query"
        if kind != "odata_query":
            return None
        service = str(value.get("service", "")).strip()
        filter_field = str(
            value.get("filter_field") or value.get("field") or ""
        ).strip()
        if not service or not filter_field:
            return None
        filter_value = str(value.get("filter_value", "{number}")).strip() or "{number}"
        expect = str(value.get("expect", "at_least_one_row")).strip() or "at_least_one_row"
        extra_raw = value.get("extra_filters", {})
        extra: dict[str, str | bool] = {}
        if isinstance(extra_raw, dict):
            for key, raw in extra_raw.items():
                name = str(key).strip()
                if not name:
                    continue
                if isinstance(raw, bool):
                    extra[name] = raw
                else:
                    extra[name] = str(raw).strip()
        return cls(
            service=service,
            filter_field=filter_field,
            filter_value=filter_value,
            extra_filters=extra,
            expect=expect,
            save_for_report=SaveForReportSpec.from_dict(
                value.get("save_for_report")
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "service": self.service,
            "filter_field": self.filter_field,
            "filter_value": self.filter_value,
            "expect": self.expect,
        }
        if self.extra_filters:
            payload["extra_filters"] = dict(self.extra_filters)
        if self.save_for_report:
            payload["save_for_report"] = self.save_for_report.as_dict()
        return payload


def parse_after_action_steps(raw: object) -> tuple[AfterActionOdataQueryStep, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("after_action_steps debe ser una lista")
    steps: list[AfterActionOdataQueryStep] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Cada after_action_steps debe ser un objeto")
        step = AfterActionOdataQueryStep.from_dict(item)
        if step is None:
            raise ValueError("Paso after_action no soportado o incompleto")
        steps.append(step)
    return tuple(steps)


def after_action_steps_from_spec_payload(value: dict[str, Any]) -> tuple[AfterActionOdataQueryStep, ...]:
    if value.get("after_action_steps"):
        return parse_after_action_steps(value.get("after_action_steps"))
    legacy = value.get("odata_confirmation")
    if isinstance(legacy, dict) and legacy:
        step = AfterActionOdataQueryStep.from_dict(
            {
                **legacy,
                "kind": "odata_query",
                "expect": "at_least_one_row",
            }
        )
        if step is None:
            return ()
        return (step,)
    return ()


def resolve_template_value(template: str, *, number: str) -> str:
    text = template.strip() or "{number}"
    return text.replace("{number}", number).replace("{document_no}", number)


def _filter_clause(field: str, value: str | bool, *, number: str) -> str:
    if isinstance(value, bool):
        return f"{field} eq {str(value).lower()}"
    resolved = resolve_template_value(str(value), number=number)
    return f"{field} eq {_odata_literal(resolved)}"


def query_odata_step_row(
    client: BusinessCentralReadClient,
    *,
    company: str,
    step: AfterActionOdataQueryStep,
    number: str,
) -> dict[str, Any] | None:
    match_value = resolve_template_value(step.filter_value, number=number)
    filters: list[str] = [
        f"{step.filter_field} eq {_odata_literal(match_value)}",
    ]
    for field_name, value in step.extra_filters.items():
        filters.append(_filter_clause(field_name, value, number=number))
    query = bc_urlencode(
        {
            "company": company,
            "$filter": " and ".join(filters),
            "$top": "1",
        }
    )
    data = client.get(f"{step.service}?{query}")
    rows = data.get("value", []) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    return row if isinstance(row, dict) else None


def fields_from_row(step: AfterActionOdataQueryStep, row: dict[str, Any]) -> dict[str, str]:
    if step.save_for_report is None:
        return {}
    raw = row.get(step.save_for_report.odata_field)
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    return {step.save_for_report.report_key: text}


@dataclass(frozen=True, slots=True)
class AfterActionEvaluation:
    """Resultado de pasos después de acción para un documento."""

    registered: bool
    fields: dict[str, str]
    used_after_steps: bool


def evaluate_after_action_steps(
    client: BusinessCentralReadClient,
    *,
    company: str,
    steps: tuple[AfterActionOdataQueryStep, ...],
    number: str,
) -> AfterActionEvaluation:
    verify_steps = tuple(
        step for step in steps if step.expect == "at_least_one_row"
    )
    if not verify_steps:
        return AfterActionEvaluation(registered=True, fields={}, used_after_steps=False)

    merged_fields: dict[str, str] = {}
    for step in verify_steps:
        row = query_odata_step_row(client, company=company, step=step, number=number)
        if row is None:
            return AfterActionEvaluation(
                registered=False,
                fields={},
                used_after_steps=True,
            )
        merged_fields.update(fields_from_row(step, row))
    return AfterActionEvaluation(
        registered=True,
        fields=merged_fields,
        used_after_steps=True,
    )


def validate_save_for_report_keys(
    steps: tuple[AfterActionOdataQueryStep, ...],
    report_keys: frozenset[str],
) -> None:
    for step in steps:
        if step.save_for_report is None:
            continue
        key = step.save_for_report.report_key
        if key not in report_keys:
            raise ValueError(
                f"save_for_report.report_key {key!r} no está en las columnas del "
                f"informe. Añada una línea «etiqueta | {key} |» (OData vacío) en "
                "columnas del informe."
            )
