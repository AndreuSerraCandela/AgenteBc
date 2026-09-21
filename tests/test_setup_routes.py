from pathlib import Path

from agentebc.config import Settings
from agentebc.paths import AppPaths
from agentebc.webapp import create_app


def test_setup_page_loads(tmp_path: Path, monkeypatch) -> None:
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
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTEBC_APP_MODE", "desktop")
    monkeypatch.setenv("AGENTEBC_ENV_FILE", str(env_file))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    paths = AppPaths.resolve()
    settings = Settings.load_fresh(env_file)
    client = create_app(settings=settings, app_paths=paths).test_client()
    response = client.get("/setup")

    assert response.status_code == 200
    assert "Configuración de AgenteBc" in response.get_data(as_text=True)
