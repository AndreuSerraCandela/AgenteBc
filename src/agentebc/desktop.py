from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from werkzeug.serving import make_server

from . import __version__
from .config import ConfigurationError
from .paths import configure_desktop_environment, default_user_data_dir, is_frozen
from .updater import check_and_offer_update

if TYPE_CHECKING:
    from werkzeug.serving import BaseWSGIServer

logger = logging.getLogger(__name__)

_WINDOWS_APP_USER_MODEL_ID = "MallaPublicidad.AgenteBc.Desktop"


def _configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    if not is_frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _show_startup_error(title: str, message: str, log_file: Path) -> None:
    detail = f"{message}\n\nRegistro de diagnóstico:\n{log_file}"
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, detail, title, 0x10)
            return
        except Exception:
            logger.exception("No se pudo mostrar el diálogo de error")
    logger.error("%s: %s", title, detail)


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
    paths = configure_desktop_environment()
    log_file = paths.logs_dir / "startup.log"
    _configure_logging(log_file)
    logger.info("Datos de usuario en %s", paths.user_root)
    logger.info("Iniciando AgenteBc %s", __version__)

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
        _show_startup_error(
            "AgenteBc — configuración no válida",
            f"{exc}\n\nRevisa {paths.env_file}",
            log_file,
        )
        return 2
    except Exception as exc:
        logger.exception("No se pudo importar la aplicación")
        _show_startup_error(
            "AgenteBc — error de arranque",
            str(exc),
            log_file,
        )
        return 3

    try:
        app = create_app(app_paths=paths)
    except ConfigurationError as exc:
        logger.error("Error de configuración: %s", exc)
        _show_startup_error(
            "AgenteBc — configuración no válida",
            f"{exc}\n\nRevisa {paths.env_file}",
            log_file,
        )
        return 2
    except Exception as exc:
        logger.exception("No se pudo crear la aplicación")
        _show_startup_error(
            "AgenteBc — error de arranque",
            str(exc),
            log_file,
        )
        return 3

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
        _show_startup_error(
            "AgenteBc — componente de escritorio ausente",
            f"No se pudo cargar pywebview: {exc}",
            log_file,
        )
        return 3

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
    exit_code = 0
    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:
        exit_code = 3
        logger.exception("No se pudo iniciar WebView2")
        _show_startup_error(
            "AgenteBc — no se pudo abrir la ventana",
            (
                f"{exc}\n\nComprueba que Microsoft Edge WebView2 Runtime "
                "esté instalado."
            ),
            log_file,
        )
    finally:
        server.shutdown()
    return exit_code


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
    try:
        args = _parser().parse_args(argv)
        return run_desktop(
            host=args.host,
            port=args.port,
            check_updates=not args.no_update_check,
        )
    except Exception as exc:
        log_file = default_user_data_dir() / "logs" / "startup.log"
        try:
            _configure_logging(log_file)
            logger.error("Error de arranque no controlado:\n%s", traceback.format_exc())
        except Exception:
            pass
        _show_startup_error(
            "AgenteBc — error de arranque",
            str(exc),
            log_file,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
