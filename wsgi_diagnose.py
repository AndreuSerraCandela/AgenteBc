"""WSGI de la app de diagnóstico BC (solo desarrollo o uso interno).

El servidor público agentebc.malla.es usa wsgi.py (portal de descarga).
"""

from agentebc.webapp import create_app

app = create_app()
