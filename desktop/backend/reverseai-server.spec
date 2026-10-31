# PyInstaller spec for the bundled ReverseAI backend.
#
# Build (from desktop/backend/):  pyinstaller reverseai-server.spec --noconfirm
# Produces dist/reverseai-server (a single self-contained executable).
#
# The server reads its UI from reverseai/server/static via __file__, so those
# files are shipped as data at the same package path. The reverseai package is
# collected whole because much of it is imported lazily inside functions.

import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# Ship the UI explicitly (whole tree -> same package path in the bundle). An
# explicit (src_dir, dest_dir) entry is more reliable than collect_data_files
# for a nested directory, which is what the server reads via sys._MEIPASS.
datas = [
    (os.path.join(ROOT, "reverseai", "server", "static"),
     os.path.join("reverseai", "server", "static")),
]

hiddenimports = collect_submodules("reverseai")

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="reverseai-server",
    debug=False,
    strip=False,
    upx=False,
    console=True,          # headless server; stdout/stderr go to the Electron log
    disable_windowed_traceback=False,
)
