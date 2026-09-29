# AgenteBc Worker — instalador, portal y skills

Aplicación de **registro en lote** (portal `/portal`, skills, informes). Misma versión
que AgenteBc (`agentebc.__version__`).

## Build del instalador

```powershell
.\scripts\build-worker.ps1
```

Genera:

- `dist\AgenteBcWorker.exe`
- `packaging\releases\AgenteBcWorker-X.Y.Z-setup.exe` (si Inno Setup 6 está instalado)

Alinea `#define MyAppVersion` en `packaging/agentebc-worker.iss` con la versión del paquete.

## Publicar en el portal (IIS)

Mismo token que acciones compartidas: `AGENTEBC_SHARE_TOKEN`.

```powershell
python scripts/publish_release.py --product worker packaging/releases/AgenteBcWorker-0.2.7-setup.exe
```

Manifiesto público: `https://agentebc.malla.es/releases/worker-latest.json`

Agente desktop sigue usando `latest.json` y `--product agente` (por defecto).

## Publicar un skill

```powershell
python scripts/publish_skill.py config/skills/malla_publicidad_facturar_ventas.skill.json --note "Malla producción"
```

API: `POST /api/skills/share` (JSON + cabecera `X-AgenteBc-Share-Token`).

## Usuario final

1. Instalar **AgenteBc Worker** desde el portal o el `.exe` de setup.
2. Abrir la app (WebView → `/portal`).
3. Configurar `.env` en `%LOCALAPPDATA%\AgenteBC\` (OData, web BC, auth) o usar `connection` en el skill.
4. En el Worker: **Buzón de skills** (`/skills/inbox`) si el consultor publicó skills al portal
   (`AGENTEBC_SHARE_URL` + `AGENTEBC_SHARE_TOKEN` en el `.env` del usuario).

Variables útiles:

```env
AGENTEBC_SHARE_URL=https://agentebc.malla.es
AGENTEBC_SHARE_TOKEN=...
AGENTEBC_WORKER_UPDATE_MANIFEST_URL=https://agentebc.malla.es/releases/worker-latest.json
AGENTEBC_WORKER_SKILLS_SHARE_DIR=   # en servidor IIS: carpeta de skills compartidos
```

En el servidor IIS, `AGENTEBC_WORKER_SKILLS_SHARE_DIR` apunta a la carpeta donde
`POST /api/skills/share` guarda los JSON pendientes.
