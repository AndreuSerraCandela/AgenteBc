from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

VALID_SAFETY_LEVELS = {"blocked", "read_only", "diagnostic", "interactive"}
RUNNABLE_SAFETY_LEVELS = frozenset({"read_only", "diagnostic", "interactive"})
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,49}$")


@dataclass(frozen=True, slots=True)
class FieldEditStep:
    field_label: str
    value: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FieldEditStep":
        step = cls(
            field_label=str(value.get("field_label", "")).strip(),
            value=str(value.get("value", "")).strip(),
        )
        step.validate()
        return step

    def validate(self) -> None:
        if not self.field_label:
            raise ValueError("Cada edición de campo necesita field_label")
        if not self.value:
            raise ValueError("Cada edición de campo necesita value")


@dataclass(frozen=True, slots=True)
class DialogStep:
    markers: tuple[str, ...]
    button: str
    selection: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DialogStep":
        markers = value.get("markers", ())
        if isinstance(markers, str):
            markers = (markers,)
        step = cls(
            markers=tuple(
                str(marker).strip()
                for marker in markers
                if str(marker).strip()
            ),
            button=str(value.get("button", "Sí")).strip() or "Sí",
            selection=_optional_text(value.get("selection")),
        )
        step.validate()
        return step

    def validate(self) -> None:
        if not self.markers:
            raise ValueError("Cada paso de diálogo necesita al menos un marcador")
        if not self.button:
            raise ValueError("Cada paso de diálogo necesita un botón")


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    id: str
    label: str
    safety: str = "blocked"
    menu_aria_label: str | None = None
    action_aria_label: str | None = None
    result_markers: tuple[str, ...] = ()
    parse_error_rows: bool = False
    auto_confirm: bool = False
    confirmation_markers: tuple[str, ...] = ()
    confirmation_button: str = "Sí"
    dialog_steps: tuple[DialogStep, ...] = ()
    field_edits: tuple[FieldEditStep, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionDefinition":
        dialog_steps = tuple(
            DialogStep.from_dict(step)
            for step in value.get("dialog_steps", [])
            if isinstance(step, dict)
        )
        confirmation_markers = tuple(
            str(marker).strip()
            for marker in value.get("confirmation_markers", [])
            if str(marker).strip()
        )
        confirmation_button = (
            str(value.get("confirmation_button", "Sí")).strip() or "Sí"
        )
        if not dialog_steps and confirmation_markers:
            dialog_steps = tuple(
                DialogStep(markers=(marker,), button=confirmation_button)
                for marker in confirmation_markers
            )
        action = cls(
            id=str(value.get("id", "")).strip(),
            label=str(value.get("label", "")).strip(),
            safety=str(value.get("safety", "blocked")).strip(),
            menu_aria_label=_optional_text(value.get("menu_aria_label")),
            action_aria_label=_optional_text(value.get("action_aria_label")),
            result_markers=tuple(
                str(marker).strip()
                for marker in value.get("result_markers", [])
                if str(marker).strip()
            ),
            parse_error_rows=bool(value.get("parse_error_rows", False)),
            auto_confirm=bool(value.get("auto_confirm", False)),
            confirmation_markers=confirmation_markers,
            confirmation_button=confirmation_button,
            dialog_steps=dialog_steps,
            field_edits=tuple(
                FieldEditStep.from_dict(step)
                for step in value.get("field_edits", [])
                if isinstance(step, dict)
            ),
        )
        action.validate()
        return action

    def validate(self) -> None:
        _validate_id(self.id, "acción")
        if not self.label:
            raise ValueError("La acción debe tener una etiqueta")
        if self.safety not in VALID_SAFETY_LEVELS:
            raise ValueError(
                "La seguridad debe ser blocked, read_only, diagnostic o interactive"
            )
        if (
            self.safety != "blocked"
            and not self.action_aria_label
            and not self.field_edits
        ):
            raise ValueError(
                "Una acción habilitada necesita action_aria_label o field_edits"
            )
        if self.auto_confirm and not self.dialog_steps:
            raise ValueError(
                "auto_confirm requiere al menos un paso de diálogo"
            )
        for step in self.dialog_steps:
            step.validate()


@dataclass(frozen=True, slots=True)
class DocumentTypeDefinition:
    id: str
    label: str
    page_id: int
    source_table: str
    odata_service: str
    odata_key_field: str
    odata_select_fields: dict[str, str] = field(default_factory=dict)
    odata_filters: dict[str, str] = field(default_factory=dict)
    page_filters: dict[str, str] = field(default_factory=dict)
    actions: tuple[ActionDefinition, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentTypeDefinition":
        definition = cls(
            id=str(value.get("id", "")).strip(),
            label=str(value.get("label", "")).strip(),
            page_id=int(value.get("page_id", 0)),
            source_table=str(value.get("source_table", "")).strip(),
            odata_service=str(value.get("odata_service", "")).strip(),
            odata_key_field=str(value.get("odata_key_field", "")).strip(),
            odata_select_fields=_string_mapping(
                value.get("odata_select_fields", {})
            ),
            odata_filters=_string_mapping(value.get("odata_filters", {})),
            page_filters=_string_mapping(value.get("page_filters", {})),
            actions=tuple(
                ActionDefinition.from_dict(action)
                for action in value.get("actions", [])
            ),
        )
        definition.validate()
        return definition

    def validate(self) -> None:
        _validate_id(self.id, "tipo de documento")
        if not self.label:
            raise ValueError("El tipo de documento debe tener una etiqueta")
        if self.page_id <= 0:
            raise ValueError("page_id debe ser un entero positivo")
        for name, value in {
            "source_table": self.source_table,
            "odata_service": self.odata_service,
            "odata_key_field": self.odata_key_field,
        }.items():
            if not value:
                raise ValueError(f"{name} es obligatorio")
        action_ids = [action.id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError(f"Hay acciones duplicadas en {self.id}")

    def action(self, action_id: str) -> ActionDefinition:
        for action in self.actions:
            if action.id == action_id:
                return action
        raise KeyError(f"Acción no configurada: {action_id}")


class DocumentTypeRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self) -> list[DocumentTypeDefinition]:
        if not self.path.is_file():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("La configuración de tipos debe ser una lista")
        definitions = [
            DocumentTypeDefinition.from_dict(item)
            for item in raw
            if isinstance(item, dict)
        ]
        ids = [definition.id for definition in definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay tipos de documento duplicados")
        return definitions

    def get(self, type_id: str) -> DocumentTypeDefinition:
        for definition in self.all():
            if definition.id == type_id:
                return definition
        raise KeyError(f"Tipo de documento no configurado: {type_id}")

    def save_document_type(self, definition: DocumentTypeDefinition) -> None:
        definition.validate()
        definitions = self.all()
        updated = False
        for index, current in enumerate(definitions):
            if current.id == definition.id:
                definitions[index] = definition
                updated = True
                break
        if not updated:
            definitions.append(definition)
        self._write(definitions)

    def save_action(self, type_id: str, action: ActionDefinition) -> None:
        action.validate()
        definitions = self.all()
        for index, definition in enumerate(definitions):
            if definition.id != type_id:
                continue
            actions = list(definition.actions)
            for action_index, current in enumerate(actions):
                if current.id == action.id:
                    actions[action_index] = action
                    break
            else:
                actions.append(action)
            value = asdict(definition)
            value["actions"] = [asdict(item) for item in actions]
            definitions[index] = DocumentTypeDefinition.from_dict(value)
            self._write(definitions)
            return
        raise KeyError(f"Tipo de documento no configurado: {type_id}")

    def _write(self, definitions: list[DocumentTypeDefinition]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                [asdict(definition) for definition in definitions],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _validate_id(value: str, kind: str) -> None:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"El id de {kind} debe usar minúsculas, números, '_' o '-'"
        )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_dialog_steps_text(value: str) -> tuple[DialogStep, ...]:
    steps: list[DialogStep] = []
    for number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if not parts or not parts[0]:
            raise ValueError(
                f"La línea {number} del diálogo debe empezar con un texto identificativo"
            )
        button = parts[1] if len(parts) > 1 and parts[1] else "Sí"
        selection = parts[2] if len(parts) > 2 and parts[2] else None
        steps.append(
            DialogStep(
                markers=(parts[0],),
                button=button,
                selection=selection,
            )
        )
    return tuple(steps)


def parse_field_edits_text(value: str) -> tuple[FieldEditStep, ...]:
    steps: list[FieldEditStep] = []
    for number, raw_line in enumerate(value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"La línea {number} del campo debe tener el formato etiqueta|valor"
            )
        steps.append(FieldEditStep(field_label=parts[0], value=parts[1]))
    return tuple(steps)


def format_field_edits_text(steps: tuple[FieldEditStep, ...]) -> str:
    return "\n".join(f"{step.field_label}|{step.value}" for step in steps)


def format_dialog_steps_text(steps: tuple[DialogStep, ...]) -> str:
    lines: list[str] = []
    for step in steps:
        marker = step.markers[0]
        if step.selection:
            lines.append(f"{marker}|{step.button}|{step.selection}")
        else:
            lines.append(f"{marker}|{step.button}")
    return "\n".join(lines)


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Se esperaba un objeto de claves y valores")
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip()
    }
