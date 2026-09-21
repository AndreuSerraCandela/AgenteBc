from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from . import __version__
from .action_share import (
    _auth_error,
    _json_error,
    actions_dir,
    register_action_share_routes,
    share_token,
)
from .updater import ReleaseManifest

_DEFAULT_RELEASES_DIR = Path(__file__).resolve().parents[2] / "packaging" / "releases"
_INSTALLER_NAME = re.compile(
    r"^AgenteBc-(?P<version>\d+\.\d+\.\d+)-setup\.exe$",
    re.IGNORECASE,
)
_MAX_INSTALLER_BYTES = 100 * 1024 * 1024
_PUBLIC_RELEASES_BASE = "https://agentebc.malla.es/releases"
_releases_dir_cache: tuple[str, str] | None = None


def releases_dir() -> Path:
    global _releases_dir_cache
    configured = os.getenv("AGENTEBC_RELEASES_DIR", "").strip()
    cache_key = f"{configured}|{Path.cwd()}"
    if _releases_dir_cache and _releases_dir_cache[0] == cache_key:
        return Path(_releases_dir_cache[1])
    preferred = (
        Path(configured).expanduser() if configured else _DEFAULT_RELEASES_DIR
    )
    fallback = Path.cwd() / "data" / "releases"
    chosen = preferred
    for candidate in (preferred, fallback, _DEFAULT_RELEASES_DIR):
        if _releases_dir_writable(candidate):
            chosen = candidate
            break
    resolved = chosen.resolve()
    if resolved != preferred.resolve():
        _seed_release_manifest(resolved, preferred)
    _releases_dir_cache = (cache_key, str(resolved))
    return resolved


def _releases_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def _seed_release_manifest(dest: Path, source: Path) -> None:
    target = dest / "latest.json"
    seed = source / "latest.json"
    if target.is_file() or not seed.is_file():
        return
    try:
        target.write_bytes(seed.read_bytes())
    except OSError:
        return


def load_release_manifest() -> ReleaseManifest | None:
    manifest_path = releases_dir() / "latest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ReleaseManifest.from_dict(payload)
    except ValueError:
        return None


def installer_available(manifest: ReleaseManifest) -> bool:
    filename = Path(manifest.download_url).name
    return (releases_dir() / filename).is_file()


def create_portal_app() -> Flask:
    _load_portal_environment()
    package_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = _MAX_INSTALLER_BYTES

    @app.get("/")
    def portal_home():
        manifest = load_release_manifest()
        ready = bool(manifest and installer_available(manifest))
        return render_template(
            "portal.html",
            manifest=manifest,
            installer_ready=ready,
            releases_dir=str(releases_dir()),
            portal_version=__version__,
        )

    @app.get("/releases/latest.json")
    def latest_manifest():
        manifest_path = releases_dir() / "latest.json"
        if not manifest_path.is_file():
            abort(404, description="No hay manifiesto de versión publicado")
        return send_from_directory(
            releases_dir(),
            "latest.json",
            mimetype="application/json",
        )

    @app.get("/releases/<path:filename>")
    def release_file(filename: str):
        folder = releases_dir()
        target = (folder / filename).resolve()
        if target.parent != folder.resolve() or not target.is_file():
            abort(404)
        return send_from_directory(folder, filename, as_attachment=True)

    @app.get("/api/portal-info")
    def portal_info():
        manifest = load_release_manifest()
        return jsonify(
            {
                "portal": "agentebc-download",
                "portal_version": __version__,
                "releases_dir": str(releases_dir()),
                "manifest": (
                    {
                        "version": manifest.version,
                        "download_url": manifest.download_url,
                        "release_notes": manifest.release_notes,
                        "installer_ready": installer_available(manifest),
                    }
                    if manifest
                    else None
                ),
                "share_enabled": bool(share_token()),
                "actions_dir": _safe_actions_dir(),
            }
        )

    register_action_share_routes(app)
    register_release_upload_routes(app)
    return app


def register_release_upload_routes(app: Flask) -> None:
    @app.post("/api/releases/upload")
    def upload_release():
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        uploaded = request.files.get("file")
        if uploaded is None or not (uploaded.filename or "").strip():
            return _json_error("Falta el fichero del instalador", 400)
        filename = Path(uploaded.filename).name
        match = _INSTALLER_NAME.match(filename)
        if match is None:
            return _json_error(
                "El nombre debe ser AgenteBc-X.Y.Z-setup.exe",
                400,
            )
        filename_version = match.group("version")
        version = (request.form.get("version") or filename_version).strip()
        if version != filename_version:
            return _json_error(
                "La versión no coincide con el nombre del instalador",
                400,
            )
        try:
            chunk_index = _optional_int(request.form.get("chunk_index"), 0)
            chunk_count = _optional_int(request.form.get("chunk_count"), 1)
        except ValueError:
            return _json_error("chunk_index y chunk_count deben ser enteros", 400)
        if chunk_count < 1 or chunk_index < 0 or chunk_index >= chunk_count:
            return _json_error("Los índices de fragmento no son válidos", 400)
        expected_sha = (request.form.get("sha256") or "").strip().lower()
        folder = releases_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / filename
            partial = dest.with_name(f"{dest.name}.partial")
            if chunk_index == 0 and partial.exists():
                partial.unlink()
            with partial.open("ab") as handle:
                uploaded.save(handle)
            if chunk_index + 1 < chunk_count:
                return (
                    jsonify(
                        {
                            "accepted": True,
                            "filename": filename,
                            "chunk_index": chunk_index,
                            "chunk_count": chunk_count,
                            "complete": False,
                        }
                    ),
                    202,
                )
            digest = hashlib.sha256(partial.read_bytes()).hexdigest()
            if expected_sha and expected_sha != digest:
                partial.unlink(missing_ok=True)
                return _json_error("El SHA256 no coincide", 400)
            os.replace(partial, dest)
            download_url = (
                request.form.get("download_url") or ""
            ).strip() or f"{_PUBLIC_RELEASES_BASE}/{filename}"
            manifest = {
                "version": version,
                "min_version": (request.form.get("min_version") or "0.2.0").strip()
                or "0.2.0",
                "download_url": download_url,
                "sha256": digest,
                "release_notes": (request.form.get("release_notes") or "").strip(),
            }
            (folder / "latest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return _json_error(f"No se pudo guardar el instalador: {exc}", 500)
        return (
            jsonify(
                {
                    "version": version,
                    "filename": filename,
                    "sha256": digest,
                    "download_url": download_url,
                    "installer_ready": True,
                }
            ),
            201,
        )


def _optional_int(value: object, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    return int(str(value).strip())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentebc-portal",
        description="Portal web de descarga de AgenteBc Desktop",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--releases-dir",
        default="",
        help="Carpeta con latest.json y los instaladores",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.releases_dir:
        os.environ["AGENTEBC_RELEASES_DIR"] = args.releases_dir
    app = create_portal_app()
    print(f"Portal AgenteBc en http://{args.host}:{args.port}")
    print(f"Releases: {releases_dir()}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


def _safe_actions_dir() -> str:
    try:
        return str(actions_dir())
    except OSError:
        return ""


def _load_portal_environment() -> None:
    """Carga el .env del sitio IIS sin importar Playwright ni Settings."""
    configured = os.getenv("AGENTEBC_ENV_FILE", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(Path.cwd() / ".env")
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if name:
                os.environ.setdefault(name, value)
        return


if __name__ == "__main__":
    raise SystemExit(main())
