from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentebc.document_types import FieldEditStep

from .field_edits import DEFAULT_POSTING_DATE_FIELD_LABEL
from .skill_connection import SkillConnection
from .after_action import validate_save_for_report_keys
from .job_spec import (
    WorkerJobSpec,
    extra_odata_filters_to_lines,
    parse_before_action_field_edit_lines,
    parse_extra_odata_filter_lines,
)
from .odata_fields import suggest_report_label

_SKILL_SUFFIX = ".skill.json"
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SkillReportField:
    key: str
    label: str
    odata: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SkillReportField:
        key = str(value.get("key", "")).strip()
        label = str(value.get("label", "")).strip() or key
        raw_odata = value.get("odata")
        if raw_odata is None or raw_odata == "":
            odata = None
        else:
            odata = str(raw_odata).strip() or None
        if not key and odata:
            key = odata
        if not key:
            raise ValueError("report.fields requiere key u odata")
        return cls(key=key, label=label, odata=odata)


@dataclass(frozen=True, slots=True)
class SkillReport:
    fields: tuple[SkillReportField, ...] = ()
    notify_emails: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SkillReport:
        if not value:
            return cls()
        raw_fields = value.get("fields", [])
        if not isinstance(raw_fields, list):
            raise ValueError("report.fields debe ser una lista")
        fields = tuple(
            SkillReportField.from_dict(item)
            for item in raw_fields
            if isinstance(item, dict)
        )
        emails = parse_email_list(value.get("notify_emails", ""))
        return cls(fields=fields, notify_emails=emails)


@dataclass(frozen=True, slots=True)
class WorkerSkill:
    id: str
    label: str
    spec: WorkerJobSpec
    description: str = ""
    report: SkillReport = field(default_factory=SkillReport)
    connection: SkillConnection | None = None
    schema_version: int = _SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorkerSkill:
        skill_id = str(value.get("id", "")).strip()
        label = str(value.get("label", "")).strip()
        if not skill_id:
            raise ValueError("skill.id es obligatorio")
        if not label:
            raise ValueError("skill.label es obligatorio")
        spec_payload = value.get("spec")
        if not isinstance(spec_payload, dict):
            raise ValueError("skill.spec es obligatorio")
        spec = WorkerJobSpec.from_dict(spec_payload, require_company=False)
        report = SkillReport.from_dict(value.get("report"))
        description = str(value.get("description", "")).strip()
        schema_version = int(value.get("schema_version", _SCHEMA_VERSION))
        connection = SkillConnection.from_dict(value.get("connection"))
        return cls(
            id=skill_id,
            label=label,
            spec=spec,
            description=description,
            report=report,
            connection=connection,
            schema_version=schema_version,
        )

    def as_dict(self) -> dict[str, Any]:
        spec = self.spec.as_dict()
        spec["report_odata_fields"] = self.report_odata_fields()
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "spec": spec,
            "report": {
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "odata": field.odata,
                    }
                    for field in self.report.fields
                ],
                "notify_emails": list(self.report.notify_emails),
            },
        }
        if self.connection:
            payload["connection"] = self.connection.as_dict()
        return payload

    def to_job_spec(self, *, dry_run: bool | None = None) -> WorkerJobSpec:
        data = self.spec.as_dict()
        data["report_odata_fields"] = self.report_odata_fields()
        if dry_run is not None:
            data["dry_run"] = dry_run
        return WorkerJobSpec.from_dict(data)

    def report_odata_fields(self) -> dict[str, str]:
        """Solo campos OData del listado del job; columnas solo-informe (odata vacío) se excluyen."""
        mapping: dict[str, str] = {}
        key_override = (self.spec.odata_key_field or "").strip()
        for item in self.report.fields:
            if item.key == "number":
                odata = key_override or (item.odata or "").strip() or "number"
                mapping["number"] = odata
                continue
            odata = (item.odata or "").strip()
            if odata:
                mapping[item.key] = odata
        return mapping


class SkillStore:
    def __init__(
        self,
        user_dir: Path,
        *,
        bundled_dirs: tuple[Path, ...] = (),
    ) -> None:
        self._user_dir = user_dir
        self._bundled_dirs = bundled_dirs

    def ensure_dirs(self) -> None:
        self._user_dir.mkdir(parents=True, exist_ok=True)

    def all(self) -> tuple[WorkerSkill, ...]:
        by_id: dict[str, WorkerSkill] = {}
        for directory in (*self._bundled_dirs, self._user_dir):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob(f"*{_SKILL_SUFFIX}")):
                try:
                    skill = WorkerSkill.from_dict(_read_json(path))
                except (ValueError, json.JSONDecodeError, TypeError):
                    continue
                by_id[skill.id] = skill
        return tuple(by_id[skill.id] for skill_id in sorted(by_id))

    def get(self, skill_id: str) -> WorkerSkill:
        for skill in self.all():
            if skill.id == skill_id:
                return skill
        raise KeyError(f"Skill no encontrado: {skill_id}")

    def save(self, skill: WorkerSkill) -> Path:
        self.ensure_dirs()
        path = self._user_dir / f"{skill.id}{_SKILL_SUFFIX}"
        path.write_text(
            json.dumps(skill.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def parse_email_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        text = str(value).replace(";", ",")
        parts = [part.strip() for part in text.split(",")]
    emails = tuple(
        part for part in parts if part and "@" in part and not part.isspace()
    )
    return emails


def build_report_fields(
    *,
    document_key_odata: str,
    extra_columns: tuple[str, ...],
    advanced_lines: str = "",
) -> tuple[SkillReportField, ...]:
    key_odata = (document_key_odata or "number").strip() or "number"
    if advanced_lines.strip():
        fields = list(
            parse_report_fields_lines(
                advanced_lines,
                document_key_odata=key_odata,
                include_document_key=True,
            )
        )
    else:
        fields = [
            SkillReportField(key="number", label="Nº documento", odata=key_odata),
        ]
    seen = {(f.odata or f.key).casefold() for f in fields}
    for odata in extra_columns:
        name = odata.strip()
        if not name or name.casefold() in seen or name.casefold() == key_odata.casefold():
            continue
        seen.add(name.casefold())
        fields.append(
            SkillReportField(
                key=_report_key_from_odata(name),
                label=suggest_report_label(name),
                odata=name,
            )
        )
    return tuple(fields)


def report_fields_to_lines(fields: tuple[SkillReportField, ...]) -> str:
    lines: list[str] = []
    for item in fields:
        if item.key == "number":
            continue
        if item.odata:
            lines.append(f"{item.label} | {item.key} | {item.odata}")
        else:
            lines.append(f"{item.label} | {item.key} |")
    return "\n".join(lines)


def parse_report_fields_lines(
    text: str,
    *,
    document_key_odata: str = "number",
    include_document_key: bool = True,
) -> tuple[SkillReportField, ...]:
    """Líneas: etiqueta | clave | campo OData (clave y OData opcionales)."""
    key_odata = (document_key_odata or "number").strip() or "number"
    fields: list[SkillReportField] = []
    if include_document_key:
        fields.append(
            SkillReportField(key="number", label="Nº documento", odata=key_odata)
        )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 1:
            odata = parts[0]
            fields.append(
                SkillReportField(key=_report_key_from_odata(odata), label=odata, odata=odata)
            )
            continue
        if len(parts) == 2:
            label, odata = parts[0], parts[1]
            key = _report_key_from_odata(odata)
            fields.append(SkillReportField(key=key, label=label or key, odata=odata))
            continue
        label, key, odata = parts[0], parts[1], parts[2].strip()
        if not key:
            key = _report_key_from_odata(odata or label)
        fields.append(
            SkillReportField(
                key=key,
                label=label or key,
                odata=odata or None,
            )
        )
    return tuple(fields)


def _report_key_from_odata(odata: str) -> str:
    ascii_key = re.sub(r"[^a-zA-Z0-9_]+", "_", odata).strip("_").lower()
    return ascii_key[:40] or "field"


def new_skill_id(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label.casefold())
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return slug[:60] or "skill"


def skill_from_builder_form(form: object) -> WorkerSkill:
    label = _form_str(form, "label")
    skill_id = _form_str(form, "skill_id") or new_skill_id(label)
    company = _form_str(form, "company")
    type_id = _form_str(form, "type_id")
    action_id = _form_str(form, "action_id")
    date_dynamic = _form_str(form, "date_dynamic") or "month_to_today"
    limit = int(_form_str(form, "limit") or "500")
    odata_service = _form_str(form, "odata_service")
    extra_filter_lines = _form_str(form, "extra_filter_lines")
    field_types = _form_field_types_json(form)
    date_odata_field = _form_str(form, "date_odata_field")
    document_key_odata = _form_str(form, "document_key_odata")
    report_fields_lines = _form_str(form, "report_fields_lines")
    emails = parse_email_list(_form_str(form, "notify_emails"))
    description = _form_str(form, "description")
    posting_date_before_register = _form_str(form, "posting_date_before_register")
    before_action_field_edits_lines = _form_str(form, "before_action_field_edits_lines")
    after_service = _form_str(form, "after_odata_service")
    after_field = _form_str(form, "after_filter_field")
    after_value = _form_str(form, "after_filter_value") or "{number}"
    after_extra_lines = _form_str(form, "after_extra_filter_lines")
    after_save_odata_field = _form_str(form, "after_save_odata_field")
    after_save_report_key = _form_str(form, "after_save_report_key")

    extra = parse_extra_odata_filter_lines(
        extra_filter_lines,
        field_types=field_types,
    )

    before_edits = list(
        parse_before_action_field_edit_lines(before_action_field_edits_lines)
    )
    if posting_date_before_register and posting_date_before_register not in {
        "",
        "none",
    }:
        before_edits.insert(
            0,
            FieldEditStep(
                field_label=DEFAULT_POSTING_DATE_FIELD_LABEL,
                value=posting_date_before_register,
            ),
        )

    spec_payload: dict[str, Any] = {
        "company": company,
        "type_id": type_id,
        "action_id": action_id,
        "date_filter": {
            "field": date_odata_field or "posting_date",
            "dynamic": date_dynamic,
        },
        "extra_odata_filters": extra,
        "limit": limit,
        "dry_run": True,
        "on_error": "report_and_continue",
        "before_action_field_edits": [
            {"field_label": step.field_label, "value": step.value}
            for step in before_edits
        ],
    }
    if odata_service:
        spec_payload["odata_service"] = odata_service
    if document_key_odata:
        spec_payload["odata_key_field"] = document_key_odata
    report_fields = build_report_fields(
        document_key_odata=document_key_odata,
        extra_columns=(),
        advanced_lines=report_fields_lines,
    )
    after_svc = after_service.strip()
    after_fld = after_field.strip()
    if after_svc or after_fld:
        if not after_svc or not after_fld:
            raise ValueError(
                "Después de acción (OData): indique servicio y campo de filtro, "
                "o deje ambos vacíos"
            )
        after_extra = parse_extra_odata_filter_lines(
            after_extra_lines,
            field_types=field_types,
        )
        step: dict[str, Any] = {
            "kind": "odata_query",
            "service": after_svc,
            "filter_field": after_fld,
            "filter_value": after_value.strip() or "{number}",
            "expect": "at_least_one_row",
        }
        if after_extra:
            step["extra_filters"] = after_extra
        save_odata = after_save_odata_field.strip()
        save_key = after_save_report_key.strip()
        if save_odata or save_key:
            if not save_odata or not save_key:
                raise ValueError(
                    "Para guardar en informe indique campo OData del paso y "
                    "clave de columna del informe"
                )
            step["save_for_report"] = {
                "odata_field": save_odata,
                "report_key": save_key,
            }
        spec_payload["after_action_steps"] = [step]
    spec = WorkerJobSpec.from_dict(spec_payload, require_company=False)
    report_keys = frozenset(field.key for field in report_fields)
    validate_save_for_report_keys(spec.after_action_steps, report_keys)
    conn_payload: dict[str, str] = {}
    odata_url = _form_str(form, "conn_odata_base_url")
    web_url = _form_str(form, "conn_web_base_url")
    conn_company = _form_str(form, "conn_company")
    if odata_url:
        conn_payload["odata_base_url"] = odata_url
    if web_url:
        conn_payload["web_base_url"] = web_url
    if conn_company:
        conn_payload["company"] = conn_company
    connection = SkillConnection.from_dict(conn_payload or None)
    return WorkerSkill(
        id=skill_id,
        label=label,
        description=description,
        spec=spec,
        report=SkillReport(fields=report_fields, notify_emails=emails),
        connection=connection,
    )


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("El skill debe ser un objeto JSON")
    return data


def _form_field_types_json(form: object) -> dict[str, str]:
    raw = _form_str(form, "odata_field_types_json")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _form_list(form: object, name: str) -> tuple[str, ...]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        return tuple(str(v).strip() for v in getlist(name) if str(v).strip())
    raw = _form_str(form, name)
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _form_str(form: object, name: str) -> str:
    getter = getattr(form, "get", None)
    if not callable(getter):
        return ""
    return str(getter(name, "")).strip()


def _form_checked(form: object, name: str) -> bool:
    getter = getattr(form, "get", None)
    if not callable(getter):
        return False
    return getter(name) in {"yes", "on", "true", "1"}
