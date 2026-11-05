"""Device connection management for the real lab hardware and simulators."""

from __future__ import annotations

import sys
import threading
import time
from collections import deque

from laserlab.mock import MockShutter, MockStage

from laserscan import settings

HARDWARE_AVAILABLE = sys.platform == "win32"
"""Real instruments are only connected from Windows."""
SIM_SPEEDUP = 10.0


def serial_ports() -> list[str]:
    """List the serial port names on this machine."""
    from serial.tools import list_ports

    return [p.device for p in list_ports.comports()]


POLL_COMMANDS = {"P", "$,S"}
"""Commands sent repeatedly to follow the stage; the monitor can hide them."""


class _TracedSerial:
    """Serial port proxy that records everything written and read."""

    def __init__(self, ser, log) -> None:
        self._ser, self._log, self._poll = ser, log, False

    def __getattr__(self, name):
        return getattr(self._ser, name)

    def write(self, data):
        text = data.decode(errors="replace").strip()
        self._poll = text in POLL_COMMANDS
        self._log("→", text, self._poll)
        return self._ser.write(data)

    def _traced(self, data):
        for line in data.decode(errors="replace").replace("\r", "\n").splitlines():
            if line.strip():
                self._log("←", line.strip(), self._poll)
        return data

    def read_until(self, *args, **kwargs):
        return self._traced(self._ser.read_until(*args, **kwargs))

    def read(self, *args, **kwargs):
        return self._traced(self._ser.read(*args, **kwargs))

    def readlines(self, *args, **kwargs):
        lines = self._ser.readlines(*args, **kwargs)
        for line in lines:
            self._traced(line)
        return lines


class Devices:
    """Holds the connected stage and shutter.

    Attributes:
        stage: Object with ``move_to_um``, ``set_velocity``, ``stop`` and ``close``.
        shutter: Object with ``open`` and ``close``, or ``None``.
        simulated: Whether the devices are simulators.
        profile: Stage profile (model, travel, units); read from the controller when real.
        position: Latest stage position in microns read in the background, or ``None``.
        traffic: Recent ``(time, direction, text, is_poll)`` communication records.
        traffic_total: Number of records ever logged (to find the new ones in ``traffic``).
    """

    def __init__(self) -> None:
        self.stage = None
        self.shutter = None
        self.simulated = False
        self.note = ""
        self.profile = settings.load()
        self.position: tuple[float, float] | None = None
        self.traffic: deque = deque(maxlen=2000)
        self.traffic_total = 0
        self._poller: threading.Thread | None = None
        self._poll_stop = threading.Event()

    def log(self, direction: str, text: str, poll: bool = False) -> None:
        """Record one communication line for the monitor panel."""
        self.traffic.append((time.time(), direction, text, poll))
        self.traffic_total += 1

    def new_traffic(self, seen: int) -> tuple[list, int]:
        """Records logged after the first ``seen`` ones, and the new total."""
        total = self.traffic_total
        count = min(total - seen, len(self.traffic))
        return (list(self.traffic)[-count:] if count > 0 else []), total

    @property
    def connected(self) -> bool:
        """Whether a stage is connected."""
        return self.stage is not None

    def connect(
        self,
        simulate: bool,
        stage_port: str | None = None,
        shutter_port: str | None = None,
        units_per_um: float = 100.0,
        start: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Connect the stage and shutter.

        Args:
            simulate: Use simulators instead of real hardware.
            stage_port: Serial port of the ProScan controller.
            shutter_port: Serial port of the SC30 shutter, or ``None`` for no shutter.
            units_per_um: Controller user units per micron, used if it cannot be read.
            start: Initial position of the simulated stage in microns.

        Raises:
            RuntimeError: If real hardware is requested off Windows or without a stage port.
        """
        self.close()
        self.note = ""
        self.profile = settings.load()
        if simulate:
            self.stage, self.shutter = MockStage(*start, speedup=SIM_SPEEDUP), MockShutter()
            self._trace_calls(self.stage, ("move_to_um", "set_velocity", "stop"))
            self._trace_calls(self.shutter, ("open", "close"))
            self.log("•", "Simulated devices connected")
        else:
            if not HARDWARE_AVAILABLE or not stage_port:
                raise RuntimeError("Real hardware needs Windows and a stage port.")
            from laserlab import ProScanStage, SC30Shutter

            self.stage = ProScanStage(stage_port, units_per_um=units_per_um)
            self.stage.ser = _TracedSerial(self.stage.ser, self.log)
            try:
                self.stage.standard_mode()
                self._read_profile()
                if shutter_port:
                    self.shutter = SC30Shutter(shutter_port)
                    self.shutter.ser = _TracedSerial(self.shutter.ser, self.log)
            except Exception:
                self.close()
                raise
        self.simulated = simulate
        self.position = self._read_position()
        self._poll_stop.clear()
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def _read_profile(self) -> None:
        """Take the stage model, travel and units from the controller."""
        try:
            info = self.stage.stage_info()
            units = self.stage.read_units_per_um()
            if not (info["size_x_mm"] and info["size_y_mm"]):
                raise ValueError("no SIZE_X / SIZE_Y in the STAGE reply")
            self.profile = {
                "model": info["model"],
                "x_range_um": [0, info["size_x_mm"] * 1000],
                "y_range_um": [0, info["size_y_mm"] * 1000],
                "units_per_um": units,
            }
        except Exception as exc:
            self.note = f"Could not read the stage information ({exc}); default stage range used."

    def _trace_calls(self, obj, names) -> None:
        """Log calls to the listed methods of a simulated device."""
        for name in names:
            method = getattr(obj, name)

            def traced(*args, _method=method, _name=name, **kwargs):
                self.log("→", f"{_name}({', '.join(f'{a:g}' if isinstance(a, float) else str(a) for a in args)})")
                return _method(*args, **kwargs)

            setattr(obj, name, traced)

    def _read_position(self) -> tuple[float, float] | None:
        stage = self.stage
        try:
            live = getattr(stage, "live_position_um", None) if stage is not None else None
            return tuple(live) if live else None
        except Exception:
            return None

    def _poll_loop(self) -> None:
        """Keep ``position`` up to date without blocking the GUI thread."""
        while not self._poll_stop.wait(0.1):
            position = self._read_position()
            if position is not None:
                self.position = position

    def position_um(self) -> tuple[float, float] | None:
        """The current stage position in microns read from the controller now, or ``None``."""
        try:
            self.position = tuple(self.stage.position_um)
        except Exception:
            self.position = None
        return self.position

    def motion(self) -> tuple[float, float] | None:
        """Acceleration (microns/s^2) and S-curve time (s), or ``None`` if unknown."""
        try:
            return self.stage.motion_profile()
        except Exception:
            return None

    def close(self) -> None:
        """Close the shutter, then all devices; errors are ignored."""
        self._poll_stop.set()
        if self._poller is not None and self._poller is not threading.current_thread():
            self._poller.join(timeout=2)
        self._poller = None
        self.position = None
        shutter_serial = getattr(self.shutter, "ser", None)
        for action in (
            getattr(self.shutter, "close", None),
            getattr(shutter_serial, "close", None),
            getattr(self.stage, "close", None),
        ):
            try:
                action and action()
            except Exception:
                pass
        self.stage = self.shutter = None
