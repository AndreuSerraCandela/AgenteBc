"""Punto de entrada para PyInstaller (evita imports relativos en desktop.py)."""

import sys

_WINDOWS_APP_USER_MODEL_ID = "MallaPublicidad.AgenteBc.Desktop"


def _configure_windows_shell() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        _WINDOWS_APP_USER_MODEL_ID
    )


_configure_windows_shell()

from agentebc.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
