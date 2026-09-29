"""Edición de campos en ficha BC antes de la acción (desde el JobSpec / skill)."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import replace
from datetime import date

from agentebc.document_types import (
    ActionDefinition,
    DocumentTypeDefinition,
    FieldEditStep,
)

from .job_spec import WorkerJobSpec

FIELD_VALUE_TODAY = frozenset({"today", "hoy"})
FIELD_VALUE_END_OF_MONTH = frozenset(
    {"end_of_month", "fin_mes", "month_end", "current_month_end"}
)

DEFAULT_POSTING_DATE_FIELD_LABEL = "Fecha registro"


def format_bc_ui_date(value: date) -> str:
    """Formato habitual en la web de BC (es-ES)."""
    return value.strftime("%d/%m/%Y")


def resolve_field_edit_value(raw: str, *, reference: date | None = None) -> str:
    ref = reference or date.today()
    token = raw.strip().casefold()
    if token in FIELD_VALUE_TODAY:
        return format_bc_ui_date(ref)
    if token in FIELD_VALUE_END_OF_MONTH:
        last_day = monthrange(ref.year, ref.month)[1]
        return format_bc_ui_date(date(ref.year, ref.month, last_day))
    return raw.strip()


def resolve_before_action_field_edits(
    spec: WorkerJobSpec,
    *,
    reference_date: date | None = None,
) -> tuple[FieldEditStep, ...]:
    resolved: list[FieldEditStep] = []
    for step in spec.before_action_field_edits:
        resolved.append(
            FieldEditStep(
                field_label=step.field_label,
                value=resolve_field_edit_value(
                    step.value,
                    reference=reference_date,
                ),
            )
        )
    return tuple(resolved)


def spec_with_posting_date_mode(
    spec: WorkerJobSpec,
    mode: str | None,
) -> WorkerJobSpec:
    token = (mode or "").strip().lower()
    if not token or token in {"none", ""}:
        return spec
    kept = tuple(
        step
        for step in spec.before_action_field_edits
        if step.field_label.casefold()
        != DEFAULT_POSTING_DATE_FIELD_LABEL.casefold()
    )
    posting = (FieldEditStep(DEFAULT_POSTING_DATE_FIELD_LABEL, token),)
    return replace(spec, before_action_field_edits=posting + kept)


def describe_before_action_edits(spec: WorkerJobSpec) -> str:
    if not spec.before_action_field_edits:
        return ""
    parts = [f"{step.field_label} → {step.value}" for step in spec.before_action_field_edits]
    return "Edición en ficha antes de registrar: " + "; ".join(parts)


def materialize_action_for_job(
    definition: DocumentTypeDefinition,
    spec: WorkerJobSpec,
    *,
    reference_date: date | None = None,
) -> ActionDefinition:
    action = definition.action(spec.action_id)
    spec_edits = resolve_before_action_field_edits(
        spec,
        reference_date=reference_date,
    )
    if not spec_edits:
        return action
    combined = action.field_edits + spec_edits
    return replace(action, field_edits=combined)
