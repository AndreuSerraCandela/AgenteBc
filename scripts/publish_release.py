"""Sube un instalador al portal sin pasar por git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import urllib.error
import urllib.request


_DEFAULT_PORTAL = "https://agentebc.malla.es"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def _share_token() -> str:
    token = os.getenv("AGENTEBC_SHARE_TOKEN", "").strip()
    if token:
        return token
    localapp = os.getenv("LOCALAPPDATA", "").strip()
    candidates = []
    if localapp:
        candidates.append(Path(localapp) / "AgenteBC" / ".env")
    candidates.append(Path.cwd() / ".env")
    for path in candidates:
        token = _read_env_file(path).get("AGENTEBC_SHARE_TOKEN", "").strip()
        if token:
            return token
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publica un instalador en POST /api/releases/upload",
    )
    parser.add_argument("installer", type=Path, help="Ruta al AgenteBc-X.Y.Z-setup.exe")
    parser.add_argument(
        "--portal",
        default=os.getenv("AGENTEBC_SHARE_URL", _DEFAULT_PORTAL).strip()
        or _DEFAULT_PORTAL,
        help="URL del portal (por defecto https://agentebc.malla.es)",
    )
    parser.add_argument("--release-notes", default="", help="Notas de la versión")
    parser.add_argument("--min-version", default="0.2.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    installer = args.installer.expanduser().resolve()
    if not installer.is_file():
        print(f"No existe el instalador: {installer}", file=sys.stderr)
        return 1
    token = _share_token()
    if not token:
        print(
            "Falta AGENTEBC_SHARE_TOKEN (variable o %LOCALAPPDATA%\\AgenteBC\\.env)",
            file=sys.stderr,
        )
        return 1
    filename = installer.name
    prefix = "AgenteBc-"
    suffix = "-setup.exe"
    if not (filename.startswith(prefix) and filename.endswith(suffix)):
        print("El fichero debe llamarse AgenteBc-X.Y.Z-setup.exe", file=sys.stderr)
        return 1
    version = filename[len(prefix) : -len(suffix)]
    digest = _sha256(installer)
    boundary = "----AgenteBcReleaseBoundary"
    notes = args.release_notes or f"AgenteBc {version}"
    fields = {
        "version": version,
        "min_version": args.min_version,
        "sha256": digest,
        "release_notes": notes,
    }
    url = args.portal.rstrip("/") + "/api/releases/upload"
    chunk_size = 8 * 1024 * 1024
    data = installer.read_bytes()
    chunks = [data[index : index + chunk_size] for index in range(0, len(data), chunk_size)]
    if not chunks:
        print("El instalador está vacío", file=sys.stderr)
        return 1
    print(f"Subiendo {filename} ({len(data)} bytes, {len(chunks)} fragmentos) a {url}")
    payload: dict[str, object] = {}
    for index, chunk in enumerate(chunks):
        body = _multipart_body(
            fields={
                **fields,
                "chunk_index": str(index),
                "chunk_count": str(len(chunks)),
            },
            filename=filename,
            file_bytes=chunk,
            boundary=boundary,
        )
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-AgenteBc-Share-Token": token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"Error {exc.code} en fragmento {index + 1}: {detail}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"No se pudo conectar con el portal: {exc}", file=sys.stderr)
            return 1
        print(f"Fragmento {index + 1}/{len(chunks)}")
    print(f"Publicado {payload.get('version')} → {payload.get('download_url')}")
    return 0


def _multipart_body(
    *,
    fields: dict[str, str],
    filename: str,
    file_bytes: bytes,
    boundary: str,
) -> bytes:
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(f"{value}\r\n".encode("utf-8"))
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return bytes(body)


if __name__ == "__main__":
    raise SystemExit(main())
