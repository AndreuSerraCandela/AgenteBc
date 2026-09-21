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
