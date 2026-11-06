"""Background execution of a scan plan with pause and safe abort."""

from __future__ import annotations

import threading
from enum import Enum

from laserscan.devices import Devices
from laserscan.planning import Segment


class State(str, Enum):
    """Executor states."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


class _Aborted(Exception):
    pass


class Executor:
    """Runs a plan on a worker thread.

    Attributes:
        state: Current ``State``.
        done: Points reached so far.
        total: Total points in the plan.
        position: Last reached (x, y) in microns, or ``None``.
        seg: Index of the segment of the last reached point.
        pt: Index of the last reached point within that segment.
        message: Last abort reason or error, empty if none.
    """

    def __init__(self, devices: Devices) -> None:
        self.devices = devices
        self.state = State.IDLE
        self.done = self.total = 0
        self.seg = self.pt = 0
        self.position: tuple[float, float] | None = None
        self.message = ""
        self._abort = threading.Event()
        self._resume = threading.Event()
        self._thread: threading.Thread | None = None
        self._laser_on = False
        self.shutter_open = False

    @property
    def running(self) -> bool:
        """Whether a plan is running or paused."""
        return self.state is not State.IDLE

    def live_position(self) -> tuple[float, float] | None:
        """Latest stage position read from the controller (microns), also while moving."""
        return self.devices.position or self.position

    def start(self, plan: list[Segment], speed: float) -> None:
        """Start executing ``plan`` in the background.

        Args:
            plan: Segments in absolute stage microns.
            speed: Stage speed in microns/s.

        Raises:
            RuntimeError: If already running, nothing is connected or the plan is empty.
        """
        if self.running or not self.devices.connected or not plan:
            raise RuntimeError("Cannot start: already running, not connected or empty plan.")
        self.done, self.total, self.message = 0, sum(len(s.points) for s in plan), ""
        self.seg = self.pt = 0
        self.position = None
        self._abort.clear()
        self._resume.set()
        self.state = State.RUNNING
        self._thread = threading.Thread(target=self._run, args=(list(plan), speed), daemon=True)
        self._thread.start()

    def toggle_pause(self) -> None:
        """Pause at the next point, or resume. The shutter is closed while paused."""
        if self.state is State.RUNNING:
            self.state = State.PAUSED
            self._resume.clear()
        elif self.state is State.PAUSED:
            self.state = State.RUNNING
            self._resume.set()

    def abort(self, reason: str = "aborted") -> None:
        """Close the shutter and stop the stage immediately.

        Safe to call from any thread at any time, including when idle.

        Args:
            reason: Text shown in ``message``.
        """
        self._abort.set()
        self._resume.set()
        self.message = reason
        shutter, stage = self.devices.shutter, self.devices.stage
        self.shutter_open = False
        for action in (getattr(shutter, "close", None), getattr(stage, "stop", None)):
            try:
                action and action()
            except Exception as exc:
                self.message += f" ({exc})"

    def _checkpoint(self) -> None:
        if self._abort.is_set():
            raise _Aborted
        if not self._resume.is_set():
            self._set_shutter(False)
            self._resume.wait()
            if self._abort.is_set():
                raise _Aborted
            self._set_shutter(self._laser_on)

    def _set_shutter(self, on: bool) -> None:
        if self.devices.shutter is not None:
            (self.devices.shutter.open if on else self.devices.shutter.close)()
            self.shutter_open = on

    def _move(self, point, seg: int, pt: int) -> None:
        self._checkpoint()
        self.devices.stage.move_to_um(float(point[0]), float(point[1]))
        self._checkpoint()
        self.position = (float(point[0]), float(point[1]))
        self.seg, self.pt = seg, pt
        self.done += 1

    def _run(self, plan: list[Segment], speed: float) -> None:
        try:
            self.devices.stage.set_velocity(speed)
            for i, seg in enumerate(plan):
                self._laser_on = False
                self._move(seg.points[0], i, 0)
                self._laser_on = seg.laser
                self._set_shutter(seg.laser)
                for j, point in enumerate(seg.points[1:], 1):
                    self._move(point, i, j)
                self._laser_on = False
                self._set_shutter(False)
        except _Aborted:
            pass
        except Exception as exc:
            self.message = f"Error: {type(exc).__name__}: {exc}"
            self.devices.log("!", self.message)
            self.abort(self.message)
        finally:
            self._laser_on = False
            try:
                self._set_shutter(False)
            except Exception as exc:
                self.message = f"{self.message} (shutter: {exc})".strip()
            finally:
                self.state = State.IDLE
