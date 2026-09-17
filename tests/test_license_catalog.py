import json
from pathlib import Path

from agentebc.license_catalog import (
    discover_extension_roots,
    resolve_extension_roots,
)
from agentebc.source_index import SourceIndex


def _write_extension(root: Path, folder: str, app_name: str) -> Path:
    extension_root = root / folder
    extension_root.mkdir(parents=True)
    (extension_root / "app.json").write_text(
        json.dumps({"name": app_name}),
        encoding="utf-8",
    )
    (extension_root / "src" / "Sample.al").parent.mkdir(parents=True, exist_ok=True)
    (extension_root / "src" / "Sample.al").write_text(
        "trigger OnRun()\nbegin\n    Error('Falta configuración');\nend;",
        encoding="utf-8",
    )
    return extension_root


def test_resolve_extension_roots_by_app_name(tmp_path: Path) -> None:
    _write_extension(tmp_path, "Funciones", "Funciones")
    _write_extension(tmp_path, "LoginPlus", "LoginPlus")

    roots = resolve_extension_roots(tmp_path, ("Funciones",))

    assert len(roots) == 1
    assert roots[0].name == "Funciones"


def test_source_index_filters_to_allowed_roots(tmp_path: Path) -> None:
    funciones = _write_extension(tmp_path, "Funciones", "Funciones")
    loginplus = _write_extension(tmp_path, "LoginPlus", "LoginPlus")
    (loginplus / "src" / "Sample.al").write_text(
        "trigger OnRun()\nbegin\n    Error('Falta configuración');\nend;",
        encoding="utf-8",
    )

    matches = SourceIndex(
        tmp_path,
        allowed_roots=(funciones,),
    ).search("Falta configuración", limit=10)

    assert matches
    assert all(match.path.startswith("Funciones") for match in matches)
    assert not any(match.path.startswith("LoginPlus") for match in matches)


def test_discover_extension_roots_indexes_folder_and_app_name(tmp_path: Path) -> None:
    root = _write_extension(tmp_path, "MallaWaweBc270", "Malla Wave 2.0")

    discovered = discover_extension_roots(tmp_path)

    assert discovered["mallawave20"] == root
    assert discovered["mallawawebc270"] == root
