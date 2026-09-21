from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST_URL = "https://agentebc.malla.es/releases/latest.json"


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    download_url: str
    sha256: str | None = None
    min_version: str | None = None
    release_notes: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReleaseManifest:
        version = str(payload.get("version", "")).strip()
        download_url = str(payload.get("download_url", "")).strip()
        if not version or not download_url:
            raise ValueError("El manifiesto de actualización no es válido")
        sha256 = payload.get("sha256")
        min_version = payload.get("min_version")
        release_notes = payload.get("release_notes")
        return cls(
            version=version,
            download_url=download_url,
            sha256=str(sha256).strip() if sha256 else None,
            min_version=str(min_version).strip() if min_version else None,
            release_notes=str(release_notes).strip() if release_notes else None,
        )


def manifest_url() -> str:
    return os.getenv("AGENTEBC_UPDATE_MANIFEST_URL", _DEFAULT_MANIFEST_URL).strip()


def fetch_latest_release(
    *,
    url: str | None = None,
    timeout_seconds: float = 10.0,
) -> ReleaseManifest:
    target = url or manifest_url()
    request = urllib.request.Request(
        target,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"No se pudo consultar actualizaciones en {target}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("El manifiesto de actualización no es un objeto JSON")
    return ReleaseManifest.from_dict(payload)


def is_newer_version(current: str, latest: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def update_available(
    current_version: str = __version__,
    *,
    url: str | None = None,
) -> ReleaseManifest | None:
    try:
        manifest = fetch_latest_release(url=url)
    except RuntimeError:
        logger.warning("Comprobación de actualización omitida", exc_info=True)
        return None
    if not is_newer_version(current_version, manifest.version):
        return None
    return manifest


def download_installer(
    manifest: ReleaseManifest,
    *,
    destination_dir: Path | None = None,
    timeout_seconds: float = 300.0,
) -> Path:
    folder = destination_dir or Path(tempfile.gettempdir())
    folder.mkdir(parents=True, exist_ok=True)
    filename = Path(manifest.download_url).name or f"AgenteBc-{manifest.version}-setup.exe"
    destination = folder / filename
    request = urllib.request.Request(manifest.download_url)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
    if manifest.sha256:
        digest = hashlib.sha256(data).hexdigest().lower()
        if digest != manifest.sha256.lower():
            raise RuntimeError("La descarga no coincide con el hash SHA256 esperado")
    destination.write_bytes(data)
    return destination


def launch_installer(installer_path: Path) -> None:
    if not installer_path.is_file():
        raise FileNotFoundError(f"No existe el instalador: {installer_path}")
    subprocess.Popen(
        [str(installer_path)],
        close_fds=True,
    )


def prompt_windows_yes_no(title: str, message: str) -> bool:
    try:
        import ctypes

        result = ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            0x00000004 | 0x00000040,
        )
        return result == 6
    except Exception:
        logger.warning("No se pudo mostrar el diálogo de actualización", exc_info=True)
        return False


def check_and_offer_update(
    *,
    current_version: str = __version__,
    prompt: Callable[[str, str], bool] | None = None,
    url: str | None = None,
) -> bool:
    manifest = update_available(current_version=current_version, url=url)
    if manifest is None:
        return False

    notes = manifest.release_notes or "Mejoras y correcciones."
    question = (
        f"Hay una nueva versión de AgenteBc ({manifest.version}).\n\n"
        f"Versión actual: {current_version}\n\n"
        f"{notes}\n\n"
        "¿Descargar e instalar ahora?"
    )
    ask = prompt or prompt_windows_yes_no
    if not ask("Actualización de AgenteBc", question):
        return False

    installer = download_installer(manifest)
    launch_installer(installer)
    return True


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in value.strip().split("."):
        digits = "".join(char for char in item if char.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)
