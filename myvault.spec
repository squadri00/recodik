# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Recodik desktop executable.

Build:  pyinstaller myvault.spec
Output: dist/Recodik-<version>-<build date>.exe (Windows)

PyInstaller does NOT cross-compile: build the Windows .exe on Windows, the macOS
binary on macOS, the Linux binary on Linux.
"""

import os
from datetime import datetime, timezone

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

# The built exe's own filename carries the version + build date, so anyone
# looking at the file (e.g. on the download server) can tell at a glance
# whether it's the current build without opening it.
_build_date = datetime.now(timezone.utc).strftime("%Y%m%d")
_exe_name = f"Recodik-{_app_version}-{_build_date}"

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
        StringStruct(u'OriginalFilename', u'{_exe_name}.exe'),
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

# Only meaningful on macOS: packaging/mac/recodik.icns, generated from
# myvault/static/recodik-logo.png by the CI build step (see
# .github/workflows/build-macos.yml) before pyinstaller runs. Absent on
# Windows/Linux builds, so icon stays None there exactly as before.
_icns = os.path.join("packaging", "mac", "recodik.icns")
_icon = _icns if _sys.platform == "darwin" and os.path.exists(_icns) else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=_exe_name,
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
    icon=_icon,
)

# macOS only: wrap the raw executable in a double-clickable Recodik.app so it
# behaves like a normal Mac application in Finder/Launchpad. Windows and
# Linux builds stop at the EXE() above, unchanged from before.
if _sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name=f"{_exe_name}.app",
        icon=_icon,
        bundle_identifier="com.eformics.recodik",
        info_plist={
            "CFBundleName": "Recodik",
            "CFBundleDisplayName": "Recodik",
            "CFBundleShortVersionString": _verstr,
            "CFBundleVersion": _verstr,
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Copyright (c) Eformics Systems",
        },
    )
