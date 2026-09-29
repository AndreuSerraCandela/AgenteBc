from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading

from agentebc.paths import configure_desktop_environment, is_frozen

from .webapp import create_app

logger = logging.getLogger(__name__)


class _LocalServer(threading.Thread):
    def __init__(self, app, host: str, port: int) -> None:
        super().__init__(daemon=True, name="agentebc-worker-server")
        from werkzeug.serving import make_server

        self._server = make_server(host, port, app, threaded=True)
        self.port = self._server.server_port

    def run(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentebc-worker-desktop")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = puerto libre")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Solo servidor HTTP (sin ventana WebView)",
    )
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="No comprobar worker-latest.json al iniciar",
    )
    args = parser.parse_args(argv)

    paths = configure_desktop_environment()
    log_file = paths.logs_dir / "worker.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    if not is_frozen():
        logging.getLogger().addHandler(logging.StreamHandler())

    logger.info("Worker — datos en %s", paths.user_root)
    logger.info("Configuración: %s", paths.env_file)

    if not args.no_update_check:
        try:
            from agentebc import __version__
            from agentebc.updater import check_and_offer_worker_update

            if check_and_offer_worker_update(current_version=__version__):
                return 0
        except Exception:
            logger.warning("No se pudo comprobar actualizaciones del worker", exc_info=True)

    try:
        app = create_app()
    except Exception as exc:
        logger.exception("No se pudo iniciar el worker")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"{exc}\n\nRevisa {paths.env_file}\nLog: {log_file}",
                "AgenteBc Worker",
                0x10,
            )
        return 2

    port = args.port if args.port > 0 else _find_free_port(args.host)
    server = _LocalServer(app, args.host, port)
    server.start()
    url = f"http://{args.host}:{server.port}/portal"
    logger.info("Worker UI: %s", url)

    if args.no_window:
        print(url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        server.shutdown()
        return 0

    try:
        import webview
    except ImportError:
        print(f"Abre en el navegador: {url}", flush=True)
        print("Instala pywebview: pip install agente-bc[desktop]", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        server.shutdown()
        return 0

    window = webview.create_window(
        "AgenteBc Worker",
        url,
        width=1200,
        height=900,
        min_size=(900, 640),
        text_select=True,
    )
    try:
        webview.start()
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
