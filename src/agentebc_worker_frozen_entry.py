"""Entrada PyInstaller para AgenteBc Worker (escritorio)."""

import sys

if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "MallaPublicidad.AgenteBc.Worker"
        )
    except Exception:
        pass

from agentebc_worker.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
