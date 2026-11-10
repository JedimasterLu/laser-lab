"""py2app configuration producing ``dist/LaserScan.app``.

Build after ``pip install ".[scan]" py2app``. Run it from ``packaging/``, because py2app rejects
the ``install_requires`` that setuptools derives from the repository's pyproject.toml::

    python packaging/make_icns.py          # optional: packaging/laserscan.icns
    cd packaging && python setup_macos.py py2app --dist-dir ../dist
    python postprocess_macos.py ../dist/LaserScan.app

The stage and shutter drivers only talk to real instruments from Windows; on macOS the app runs with
simulated devices, which is what the bundle is for.
"""

import re
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "packaging" / "laserscan.icns"

OPTIONS = {
    "argv_emulation": False,  # would interfere with the GUI event loop
    "packages": [
        "laserscan",  # includes web/ and assets/
        "numpy",
        "shapely",
        "svgelements",
        "ezdxf",
        "fontTools",  # ezdxf
        "pyparsing",  # ezdxf
        "typing_extensions",
        "gdstk",
        "PIL",
        "potrace",
        "serial",
        "webview",
        "bottle",  # pywebview's static file server
        "proxy_tools",
    ],
    # laserlab exports its classes lazily, so the static analysis cannot see these.
    "includes": [
        "laserlab.stage", "laserlab.shutter", "laserlab.mock",
        "objc", "Foundation", "AppKit", "WebKit", "Quartz", "PyObjCTools",
    ],  # fmt: skip
    "excludes": [
        "tkinter", "IPython", "ipykernel", "pytest", "scipy", "pandas", "matplotlib", "cv2", "slmsuite", "torch",
        "skia", "PyQt5", "PyQt6", "PySide2", "PySide6",
    ],  # fmt: skip
    "plist": {
        "CFBundleName": "LaserScan",
        "CFBundleDisplayName": "LaserScan",
        "CFBundleIdentifier": "io.github.laserlab.laserscan",
        "CFBundleShortVersionString": "0.0.0",  # replaced from laserscan.__version__ below
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
}
if ICON.exists():
    OPTIONS["iconfile"] = str(ICON)

init = (ROOT / "src" / "laserscan" / "__init__.py").read_text(encoding="utf-8")
OPTIONS["plist"]["CFBundleShortVersionString"] = re.search(r'__version__ = "([^"]+)"', init).group(1)

setup(
    name="LaserScan",
    app=[str(ROOT / "packaging" / "launcher.py")],
    options={"py2app": OPTIONS},
)
