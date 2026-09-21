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
