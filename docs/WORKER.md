# AgenteBc Worker

Módulo **separado** del flujo consultor (`agentebc`, `agentebc-web`, `agentebc-desktop`).
Sirve para planificar y ejecutar trabajos de registro por lotes con **vista previa**
antes de confirmar.

## Instalación

Tras instalar el paquete:

```powershell
agentebc-worker filters
agentebc-worker preset-list
```

## Entorno de prueba (primera vez)

```powershell
.\scripts\setup-worker-test-env.ps1
```

Instala dependencias, Playwright chromium y valida tu `.env`.

Atajos en la raíz del repo:

- **`Probar-Worker.bat`** — ventana de escritorio (WebView)
- **`Probar-Worker-Navegador.bat`** — abre http://127.0.0.1:8766 + servidor

## Probar sin instalador (recomendado mientras desarrollas)

Desde la raíz del repo, con tu `.env` local:

```powershell
.\scripts\run-worker-dev.ps1
```

Abre ventana **AgenteBc Worker** (WebView) con lenguaje natural, presets y preview.
Usa el `.env` del proyecto (`AGENTEBC_ENV_FILE`).

Solo HTTP en el navegador:

```powershell
.\scripts\run-worker-dev.ps1 -NoWindow
# o: agentebc-worker serve --port 8766
```

Dependencias: `pip install -e ".[desktop,windows-auth]"` y `playwright install chromium`
(o `AGENTEBC_BROWSER_CHANNEL=chrome`).

## Skills (repartir trabajos sin programar)

Un **skill** (`.skill.json`) define empresa, tipo, acción, filtros OData,
campos del informe y correos. Incluido de ejemplo:

- `config/skills/malla_publicidad_facturar_ventas.skill.json` — ventas Malla,
  «Esperar Orden Cliente» = false, fecha hasta hoy o fin de mes, informe
  nº documento / nº contrato, correos del usuario.

En la UI del worker: **Editor de skills** (`/skills`) para crear otros sin
tocar Python. Los skills del usuario se guardan en
`%LOCALAPPDATA%\AgenteBC\worker\skills\`.

Tras ejecutar un lote **desde un skill** (preview con skill → Ejecutar):

1. Informe JSON en `%LOCALAPPDATA%\AgenteBC\worker\reports\`
2. Resumen con **LM Studio** (o DeepSeek API) si `AGENTEBC_AI_PROVIDER` está activo
3. **Correo** a los destinatarios del skill si el lote fue registro real y SMTP está
   configurado (`AGENTEBC_SMTP_*` en `.env`)

En la UI marque «Tras el lote: informe + IA + correo (skill)».

Ver `config/skills/README.md`.

## Ejecutable Windows (Worker solo)

No incluye la app de diagnóstico consultor (`AgenteBc.exe`):

```powershell
.\scripts\build-worker.ps1
```

Salida: `dist\AgenteBcWorker.exe`. Config en `%LOCALAPPDATA%\AgenteBC\.env`
(copia tu OData, `AGENTEBC_WEB_BASE_URL`, usuario/contraseña web).

El instalador completo del consultor sigue siendo `.\scripts\build-desktop.ps1`.

## Lenguaje natural

Compilar instrucción → JobSpec (primero reglas; si falla, IA con `lm_studio` o
`deepseek` API):

```powershell
agentebc-worker plan "Registrar las facturas de venta de Malla Publicidad de septiembre"
agentebc-worker plan "Registrar ventas de Malla del mes en curso" --preview --save-pending
agentebc-worker plan "..." --llm
```

Menciones opcionales: `@sales_invoice`, `@registrar_factura`, `@facturas_venta`.

Filtros dinámicos reconocidos en frases: **mes en curso**, **año en curso**, meses
por nombre (septiembre, …) con año opcional.

## Vista previa (CLI)

Con preset predefinido y empresa:

```powershell
agentebc-worker preview --preset sales_invoice_register_current_month --company "Malla Publicidad" --save-pending
```

Manual con mes en curso:

```powershell
agentebc-worker preview --company "Malla Publicidad" --type-id sales_invoice --action-id registrar_factura --date-dynamic current_month
```

Por defecto `dry_run` está activo. Para planificar ejecución real en el preview:

```powershell
agentebc-worker preview --preset sales_invoice_register_current_month --company "Malla Publicidad" --no-dry-run --save-pending
```

## Guardar preset tras revisar

```powershell
agentebc-worker preset-save --from-pending --name "Ventas mes Malla"
```

Los presets guardados viven en `{user_root}/worker/presets.json`. Los predefinidos
están en `config/worker_presets.json` (solo lectura; al guardar se copian al usuario).

## Ejecutar (requiere confirmación explícita)

```powershell
agentebc-worker run --confirm yes --pending
```

## UI web mínima

```powershell
agentebc-worker serve --port 8766
```

Abrir `http://127.0.0.1:8766/`.

## Filtros dinámicos

| Id | Significado |
|----|-------------|
| `current_month` | Del día 1 al último día del mes local |
| `current_year` | Del 1 ene al 31 dic del año local |

Referencia opcional en preview: `--reference-date 2026-09-15`.

## Resumen IA en el informe (LM Studio)

El correo/informe tras un lote puede incluir un resumen generado por IA. Usa
**parámetros propios del worker**, distintos de la IA web del consultor:

| Variable | Uso |
|----------|-----|
| `AGENTEBC_WORKER_AI_PROVIDER` | `lm_studio` (recomendado) o `deepseek` |
| `AGENTEBC_WORKER_LM_STUDIO_URL` | API OpenAI-compatible de LM Studio (p. ej. `http://127.0.0.1:1234/v1`) |
| `AGENTEBC_WORKER_LM_STUDIO_MODEL` | Modelo cargado en LM Studio (opcional; si falta, usa `AGENTEBC_LM_STUDIO_MODEL`) |

Si no define `WORKER_*`, se usa `AGENTEBC_LM_STUDIO_URL` cuando exista. Con
`AGENTEBC_AI_PROVIDER=deepseek_web` en el consultor, **hay que** configurar LM
Studio para el worker o el informe dirá que la IA no está disponible.

LM Studio debe estar en marcha con el servidor local activado antes del lote.

## Configuración

Usa el mismo `.env` que AgenteBc:

- `AGENTEBC_ODATA_BASE_URL` — listados OData (worker preview, diagnóstico).
- `AGENTEBC_WEB_BASE_URL` — **opcional**; base del cliente web para Playwright
  (sin `/ODataV4`). Si OData está en `:7048` y el navegador en `:8080`, define
  por ejemplo `http://localhost:8080/BC270`.
- Credenciales web (`AGENTEBC_USERNAME` / `AGENTEBC_PASSWORD`) para el login en
  Playwright; OData puede usar `AGENTEBC_AUTH_MODE=windows` aparte.

## Fiabilidad del registro (informe ↔ BC)

Tras cada factura con acción **Registrar**, el worker:

1. Solo acepta éxito web si el resultado es `completed` y aparece el diálogo de
   «factura registrada» (o reintenta si no).
2. Comprueba OData (`Status` Open / `Posting_No`) con esperas de hasta ~14 s.
3. Reconcilia el lote al final: un «success» sin registro real pasa a **error**;
   un «error» con documento ya registrado en OData pasa a **success**.

Auditoría manual de un informe:

```powershell
$env:AGENTEBC_ENV_FILE = ".env"
python scripts/verify_batch_odata.py --batch-report worker\reports\<informe>.json
```

Lote de prueba sin correo:

```powershell
python scripts/run_integration_batch.py 5 worker\jobs\integration_from_15.json
```

Muchos errores de BC del tipo *«serie V-FAC+ en una fecha anterior a …»* se
evitan configurando en el skill **Antes de registrar → Fecha registro** =
`today` o `end_of_month` (`before_action_field_edits` en el JSON). El worker
edita la ficha, guarda y luego pulsa Registrar.
