from agentebc.document_types import ActionDefinition, DialogStep
from agentebc.web_preview import (
    BusinessCentralWebPreview,
    action_bar_expand_selectors,
    menu_aria_parts,
    menu_aria_root,
    menuitem_label_aliases,
    _confirmation_visible,
    _encode_error_grid_headers,
    _extract_bc_dialog_details,
    _extract_bc_dialog_message,
    _find_call_stack_in_values,
    _fold_dialog_text,
    _parse_error_rows,
)


def test_parses_business_central_error_row() -> None:
    rows = (
        "Tipo de mensaje\tDescripción\tContexto",
        "Error\tFecha registro no está dentro del intervalo permitido."
        "\tSales Header: Factura,P4941\tFecha registro"
        "\tGeneral Ledger Setup: \"\"\tPermitir registro desde"
        "\tComprobar campos del documento.\thttps://example.test"
        '\t"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22\t10:00',
    )

    messages = _parse_error_rows(rows)

    assert len(messages) == 1
    assert messages[0].message_type == "Error"
    assert messages[0].context == "Sales Header: Factura,P4941"
    assert messages[0].source == 'General Ledger Setup: ""'
    assert '"Sales-Post"' in (messages[0].call_stack or "")


def test_detects_confirmation_dialog_text() -> None:
    body = (
        "¿Desea crear los borradores de facturas para el actual contrato?\n"
        "Sí\nNo"
    )

    assert _confirmation_visible(
        body,
        ("¿Desea crear los borradores de facturas",),
    )
    assert not _confirmation_visible(body, ("¿Desea anular",))


def test_matches_dialog_title_ignoring_accents_and_loose_token() -> None:
    body = "Dialogo Albaranes\n¿Cuántos albaranes quiere crear?"

    assert _fold_dialog_text("Diálogo Albaranes") == "dialogo albaranes"
    assert _confirmation_visible(body, ("Diálogo Albaranes",))
    assert _confirmation_visible(
        "¿Cuántos albaranes quiere crear?",
        ("Diálogo Albaranes",),
        loose=True,
    )
    assert not _confirmation_visible(
        "¿Cuántos albaranes quiere crear?",
        ("Diálogo Albaranes",),
    )


def test_extracts_business_central_message_dialog_text() -> None:
    dialog = (
        "Ya se han creado los borradores de facturas de este contrato.\n"
        "Compartir detalles\n"
        "¿Le resultó útil esta información?\n"
        "Sí\nNo\n"
        "Aceptar"
    )

    message = _extract_bc_dialog_message(dialog)

    assert message == (
        "Ya se han creado los borradores de facturas de este contrato."
    )


def test_finds_call_stack_without_support_url_column() -> None:
    rows = (
        "Error\tFecha registro no está dentro del intervalo permitido."
        "\tSales Header: Factura,P4941\tFecha registro"
        "\tGeneral Ledger Setup\tPermitir registro desde"
        "\tComprobar campos del documento."
        '\t"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22',
    )

    messages = _parse_error_rows(rows)

    assert len(messages) == 1
    assert '"Sales-Post"' in (messages[0].call_stack or "")
    assert "CheckSalesDocument line 22" in (messages[0].call_stack or "")


def test_find_call_stack_in_values_prefers_last_matching_column() -> None:
    values = (
        "Error",
        "Fecha registro no está dentro del intervalo permitido.",
        '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22',
    )

    stack = _find_call_stack_in_values(values)

    assert stack is not None
    assert "CheckSalesDocument line 22" in stack


def test_parses_error_row_with_headers_for_posting_date() -> None:
    headers = _encode_error_grid_headers(
        [
            "Tipo de mensaje",
            "Descripción",
            "Contexto",
            "Campo",
            "Origen",
            "Campo origen",
            "Información adicional",
            "Obtener ayuda sobre este error",
            "Pila de llamadas AL",
            "Hora del error",
        ]
    )
    row = (
        "Error\tFecha registro no está dentro del intervalo permitido."
        "\tSales Header: Factura,P4941\tFecha registro"
        "\tGeneral Ledger Setup: \"\"\tPermitir registro desde"
        "\tComprobar campos del documento."
        "\thttps://example.test"
        '\t"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22'
        "\t10:00"
    )

    messages = _parse_error_rows((headers, row))

    assert messages[0].context_field == "Fecha registro"
    assert messages[0].source == 'General Ledger Setup: ""'
    assert messages[0].source_field == "Permitir registro desde"
    assert messages[0].additional_information == "Comprobar campos del documento."
    assert '"Sales-Post"' in (messages[0].call_stack or "")


def test_parses_customer_blocked_row_with_fewer_columns() -> None:
    headers = _encode_error_grid_headers(
        [
            "Tipo de mensaje",
            "Descripción",
            "Contexto",
            "Información adicional",
            "Pila de llamadas AL",
            "Hora del error",
        ]
    )
    stack = (
        "Customer(Table 18).CustBlockedErrorMessage line 14 - Base Application"
        '\\"Sales-Post"(CodeUnit 80).CheckCustBlockage line 23'
    )
    row = (
        "Error\tNo puede registrar este tipo de documento cuando el cliente "
        "43P000031 está bloqueado por el tipo Factura"
        "\tSales Header: Factura,PI240014"
        "\tComprobar campos del documento de ventas."
        f"\t{stack}"
        "\t16/09/2026 9:57"
    )

    messages = _parse_error_rows((headers, row))

    assert len(messages) == 1
    assert messages[0].context == "Sales Header: Factura,PI240014"
    assert messages[0].context_field is None
    assert messages[0].source == "Customer: 43P000031"
    assert messages[0].source_field is None
    assert messages[0].additional_information == (
        "Comprobar campos del documento de ventas."
    )
    assert "CustBlockedErrorMessage" in (messages[0].call_stack or "")


def test_normalizes_misaligned_positional_row_for_customer_blocked() -> None:
    stack = (
        "Customer(Table 18).CustBlockedErrorMessage line 14"
        '\\"Sales-Post"(CodeUnit 80).CheckCustBlockage line 23'
    )
    row = (
        "Error\tNo puede registrar este tipo de documento cuando el cliente "
        "43P000031 está bloqueado por el tipo Factura"
        "\tSales Header: Factura,PI240014"
        "\tComprobar campos del documento de ventas."
        f"\t{stack}"
        "\t16/09/2026 9:57"
    )

    messages = _parse_error_rows((row,))

    assert messages[0].source == "Customer: 43P000031"
    assert messages[0].context_field is None
    assert "CustBlockedErrorMessage" in (messages[0].call_stack or "")


def test_dialog_work_pending_while_steps_incomplete() -> None:
    action = ActionDefinition(
        id="registrar_factura",
        label="Registrar",
        safety="diagnostic",
        auto_confirm=True,
        dialog_steps=(
            DialogStep(
                markers=("¿Confirma que desea registrar la factura",),
                button="Sí",
            ),
        ),
        result_markers=("Mensajes de error", "Registrar"),
    )
    preview = BusinessCentralWebPreview.__new__(BusinessCentralWebPreview)

    assert preview._dialog_work_pending(None, action, set()) is True
    assert preview._dialog_work_pending(None, action, {0}) is False


def test_extracts_shared_details_from_message_dialog() -> None:
    dialog = (
        "Ya se han creado los borradores de facturas de este contrato.\n"
        "Compartir detalles\n"
        '"GestionFacturación"(Codeunit 50010).Crear_Facturas_Terminos line 634'
    )

    details = _extract_bc_dialog_details(dialog)

    assert details is not None
    assert "Crear_Facturas_Terminos line 634" in details


def test_menu_aria_parts_supports_nested_path() -> None:
    assert menu_aria_parts("Acciones|Registro|Otros") == (
        "Acciones",
        "Registro",
        "Otros",
    )
    assert menu_aria_root("Acciones|Registro|Otros") == "Acciones"
    assert menu_aria_parts("Acciones relacionadas para Registrar") == (
        "Acciones relacionadas para Registrar",
    )
    assert menu_aria_parts(None) == ()
    assert menuitem_label_aliases("Outros") == ("Outros", "Otros")
    assert menuitem_label_aliases("Registrar...") == (
        "Registrar...",
        "Registar...",
    )
    assert menuitem_label_aliases("Más opciones")[0] == "Más opciones"
    selectors = action_bar_expand_selectors()
    assert any("Más opciones" in selector for selector in selectors)
    assert any("Mostrar acciones secundarias" in selector for selector in selectors)
