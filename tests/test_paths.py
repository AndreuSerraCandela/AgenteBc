from pathlib import Path

from agentebc.paths import AppPaths, configure_desktop_environment, is_desktop_mode


def test_desktop_paths_use_local_app_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("AGENTEBC_APP_MODE", "desktop")
    paths = AppPaths.resolve()

    assert is_desktop_mode() is True
    assert paths.user_root == tmp_path / "AgenteBC"
    assert paths.env_file == tmp_path / "AgenteBC" / ".env"
    assert paths.reports_dir == tmp_path / "AgenteBC" / "reports"


def test_configure_desktop_environment_creates_env_from_example(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("AGENTEBC_APP_MODE", "desktop")

    paths = configure_desktop_environment()

    assert paths.env_file.is_file()
    assert "AGENTEBC_ODATA_BASE_URL" in paths.env_file.read_text(encoding="utf-8")
    assert paths.config_dir.is_dir()
    assert (paths.config_dir / "document_types.json").is_file()
    assert paths.logs_dir.is_dir()


def test_example_configuration_is_safe_for_first_start() -> None:
    project_root = Path(__file__).resolve().parents[1]
    values = {}
    for line in (project_root / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            values[name] = value

    assert values["AGENTEBC_ODATA_BASE_URL"] == ""
    assert values["AGENTEBC_SOURCE_PATH"] == ""
    assert values["AGENTEBC_ALPACKAGES_PATH"] == ""
    assert values["AGENTEBC_BC_AGENT_URL"] == ""
    assert values["AGENTEBC_AI_PROVIDER"] == ""


def test_existing_obsolete_placeholders_are_migrated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTEBC_APP_MODE", "desktop")
    user_root = tmp_path / "user"
    user_root.mkdir()
    env_file = user_root / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AGENTEBC_ODATA_BASE_URL=https://servidor/instancia/ODataV4",
                "AGENTEBC_COMPANY=Nombre de la empresa",
                r"AGENTEBC_SOURCE_PATH=C:\Ruta\A\Fuentes\BC",
                r"AGENTEBC_ALPACKAGES_PATH=C:\Ruta\A\Fuentes\BC\Funciones\.alpackages",
                "AGENTEBC_BC_AGENT_URL=http://192.168.10.238:5051",
                "AGENTEBC_BC_AGENT_TOKEN=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    bundle_root = Path(__file__).resolve().parents[1]
    paths = AppPaths(
        bundle_root=bundle_root,
        user_root=user_root,
        development_root=bundle_root,
    )

    paths.ensure_user_setup()

    migrated = env_file.read_text(encoding="utf-8")
    assert "AGENTEBC_ODATA_BASE_URL=\n" in migrated
    assert "AGENTEBC_SOURCE_PATH=\n" in migrated
    assert "AGENTEBC_ALPACKAGES_PATH=\n" in migrated
    assert "AGENTEBC_BC_AGENT_URL=\n" in migrated
