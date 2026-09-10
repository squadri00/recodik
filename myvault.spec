# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the MyVault desktop executable.

Build:  pyinstaller myvault.spec
Output: dist/MyVault  (dist/MyVault.exe on Windows)

PyInstaller does NOT cross-compile: build the Windows .exe on Windows, the macOS
binary on macOS, the Linux binary on Linux.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("myvault/templates", "myvault/templates"),
    ("myvault/static", "myvault/static"),
    ("myvault/schema.sql", "myvault"),
]

hiddenimports = [
    "myvault.auth",
    "myvault.categories",
    "myvault.records",
    "myvault.search",
    "myvault.templates_io",
    "myvault.settings",
    "myvault.store",
    "myvault.crypto",
    "myvault.fieldtypes",
    "myvault.util",
    "myvault.db",
    "myvault.paths",
] + collect_submodules("waitress")

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MyVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
