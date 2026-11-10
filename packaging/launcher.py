"""PyInstaller entry point for the LaserScan executable."""

import sys
import traceback

from laserscan.cli import log_path, main


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
        main()
    except Exception:
        _report_fatal()
        raise
