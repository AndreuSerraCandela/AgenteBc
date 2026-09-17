from pathlib import Path

import pytest

from agentebc.document_types import (
    ActionDefinition,
    DialogStep,
    DocumentTypeDefinition,
    DocumentTypeRegistry,
    parse_dialog_steps_text,
)


def _definition(actions=()):
    return DocumentTypeDefinition(
        id="sales_contract",
        label="Ficha Contrato Venta",
        page_id=50209,
        source_table="Sales Header",
        odata_service="salesDocuments",
        odata_key_field="number",
        odata_select_fields={"number": "number"},
        odata_filters={"documentType": "Order"},
        page_filters={"Document Type": "Order"},
        actions=actions,
    )


def test_registry_persists_document_types_and_actions(tmp_path: Path) -> None:
    registry = DocumentTypeRegistry(tmp_path / "types.json")
    registry.save_document_type(_definition())
    registry.save_action(
        "sales_contract",
        ActionDefinition(
            id="statistics",
            label="Estadísticas",
            safety="read_only",
            action_aria_label="Estadísticas",
        ),
    )

    loaded = registry.get("sales_contract")

    assert loaded.page_id == 50209
    assert loaded.action("statistics").safety == "read_only"


def test_enabled_action_requires_selector() -> None:
    with pytest.raises(ValueError):
        ActionDefinition(
            id="unsafe",
            label="Acción",
            safety="diagnostic",
        ).validate()


def test_blocked_discovered_action_can_be_saved_without_selector() -> None:
    action = ActionDefinition(
        id="unknown_action",
        label="Acción desconocida",
        safety="blocked",
    )

    action.validate()


def test_auto_confirm_requires_dialog_steps() -> None:
    with pytest.raises(ValueError):
        ActionDefinition(
            id="propose",
            label="Proponer",
            safety="diagnostic",
            action_aria_label="Proponer",
            auto_confirm=True,
        ).validate()


def test_parses_dialog_steps_text() -> None:
    steps = parse_dialog_steps_text(
        "¿Desea crear los borradores|Sí\n"
        "Por términos|Aceptar|Por términos\n"
    )

    assert len(steps) == 2
    assert steps[1].button == "Aceptar"
    assert steps[1].selection == "Por términos"


def test_registry_persists_dialog_steps(tmp_path: Path) -> None:
    registry = DocumentTypeRegistry(tmp_path / "types.json")
    registry.save_document_type(_definition())
    registry.save_action(
        "sales_contract",
        ActionDefinition(
            id="proponer_facturacion",
            label="Proponer facturación contratos...",
            safety="diagnostic",
            action_aria_label="Proponer facturación contratos...",
            auto_confirm=True,
            dialog_steps=(
                DialogStep(
                    markers=("¿Desea crear los borradores de facturas",),
                    button="Sí",
                ),
                DialogStep(
                    markers=("Por términos",),
                    button="Aceptar",
                    selection="Por términos",
                ),
            ),
        ),
    )

    loaded = registry.get("sales_contract").action("proponer_facturacion")

    assert loaded.auto_confirm is True
    assert loaded.dialog_steps[1].button == "Aceptar"
