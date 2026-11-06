"""Bridge between the web user interface (QWebChannel) and the instruments, planner and executor."""

from __future__ import annotations

import base64
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from laserscan import __version__, fileio, project, settings, shapeops
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
PUSH_MS = 100
PROJECT_FILTER = "LaserScan project (*.laserscan.json *.json)"
IMPORT_FILTER = "Drawings (*.svg *.dxf *.gds *.gds2 *.gdsii *.csv);;SVG (*.svg);;DXF (*.dxf);;GDSII (*.gds *.gds2 *.gdsii);;CSV points (*.csv)"
BITMAP_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp)"
EXPORT_TYPES = {"CSV (*.csv)": ".csv", "G-code (*.gcode)": ".gcode", "NumPy archive (*.npz)": ".npz"}


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min {secs} s"


class Bridge(QObject):
    """Slots called from JavaScript (all return JSON text) and the periodic ``state`` signal."""

    state = Signal(str)

    def __init__(self, window, simulate: bool) -> None:
        super().__init__(window)
        self.window = window
        self.s = SESSION
        self.simulate = simulate or not HARDWARE_AVAILABLE
        self.profile = settings.load()
        self.path: Path | None = None
        self.bitmap = None  # grey array of the bitmap being imported
        self.origin: tuple[float, float] = (0.0, 0.0)
        self.motion: tuple[float, float] | None = None
        self.can_start = False
        self.device_msg = ""
        self._seen = 0
        self._timer = QTimer(self, interval=PUSH_MS, timeout=self._push)

    # -- helpers -----------------------------------------------------------------

    def _stage_center(self) -> tuple[float, float]:
        (x0, x1), (y0, y1) = self.profile["x_range_um"], self.profile["y_range_um"]
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _refresh_origin(self) -> None:
        """Read the stage position (the plan origin) and its acceleration profile."""
        if self.s.executor.running:
            return
        position = self.s.devices.position_um()
        self.origin = position or (0.0, 0.0)
        self.motion = self.s.devices.motion()

    def _after_connect(self) -> None:
        dev = self.s.devices
        self.profile = dev.profile if dev.connected else settings.load()
        self._refresh_origin()

    @staticmethod
    def _params(data: dict) -> Params:
        params = Params(**data)
        return params if params.pattern in PATTERNS else Params(**{**data, "pattern": Params().pattern})

    def _replan(self, shapes: list[dict], data: dict) -> dict:
        """Build the plan for the current origin and return everything the preview needs."""
        s, params = self.s, self._params(data)
        shapes = [clean_shape(d) for d in shapes]
        problems = []
        try:
            plan = build_plan(shapes, params)
        except ValueError as exc:
            plan = []
            problems.append(str(exc))
        flags, messages = overrun(plan, self.origin, self.profile["x_range_um"], self.profile["y_range_um"])
        if messages:
            problems.append("Path leaves the stage range from the current position: " + "; ".join(messages) + ".")
        s.plan, s.params, s.problems = plan, params, problems
        accel, ramp = self.motion or (None, 0.0)
        on, _off, seconds = estimate(plan, params.speed, accel, ramp)
        basis = "with acceleration" if self.motion else "constant speed, acceleration unknown"
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
            "origin": list(self.origin),
        }

    # -- slots ---------------------------------------------------------------------

    @Slot(result=str)
    def init(self) -> str:
        return json.dumps(
            {
                "version": __version__,
                "simulate": self.simulate,
                "mac": sys.platform == "darwin",
                "ports": [] if self.simulate else serial_ports(),
                "defaultPorts": DEFAULT_PORTS,
                "patterns": list(PATTERNS),
                "params": asdict(Params()),
            }
        )

    @Slot(result=str)
    def ready(self) -> str:
        """The page is loaded: connect (simulated at once, real after the window is up) and start pushing state."""
        if self.simulate:
            self.s.devices.connect(simulate=True, start=self._stage_center())
            self._after_connect()
        else:
            QTimer.singleShot(300, lambda: self.connectDevices(DEFAULT_PORTS[0], DEFAULT_PORTS[1]))
        self._timer.start()
        return ""

    @Slot(str, str, result=str)
    def replan(self, shapes: str, params: str) -> str:
        return json.dumps(self._replan(json.loads(shapes), json.loads(params)))

    @Slot(str, result=str)
    def setView(self, mode: str) -> str:
        if mode == "preview":
            self._refresh_origin()
        return ""

    @Slot(str, str, result=str)
    def connectDevices(self, stage_port: str, shutter_port: str) -> str:
        s = self.s
        if s.executor.running:
            return json.dumps({"error": "Abort the run first."})
        try:
            s.devices.connect(
                self.simulate,
                stage_port or None,
                None if shutter_port in ("", "None", "Simulated") else shutter_port,
                self.profile["units_per_um"],
                self._stage_center(),
            )
        except Exception as exc:
            self.device_msg = f"Connection failed: {exc}"
            return json.dumps({"error": self.device_msg})
        self.device_msg = s.devices.note
        self._after_connect()
        return json.dumps({"note": s.devices.note})

    @Slot(str, str, result=str)
    def disconnectDevices(self, _stage: str, _shutter: str) -> str:
        if self.s.executor.running:
            return json.dumps({"error": "Abort the run first."})
        self.s.devices.close()
        self.device_msg = ""
        self._after_connect()
        return json.dumps({})

    @Slot(str, str, str, result=str)
    def start(self, shapes: str, params: str, view: str) -> str:
        s = self.s
        if not s.devices.connected:
            return json.dumps({"error": "Connect the devices first."})
        if view == "design":  # in the preview the origin is already fixed to what the path was shown at
            self._refresh_origin()
        result = self._replan(json.loads(shapes), json.loads(params))
        if s.problems or not s.plan:
            result["error"] = "Nothing to scan, or the plan leaves the stage range."
            return json.dumps(result)
        try:
            s.executor.start(shift(s.plan, self.origin), s.params.speed)
        except RuntimeError as exc:
            result["error"] = str(exc)
        return json.dumps(result)

    @Slot(result=str)
    def togglePause(self) -> str:
        self.s.executor.toggle_pause()
        return ""

    @Slot(result=str)
    def abort(self) -> str:
        self.s.executor.abort("Aborted by user")
        return ""

    def _titled(self, path: str | None) -> None:
        """Remember the current project file and show its name in the window title."""
        self.path = Path(path) if path else None
        self.window.setWindowTitle(f"{self.path.name} — LaserScan" if self.path else "LaserScan")

    @staticmethod
    def _with_suffix(path: str, chosen_filter: str, suffixes: dict[str, str]) -> str:
        """Add the suffix of the selected file type unless the name already has one of the known suffixes."""
        name = path.lower()
        if any(name.endswith(suffix) for suffix in suffixes.values()):
            return path
        return path + next((suffix for label, suffix in suffixes.items() if label == chosen_filter), next(iter(suffixes.values())))

    @Slot(result=str)
    def openProject(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self.window, "Open project", self._dir(), PROJECT_FILTER)
        if not path:
            return json.dumps({"cancelled": True})
        try:
            shapes, params, file_profile = project.load(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return json.dumps({"error": str(exc)})
        self._titled(path)
        differs = bool(file_profile) and (
            file_profile.get("x_range_um") != self.profile["x_range_um"]
            or file_profile.get("y_range_um") != self.profile["y_range_um"]
        )
        return json.dumps({"shapes": shapes, "params": asdict(params), "differs": differs})

    @Slot(str, str, bool, result=str)
    def saveProject(self, shapes: str, params: str, save_as: bool) -> str:
        """Save to the current file, or ask for one (always when ``save_as``). Returns JSON with ``error`` or ``name``."""
        path = None if save_as or self.path is None else str(self.path)
        if path is None:
            default = str(Path(self._dir()) / (self.path.name if self.path else "scan.laserscan.json"))
            path, _ = QFileDialog.getSaveFileName(self.window, "Save project", default, PROJECT_FILTER)
            if not path:
                return json.dumps({"cancelled": True})
            if not path.lower().endswith(".json"):
                path += ".laserscan.json"
        try:
            project.save(path, json.loads(shapes), self._params(json.loads(params)), self.profile)
        except OSError as exc:
            return json.dumps({"error": f"Cannot save project: {exc}"})
        self._titled(path)
        return json.dumps({"name": Path(path).name})

    @Slot(result=str)
    def importDrawing(self) -> str:
        """Ask for an SVG, DXF or CSV file and return its shapes (the page adds them to the drawing)."""
        path, _ = QFileDialog.getOpenFileName(self.window, "Import drawing", self._dir(), IMPORT_FILTER)
        if not path:
            return json.dumps({"cancelled": True})
        try:
            result = fileio.import_shapes(path)
        except (OSError, ValueError) as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"shapes": result.shapes, "message": result.message})

    @Slot(result=str)
    def openBitmap(self) -> str:
        """Ask for an image, keep its grey values for tracing, and return a PNG preview with the Otsu threshold."""
        from PIL import Image

        path, _ = QFileDialog.getOpenFileName(self.window, "Import bitmap", self._dir(), BITMAP_FILTER)
        if not path:
            return json.dumps({"cancelled": True})
        try:
            gray = fileio.load_bitmap(path)
        except (OSError, ValueError) as exc:
            return json.dumps({"error": str(exc)})
        self.bitmap = gray
        buffer = io.BytesIO()
        Image.fromarray(gray).save(buffer, "PNG")
        return json.dumps(
            {
                "name": Path(path).name,
                "w": int(gray.shape[1]),
                "h": int(gray.shape[0]),
                "otsu": fileio.otsu_threshold(gray),
                "png": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
            }
        )

    @Slot(str, result=str)
    def traceBitmap(self, options: str) -> str:
        """Trace the bitmap from ``openBitmap`` with the dialog's settings and return the shapes."""
        if self.bitmap is None:
            return json.dumps({"error": "No bitmap is open."})
        o = json.loads(options)
        try:
            result = fileio.trace_bitmap(
                self.bitmap, int(o["threshold"]), bool(o["invert"]), float(o["width"]), int(o["speckle"]), float(o["smooth"])
            )
        except (ValueError, KeyError, TypeError) as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"shapes": result.shapes, "message": result.message + "."})

    @Slot(result=str)
    def closeBitmap(self) -> str:
        self.bitmap = None
        return ""

    @Slot(str, str, result=str)
    def exportPlan(self, shapes: str, params: str) -> str:
        """Ask for a file name and write the scan path (CSV, G-code or NPZ, relative to the start position)."""
        parsed = self._params(json.loads(params))
        try:
            plan = build_plan([clean_shape(d) for d in json.loads(shapes)], parsed)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        if not plan:
            return json.dumps({"error": "Nothing to export: draw a shape first."})
        stem = self.path.name.removesuffix(".json").removesuffix(".laserscan") if self.path else "scan"
        path, chosen = QFileDialog.getSaveFileName(
            self.window, "Export scan path", str(Path(self._dir()) / f"{stem}.csv"), ";;".join(EXPORT_TYPES)
        )
        if not path:
            return json.dumps({"cancelled": True})
        path = self._with_suffix(path, chosen, EXPORT_TYPES)
        try:
            fileio.export_plan(plan, parsed, path)
        except (OSError, ValueError) as exc:
            return json.dumps({"error": f"Cannot export: {exc}"})
        return json.dumps({"name": Path(path).name})

    def _dir(self) -> str:
        """Folder the file dialogs start in: the current project's folder, else the user's home."""
        return str(self.path.parent) if self.path else str(Path.home())

    @Slot(str, int, result=str)
    def merge(self, shapes: str, index: int) -> str:
        result, selected, message = shapeops.merge(json.loads(shapes), index)
        return json.dumps({"merged": bool(selected), "shapes": result, "selected": selected, "message": message})

    @Slot(str, str, result=str)
    def mergeSelected(self, shapes: str, indices: str) -> str:
        result, selected, message = shapeops.merge_many(json.loads(shapes), json.loads(indices))
        return json.dumps({"merged": bool(selected), "shapes": result, "selected": selected, "message": message})

    @Slot(str, result=str)
    def log(self, text: str) -> str:
        print("[web]", text, file=sys.stderr)
        return ""

    # -- state push ------------------------------------------------------------------

    def _push(self) -> None:
        s, ex, dev = self.s, self.s.executor, self.s.devices
        records, self._seen = dev.new_traffic(self._seen)
        position = ex.live_position()
        self.state.emit(
            json.dumps(
                {
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
                    "profile": self.profile,
                    "canStart": not s.problems and bool(s.plan),
                    "traffic": [[t, d, text, poll] for t, d, text, poll in records],
                    "deviceMsg": self.device_msg,
                }
            )
        )
