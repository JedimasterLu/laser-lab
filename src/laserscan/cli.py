"""Command-line entry point: ``laserscan``."""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence

from laserscan import __version__


def main(argv: Sequence[str] | None = None) -> None:
    """Start the application.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.
    """
    parser = argparse.ArgumentParser(prog="laserscan", description="Draw and run laser scan paths.")
    parser.add_argument("--simulate", action="store_true", help="Start with simulated devices connected.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from laserscan.main_window import MainWindow
    from laserscan.session import SESSION
    from laserscan.theme import STYLE

    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    for effect in (Qt.UI_AnimateMenu, Qt.UI_FadeMenu, Qt.UI_AnimateCombo, Qt.UI_AnimateTooltip, Qt.UI_FadeTooltip):
        app.setEffectEnabled(effect, False)
    app.setStyleSheet(STYLE)
    app.aboutToQuit.connect(lambda: SESSION.shutdown("application quit"))
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    window = MainWindow(simulate=args.simulate)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
