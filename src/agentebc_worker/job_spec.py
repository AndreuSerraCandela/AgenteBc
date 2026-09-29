from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from agentebc.document_types import (
    DocumentTypeDefinition,
    DocumentTypeRegistry,
    FieldEditStep,
    RUNNABLE_SAFETY_LEVELS,
)

from .after_action import (
    AfterActionOdataQueryStep,
    after_action_steps_from_spec_payload,
)
from .dynamic_filters import DYNAMIC_FILTER_IDS, resolve_dynamic_filter


@dataclass(frozen=True, slots=True)
class DateFilterSpec:
    """Campo lógico del tipo (p. ej. posting_date) o nombre OData directo."""

    field: str
    dynamic: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> DateFilterSpec | None:
        if not value or not isinstance(value, dict):
            return None
        field_name = str(value.get("field", "")).strip()
        if not field_name:
            raise ValueError("date_filter.field es obligatorio")
        dynamic = _optional_str(value.get("dynamic"))
        raw_from = value.get("from") or value.get("date_from")
        raw_to = value.get("to") or value.get("date_to")
        parsed_from = _parse_date(raw_from) if raw_from else None
        parsed_to = _parse_date(raw_to) if raw_to else None
        if dynamic and dynamic not in DYNAMIC_FILTER_IDS:
            raise ValueError(f"date_filter.dynamic no válido: {dynamic!r}")
        if dynamic and (parsed_from or parsed_to):
            raise ValueError("No combine dynamic con from/to fijos en date_filter")
        if not dynamic and (parsed_from is None or parsed_to is None):
            raise ValueError(
                "date_filter requiere dynamic o bien from y to explícitos"
            )
        return cls(
            field=field_name,
            dynamic=dynamic,
            date_from=parsed_from,
            date_to=parsed_to,
        )

    def validate(self) -> None:
        if not self.field:
            raise ValueError("date_filter.field es obligatorio")


@dataclass(frozen=True, slots=True)
class WorkerJobSpec:
    company: str
    type_id: str
    action_id: str
    date_filter: DateFilterSpec | None = None
    extra_odata_filters: dict[str, str | bool] = field(default_factory=dict)
    report_odata_fields: dict[str, str] = field(default_factory=dict)
    odata_service: str | None = None
    odata_key_field: str | None = None
    limit: int = 200
    dry_run: bool = True
    on_error: str = "report_and_continue"
    before_action_field_edits: tuple[FieldEditStep, ...] = ()
    after_action_steps: tuple[AfterActionOdataQueryStep, ...] = ()

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        require_company: bool = True,
    ) -> WorkerJobSpec:
        company = str(value.get("company", "")).strip()
        type_id = str(value.get("type_id", "")).strip()
        action_id = str(value.get("action_id", "")).strip()
        if require_company and not company:
            raise ValueError("company es obligatorio")
        if not type_id:
            raise ValueError("type_id es obligatorio")
        if not action_id:
            raise ValueError("action_id es obligatorio")
        limit = int(value.get("limit", 200))
        if limit <= 0 or limit > 5000:
            raise ValueError("limit debe estar entre 1 y 5000")
        on_error = str(value.get("on_error", "report_and_continue")).strip()
        if on_error not in {"report_and_continue", "stop"}:
            raise ValueError("on_error debe ser report_and_continue o stop")
        extra = value.get("extra_odata_filters", {})
        if not isinstance(extra, dict):
            raise ValueError("extra_odata_filters debe ser un objeto")
        extra_odata = _parse_extra_odata_filters(extra)
        report_raw = value.get("report_odata_fields", {})
        if not isinstance(report_raw, dict):
            raise ValueError("report_odata_fields debe ser un objeto")
        report_odata = {
            str(k).strip(): str(v).strip()
            for k, v in report_raw.items()
            if str(k).strip() and str(v).strip()
        }
        odata_service = _optional_str(value.get("odata_service"))
        odata_key_field = _optional_str(value.get("odata_key_field"))
        before_edits = _parse_before_action_field_edits(
            value.get("before_action_field_edits")
        )
        spec = cls(
            company=company,
            type_id=type_id,
            action_id=action_id,
            date_filter=DateFilterSpec.from_dict(value.get("date_filter")),
            extra_odata_filters=extra_odata,
            report_odata_fields=report_odata,
            odata_service=odata_service,
            odata_key_field=odata_key_field,
            limit=limit,
            dry_run=bool(value.get("dry_run", True)),
            on_error=on_error,
            before_action_field_edits=before_edits,
            after_action_steps=after_action_steps_from_spec_payload(value),
        )
        return spec

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.date_filter:
            df = {
                "field": self.date_filter.field,
                "dynamic": self.date_filter.dynamic,
            }
            if self.date_filter.date_from:
                df["from"] = self.date_filter.date_from.isoformat()
            if self.date_filter.date_to:
                df["to"] = self.date_filter.date_to.isoformat()
            payload["date_filter"] = df
        else:
            payload["date_filter"] = None
        payload["before_action_field_edits"] = [
            {"field_label": step.field_label, "value": step.value}
            for step in self.before_action_field_edits
        ]
        payload["after_action_steps"] = [
            step.as_dict() for step in self.after_action_steps
        ]
        payload.pop("odata_confirmation", None)
        return payload

    def validate_against_registry(self, registry: DocumentTypeRegistry) -> None:
        definition = registry.get(self.type_id)
        action = definition.action(self.action_id)
        if action.safety not in RUNNABLE_SAFETY_LEVELS:
            raise ValueError(
                f"La acción {self.action_id} no está habilitada para el worker "
                f"(safety={action.safety})"
            )
        if self.date_filter:
            self.date_filter.validate()
            if not (self.odata_service or "").strip():
                _resolve_odata_field(definition, self.date_filter.field)


def resolve_date_filter(
    date_filter: DateFilterSpec,
    *,
    reference: date | None = None,
) -> tuple[date, date]:
    if date_filter.dynamic:
        resolved = resolve_dynamic_filter(date_filter.dynamic, reference=reference)
        return resolved.date_from, resolved.date_to
    assert date_filter.date_from is not None and date_filter.date_to is not None
    if date_filter.date_from > date_filter.date_to:
        raise ValueError("date_filter.from no puede ser posterior a date_filter.to")
    return date_filter.date_from, date_filter.date_to


def _resolve_odata_field(
    definition: DocumentTypeDefinition,
    field_key: str,
) -> str:
    if field_key in definition.odata_select_fields:
        return definition.odata_select_fields[field_key]
    if field_key in definition.odata_select_fields.values():
        return field_key
    raise ValueError(
        f"Campo de fecha {field_key!r} no está en odata_select_fields de "
        f"{definition.id}"
    )


def odata_date_field(
    definition: DocumentTypeDefinition,
    date_filter: DateFilterSpec,
    *,
    custom_odata_service: bool = False,
) -> str:
    try:
        return _resolve_odata_field(definition, date_filter.field)
    except ValueError:
        if custom_odata_service:
            return date_filter.field.strip()
        raise


def resolve_odata_service(
    spec: WorkerJobSpec,
    definition: DocumentTypeDefinition,
) -> str:
    override = (spec.odata_service or "").strip()
    if override:
        return override
    return definition.odata_service


def uses_custom_odata_service(
    spec: WorkerJobSpec,
    definition: DocumentTypeDefinition,
) -> bool:
    return resolve_odata_service(spec, definition) != definition.odata_service


def resolve_odata_key_field(
    spec: WorkerJobSpec,
    definition: DocumentTypeDefinition,
) -> str:
    explicit = (spec.odata_key_field or "").strip()
    if explicit:
        return explicit
    mapped = (spec.report_odata_fields.get("number") or "").strip()
    if mapped and mapped != "number":
        return mapped
    return definition.odata_key_field


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: object) -> date:
    text = str(value).strip()
    if len(text) >= 10:
        text = text[:10]
    return date.fromisoformat(text)


def extra_odata_filters_to_lines(extra: dict[str, str | bool]) -> str:
    lines: list[str] = []
    for field, value in extra.items():
        if isinstance(value, bool):
            lines.append(f"{field} | {'true' if value else 'false'}")
        elif value == "":
            lines.append(f"{field} | (vacío)")
        else:
            lines.append(f"{field} | {value}")
    return "\n".join(lines)


def parse_extra_odata_filter_lines(
    text: str,
    *,
    field_types: dict[str, str] | None = None,
) -> dict[str, str | bool]:
    """Una línea por filtro: ``campo | valor`` (# comentarios).

    ``false``/``true`` → booleano solo si el tipo OData del campo es boolean
    (p. ej. del documento de ejemplo). Si no, use ``No``, ``Yes``, etc. como texto.
    ``(vacío)`` → cadena vacía.
    """
    types = field_types or {}
    parsed: dict[str, str | bool] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            field, raw_value = line.split("|", 1)
        elif "=" in line:
            field, raw_value = line.split("=", 1)
        else:
            raise ValueError(f"Filtro OData mal formado: {line!r}")
        field = field.strip()
        raw_value = raw_value.strip()
        if not field:
            raise ValueError(f"Filtro OData sin nombre de campo: {line!r}")
        parsed[field] = _parse_extra_filter_value(raw_value, types.get(field))
    return parsed


def _parse_extra_filter_value(raw_value: str, field_type: str | None) -> str | bool:
    lowered = raw_value.casefold()
    if lowered in {"(vacío)", "(vacio)", '""', "''"}:
        return ""
    if lowered in {"false", "true"}:
        if field_type == "boolean":
            return lowered == "true"
        if field_type in {None, "unknown", "string"}:
            return raw_value
        return lowered == "true"
    if lowered.startswith("bool:"):
        token = lowered[5:].strip()
        if token in {"false", "true"}:
            return token == "true"
    if lowered.startswith("str:"):
        return raw_value[4:].strip()
    return raw_value


def _parse_extra_odata_filters(extra: object) -> dict[str, str | bool]:
    if not isinstance(extra, dict):
        raise ValueError("extra_odata_filters debe ser un objeto")
    parsed: dict[str, str | bool] = {}
    for raw_key, raw_value in extra.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if isinstance(raw_value, bool):
            parsed[key] = raw_value
            continue
        if isinstance(raw_value, str):
            lowered = raw_value.strip().lower()
            if lowered == "true":
                parsed[key] = True
                continue
            if lowered == "false":
                parsed[key] = False
                continue
            if raw_value.strip():
                parsed[key] = raw_value.strip()
            continue
        parsed[key] = str(raw_value).strip()
    return parsed


def _parse_before_action_field_edits(raw: object) -> tuple[FieldEditStep, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ValueError("before_action_field_edits debe ser una lista")
    steps: list[FieldEditStep] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Cada before_action_field_edits debe ser un objeto")
        steps.append(FieldEditStep.from_dict(item))
    return tuple(steps)


def parse_before_action_field_edit_lines(text: str) -> tuple[FieldEditStep, ...]:
    """Líneas ``Etiqueta campo | valor`` (valor: today, end_of_month o literal)."""
    steps: list[FieldEditStep] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            raise ValueError(f"Edición de campo mal formada: {line!r}")
        label, value = line.split("|", 1)
        steps.append(
            FieldEditStep(
                field_label=label.strip(),
                value=value.strip(),
            )
        )
    return tuple(steps)
