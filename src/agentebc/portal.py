from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory

from . import __version__
from .updater import ReleaseManifest

_DEFAULT_RELEASES_DIR = Path(__file__).resolve().parents[2] / "packaging" / "releases"


def releases_dir() -> Path:
    configured = os.getenv("AGENTEBC_RELEASES_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _DEFAULT_RELEASES_DIR.resolve()


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
    package_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )

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
            }
        )

    return app


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


if __name__ == "__main__":
    raise SystemExit(main())
