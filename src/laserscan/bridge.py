"""Bridge between the web user interface (QWebChannel) and the instruments, planner and executor."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from laserscan import __version__, project, settings, shapeops
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

    @Slot(result=str)
    def openProject(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self.window, "Open project", "", "LaserScan project (*.json)")
        if not path:
            return json.dumps({"cancelled": True})
        try:
            with open(path, encoding="utf-8") as f:
                shapes, params, file_profile = project.loads(f.read())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return json.dumps({"error": str(exc)})
        differs = bool(file_profile) and (
            file_profile.get("x_range_um") != self.profile["x_range_um"]
            or file_profile.get("y_range_um") != self.profile["y_range_um"]
        )
        return json.dumps({"shapes": shapes, "params": asdict(params), "differs": differs})

    @Slot(str, str, result=str)
    def saveProject(self, shapes: str, params: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self.window, "Save project", "scan.laserscan.json", "LaserScan project (*.json)")
        if not path:
            return ""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(project.dumps(json.loads(shapes), self._params(json.loads(params)), self.profile))
        except OSError as exc:
            return f"Cannot save project: {exc}"
        return ""

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
