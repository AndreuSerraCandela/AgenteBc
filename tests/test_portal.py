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
