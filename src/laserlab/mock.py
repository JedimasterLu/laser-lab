"""Hardware-free stand-ins for the stage and shutter."""

import math
import threading
import time


class MockStage:
    """Simulated stage exposing the micron interface of ``ProScanStage``."""

    def __init__(self, x: float = 0.0, y: float = 0.0, velocity: float = 100.0, speedup: float = 1.0):
        """Create the stage.

        Args:
            x: Initial x position in microns.
            y: Initial y position in microns.
            velocity: Initial velocity in microns/s.
            speedup: Factor that shortens simulated move times.
        """
        self._pos = (float(x), float(y))
        self._velocity = float(velocity)
        self.speedup = float(speedup)
        self._stop = threading.Event()

    @property
    def position_um(self) -> tuple[float, float]:
        """The current (x, y) position in microns."""
        return self._pos

    @property
    def live_position_um(self) -> tuple[float, float]:
        """The current (x, y) position in microns (always live)."""
        return self._pos

    def motion_profile(self) -> None:
        """The simulator has no acceleration model."""
        return None

    def set_velocity(self, velocity: float):
        """Set the velocity in microns/s."""
        self._velocity = float(velocity)

    def move_to_um(self, x: float, y: float):
        """Move linearly to (x, y) in microns, returning early after ``stop``."""
        self._stop.clear()
        x0, y0 = self._pos
        duration = math.hypot(x - x0, y - y0) / self._velocity / self.speedup
        start = time.monotonic()
        while not self._stop.is_set():
            frac = min(1.0, (time.monotonic() - start) / duration) if duration else 1.0
            self._pos = (x0 + (x - x0) * frac, y0 + (y - y0) * frac)
            if frac >= 1.0:
                return
            time.sleep(0.02)

    def stop(self):
        """Stop the move in progress."""
        self._stop.set()

    def close(self):
        """Release the stage (no-op)."""


class MockShutter:
    """Simulated shutter."""

    def __init__(self):
        self._open = False

    def open(self, channel: int = 1):
        """Open the shutter."""
        self._open = True

    def close(self, channel: int = 1):
        """Close the shutter."""
        self._open = False

    def is_open(self, channel: int = 1) -> bool:
        """Whether the shutter is open."""
        return self._open
