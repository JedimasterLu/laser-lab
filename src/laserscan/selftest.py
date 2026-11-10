"""Sanity check of an installed or bundled build (``laserscan --selftest``).

Imports every lazily loaded module, checks that the web page's files are present, plans a small scan through the
API, then opens the real window, waits for the page to build itself and runs the page's own checks (Paper.js
drawing, shape round trip) inside the web view.

Set ``LASERSCAN_SELFTEST_HEADLESS=1`` to skip the window: the macOS runners of GitHub Actions have no usable window
session (the web view never finishes loading there), so that job checks everything but the window.
"""

from __future__ import annotations

import importlib
import os
import threading
import time
import traceback

MODULES = (
    "shapely.geometry", "shapely.ops", "shapely.affinity", "svgelements", "ezdxf", "gdstk",
    "PIL.Image", "potrace", "serial.tools.list_ports", "laserlab.stage", "laserlab.shutter",
    "laserlab.mock", "webview",
)  # fmt: skip
SQUARE = {"type": "path", "path": "M0,0L400,0L400,300L0,300Z", "op": "add"}
PAGE_TIMEOUT_S = 90


WEB_FILES = (
    "index.html", "css/theme.css", "vendor/paper-core.min.js", "js/shapes.js", "js/canvas.js", "js/ui.js", "js/app.js",
)  # fmt: skip


def _check_assets() -> None:
    from laserscan.desktop import WEB_DIR

    missing = [name for name in WEB_FILES if not (WEB_DIR / name).is_file()]
    if missing:
        raise RuntimeError(f"web files missing from the build: {missing}")


def _check_api() -> None:
    from laserscan.api import Api

    api = Api(simulate=True)
    info = api.init()
    if not info["patterns"]:
        raise RuntimeError("the API reports no scan patterns")
    result = api.replan([SQUARE], info["params"])
    if not result["plan"] or result["problems"]:
        raise RuntimeError(f"planning a square failed: {result['problems']}")


def _check_window() -> None:
    """Open the window, wait for ``window.__ready`` and run ``window.__selftest()`` in the page."""
    import webview

    from laserscan import desktop
    from laserscan.api import Api

    api = Api(simulate=True)
    window = desktop.create_window(api)
    outcome: dict[str, object] = {}

    def probe() -> None:
        try:
            deadline = time.monotonic() + PAGE_TIMEOUT_S
            while not window.evaluate_js("window.__ready === true"):
                if time.monotonic() > deadline:
                    raise RuntimeError("the page did not finish loading")
                time.sleep(0.5)
            outcome["report"] = window.evaluate_js("window.__selftest()")
        except Exception:  # noqa: BLE001  (reported through the outcome)
            outcome["error"] = traceback.format_exc()
        finally:
            window.destroy()

    webview.start(probe)
    if "error" in outcome:
        raise RuntimeError(str(outcome["error"]))
    report = outcome.get("report")
    if not isinstance(report, dict) or report.get("failures"):
        raise RuntimeError(f"page self-test failed: {report}")
    print(f"page self-test: {report['passed']} checks passed")


def run() -> int:
    """Run the checks, printing the outcome.

    Returns:
        Process exit code: 0 on success.
    """
    timer = threading.Timer(PAGE_TIMEOUT_S + 60, lambda: (print("SELFTEST TIMEOUT", flush=True), os._exit(2)))
    timer.daemon = True
    timer.start()
    try:
        for name in MODULES:
            importlib.import_module(name)
        _check_assets()
        _check_api()
        if os.environ.get("LASERSCAN_SELFTEST_HEADLESS"):
            print("window check skipped (LASERSCAN_SELFTEST_HEADLESS)")
        else:
            _check_window()
    except Exception:  # noqa: BLE001  (any failure is a failed self-test)
        print("SELFTEST FAILED")
        traceback.print_exc()
        return 1
    print("SELFTEST OK")
    return 0
