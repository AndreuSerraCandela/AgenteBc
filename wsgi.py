"""
WSGI entry point para IIS (portal de descarga AgenteBc).

En agentebc.malla.es debe publicarse el portal, no la app de diagnóstico
(esa corre en el PC del consultor con agentebc-desktop).

Para desarrollo local del diagnóstico web usa: agentebc-web
Para desarrollo local del portal usa: agentebc-portal
"""
from __future__ import annotations

import os
import sys

if getattr(sys.stdout, "encoding", None) != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if getattr(sys.stderr, "encoding", None) != "utf-8":
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

project_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(project_dir, "src")
for path in (project_dir, src_dir):
    if path not in sys.path:
        sys.path.insert(0, path)
os.chdir(project_dir)

log_file = None
try:
    log_file = os.path.join(project_dir, "logs", "wsgi.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(f"\n=== Iniciando WSGI - {os.getenv('HTTP_PLATFORM_PORT', 'N/A')} ===\n")
        handle.write(f"Project dir: {project_dir}\n")
        handle.write(f"Python path: {sys.executable}\n")
        handle.write(f"Releases dir: {os.getenv('AGENTEBC_RELEASES_DIR', '(default)')}\n")
        handle.write(f"Actions dir: {os.getenv('AGENTEBC_ACTIONS_DIR', '(default)')}\n")
except Exception:
    pass

try:
    from agentebc.portal import create_portal_app

    application = create_portal_app()
    app = application
    if log_file:
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write("Portal AgenteBc importado correctamente\n")
except Exception as exc:
    if log_file:
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"Error importando portal: {exc}\n")
            import traceback

            handle.write(traceback.format_exc())
    raise

if os.environ.get("HTTP_PLATFORM_PORT"):
    try:
        port = int(os.environ.get("HTTP_PLATFORM_PORT", "8765"))
        if log_file:
            with open(log_file, "a", encoding="utf-8") as handle:
                handle.write(f"Iniciando waitress en puerto {port} (IIS)\n")
        from waitress import serve

        print(f"Iniciando portal AgenteBc en puerto {port} (IIS)", flush=True)
        serve(application, host="127.0.0.1", port=port, threads=4, channel_timeout=120)
    except Exception as exc:
        if log_file:
            with open(log_file, "a", encoding="utf-8") as handle:
                handle.write(f"Error iniciando waitress: {exc}\n")
                import traceback

                handle.write(traceback.format_exc())
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        raise

if __name__ == "__main__" and not os.environ.get("HTTP_PLATFORM_PORT"):
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8765"))
    application.run(debug=True, host=host, port=port, use_reloader=False)
