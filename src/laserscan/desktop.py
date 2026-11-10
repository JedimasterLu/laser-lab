"""Native window (pywebview) around the web user interface.

pywebview shows ``web/index.html`` in the system web view (WebView2 on Windows, WKWebView on macOS) and exposes
:class:`laserscan.api.Api` to the page as ``window.pywebview.api``. There is no local web server: the page is a
static file and talks to Python through that object only.
"""

from __future__ import annotations

import threading
from pathlib import Path

import webview

from laserscan.api import Api
from laserscan.session import SESSION

WEB_DIR = Path(__file__).parent / "web"
TITLE = "LaserScan"
BACKGROUND = "#f3f4f6"


def _height() -> int:
    """Window height: 860 px, or what fits on the first screen."""
    try:
        return min(860, webview.screens[0].height - 80)
    except Exception:  # noqa: BLE001  (no screen information before the GUI loop starts on some platforms)
        return 860


def create_window(api: Api) -> webview.Window:
    """Create the main window (it is shown by ``webview.start``) and guard it against closing mid-scan.

    Args:
        api: The API exposed to the page.

    Returns:
        The window.
    """
    window = webview.create_window(
        TITLE,
        str(WEB_DIR / "index.html"),
        js_api=api,
        width=1360,
        height=_height(),
        min_size=(1100, 640),
        background_color=BACKGROUND,
        text_select=True,  # the terminal panel is meant to be copied from
    )
    api.attach(window)
    force = threading.Event()

    def ask() -> None:
        """Ask on a separate thread: ``closing`` runs on the GUI thread, where a dialog would deadlock."""
        if window.create_confirmation_dialog(
            "Scan running", "A scan is running. Closing will abort it and close the shutter. Close anyway?"
        ):
            force.set()
            window.destroy()

    def closing() -> bool | None:
        if SESSION.executor.running and not force.is_set():
            threading.Thread(target=ask, daemon=True).start()
            return False  # cancel this close; ``ask`` closes the window if the user agrees
        return None

    window.events.closing += closing
    return window


def run(simulate: bool = False, debug: bool = False) -> None:
    """Open the window and block until it is closed; all devices are closed afterwards.

    Args:
        simulate: Start with simulated devices connected.
        debug: Enable the web inspector.
    """
    api = Api(simulate)
    create_window(api)
    try:
        webview.start(debug=debug)
    finally:
        SESSION.shutdown("window closed")
