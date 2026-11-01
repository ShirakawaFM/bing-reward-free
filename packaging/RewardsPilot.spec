# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
datas = playwright_datas + [
    (str(ROOT / "web" / "dist"), "web/dist"),
    (str(ROOT / "config.example.toml"), "."),
    (str(ROOT / "queries.txt"), "."),
    (str(ROOT / "assets" / "app.ico"), "assets"),
    (str(ROOT / "assets" / "task-browser.ico"), "assets"),
]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=playwright_binaries,
    datas=datas,
    hiddenimports=playwright_hidden + ["pystray._win32"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest", "setuptools", "pip"],
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
    name="RewardsPilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
