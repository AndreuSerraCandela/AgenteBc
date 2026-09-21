from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


class AiWebCdpError(RuntimeError):
    """Error al comprobar o lanzar Chrome con depuración remota."""


def is_cdp_available(cdp_url: str, *, timeout_seconds: float = 1.0) -> bool:
    version_url = _cdp_version_url(cdp_url)
    try:
        with urllib.request.urlopen(version_url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def ensure_ai_web_cdp_ready(
    cdp_url: str,
    start_url: str,
    *,
    profile_dir: Path | None = None,
    launch_wait_seconds: float = 20.0,
) -> None:
    if is_cdp_available(cdp_url):
        return

    chrome = find_chrome_executable()
    if chrome is None:
        raise AiWebCdpError(
            "No se encontró Google Chrome para abrir la depuración remota (CDP)."
        )

    port = _cdp_port(cdp_url)
    profile = profile_dir or default_cdp_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)

    subprocess.Popen(
        [
            str(chrome),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            start_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    deadline = time.monotonic() + launch_wait_seconds
    while time.monotonic() < deadline:
        if is_cdp_available(cdp_url):
            return
        time.sleep(0.5)

    raise AiWebCdpError(
        f"Chrome no respondió en {cdp_url} tras {int(launch_wait_seconds)} s. "
        f"Inicia sesión manualmente en {start_url} y vuelve a intentarlo."
    )


def default_cdp_profile_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AgenteBC-Chrome"
    return Path.home() / ".agentebc" / "chrome-cdp"


def find_chrome_executable() -> Path | None:
    candidates = (
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _cdp_version_url(cdp_url: str) -> str:
    parsed = urlparse(cdp_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"URL CDP no válida: {cdp_url}")
    return f"{parsed.scheme}://{parsed.netloc}/json/version"


def _cdp_port(cdp_url: str) -> int:
    parsed = urlparse(cdp_url)
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80
