# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec producing a one-folder LaserScan build.

Build from the repository root with a runtime-only environment::

    uv sync --no-dev --extra scan --group build
    uv run --no-sync pyinstaller packaging/laserscan.spec --noconfirm

``--no-sync`` stops ``uv run`` from re-installing the dev dependency group.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH is injected by PyInstaller)

# Installed in developer environments or pulled in by extras, but never used by LaserScan.
EXCLUDES = [
    "tkinter",
    "_tkinter",
    "matplotlib",
    "IPython",
    "ipykernel",
    "pytest",
    "scipy",
    "pandas",
    "skia",
    "slmsuite",
    "cv2",
    "torch",
    "gymnasium",
    "stable_baselines3",
    "trackpy",
    "pyglet",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

# Files inside the Qt tree that the app never loads.
DROP_BINARIES = (
    "opengl32sw.dll",  # 20 MB software OpenGL; Chromium renders through ANGLE/D3D
    "Qt6Pdf",
    "Qt6Designer",
    "Qt6Quick3D",
    "Qt63D",
    "Qt6Charts",
    "Qt6Multimedia",
)
DROP_DATAS = (
    "qtwebengine_devtools_resources.pak",  # Chromium DevTools UI; the context menu is disabled
)


def keep_binary(entry):
    name = Path(entry[0]).name
    return not any(name.startswith(prefix) or name == prefix for prefix in DROP_BINARIES)


def keep_data(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if name in DROP_DATAS or name.endswith(".qm"):  # Qt translations
        return False
    if "/qtwebengine_locales/" in dest and name != "en-US.pak":  # Chromium needs only one locale
        return False
    return True


a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src" / "laserscan" / "web"), "laserscan/web"),
        (str(ROOT / "src" / "assets"), "laserscan/assets"),
    ],
    # laserlab exports its classes lazily, so the static analysis cannot see these.
    hiddenimports=["laserlab.stage", "laserlab.shutter", "laserlab.mock"],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,  # strip asserts and docstrings from bytecode
)
a.binaries = [b for b in a.binaries if keep_binary(b)]
a.datas = [d for d in a.datas if keep_data(d)]
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LaserScan",
    icon=str(ROOT / "packaging" / "laserscan.ico"),
    console=False,  # no terminal window; output goes to a log file
    upx=False,  # UPX increases antivirus false positives
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LaserScan",
)
