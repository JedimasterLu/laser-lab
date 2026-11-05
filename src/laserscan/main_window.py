"""Main window: a native window hosting the web user interface (QtWebEngine)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QUrl, Qt
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QMessageBox

from laserscan.bridge import Bridge
from laserscan.session import SESSION

WEB_DIR = Path(__file__).parent / "web"


class Page(QWebEnginePage):
    """Page that forwards JavaScript console output to stderr."""

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        print(f"[js] {message} ({Path(source).name}:{line})", file=sys.stderr)


class MainWindow(QMainWindow):
    """The LaserScan window."""

    def __init__(self, simulate: bool = False) -> None:
        """Build the window.

        Args:
            simulate: Use simulated devices instead of the real instruments.
        """
        super().__init__()
        self.s = SESSION
        self.setWindowTitle("LaserScan")
        height = min(860, self.screen().availableGeometry().height() - 40)
        self.resize(1360, height)
        self.setMinimumSize(1100, 640)
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.page = Page(self.view)
        self.page.setBackgroundColor(QColor("#f3f4f6"))
        self.view.setPage(self.page)
        self.bridge = Bridge(self, simulate)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))
        self.view.installEventFilter(self)
        self.view.loadFinished.connect(self._watch_gestures)

    def _watch_gestures(self) -> None:
        """Web content receives events through a child widget of the view; watch that one too."""
        proxy = self.view.focusProxy()
        if proxy is not None:
            proxy.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        """Turn a trackpad pinch (a native gesture) into a canvas zoom instead of a page zoom."""
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            at = self.view.mapFromGlobal(event.globalPosition().toPoint())
            self.page.runJavaScript(f"window.__pinch && window.__pinch({event.value()}, {at.x()}, {at.y()})")
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        if self.s.executor.running and QMessageBox.question(
            self,
            "Scan running",
            "A scan is running. Closing will abort it and close the shutter. Close anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return event.ignore()
        self.s.shutdown("window closed")
        event.accept()
