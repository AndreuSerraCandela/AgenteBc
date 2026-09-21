from pathlib import Path

from agentebc.action_share import (
    ActionShareConflict,
    ActionShareStore,
    install_shared_action,
    recipe_for_share,
)
from agentebc.document_types import (
    ActionDefinition,
    DocumentTypeDefinition,
    DocumentTypeRegistry,
)
from agentebc.portal import create_portal_app


def _action(**overrides) -> ActionDefinition:
    values = {
        "id": "preview_posting",
        "label": "Vista previa registro",
        "safety": "interactive",
        "action_aria_label": "Registrar",
    }
    values.update(overrides)
    return ActionDefinition(**values)


def _document_type(*actions: ActionDefinition) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        id="sales_invoice",
        label="Factura venta",
        page_id=43,
        source_table="Sales Header",
        odata_service="salesDocuments",
        odata_key_field="number",
        odata_select_fields={"number": "number"},
        actions=actions,
    )


def test_store_share_inbox_and_ack(tmp_path: Path) -> None:
    store = ActionShareStore(tmp_path / "actions")
    action = _action()
    item = store.share(
        document_type=_document_type(action, _action(id="other", label="Otra")),
        action=action,
        from_user="Andrés",
        note="Nueva receta",
    )

    pending = store.list(status="pending")
    loaded = store.get(item.id)

    assert item.status == "pending"
    assert len(pending) == 1
    assert pending[0].from_user == "Andrés"
    assert loaded.action["id"] == "preview_posting"
    assert [entry["id"] for entry in loaded.document_type["actions"]] == [
        "preview_posting"
    ]

    acked = store.ack(item.id, status="accepted", acked_by="Pepe")
    assert acked.status == "accepted"
    assert store.list(status="pending") == []
    assert store.list(status="accepted")[0].acked_by == "Pepe"


def test_ack_of_processed_item_conflicts(tmp_path: Path) -> None:
    store = ActionShareStore(tmp_path / "actions")
    item = store.share(document_type=_document_type(), action=_action())
    store.ack(item.id, status="rejected", acked_by="Pepe")

    try:
        store.ack(item.id, status="accepted", acked_by="Pepe")
    except ActionShareConflict:
        return
    raise AssertionError("expected ActionShareConflict")


def test_install_does_not_copy_other_actions(tmp_path: Path) -> None:
    registry = DocumentTypeRegistry(tmp_path / "document_types.json")
    extra = _action(id="other", label="Otra")
    incoming = _action()
    store = ActionShareStore(tmp_path / "actions")
    item = store.share(
        document_type=_document_type(incoming, extra),
        action=incoming,
    )

    install_shared_action(registry, item)
    loaded = registry.get("sales_invoice")

    assert loaded.action("preview_posting").label == "Vista previa registro"
    try:
        loaded.action("other")
    except KeyError:
        return
    raise AssertionError("la acción extra no debía instalarse")


def test_install_keeps_existing_local_actions(tmp_path: Path) -> None:
    registry = DocumentTypeRegistry(tmp_path / "document_types.json")
    local = _action(id="statistics", label="Estadísticas", safety="read_only")
    registry.save_document_type(_document_type(local))
    incoming = _action()
    install_shared_action(
        registry,
        {
            "document_type": recipe_for_share(_document_type(incoming), incoming)[0],
            "action": recipe_for_share(_document_type(incoming), incoming)[1],
        },
    )
    loaded = registry.get("sales_invoice")
    assert {action.id for action in loaded.actions} == {
        "statistics",
        "preview_posting",
    }


def test_portal_share_inbox_and_ack(tmp_path: Path, monkeypatch) -> None:
    actions = tmp_path / "actions"
    monkeypatch.setenv("AGENTEBC_ACTIONS_DIR", str(actions))
    monkeypatch.setenv("AGENTEBC_SHARE_TOKEN", "secret-token")
    client = create_portal_app().test_client()
    action = _action()
    type_payload, action_payload = recipe_for_share(_document_type(action), action)

    denied = client.post(
        "/api/actions/share",
        json={"document_type": type_payload, "action": action_payload},
    )
    assert denied.status_code == 401

    created = client.post(
        "/api/actions/share",
        json={
            "document_type": type_payload,
            "action": action_payload,
            "from_user": "Andrés",
            "note": "Probar registro",
        },
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert created.status_code == 201
    share_id = created.json["id"]

    inbox = client.get(
        "/api/actions/inbox",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert inbox.status_code == 200
    assert inbox.json["count"] == 1
    assert inbox.json["items"][0]["action"]["id"] == "preview_posting"

    ack = client.post(
        f"/api/actions/{share_id}/ack",
        json={"status": "accepted", "acked_by": "Pepe"},
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert ack.status_code == 200
    assert ack.json["status"] == "accepted"

    empty = client.get(
        "/api/actions/inbox",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert empty.json["count"] == 0


def test_portal_share_requires_token_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTEBC_ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.delenv("AGENTEBC_SHARE_TOKEN", raising=False)
    monkeypatch.delenv("AGENTEBC_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    client = create_portal_app().test_client()
    response = client.get("/api/actions/inbox")
    assert response.status_code == 503


def test_portal_reads_share_token_from_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTEBC_ACTIONS_DIR", str(tmp_path / "actions"))
    monkeypatch.delenv("AGENTEBC_SHARE_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("AGENTEBC_SHARE_TOKEN=from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env_file))
    monkeypatch.chdir(tmp_path)
    client = create_portal_app().test_client()
    denied = client.get("/api/actions/inbox")
    allowed = client.get(
        "/api/actions/inbox",
        headers={"X-AgenteBc-Share-Token": "from-env-file"},
    )
    assert denied.status_code == 401
    assert allowed.status_code == 200
