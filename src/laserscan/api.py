"""Python side of the web user interface: the object pywebview exposes to the page as ``window.pywebview.api``.

Every public method is callable from JavaScript (``await pywebview.api.replan(shapes, params)``) and returns a
JSON-friendly value. State lives in attributes starting with an underscore, which pywebview neither exposes nor
walks. Calls arrive on worker threads, so the parts that change the session hold ``_lock``; file dialogs do not,
so the page keeps getting state updates while one is open.
"""

from __future__ import annotations

import base64
import io
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from laserscan import __version__, fileio, settings, shapeops
from laserscan.devices import HARDWARE_AVAILABLE, serial_ports
from laserscan.executor import State
from laserscan.planning import (
    PATTERNS,
    Params,
    build_plan,
    clean_shape,
    estimate,
    overrun,
    region_polygons,
    shift,
)
from laserscan.session import SESSION

DEFAULT_PORTS = ("COM3", "COM6")
"""Default (stage, shutter) serial ports of the lab machine."""
# pywebview filters are 'Description (*.ext;*.ext)': the description may hold only letters, digits, "_" and spaces.
IMPORT_TYPES = (
    "Drawings and images (*.svg;*.dxf;*.gds;*.gds2;*.gdsii;*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.webp)",
    "SVG (*.svg)",
    "DXF (*.dxf)",
    "GDSII (*.gds;*.gds2;*.gdsii)",
    "Images (*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.webp)",
    "CSV points (*.csv)",
)
DRAWING_TYPES = ("SVG (*.svg)", "DXF (*.dxf)")
PATH_TYPES = ("CSV (*.csv)", "G code (*.gcode)", "NumPy archive (*.npz)")


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min {secs} s"


def with_suffix(path: str, suffixes: tuple[str, ...], default: str) -> str:
    """Add ``default`` to a file name that has none of the known ``suffixes`` (a dialog does not always add one)."""
    return path if path.lower().endswith(suffixes) else path + default


class Api:
    """Methods the page calls; see the module docstring."""

    def __init__(self, simulate: bool = False) -> None:
        """Create the API.

        Args:
            simulate: Use simulated devices instead of the real instruments.
        """
        self._s = SESSION
        self._simulate = simulate or not HARDWARE_AVAILABLE
        self._profile = settings.load()
        self._window: Any = None
        self._dir = Path.home()  # folder the file dialogs start in: where the last file was
        self._bitmap = None  # grey array of the bitmap being imported
        self._origin: tuple[float, float] = (0.0, 0.0)
        self._motion: tuple[float, float] | None = None
        self._device_msg = ""
        self._seen = 0
        self._lock = threading.RLock()

    def attach(self, window: Any) -> None:
        """Give the API the window it opens dialogs on and titles. Not callable from the page."""
        self._window = window

    # -- helpers -----------------------------------------------------------------

    def _stage_center(self) -> tuple[float, float]:
        (x0, x1), (y0, y1) = self._profile["x_range_um"], self._profile["y_range_um"]
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _refresh_origin(self) -> None:
        """Read the stage position (the plan origin) and its acceleration profile."""
        if self._s.executor.running:
            return
        position = self._s.devices.position_um()
        self._origin = position or (0.0, 0.0)
        self._motion = self._s.devices.motion()

    def _after_connect(self) -> None:
        dev = self._s.devices
        self._profile = dev.profile if dev.connected else settings.load()
        self._refresh_origin()

    @staticmethod
    def _params(data: dict) -> Params:
        params = Params(**data)
        return params if params.pattern in PATTERNS else Params(**{**data, "pattern": Params().pattern})

    def _replan(self, shapes: list[dict], data: dict) -> dict:
        """Build the plan for the current origin and return everything the preview needs."""
        s, params = self._s, self._params(data)
        shapes = [clean_shape(d) for d in shapes]
        problems = []
        try:
            plan = build_plan(shapes, params)
        except ValueError as exc:
            plan = []
            problems.append(str(exc))
        flags, messages = overrun(plan, self._origin, self._profile["x_range_um"], self._profile["y_range_um"])
        if messages:
            problems.append("Path leaves the stage range from the current position: " + "; ".join(messages) + ".")
        s.plan, s.params, s.problems = plan, params, problems
        accel, ramp = self._motion or (None, 0.0)
        on, _off, seconds = estimate(plan, params.speed, accel, ramp)
        basis = "with acceleration" if self._motion else "constant speed, acceleration unknown"
        text = f"{len(plan)} segments · {on / 1000:.2f} mm scanned · {_duration(seconds)} ({basis})" if plan else ""
        region = [
            [list(map(float, c)) for c in ring.coords]
            for poly in region_polygons(shapes)
            for ring in (poly.exterior, *poly.interiors)
        ]
        return {
            "plan": [{"p": np.round(seg.points, 3).tolist(), "l": seg.laser, "bad": bad} for seg, bad in zip(plan, flags)],
            "region": region,
            "estimate": text,
            "problems": problems,
            "origin": list(self._origin),
        }

    def _pick_open(self, types: tuple[str, ...]) -> str | None:
        from webview import FileDialog

        chosen = self._window.create_file_dialog(FileDialog.OPEN, directory=str(self._dir), file_types=types)
        if not chosen:
            return None
        self._dir = Path(chosen[0]).parent
        return str(chosen[0])

    def _pick_save(self, name: str, types: tuple[str, ...]) -> str | None:
        from webview import FileDialog

        chosen = self._window.create_file_dialog(FileDialog.SAVE, directory=str(self._dir), save_filename=name, file_types=types)
        if not chosen:
            return None
        path = str(chosen if isinstance(chosen, str) else chosen[0])
        self._dir = Path(path).parent
        return path

    # -- start-up ------------------------------------------------------------------

    def init(self) -> dict:
        """Constants the page needs before it can build its controls."""
        return {
            "version": __version__,
            "simulate": self._simulate,
            "mac": sys.platform == "darwin",
            "ports": [] if self._simulate else serial_ports(),
            "defaultPorts": list(DEFAULT_PORTS),
            "patterns": list(PATTERNS),
            "params": asdict(Params()),
        }

    def ready(self) -> None:
        """The page is built: connect (simulated at once, real after the window is up)."""
        with self._lock:
            if self._simulate:
                self._s.devices.connect(simulate=True, start=self._stage_center())
                self._after_connect()
                return
        threading.Timer(0.3, self.connect_devices, DEFAULT_PORTS).start()

    # -- planning and devices -------------------------------------------------------

    def replan(self, shapes: list[dict], params: dict) -> dict:
        with self._lock:
            return self._replan(shapes, params)

    def set_view(self, mode: str) -> None:
        if mode == "preview":
            with self._lock:
                self._refresh_origin()

    def connect_devices(self, stage_port: str, shutter_port: str) -> dict:
        s = self._s
        with self._lock:
            if s.executor.running:
                return {"error": "Abort the run first."}
            try:
                s.devices.connect(
                    self._simulate,
                    stage_port or None,
                    None if shutter_port in ("", "None", "Simulated") else shutter_port,
                    self._profile["units_per_um"],
                    self._stage_center(),
                )
            except Exception as exc:  # noqa: BLE001  (any driver or serial error is shown to the user)
                self._device_msg = f"Connection failed: {exc}"
                return {"error": self._device_msg}
            self._device_msg = s.devices.note
            self._after_connect()
            return {"note": s.devices.note}

    def disconnect_devices(self, _stage: str = "", _shutter: str = "") -> dict:
        with self._lock:
            if self._s.executor.running:
                return {"error": "Abort the run first."}
            self._s.devices.close()
            self._device_msg = ""
            self._after_connect()
            return {}

    def start(self, shapes: list[dict], params: dict, view: str) -> dict:
        s = self._s
        with self._lock:
            if not s.devices.connected:
                return {"error": "Connect the devices first."}
            if view == "design":  # in the preview the origin is already fixed to what the path was shown at
                self._refresh_origin()
            result = self._replan(shapes, params)
            if s.problems or not s.plan:
                result["error"] = "Nothing to scan, or the plan leaves the stage range."
                return result
            try:
                s.executor.start(shift(s.plan, self._origin), s.params.speed)
            except RuntimeError as exc:
                result["error"] = str(exc)
            return result

    def toggle_pause(self) -> None:
        self._s.executor.toggle_pause()

    def abort(self) -> None:
        self._s.executor.abort("Aborted by user")

    # -- files ------------------------------------------------------------------------

    def import_file(self) -> dict:
        """Ask for a drawing (SVG, DXF, GDSII, CSV) or an image.

        A drawing returns its ``shapes`` and a ``message`` (the page adds them to the drawing). An image returns a
        ``bitmap`` preview for the tracing dialog, which then calls :meth:`trace_bitmap`.
        """
        path = self._pick_open(IMPORT_TYPES)
        if not path:
            return {"cancelled": True}
        try:
            if path.lower().endswith(fileio.BITMAP_SUFFIXES):
                return {"bitmap": self._open_bitmap(path)}
            result = fileio.import_shapes(path)
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}
        return {"shapes": result.shapes, "message": result.message}

    def _open_bitmap(self, path: str) -> dict:
        """Keep the grey values of an image for tracing and describe it with a PNG preview and the Otsu threshold."""
        from PIL import Image

        gray = fileio.load_bitmap(path)
        self._bitmap = gray
        buffer = io.BytesIO()
        Image.fromarray(gray).save(buffer, "PNG")
        return {
            "name": Path(path).name,
            "w": int(gray.shape[1]),
            "h": int(gray.shape[0]),
            "otsu": fileio.otsu_threshold(gray),
            "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        }

    def trace_bitmap(self, options: dict) -> dict:
        """Trace the bitmap from ``import_file`` with the dialog's settings and return the shapes."""
        if self._bitmap is None:
            return {"error": "No bitmap is open."}
        try:
            result = fileio.trace_bitmap(
                self._bitmap,
                int(options["threshold"]),
                bool(options["invert"]),
                float(options["width"]),
                int(options["speckle"]),
                float(options["smooth"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            return {"error": str(exc)}
        return {"shapes": result.shapes, "message": result.message + "."}

    def close_bitmap(self) -> None:
        self._bitmap = None

    def export_drawing(self, shapes: list[dict]) -> dict:
        """Ask for a file name and write the drawing as SVG or DXF (what will be scanned, relative to the start position)."""
        cleaned = [clean_shape(d) for d in shapes]
        try:
            fileio.drawing_geometry(cleaned)
        except ValueError as exc:
            return {"error": str(exc)}
        path = self._pick_save("scan.svg", DRAWING_TYPES)
        if not path:
            return {"cancelled": True}
        path = with_suffix(path, fileio.DRAWING_SUFFIXES, ".svg")
        try:
            summary = fileio.export_drawing(cleaned, path)
        except (OSError, ValueError) as exc:
            return {"error": f"Cannot export: {exc}"}
        return {"name": Path(path).name, "message": summary}

    def export_plan(self, shapes: list[dict], params: dict) -> dict:
        """Ask for a file name and write the scan path (CSV, G-code or NPZ, relative to the start position)."""
        parsed = self._params(params)
        try:
            plan = build_plan([clean_shape(d) for d in shapes], parsed)
        except ValueError as exc:
            return {"error": str(exc)}
        if not plan:
            return {"error": "Nothing to export: draw a shape first."}
        path = self._pick_save("scan.csv", PATH_TYPES)
        if not path:
            return {"cancelled": True}
        path = with_suffix(path, fileio.PATH_SUFFIXES, ".csv")
        try:
            fileio.export_plan(plan, parsed, path)
        except (OSError, ValueError) as exc:
            return {"error": f"Cannot export: {exc}"}
        return {"name": Path(path).name}

    # -- shape operations ---------------------------------------------------------------

    def merge(self, shapes: list[dict], index: int) -> dict:
        result, selected, message = shapeops.merge(shapes, index)
        return {"merged": bool(selected), "shapes": result, "selected": selected, "message": message}

    def merge_selected(self, shapes: list[dict], indices: list[int]) -> dict:
        result, selected, message = shapeops.merge_many(shapes, indices)
        return {"merged": bool(selected), "shapes": result, "selected": selected, "message": message}

    def log(self, text: str) -> None:
        print("[web]", text, file=sys.stderr)

    # -- state ------------------------------------------------------------------------------

    def state(self) -> dict:
        """Everything the page shows about devices and the run; the page polls this ten times a second."""
        with self._lock:
            s, ex, dev = self._s, self._s.executor, self._s.devices
            records, self._seen = dev.new_traffic(self._seen)
            position = ex.live_position()
            return {
                "connected": dev.connected,
                "simulated": dev.simulated,
                "running": ex.running,
                "paused": ex.state is State.PAUSED,
                "message": ex.message,
                "done": ex.done,
                "total": ex.total,
                "seg": ex.seg,
                "pt": ex.pt,
                "shutter": dev.shutter is not None and ex.shutter_open,
                "position": list(position) if position else None,
                "profile": self._profile,
                "canStart": not s.problems and bool(s.plan),
                "traffic": [[t, d, text, poll] for t, d, text, poll in records],
                "deviceMsg": self._device_msg,
            }
