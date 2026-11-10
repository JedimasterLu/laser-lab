"""Command-line entry point: ``laserscan``."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from laserscan import __version__


def log_path() -> Path:
    """Return where a windowed build writes its console output."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "LaserScan" / "laserscan.log"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "LaserScan" / "laserscan.log"
    return Path.home() / ".laserscan" / "laserscan.log"


def _attach_log() -> None:
    """Send output to a log file when the process has no console (a windowed build has ``sys.stderr`` set to ``None``)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _exit_now(code: int) -> None:
    """Leave the process without waiting for threads.

    The page polls the state ten times a second. When the window is destroyed, pywebview can be left with a
    non-daemon thread that waits forever to deliver the result of such a call to a page that is gone, and Python
    would then wait for it at exit, keeping the serial ports open. The devices are closed before this is called.
    """
    sys.stdout and sys.stdout.flush()
    sys.stderr and sys.stderr.flush()
    os._exit(code)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(prog="laserscan", description="Draw and run laser scan paths.")
    parser.add_argument("--simulate", action="store_true", help="Start with simulated devices connected.")
    parser.add_argument("--debug", action="store_true", help="Enable the web inspector (right-click > Inspect).")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)  # used by CI on built bundles
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Start the application.

    Args:
        argv: Argument list; ``None`` uses ``sys.argv``.
    """
    _attach_log()  # before the heavy imports, some of which touch sys.stdout
    args = parse_args(argv)
    if args.selftest:
        from laserscan import selftest

        _exit_now(selftest.run())
    from laserscan import desktop

    desktop.run(simulate=args.simulate, debug=args.debug)  # closes the devices when the window is closed
    _exit_now(0)


if __name__ == "__main__":
    main()
