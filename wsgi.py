"""Punto de entrada WSGI para el servidor (IIS, waitress, etc.).

En agentebc.malla.es debe publicarse el portal de descarga, no la app de
diagnóstico (esa corre en el PC del consultor con agentebc-desktop).

Para desarrollo local del diagnóstico web usa: agentebc-web
"""

from agentebc.portal import create_portal_app

app = create_portal_app()