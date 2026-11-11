"""PyInstaller entry point for the LaserScan executable."""

import os
import sys
import traceback
from pathlib import Path

from laserscan.cli import log_path, main


def _unblock_bundle() -> None:
    """Strip the "downloaded from the internet" mark (Zone.Identifier) from the bundled DLLs.

    A zip downloaded from GitHub and extracted with Explorer marks every file inside. .NET Framework then refuses to
    load the marked ``Python.Runtime.dll`` and pywebview dies with "Failed to resolve Python.Runtime.Loader.Initialize".
    This must run before pywebview imports pythonnet (``clr``).
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for path in root.rglob("*"):
        if path.suffix.lower() in {".dll", ".pyd"}:
            try:
                os.remove(f"{path}:Zone.Identifier")
            except OSError:
                pass  # not marked, or the file system has no alternate data streams


def _report_fatal() -> None:
    """Tell the user why the build died, since there is no console to show it."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, f"LaserScan failed to start.\nDetails: {path}", "LaserScan", 0x10)


if __name__ == "__main__":
    try:
        _unblock_bundle()
        main()
    except Exception:
        _report_fatal()
        raise
