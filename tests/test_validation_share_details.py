from agentebc.web_preview import (
    PreviewMessage,
    _extract_bc_dialog_message,
    _extract_field_validation_lines,
    _extract_validation_source_fields,
    _extract_validation_target_field,
    _merge_shared_details_into_messages,
    primary_preview_message,
)


def test_merge_shared_details_adds_call_stack_to_field_validation() -> None:
    messages = [
        PreviewMessage(
            message_type="Error",
            description="Firmado",
            context="Validación de campo",
            context_field="Campo 1",
            source=None,
            source_field=None,
            additional_information=None,
            call_stack=None,
        )
    ]
    shared = (
        "El campo de validación Estado ha revelado un problema en el campo "
        "Comentario Cabecera.\n"
        "Comentario Cabecera debe tener un valor.\n"
        '"EventosTablas"(Codeunit 50123).OnValidateEstado line 42'
    )

    merged = _merge_shared_details_into_messages(messages, shared)

    assert len(merged) == 1
    assert "Comentario Cabecera" in merged[0].description
    assert merged[0].source_field == "Comentario Cabecera"
    assert merged[0].call_stack is not None
    assert "EventosTablas" in merged[0].call_stack
    assert "Comentario Cabecera debe tener un valor" in (
        merged[0].additional_information or ""
    )


def test_primary_preview_message_prefers_call_stack_over_banner() -> None:
    messages = (
        PreviewMessage(
            message_type="Error",
            description="La página tiene 2 errores.",
            context="Validación de página",
            context_field=None,
            source=None,
            source_field=None,
            additional_information=None,
            call_stack=None,
        ),
        PreviewMessage(
            message_type="Error",
            description="Comentario Cabecera debe tener un valor.",
            context="Validación de campo",
            context_field="Estado",
            source=None,
            source_field="Comentario Cabecera",
            additional_information=None,
            call_stack='"EventosTablas"(Codeunit 50123).OnValidate line 42',
        ),
    )

    primary = primary_preview_message(messages)

    assert primary.call_stack is not None
    assert "EventosTablas" in primary.call_stack


def test_extracts_visible_spanish_validation_line() -> None:
    body = (
        "La página tiene 2 errores.\n"
        "El campo de validación Estado ha revelado un problema en el campo "
        "Comentario Cabecera."
    )

    lines = _extract_field_validation_lines(body)

    assert len(lines) == 1
    assert _extract_validation_target_field(lines[0]) == "Comentario Cabecera"


def test_validation_popover_markers_include_spanish_text() -> None:
    from agentebc.web_preview import _VALIDATION_POPOVER_MARKERS

    assert any("ha revelado un problema" in marker for marker in _VALIDATION_POPOVER_MARKERS)


def test_extract_bc_dialog_message_skips_support_preamble() -> None:
    shared = (
        "Si solicita soporte, proporcione los detalles siguientes para ayudar "
        "a solucionar el problema:\n"
        "\n"
        "Mensaje de error:\n"
        "El campo de validación Estado ha revelado un problema en el campo "
        "Comentario Cabecera.\n"
        "\n"
        "Id. sesión interno:\n"
        "558d97f4-ce90-4956-b23b-79069a73a7f2\n"
        "\n"
        "Pila de llamadas AL:\n"
        "ControldeEventosTables(CodeUnit 50016).Tabla36_EstadoOnValidate line 30"
    )

    message = _extract_bc_dialog_message(shared)

    assert message is not None
    assert "Estado ha revelado un problema" in message
    assert "Si solicita soporte" not in message


def test_merge_shared_details_with_unquoted_call_stack() -> None:
    messages = [
        PreviewMessage(
            message_type="Error",
            description="El campo de validación Estado ha revelado un problema.",
            context="Validación de campo",
            context_field="Estado",
            source=None,
            source_field="Comentario Cabecera",
            additional_information=None,
            call_stack=None,
        )
    ]
    shared = (
        "Si solicita soporte, proporcione los detalles siguientes.\n"
        "Mensaje de error:\n"
        "El campo de validación Estado ha revelado un problema en el campo "
        "Comentario Cabecera.\n"
        "Pila de llamadas AL:\n"
        "ControldeEventosTables(CodeUnit 50016).Tabla36_EstadoOnValidate line 30"
    )

    merged = _merge_shared_details_into_messages(messages, shared)

    assert merged[0].call_stack is not None
    assert "Tabla36_EstadoOnValidate" in merged[0].call_stack
    assert "Estado ha revelado un problema" in merged[0].description


def test_extract_validation_source_field_from_spanish_message() -> None:
    source, source_field = _extract_validation_source_fields(
        "El campo de validación Estado ha revelado un problema en el campo "
        "Comentario Cabecera."
    )

    assert source is None
    assert source_field == "Comentario Cabecera"
