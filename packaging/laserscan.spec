# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec producing a one-folder LaserScan build for Windows.

The window is pywebview on the system's Edge WebView2 runtime, so no browser engine is bundled.

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
    # pywebview offers Qt / GTK / CEF back ends; Windows uses WebView2 only.
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "gi",
    "cefpython3",
]

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
