# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the HM Bridge Windows agent (windowed, one-file exe).

Built on Windows via ``build_win.bat``. The MetaTrader5 package ships its
loader DLL next to the Python module — bundle it explicitly so the frozen
exe can still find it.
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
    ["agent_app.py"],
    pathex=[],
    binaries=_mt5_libs,
    datas=[("assets", "assets")],
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
    a.binaries,
    a.datas,
    [],
    name="HM_Bridge_Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
    version="installer/version_info.txt",
)
