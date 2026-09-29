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


def test_extracts_reservation_project_dialog_text() -> None:
    dialog = (
        "No hay reservas en el proyecto PR25-M1982 de la empresa Malla Publicidad.\n"
        "Compartir detalles\n"
        "¿Le resultó útil esta información?\n"
        "Sí\nNo\n"
        "Aceptar"
    )
    message = _extract_bc_dialog_message(dialog)
    assert message == (
        "No hay reservas en el proyecto PR25-M1982 de la empresa Malla Publicidad."
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


def test_error_messages_page_in_dialog_title() -> None:
    from agentebc.web_preview import _is_error_messages_page

    dialog = (
        "Mensajes de error\n"
        "Tipo de mensaje\nDescripción\nContexto\n"
        "Error\tNo puede asignar números nuevos.\tSales Header:..."
    )
    assert _is_error_messages_page(dialog)


def test_posting_success_not_on_page_copy_without_dialog() -> None:
    from agentebc.web_preview import (
        _POSTING_SUCCESS_DIALOG_MARKERS,
        _confirmation_visible,
    )

    menu_only = (
        "Facturas de venta\n"
        "Facturas de venta registradas\n"
        "Estado lanzado\n"
        "Registrar factura"
    )
    assert not _confirmation_visible(
        menu_only,
        _POSTING_SUCCESS_DIALOG_MARKERS,
    )


def test_posting_success_marker_detected() -> None:
    from agentebc.web_preview import (
        _POSTING_SUCCESS_DIALOG_MARKERS,
        _confirmation_visible,
    )

    text = (
        "La factura se registró con el número EX26-M1151 y se movió a la "
        "ventana de facturas de venta registradas. "
        "¿Quiere abrir la factura registrada?"
    )
    assert _confirmation_visible(
        text,
        _POSTING_SUCCESS_DIALOG_MARKERS,
        loose=True,
    )


def test_post_register_dialog_marker_matches() -> None:
    text = (
        "La factura se registró con el número EX26-M1151 y se movió a la "
        "ventana de facturas de venta registradas. "
        "¿Quiere abrir la factura registrada?"
    )
    assert _confirmation_visible(
        text,
        ("¿Quiere abrir la factura registrada",),
    )


def test_cap_wait_seconds_respects_posting_deadline() -> None:
    preview = BusinessCentralWebPreview.__new__(BusinessCentralWebPreview)
    deadline = __import__("time").monotonic() + 5.0
    capped = preview._cap_wait_seconds(90.0, deadline)
    assert 0.0 < capped <= 5.5


def test_all_dialog_steps_handled() -> None:
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
            DialogStep(
                markers=("¿Quiere abrir la factura registrada",),
                button="No",
            ),
        ),
    )
    preview = BusinessCentralWebPreview.__new__(BusinessCentralWebPreview)

    assert preview._all_dialog_steps_handled(action, {0, 1}) is True
    assert preview._all_dialog_steps_handled(action, {0}) is False
    assert preview._all_dialog_steps_handled(action, set()) is False

    optional_first = ActionDefinition(
        id="registrar_factura",
        label="Registrar",
        safety="diagnostic",
        auto_confirm=True,
        dialog_steps=(
            DialogStep(
                markers=("¿Confirma que desea registrar la factura",),
                button="Sí",
                optional=True,
            ),
            DialogStep(
                markers=("¿Quiere abrir la factura registrada",),
                button="No",
            ),
        ),
    )
    assert preview._all_dialog_steps_handled(optional_first, {1}) is True
    assert preview._required_dialog_steps_pending(optional_first, {1}) is False


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
            DialogStep(
                markers=("¿Quiere abrir la factura registrada",),
                button="No",
            ),
        ),
        result_markers=("Mensajes de error", "Registrar"),
    )
    preview = BusinessCentralWebPreview.__new__(BusinessCentralWebPreview)

    assert preview._dialog_work_pending(None, action, set()) is True
    assert preview._dialog_work_pending(None, action, {0}) is True
    assert preview._dialog_work_pending(None, action, {0, 1}) is False


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


def test_posting_date_change_notice_marker() -> None:
    from agentebc.web_preview import _confirmation_visible

    text = (
        "Información en una línea\n"
        "Ha cambiado el Fecha registro en el pedido de venta, lo que puede "
        "afectar a los precios y descuentos de las líneas de ventas."
    )
    assert _confirmation_visible(
        text,
        (
            "Ha cambiado el Fecha registro en el pedido de venta",
            "precios y descuentos de las líneas de ventas",
        ),
        loose=True,
    )


def test_page_is_in_edit_mode_requires_save_not_discard_only() -> None:
    from unittest.mock import MagicMock

    from agentebc.web_preview import _page_is_in_edit_mode

    frame = MagicMock()
    discard = MagicMock()
    discard.count.return_value = 1
    discard.first.is_visible.return_value = True
    guardar = MagicMock()
    guardar.count.return_value = 0

    def role_side_effect(role: str, name: str = "", **kwargs: object) -> MagicMock:
        if role == "button" and name in {"Guardar", "Save"}:
            return guardar
        if role == "button" and name == "Descartar":
            return discard
        return MagicMock(count=MagicMock(return_value=0))

    frame.get_by_role.side_effect = role_side_effect
    frame.locator.return_value = MagicMock(count=MagicMock(return_value=0))

    assert _page_is_in_edit_mode(frame) is False
