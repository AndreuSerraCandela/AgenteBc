import hashlib
import io
import json
from pathlib import Path

from agentebc.portal import create_portal_app, releases_dir


def test_portal_home_shows_download_when_installer_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    installer = releases / "AgenteBc-0.2.0-setup.exe"
    installer.write_bytes(b"fake-installer")
    (releases / "latest.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "download_url": "https://agentebc.malla.es/releases/AgenteBc-0.2.0-setup.exe",
                "release_notes": "Prueba",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))

    client = create_portal_app().test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Descargar AgenteBc 0.2.0" in html
    assert "Instalador en preparación" not in html


def test_portal_serves_latest_json(tmp_path: Path, monkeypatch) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    manifest = {
        "version": "0.2.0",
        "download_url": "https://example.test/setup.exe",
    }
    (releases / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))

    client = create_portal_app().test_client()
    response = client.get("/releases/latest.json")

    assert response.status_code == 200
    assert response.json["version"] == "0.2.0"


def test_releases_dir_defaults_to_packaging_folder() -> None:
    path = releases_dir()
    assert path.name == "releases"
    assert "packaging" in str(path)


def test_upload_release_writes_installer_and_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))
    monkeypatch.setenv("AGENTEBC_SHARE_TOKEN", "secret-token")
    client = create_portal_app().test_client()
    payload = b"fake-installer-bytes"
    digest = hashlib.sha256(payload).hexdigest()

    denied = client.post("/api/releases/upload")
    assert denied.status_code == 401

    bad_name = client.post(
        "/api/releases/upload",
        data={"file": (io.BytesIO(payload), "setup.exe")},
        content_type="multipart/form-data",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert bad_name.status_code == 400

    mismatch = client.post(
        "/api/releases/upload",
        data={
            "file": (io.BytesIO(payload), "AgenteBc-0.2.6-setup.exe"),
            "sha256": "0" * 64,
        },
        content_type="multipart/form-data",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert mismatch.status_code == 400

    created = client.post(
        "/api/releases/upload",
        data={
            "file": (io.BytesIO(payload), "AgenteBc-0.2.6-setup.exe"),
            "release_notes": "Prueba de publicación",
        },
        content_type="multipart/form-data",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert created.status_code == 201
    assert created.json["version"] == "0.2.6"
    assert created.json["sha256"] == digest
    installer = releases / "AgenteBc-0.2.6-setup.exe"
    assert installer.read_bytes() == payload
    manifest = json.loads((releases / "latest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.6"
    assert manifest["sha256"] == digest
    assert manifest["download_url"].endswith("AgenteBc-0.2.6-setup.exe")


def test_upload_release_accepts_chunks(tmp_path: Path, monkeypatch) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))
    monkeypatch.setenv("AGENTEBC_SHARE_TOKEN", "secret-token")
    client = create_portal_app().test_client()
    payload = b"abcdef123456"
    digest = hashlib.sha256(payload).hexdigest()
    headers = {"X-AgenteBc-Share-Token": "secret-token"}

    first = client.post(
        "/api/releases/upload",
        data={
            "file": (io.BytesIO(payload[:6]), "AgenteBc-0.2.6-setup.exe"),
            "chunk_index": "0",
            "chunk_count": "2",
            "sha256": digest,
        },
        content_type="multipart/form-data",
        headers=headers,
    )
    assert first.status_code == 202
    assert first.json["complete"] is False

    last = client.post(
        "/api/releases/upload",
        data={
            "file": (io.BytesIO(payload[6:]), "AgenteBc-0.2.6-setup.exe"),
            "chunk_index": "1",
            "chunk_count": "2",
            "sha256": digest,
            "release_notes": "Por fragmentos",
        },
        content_type="multipart/form-data",
        headers=headers,
    )
    assert last.status_code == 201
    assert (releases / "AgenteBc-0.2.6-setup.exe").read_bytes() == payload
    assert json.loads((releases / "latest.json").read_text(encoding="utf-8"))[
        "sha256"
    ] == digest


def test_worker_upload_writes_worker_manifest(tmp_path: Path, monkeypatch) -> None:
    releases = tmp_path / "releases"
    releases.mkdir()
    monkeypatch.setenv("AGENTEBC_RELEASES_DIR", str(releases))
    monkeypatch.setenv("AGENTEBC_SHARE_TOKEN", "secret-token")
    client = create_portal_app().test_client()
    payload = b"worker-installer"
    headers = {"X-AgenteBc-Share-Token": "secret-token"}

    created = client.post(
        "/api/releases/upload",
        data={
            "file": (io.BytesIO(payload), "AgenteBcWorker-0.2.9-setup.exe"),
            "product": "worker",
            "release_notes": "Worker test",
        },
        content_type="multipart/form-data",
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json["product"] == "worker"
    manifest = json.loads(
        (releases / "worker-latest.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.2.9"
    assert (releases / "AgenteBcWorker-0.2.9-setup.exe").read_bytes() == payload


def test_skills_share_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTEBC_WORKER_SKILLS_SHARE_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AGENTEBC_SHARE_TOKEN", "secret-token")
    client = create_portal_app().test_client()
    skill = {
        "schema_version": 1,
        "id": "demo_skill",
        "label": "Demo",
        "spec": {
            "company": "X",
            "type_id": "sales_invoice",
            "action_id": "registrar_factura",
            "limit": 1,
        },
        "report": {"fields": [], "notify_emails": []},
    }
    denied = client.post("/api/skills/share", json={"skill": skill})
    assert denied.status_code == 401
    created = client.post(
        "/api/skills/share",
        json={"skill": skill, "note": "Prueba"},
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert created.status_code == 201
    share_id = created.json["id"]
    inbox = client.get(
        "/api/skills/inbox",
        headers={"X-AgenteBc-Share-Token": "secret-token"},
    )
    assert inbox.status_code == 200
    assert inbox.json["count"] == 1
    assert inbox.json["items"][0]["id"] == share_id
