from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
from typing import TYPE_CHECKING

from werkzeug.serving import make_server

from . import __version__
from .config import ConfigurationError
from .paths import configure_desktop_environment
from .updater import check_and_offer_update

if TYPE_CHECKING:
    from werkzeug.serving import BaseWSGIServer

logger = logging.getLogger(__name__)

_WINDOWS_APP_USER_MODEL_ID = "MallaPublicidad.AgenteBc.Desktop"


def _configure_windows_shell() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _WINDOWS_APP_USER_MODEL_ID
        )
    except Exception:
        logger.warning("No se pudo establecer AppUserModelID", exc_info=True)


def _apply_window_icon(window, icon_path: str | None) -> None:
    if sys.platform != "win32" or not icon_path:
        return

    native = window.native
    if native is None:
        return

    try:
        from System.Drawing import Icon

        native.Icon = Icon(icon_path)
    except Exception:
        logger.warning("No se pudo aplicar el icono de la ventana", exc_info=True)


class LocalServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int) -> None:
        super().__init__(daemon=True, name="agentebc-local-server")
        self._server: BaseWSGIServer = make_server(
            host,
            port,
            app,
            threaded=True,
        )
        self.host = host
        self.port = self._server.server_port

    def run(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def run_desktop(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    check_updates: bool = True,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = configure_desktop_environment()
    logger.info("Datos de usuario en %s", paths.user_root)

    if check_updates:
        try:
            if check_and_offer_update():
                return 0
        except Exception:
            logger.warning("No se pudo comprobar actualizaciones", exc_info=True)

    try:
        from .webapp import create_app
    except ConfigurationError as exc:
        logger.error("Error de configuración: %s", exc)
        return 2

    try:
        app = create_app(app_paths=paths)
    except ConfigurationError as exc:
        logger.error("Error de configuración: %s", exc)
        return 2

    chosen_port = port or find_free_port(host)
    server = LocalServerThread(app, host, chosen_port)
    server.start()
    url = f"http://{host}:{server.port}"

    try:
        import webview
    except ImportError as exc:
        logger.error(
            "Falta pywebview. Instala con: pip install agente-bc[desktop]"
        )
        server.shutdown()
        raise SystemExit(2) from exc

    _configure_windows_shell()
    icon_file = paths.app_icon_file
    icon_path = str(icon_file) if icon_file else None

    window = webview.create_window(
        "AgenteBc",
        url,
        width=1440,
        height=960,
        min_size=(1024, 700),
        text_select=True,
    )
    if icon_path:
        window.events.shown += lambda: _apply_window_icon(window, icon_path)
    try:
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentebc-desktop",
        description="AgenteBc como aplicación de escritorio para Windows",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="No comprobar actualizaciones al iniciar",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AgenteBc {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_desktop(
        host=args.host,
        port=args.port,
        check_updates=not args.no_update_check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
