# AgenteBc Desktop

Aplicación de escritorio para consultores de Malla. Ejecuta AgenteBc en el PC del
usuario con CDP local (Google Modo IA / DeepSeek web) y ventana propia WebView2.

## Desarrollo local

```powershell
pip install -e ".[desktop,dev]"
agentebc-desktop
```

La primera vez crea:

- `%LOCALAPPDATA%\AgenteBC\.env` (copiado desde `.env.example`)
- `%LOCALAPPDATA%\AgenteBC\config\document_types.json`
- `%LOCALAPPDATA%\AgenteBC\reports\`

Edita el `.env` en esa carpeta con credenciales BC, IA, etc.

## Build del instalador

```powershell
.\scripts\build-desktop.ps1
```

1. Genera `dist\AgenteBc.exe` con PyInstaller.
2. Abre `packaging\agentebc.iss` en **Inno Setup** y compila.
3. Obtienes `AgenteBc-0.2.0-setup.exe`.

## Publicación y actualizaciones

Publica en el servidor:

- `https://agentebc.malla.es/releases/latest.json`
- `https://agentebc.malla.es/releases/AgenteBc-x.y.z-setup.exe`

Plantilla: `packaging/releases/latest.json.example`

Al iniciar, la app consulta el manifiesto. Si hay versión nueva, pregunta si
descargar e instalar. Opcional en `.env`:

```env
AGENTEBC_UPDATE_MANIFEST_URL=https://agentebc.malla.es/releases/latest.json
```

## Portal web de descarga

Prueba local del portal (como `https://agentebc.malla.es`):

```powershell
pip install -e .
agentebc-portal
```

Abre `http://127.0.0.1:8765` (el 8080 suele estar ocupado por IIS/BC).

La app instalada **no depende** del portal para funcionar; solo para descargas
y comprobar actualizaciones.

## Despliegue en el servidor (IIS)

AgenteBc en servidor **no es** la misma app que en el PC del consultor:

| Dónde | Qué se ejecuta | Para qué |
|-------|----------------|----------|
| **Servidor** (`agentebc.malla.es`) | Portal de descarga (`wsgi.py`) | Página de descarga + `/releases/` |
| **PC del consultor** | App de escritorio (`AgenteBc.exe`) | Diagnóstico BC + IA local |

Al abrir `https://agentebc.malla.es` debe verse la pantalla de descarga (como en
`http://127.0.0.1:8765` en local). El diagnóstico BC **no** va en el servidor.

### Integración con appdesktop (apps.malla.es)

En [App Malla Desktop](https://apps.malla.es/admin/apps) la app **agentebc** debe tener:

- **wwwroot:** `C:\inetpub\wwwroot\AgenteBc`
- **app_pool:** `AgenteBc`
- **Repo:** `AndreuSerraCandela/AgenteBc`

Botones del panel:

1. **Licencia** → registra la app en licence.malla.es (MyBeLic).
2. **Webhook** → despliegue automático en cada push a `main`.
3. **Desplegar ahora** → primera instalación manual.

El deploy (`Deploy-App.ps1`) copia el código con `robocopy`, ejecuta
`pip install -r requirements.txt` y recicla el app pool. **No** sube el `.exe`
del instalador (va aparte).

### Pasos (igual que Rutas, RoadBook, etc.)

Ficheros de despliegue en la raíz del proyecto:

| Fichero | Uso |
|---------|-----|
| `web.config` | HttpPlatformHandler + `AGENTEBC_RELEASES_DIR` |
| `wsgi.py` | Portal + waitress cuando IIS asigna puerto |
| `requirements_web.txt` | Flask y waitress (sin Playwright) |
| `install_web_iis.bat` | Instala en `C:\Python\python.exe` del servidor |

1. **Copiar el proyecto** al servidor (carpeta del sitio IIS).

2. **Editar `web.config`** si hace falta:
   - `processPath` → Python de IIS (suele ser `C:\Python\python.exe`)
   - `AGENTEBC_RELEASES_DIR` → carpeta con `latest.json` y el `.exe` (por defecto `.\releases`)

3. **Ejecutar en el servidor** (como administrador, en la carpeta del sitio):

   ```bat
   install_web_iis.bat
   ```

4. **Copiar los instaladores** a `releases\`:

   ```
   packaging/releases/latest.json   →  releases/latest.json
   packaging/releases/AgenteBc-*.exe  →  releases/
   ```

5. **Crear el sitio en IIS** apuntando a la carpeta del proyecto (donde está
   `web.config`). Si necesitas el diagnóstico web en otro sitio interno, usa
   `wsgi_diagnose.py` en lugar de `wsgi.py`.

6. **Carpeta de releases del instalador** (fuera del código git, recomendado):

   ```
   C:\inetpub\data\AgenteBc\releases\
   ```

   En `web.config` del servidor:

   ```xml
   <environmentVariable name="AGENTEBC_RELEASES_DIR" value="C:\inetpub\data\AgenteBc\releases" />
   ```

   Copia manualmente (no van en git):

   - `latest.json`
   - `AgenteBc-x.y.z-setup.exe`

7. **Comprobar** que responden:

   - `https://agentebc.malla.es/` → pantalla de descarga
   - `https://agentebc.malla.es/releases/latest.json` → manifiesto JSON
   - `https://agentebc.malla.es/releases/AgenteBc-0.2.0-setup.exe` → instalador

### Primera instalación (checklist)

| Paso | Dónde | Qué hacer |
|------|-------|-----------|
| 1 | IIS | Crear sitio `agentebc.malla.es`, app pool `AgenteBc`, carpeta `C:\inetpub\wwwroot\AgenteBc` |
| 2 | appdesktop | Alta de app `agentebc` con wwwroot y app_pool (ya en catálogo) |
| 3 | appdesktop | Botón **Licencia** (MyBeLic) |
| 4 | appdesktop | Botón **Desplegar ahora** o push a `main` con webhook |
| 5 | Servidor | Copiar `latest.json` + `.exe` a `C:\inetpub\data\AgenteBc\releases\` |
| 6 | Navegador | Abrir `https://agentebc.malla.es` y probar descarga |

### Al publicar una versión nueva

1. En tu PC: `.\scripts\build-desktop.ps1`
2. Copia al servidor `latest.json` y el `.exe` nuevos (misma carpeta `releases`)
3. El `download_url` de `latest.json` debe usar la URL pública del servidor

No hace falta reiniciar la app de escritorio de los consultores; ellos reciben
la actualización al abrir AgenteBc (consulta `latest.json`).

## CDP e IA web

Con la app de escritorio, `AGENTEBC_AI_WEB_CDP_URL=http://127.0.0.1:9222` se
resuelve en el PC del consultor. Chrome y login de Google/DeepSeek son locales.

## Modos de ejecución

| Comando | Uso |
|---------|-----|
| `agentebc-desktop` | App de escritorio (recomendado consultores) |
| `agentebc-web` | Servidor Flask en navegador (desarrollo) |
| `agentebc check-config` | CLI diagnóstico |
