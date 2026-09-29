# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "config" / "document_types.json"), "config"),
    (str(ROOT / "config" / "worker_presets.json"), "config"),
    (str(ROOT / "config" / "skills"), "config/skills"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "packaging" / "agentebc.ico"), "."),
]

hiddenimports = [
    "agentebc",
    "agentebc_worker",
    "agentebc_worker.cli",
    "agentebc_worker.webapp",
    "agentebc_worker.desktop",
    "agentebc_worker.runner",
    "agentebc_worker.natural_language",
    "agentebc.config",
    "agentebc.web_preview",
    "agentebc.bc_client",
    "agentebc.documents",
    "agentebc.document_types",
    "flask",
    "jinja2",
    "playwright",
    "requests",
    "requests_negotiate_sspi",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "werkzeug",
    "clr",
]

a = Analysis(
    [str(ROOT / "src" / "agentebc_worker_frozen_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AgenteBcWorker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "agentebc.ico"),
)
