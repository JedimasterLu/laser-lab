import re
import threading
import time

import numpy as np
import serial


class ProScanStage:
    """Prior ProScan III stage controller over a serial port.

    Positions passed to ``move_to``, ``move_by`` and ``scan`` are controller
    user units. The ``*_um`` methods convert from microns using ``units_per_um``.
    """

    def __init__(self, port: str, wait_time: float = 1e-2, units_per_um: float = 100.0):
        """Open the controller.

        Args:
            port: Serial port name.
            wait_time: Polling interval in seconds used by ``wait``.
            units_per_um: Controller user units per micron. Call
                ``read_units_per_um`` to take it from the controller instead.
        """
        self.ser = serial.Serial(port, baudrate=9600, timeout=1)
        self._lock = threading.RLock()
        self._abort = threading.Event()
        self._live_lock = threading.Lock()
        self._moving = False
        self._pending = 0
        self._live: tuple[float, float] | None = None
        self._comp: str | None = None
        self.wait_time = wait_time
        self.units_per_um = float(units_per_um)
        match = re.search(r"MICROSTEPS/MICRON\s*=\s*([\d.]+)", "\n".join(self.info))
        self.steps_per_micron = float(match.group(1)) if match else 0.0
        self._velocity = self.velocity

    def _query(self, command: str) -> str:
        """Send a command and return its single-line reply."""
        with self._lock:
            self.ser.write(f"{command}\r".encode())
            return self.ser.read_until(b"\r").decode().strip()

    def _take_position(self, reply: str) -> bool:
        """Record a position reply to ``live_position_um`` and report whether ``reply`` was one."""
        if not re.fullmatch(r"-?\d+(\.\d+)?,-?\d+(\.\d+)?(,-?\d+(\.\d+)?)?", reply):
            return False
        x, y = reply.split(",")[:2]
        self._live = (float(x), float(y))
        self._pending = max(0, self._pending - 1)
        return True

    def _move(self, command: str, timeout: float = 300.0) -> None:
        """Send a movement command and block until the controller replies ``R``.

        Position replies requested by ``live_position_um`` while moving are
        consumed here and not mistaken for the end-of-move reply.

        Args:
            command: Movement command without the terminator.
            timeout: Maximum wait in seconds.

        Raises:
            RuntimeError: If the controller returns an error code.
            TimeoutError: If no end-of-move reply arrives in time.
        """
        with self._lock:
            self._moving = True
            try:
                self.ser.write(f"{command}\r".encode())
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    reply = self.ser.read_until(b"\r").decode().strip()
                    if self._take_position(reply):
                        continue
                    if reply == "R" or self._abort.is_set():
                        break
                    if reply.startswith("E"):
                        raise RuntimeError(f"Stage error: {reply}")
                else:
                    raise TimeoutError(f"No end-of-move reply for {command!r}")
            finally:
                with self._live_lock:
                    self._moving = False
            end = time.monotonic() + 0.1
            while self._pending and time.monotonic() < end:
                if self.ser.in_waiting:
                    self._take_position(self.ser.read_until(b"\r").decode().strip())
                else:
                    time.sleep(0.005)
            self._pending = 0

    @property
    def info(self) -> list[str]:
        with self._lock:
            self.ser.write("STAGE\r".encode())
            lines = self.ser.readlines()[0]
        return lines.decode().split("\r")

    @property
    def velocity(self) -> float:
        """The maximum velocity of stage in microns/s."""
        return float(self._query("SMS,u"))

    def is_close(
            self,
            pos1: tuple[float, float],
            pos2: tuple[float, float],
            threshold: float = 10
        ) -> bool:
        """Check if two positions are close enough within a threshold."""
        return abs(pos1[0] - pos2[0]) < threshold and abs(pos1[1] - pos2[1]) < threshold

    @property
    def is_stop(self) -> bool:
        """Whether neither the X nor the Y axis is moving (``$,S`` status)."""
        return self._query("$,S") == "0"

    def wait(self, max_time: float = 1):
        """Block until the stage stops or ``max_time`` seconds pass."""
        deadline = time.monotonic() + max_time
        while not self.is_stop and time.monotonic() < deadline:
            time.sleep(self.wait_time)

    @property
    def position(self) -> tuple[float, float]:
        """The current (x, y) position in controller user units.

        Raises:
            RuntimeError: If the controller returns an error.
        """
        reply = self._query("P")
        if reply.startswith("E"):
            raise RuntimeError(f"Stage error: {reply}")
        x, y, _ = reply.split(",")
        return float(x), float(y)

    @property
    def position_um(self) -> tuple[float, float]:
        """The current (x, y) position in microns."""
        x, y = self.position
        return x / self.units_per_um, y / self.units_per_um

    @property
    def live_position_um(self) -> tuple[float, float] | None:
        """Position in microns that also works while a move is in progress.

        During a move this asks the controller for ``P`` without waiting and
        returns the latest reply received so far (``None`` before the first).
        """
        with self._live_lock:
            if self._moving:
                self._pending += 1
                self.ser.write(b"P\r")
                live = self._live
                return None if live is None else (live[0] / self.units_per_um, live[1] / self.units_per_um)
        return self.position_um

    def read_units_per_um(self) -> float:
        """Read the stage resolution (``RES,S``, microns per user unit) and set ``units_per_um``.

        Returns:
            Controller user units per micron.

        Raises:
            RuntimeError: If the reply is not a positive number.
        """
        reply = self._query("RES,S")
        try:
            resolution = float(reply)
        except ValueError:
            resolution = 0.0
        if resolution <= 0:
            raise RuntimeError(f"Unexpected RES,S reply: {reply!r}")
        self.units_per_um = 1.0 / resolution
        return self.units_per_um

    def motion_profile(self) -> tuple[float, float]:
        """Read the acceleration (``SAS,u``) and S-curve setting (``SCS``).

        Returns:
            Acceleration in microns/s^2 and the S-curve time per acceleration
            change in seconds (the manual gives 13 ms at ``SCS`` 100 and 6.5 ms at 200,
            so ``1.3 / SCS``).

        Raises:
            RuntimeError: If a reply is not numeric.
        """
        try:
            return float(self._query("SAS,u")), 1.3 / float(self._query("SCS"))
        except ValueError as exc:
            raise RuntimeError(f"Unexpected SAS/SCS reply: {exc}") from exc

    def move_to(self, x: float, y: float):
        """Move to the absolute position (x, y) in user units."""
        self._move(f"G {round(x)},{round(y)}")

    def move_to_um(self, x: float, y: float):
        """Move to the absolute position (x, y) in microns."""
        self.move_to(x * self.units_per_um, y * self.units_per_um)

    def move_by(self, dx: float, dy: float):
        """Move by (dx, dy) in user units."""
        self._move(f"GR {round(dx)},{round(dy)}")

    def scan(
            self,
            positions: list[tuple[float, float]] | np.ndarray,
            intervals: list[float] | float = 0):
        for i, pos in enumerate(positions):
            self.move_to(*pos)
            self.wait()
            if isinstance(intervals, list) and i < len(intervals):
                time.sleep(intervals[i])
            elif isinstance(intervals, (int, float)):
                time.sleep(intervals)

    def set_velocity(self, velocity: float):
        """Set the maximum velocity of stage in microns/s.

        Raises:
            RuntimeWarning: If the controller rejects the value.
        """
        if self._query(f"SMS,{velocity},u") != "0":
            raise RuntimeWarning("Failed to set velocity!")
        self._velocity = velocity

    def stop(self):
        """Stop movement in a controlled way (``I``) and clear the command queue.

        Safe to call from another thread while a move is in progress; the
        blocked move returns and stale replies are discarded.
        """
        self._abort.set()
        self.ser.write(b"I\r")
        with self._lock:
            time.sleep(0.05)
            self.ser.reset_input_buffer()
            self._pending = 0
            self._abort.clear()

    def standard_mode(self):
        """Switch the controller to standard mode (``COMP,0``).

        The previous mode is restored by ``close``.
        """
        self._comp = self._query("COMP")
        if self._comp == "1":
            self._query("COMP,0")

    def close(self):
        if not self.ser.is_open:
            return
        if self._comp == "1":
            self._query("COMP,1")
        self.ser.write("I\r".encode())
        time.sleep(0.1)
        self.ser.close()

    def __del__(self):
        if getattr(self, "ser", None) is not None and self.ser.is_open:
            self.close()
