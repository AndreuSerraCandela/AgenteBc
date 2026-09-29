"""Envía informe de conclusiones del worker (uso puntual)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentebc.config import Settings
from agentebc_worker.mailer import SmtpSettings, send_plain_email


def main() -> int:
    recipient = sys.argv[1] if len(sys.argv) > 1 else "andreuserra@malla.es"
    Settings.load_fresh(ROOT / ".env")
    smtp = SmtpSettings.from_environment()
    if smtp is None:
        print("SMTP no configurado", file=sys.stderr)
        return 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"AgenteBc Worker — facturación Malla Publicidad ({now})"

    body = f"""Hola Andrés,

Te envío el resumen automático del trabajo en el worker de facturación (skill malla_publicidad_facturar_ventas) mientras no estabas.

Estado: operativo y coherente con OData
======================================

Problema que bloqueaba el lote
------------------------------
Las facturas fallaban al poner «Fecha registro = hoy» antes de Registrar. BC mostraba un botón «Descartar» en otra zona de la pantalla y el agente lo interpretaba como «modo edición». No pulsaba el lápiz («Realizar cambios en la página») y el campo seguía en solo lectura (SPAN), de ahí el error:
«No se pudo asignar el valor … al campo Fecha registro».

Corrección aplicada (web_preview.py)
------------------------------------
• Modo edición: solo si hay Guardar / Save visible (Descartar solo ya no basta).
• Tras activar edición, se exige un control escribible (input, no SPAN readonly).
• Clic más fiable en «Realizar cambios en la página» y detección de Guardar también por title/aria-label.
• Test unitario: test_page_is_in_edit_mode_requires_save_not_discard_only.

Pruebas reales ejecutadas hoy (28/09/2026)
-------------------------------------------
Lotes OData tras el fix — informe success = documento ya no Open en FacturaVenta:

• 1 doc: ML257156 — OK
• 3 docs: ML257279, ML257366, ML257397 — OK (antes daban falsos positivos)
• 3 docs (reintento inicial): ML256899, ML257065, ML257097 — error fecha (antes del fix)
• 5 docs: ML257409, ML257435, ML257451, ML257469, ML257481 — OK

Total registradas correctamente en esta sesión (post-fix): 9 facturas, todas reconciliadas con OData.

Pendientes según filtro del skill (mes actual, Open, Firmado, etc.): ~259 facturas (consulta OData al cierre del informe).

Cómo seguir
-----------
• Worker UI: python -m agentebc_worker.cli serve --host 127.0.0.1 --port 8766
• Lote desde consola (sin correo): AGENTEBC_ENV_FILE=.env python scripts/run_integration_batch.py N
• En la skill/UI: «Fecha registro = hoy» antes de registrar (evita serie V-FAC+ en fecha antigua).

Notas
-----
• Script de diagnóstico: scripts/probe_posting_date_field.py <Nº factura>
• Informes del worker pueden usar LM Studio (AGENTEBC_WORKER_AI_*) sin depender de la IA web del consultor.
• Si alguna factura concreta falla, revisar captura en reports/ y mensaje BC (p. ej. bloqueos de contrato).

Un saludo,
AgenteBc (informe automático)
Generado: {now} (hora local del equipo)
"""

    send_plain_email(
        smtp=smtp,
        recipients=(recipient,),
        subject=subject,
        body=body,
    )
    print(f"Enviado a {recipient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
