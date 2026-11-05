"""PyInstaller entry point for the LaserScan executable."""

import os
import sys
import traceback
from pathlib import Path


def log_path() -> Path:
    """Return the file that receives console output and fatal errors of the windowed build."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
    return base / "LaserScan" / "laserscan.log"


def _redirect_streams() -> None:
    """A windowed build has no console, so ``sys.stderr`` is ``None``; send it to a log file."""
    if sys.stderr is None or sys.stdout is None:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115  (lives as long as the process)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def _report_fatal() -> None:
    """Tell the user why the build died, since there is no console to show it."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, f"LaserScan failed to start.\nDetails: {path}", "LaserScan", 0x10)


def _self_test() -> int:
    """Import every lazily loaded module and load the web UI once; used by CI to check the bundle."""
    import importlib

    for name in (
        "shapely.geometry", "shapely.ops", "shapely.affinity", "svgelements", "ezdxf", "gdstk",
        "PIL.Image", "potrace", "serial.tools.list_ports", "laserlab.stage", "laserlab.shutter",
        "laserlab.mock", "PySide6.QtSvg", "PySide6.QtWebChannel",
    ):  # fmt: skip
        importlib.import_module(name)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from laserscan.main_window import MainWindow, app_icon

    app = QApplication(sys.argv[:1])
    if app_icon() is None or app_icon().isNull():
        print("self-test: icon missing", file=sys.stderr)
        return 1
    window = MainWindow(simulate=True)
    result = {"ok": None}

    def finished(ok: bool) -> None:
        result["ok"] = ok
        app.quit()

    window.view.loadFinished.connect(finished)
    QTimer.singleShot(60_000, app.quit)
    window.show()
    app.exec()
    print(f"self-test: page load ok={result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    _redirect_streams()
    try:
        if "--self-test" in sys.argv:
            sys.exit(_self_test())
        from laserscan.cli import main

        main()
    except Exception:
        _report_fatal()
        raise
