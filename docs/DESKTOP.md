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

### Pasos (igual que otras apps Python en IIS)

1. **Instalar el paquete** en el entorno del sitio:

   ```powershell
   pip install -e .
   ```

2. **Apuntar IIS al WSGI correcto**: `wsgi.py` del proyecto (usa
   `create_portal_app()`, no la app de diagnóstico). Si necesitas el diagnóstico
   web en otro sitio interno, usa `wsgi_diagnose.py`.

3. **Crear carpeta de releases** en el servidor, por ejemplo:

   ```
   D:\webs\agentebc.malla.es\releases\
   ```

4. **Copiar los ficheros** desde tu PC de desarrollo:

   ```
   packaging/releases/latest.json
   packaging/releases/AgenteBc-0.2.0-setup.exe
   ```

5. **Variable de entorno** en el sitio IIS (o en `web.config`):

   ```env
   AGENTEBC_RELEASES_DIR=D:\webs\agentebc.malla.es\releases
   ```

6. **Comprobar** que responden:

   - `https://agentebc.malla.es/` → pantalla de descarga
   - `https://agentebc.malla.es/releases/latest.json` → manifiesto JSON
   - `https://agentebc.malla.es/releases/AgenteBc-0.2.0-setup.exe` → instalador

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
