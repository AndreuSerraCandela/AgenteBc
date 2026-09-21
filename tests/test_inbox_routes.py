from pathlib import Path

from agentebc.config import Settings
from agentebc.document_types import (
    ActionDefinition,
    DocumentTypeDefinition,
    DocumentTypeRegistry,
)
from agentebc.paths import AppPaths
from agentebc.webapp import create_app


class FakeShareClient:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.shared: list[tuple[str, str, str]] = []
        self.acked: list[tuple[str, str, str]] = []

    def share(self, definition, action, *, from_user="", note=""):
        self.shared.append((definition.id, action.id, note))
        return {"id": "shared-1"}

    def inbox(self, *, status="pending"):
        return [item for item in self.items if item.get("status", "pending") == status]

    def pending_count(self) -> int:
        return len(self.inbox())

    def get(self, share_id: str) -> dict:
        for item in self.items:
            if item["id"] == share_id:
                return item
        raise KeyError(share_id)

    def ack(self, share_id: str, *, status: str, acked_by: str = "") -> dict:
        self.acked.append((share_id, status, acked_by))
        return {"id": share_id, "status": status}


def _desktop_app(tmp_path: Path, monkeypatch, fake: FakeShareClient):
    user_root = tmp_path / "AgenteBC"
    user_root.mkdir()
    env_file = user_root / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://bc.local/BC/ODataV4",
                "AGENTEBC_AUTH_MODE=basic",
                "AGENTEBC_USERNAME=u",
                "AGENTEBC_PASSWORD=p",
                "AGENTEBC_COMPANY=Empresa",
                "AGENTEBC_SHARE_TOKEN=secret-token",
                "AGENTEBC_SHARE_USER=Andrés",
            ]
        ),
        encoding="utf-8",
    )
    config_dir = user_root / "config"
    config_dir.mkdir()
    registry = DocumentTypeRegistry(config_dir / "document_types.json")
    registry.save_document_type(
        DocumentTypeDefinition(
            id="sales_invoice",
            label="Factura venta",
            page_id=43,
            source_table="Sales Header",
            odata_service="salesDocuments",
            odata_key_field="number",
            actions=(
                ActionDefinition(
                    id="preview_posting",
                    label="Vista previa registro",
                    safety="interactive",
                    action_aria_label="Registrar",
                ),
            ),
        )
    )
    monkeypatch.setenv("AGENTEBC_APP_MODE", "desktop")
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env_file))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    class ClientStub:
        def __new__(cls, *args, **kwargs):
            return fake

        @staticmethod
        def from_settings(settings):
            return fake

    monkeypatch.setattr("agentebc.webapp.ActionShareClient", ClientStub)
    paths = AppPaths.resolve()
    settings = Settings.load_fresh(env_file)
    return create_app(settings=settings, app_paths=paths).test_client(), registry


def test_share_action_from_configuration(tmp_path: Path, monkeypatch) -> None:
    fake = FakeShareClient([])
    client, _registry = _desktop_app(tmp_path, monkeypatch, fake)

    response = client.post(
        "/configuration/share",
        data={
            "type_id": "sales_invoice",
            "action_id": "preview_posting",
            "note": "Para el compañero",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert fake.shared == [("sales_invoice", "preview_posting", "Para el compañero")]


def test_inbox_accept_installs_locally_and_acks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    incoming = {
        "id": "11111111-1111-4111-8111-111111111111",
        "status": "pending",
        "from_user": "Andrés",
        "note": "Nueva",
        "created_at": "2026-09-21T10:00:00+00:00",
        "document_type": {
            "id": "purchase_invoice",
            "label": "Factura compra",
            "page_id": 51,
            "source_table": "Purchase Header",
            "odata_service": "purchaseDocuments",
            "odata_key_field": "number",
            "odata_select_fields": {"number": "number"},
            "odata_filters": {},
            "page_filters": {},
            "actions": [],
        },
        "action": {
            "id": "preview_posting",
            "label": "Vista previa registro",
            "safety": "interactive",
            "action_aria_label": "Registrar",
        },
    }
    fake = FakeShareClient([incoming])
    client, registry = _desktop_app(tmp_path, monkeypatch, fake)

    page = client.get("/inbox")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Vista previa registro" in html
    assert "Aceptar e instalar" in html

    response = client.post(
        "/inbox/accept",
        data={"share_id": incoming["id"]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    loaded = registry.get("purchase_invoice")
    assert loaded.action("preview_posting").safety == "interactive"
    assert fake.acked == [(incoming["id"], "accepted", "Andrés")]
    assert "sales_invoice" in {item.id for item in registry.all()}


def test_inbox_reject_does_not_install(tmp_path: Path, monkeypatch) -> None:
    incoming = {
        "id": "22222222-2222-4222-8222-222222222222",
        "status": "pending",
        "from_user": "Andrés",
        "note": "",
        "created_at": "2026-09-21T10:00:00+00:00",
        "document_type": {
            "id": "purchase_invoice",
            "label": "Factura compra",
            "page_id": 51,
            "source_table": "Purchase Header",
            "odata_service": "purchaseDocuments",
            "odata_key_field": "number",
            "odata_select_fields": {},
            "odata_filters": {},
            "page_filters": {},
            "actions": [],
        },
        "action": {
            "id": "preview_posting",
            "label": "Vista previa registro",
            "safety": "interactive",
            "action_aria_label": "Registrar",
        },
    }
    fake = FakeShareClient([incoming])
    client, registry = _desktop_app(tmp_path, monkeypatch, fake)

    response = client.post(
        "/inbox/reject",
        data={"share_id": incoming["id"]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert fake.acked == [(incoming["id"], "rejected", "Andrés")]
    try:
        registry.get("purchase_invoice")
    except KeyError:
        return
    raise AssertionError("rechazar no debe instalar el tipo")
