# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "config" / "document_types.json"), "config"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "src" / "agentebc" / "templates"), "agentebc/templates"),
    (str(ROOT / "packaging" / "agentebc.ico"), "."),
]

hiddenimports = [
    "agentebc",
    "agentebc.desktop",
    "agentebc.updater",
    "agentebc.paths",
    "agentebc.env_store",
    "agentebc.webapp",
    "agentebc.google_ai_web",
    "agentebc.deepseek_web",
    "agentebc.ai_web_cdp",
    "agentebc.llm_conclusions",
    "agentebc.web_preview",
    "agentebc.config",
    "flask",
    "jinja2",
    "playwright",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "werkzeug",
    "clr",
]

a = Analysis(
    [str(ROOT / "src" / "agentebc_desktop_entry.py")],
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
    name="AgenteBc",
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
