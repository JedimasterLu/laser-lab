"""Device connection management for the real lab hardware and simulators."""

from __future__ import annotations

import sys

from laserlab.mock import MockShutter, MockStage

HARDWARE_AVAILABLE = sys.platform == "win32"
"""Real instruments are only connected from Windows."""
SIM_SPEEDUP = 10.0


def serial_ports() -> list[str]:
    """List the serial port names on this machine."""
    from serial.tools import list_ports

    return [p.device for p in list_ports.comports()]


class Devices:
    """Holds the connected stage and shutter.

    Attributes:
        stage: Object with ``move_to_um``, ``set_velocity``, ``stop`` and ``close``.
        shutter: Object with ``open`` and ``close``, or ``None``.
        simulated: Whether the devices are simulators.
    """

    def __init__(self) -> None:
        self.stage = None
        self.shutter = None
        self.simulated = False
        self.note = ""

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
        if simulate:
            self.stage, self.shutter = MockStage(*start, speedup=SIM_SPEEDUP), MockShutter()
        else:
            if not HARDWARE_AVAILABLE or not stage_port:
                raise RuntimeError("Real hardware needs Windows and a stage port.")
            from laserlab import ProScanStage, SC30Shutter

            self.stage = ProScanStage(stage_port, units_per_um=units_per_um)
            self.stage.standard_mode()
            try:
                self.note = f"Units per µm read from the controller: {self.stage.read_units_per_um():g}."
            except Exception as exc:
                self.note = f"Could not read units per µm ({exc}); using {units_per_um:g}."
            self.shutter = SC30Shutter(shutter_port) if shutter_port else None
        self.simulated = simulate

    def position_um(self) -> tuple[float, float] | None:
        """The current stage position in microns, or ``None`` if unavailable."""
        try:
            return tuple(self.stage.position_um)
        except Exception:
            return None

    def motion(self) -> tuple[float, float] | None:
        """Acceleration (microns/s^2) and S-curve time (s), or ``None`` if unknown."""
        try:
            return self.stage.motion_profile()
        except Exception:
            return None

    def close(self) -> None:
        """Close the shutter, then all devices; errors are ignored."""
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
