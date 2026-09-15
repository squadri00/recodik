# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Recodik desktop executable.

Build:  pyinstaller myvault.spec
Output: dist/Recodik  (dist/Recodik.exe on Windows)

PyInstaller does NOT cross-compile: build the Windows .exe on Windows, the macOS
binary on macOS, the Linux binary on Linux.
"""

from PyInstaller.utils.hooks import collect_submodules

# --- version info: generated from myvault.__version__, the one source of
# truth also shown in the app's own footer -- so the two can never drift
# apart the way a hand-maintained version_info.txt would. ---
import sys as _sys

_sys.path.insert(0, ".")
from myvault import __version__ as _app_version

_ver_parts = [int(p) for p in _app_version.split(".")] + [0, 0, 0, 0]
_filevers = tuple(_ver_parts[:4])
_verstr = ".".join(str(p) for p in _filevers)

with open("version_info.txt", "w", encoding="utf-8") as _f:
    _f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_filevers},
    prodvers={_filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Eformics Systems'),
        StringStruct(u'FileDescription', u'Recodik - self-hosted record keeper'),
        StringStruct(u'FileVersion', u'{_verstr}'),
        StringStruct(u'InternalName', u'Recodik'),
        StringStruct(u'LegalCopyright', u'Copyright (c) Eformics Systems'),
        StringStruct(u'OriginalFilename', u'Recodik.exe'),
        StringStruct(u'ProductName', u'Recodik'),
        StringStruct(u'ProductVersion', u'{_verstr}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""")

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
    "myvault.richtext",
    "myvault.alerts",
    "myvault.backup",
    "markdown.extensions.nl2br",
] + collect_submodules("waitress") + collect_submodules("markdown.extensions")

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
    name="Recodik",
    version="version_info.txt",
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
