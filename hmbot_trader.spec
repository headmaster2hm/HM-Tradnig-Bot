# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the HM Bot Trader dashboard (console exe, one-folder build).

Built on Windows via ``build_installer.ps1`` / ``build_installer.bat``, then
wrapped into ``HMBotTrader-Setup.exe`` by Inno Setup.

The MetaTrader5 package ships a native ``_core*.pyd`` next to its Python
module — bundle it explicitly so the frozen exe can still load it.
"""

import os

import MetaTrader5 as _mt5  # available at build time on Windows

_mt5_dir = os.path.dirname(_mt5.__file__)
_mt5_libs = [
    (os.path.join(_mt5_dir, fname), "MetaTrader5")
    for fname in os.listdir(_mt5_dir)
    if fname.endswith((".dll", ".pyd"))
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=_mt5_libs,
    datas=[
        ("config/settings.dist.json", "config"),
        ("dashboard/web", "dashboard/web"),
        ("assets", "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HMBotTrader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
    version="installer/hmbot_version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HMBotTrader",
)
