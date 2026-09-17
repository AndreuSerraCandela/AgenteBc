import pytest

from agentebc.document_types import ActionDefinition, FieldEditStep, parse_field_edits_text
from agentebc.web_preview import (
    _extract_inline_error_lines,
    _extract_page_error_banner,
)


def test_field_edit_action_does_not_require_aria_label() -> None:
    action = ActionDefinition(
        id="estado_firmado",
        label="Cambiar estado a Firmado",
        safety="interactive",
        field_edits=(FieldEditStep(field_label="Estado", value="Firmado"),),
    )

    action.validate()


def test_enabled_action_still_requires_selector_or_field_edit() -> None:
    with pytest.raises(ValueError):
        ActionDefinition(
            id="unsafe",
            label="Acción",
            safety="interactive",
        ).validate()


def test_parses_field_edits_text() -> None:
    steps = parse_field_edits_text("Estado|Firmado\n# comentario\nTipo|Anual")

    assert len(steps) == 2
    assert steps[0].field_label == "Estado"
    assert steps[0].value == "Firmado"


def test_extracts_page_error_banner() -> None:
    body = (
        "Contratos Venta\n"
        "La página tiene 2 errores. Seleccione Actualizar (F5) para deshacer los cambios."
    )

    banner = _extract_page_error_banner(body)

    assert banner is not None
    assert "2 errores" in banner


def test_edit_mode_markers_include_spanish_labels() -> None:
    from agentebc.web_preview import (
        _EDIT_ACTIVATE_PATTERNS,
        _EDIT_BUTTON_LABELS,
        _EDIT_MODE_ACTIVE_PATTERNS,
        _EDIT_MODE_MARKERS,
    )

    assert "Editar" in _EDIT_BUTTON_LABELS
    assert "Realizar cambios en la página" in _EDIT_BUTTON_LABELS
    assert "Realizar cambios" in _EDIT_ACTIVATE_PATTERNS
    assert "solo lectura" in _EDIT_MODE_ACTIVE_PATTERNS
    assert "Guardar" in _EDIT_MODE_MARKERS


def test_extracts_inline_field_error_lines() -> None:
    body = (
        "Comentario Cabecera debe tener un valor.\n"
        "No puede continuar hasta corregir los errores."
    )

    lines = _extract_inline_error_lines(body)

    assert any("Comentario Cabecera" in line for line in lines)
