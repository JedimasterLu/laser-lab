"""Cross-platform wrapper for the Thorlabs EXULUS SLM.

This module exposes a high-level :class:`EXULUS` class that wraps the
Thorlabs SDK (``EXULUS_COMMAND_LIB``, ``Thorlabs_EXULUS_CGHCalculate``
and ``Thorlabs_EXULUS_CGHDisplay``).

The Thorlabs SDK ships only Windows ``.dll`` binaries, so importing it
on macOS / Linux raises ``OSError``. To keep development and unit tests
working on every platform, the module picks an implementation at
runtime:

* ``LASERLAB_MOCK=1``  -> forces :class:`_MockBackend` (in-memory).
* Otherwise            -> tries :class:`_RealBackend`; on failure the
  factory raises a ``RuntimeError`` explaining how to switch to mock.

Example:
    >>> from laserlab.slm import EXULUS
    >>> with EXULUS() as slm:  # doctest: +SKIP
    ...     slm.set_phase_stroke(1)
    ...     slm.set_hflip(True)
    ...     slm.show_image("target.png")

    On macOS / Linux (no DLLs available), run with
    ``LASERLAB_MOCK=1 python my_script.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional, Protocol

import cv2
import numpy as np
from ctypes import c_ubyte


# --------------------------------------------------------------------------- #
# Backend protocol                                                            #
# --------------------------------------------------------------------------- #
class SLMBackend(Protocol):
    """Protocol every SLM backend must implement.

    All methods are abstract; concrete backends are :class:`_RealBackend`
    (Windows + Thorlabs DLLs) and :class:`_MockBackend` (in-memory, used
    on macOS / Linux and in unit tests).
    """

    # --- device control ----------------------------------------------------
    def list_devices(self) -> list[tuple[str, str]]: ...
    def open(self, serial: str, baud: int, timeout: int) -> int: ...
    def close(self, hdl: int) -> int: ...
    def check_communication(self, hdl: int) -> int: ...

    def set_hflip(self, hdl: int, on: bool) -> int: ...
    def get_hflip(self, hdl: int) -> int: ...
    def set_vflip(self, hdl: int, on: bool) -> int: ...
    def get_vflip(self, hdl: int) -> int: ...
    def set_phase_stroke(self, hdl: int, mode: int) -> int: ...
    def get_phase_stroke(self, hdl: int) -> int: ...
    def set_test_pattern(self, hdl: int, on: bool) -> int: ...
    def get_test_pattern(self, hdl: int) -> int: ...
    def save_default_setting(self, hdl: int) -> int: ...

    # --- CGH calculation ---------------------------------------------------
    def cgh_image_resize(
        self,
        src: np.ndarray,
        width: int,
        height: int,
        mode: int,
        background: int,
    ) -> np.ndarray: ...
    def cgh_init(self) -> int: ...
    def cgh_create(self) -> int: ...
    def cgh_update_all(
        self,
        hdl: int,
        width: int,
        height: int,
        pixel_pitch_m: float,
        distance_m: float,
        wavelength_m: float,
    ) -> int: ...
    def cgh_calc(self, hdl: int, buffer: np.ndarray, stroke_m: float) -> int: ...
    def cgh_close(self, hdl: int) -> int: ...

    # --- display -----------------------------------------------------------
    def display_get_monitor_count(self) -> int: ...
    def display_create_window(
        self, monitor: int, width: int, height: int, title: str
    ) -> int: ...
    def display_set_window_info(
        self, hdl: int, width: int, height: int, channels: int
    ) -> int: ...
    def display_show(self, hdl: int, buffer: np.ndarray) -> int: ...
    def display_close_window(self, hdl: int) -> int: ...


# --------------------------------------------------------------------------- #
# Real backend (Windows + Thorlabs DLLs)                                      #
# --------------------------------------------------------------------------- #
class _RealBackend:
    """Wraps the Thorlabs SDK using ctypes. Windows only.

    The SDK uses relative paths in ``cdll.LoadLibrary("xxx.dll")``, so the
    constructor temporarily ``chdir``'s into the SDK directory at import
    time and restores the previous working directory afterwards.

    Attributes:
        _dev: Mapping of device-command name to its SDK callable.
        _cgh: Mapping of CGH-command name to its SDK callable.
        _disp: Mapping of display-command name to its SDK callable.
    """

    _dev: dict[str, Any]
    _cgh: dict[str, Any]
    _disp: dict[str, Any]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "Thorlabs EXULUS SDK is Windows-only (DLLs cannot be loaded on "
                f"{sys.platform}). Set LASERLAB_MOCK=1 for development."
            )

        sdk_dir = Path(__file__).resolve().parents[1] / "Thorlabs_EXULUS_PythonSDK"
        if not sdk_dir.exists():
            raise FileNotFoundError(f"Thorlabs SDK directory not found: {sdk_dir}")

        old_cwd = os.getcwd()
        os.chdir(sdk_dir)
        try:
            from EXULUS_COMMAND_LIB import (  # type: ignore[import-not-found]
                EXULUSCheckCommunication,
                EXULUSClose,
                EXULUSGetPhaseStrokeMode,
                EXULUSGetScreenHorizontalFlip,
                EXULUSGetScreenVerticalFlip,
                EXULUSGetTestPatternStatus,
                EXULUSListDevices,
                EXULUSOpen,
                EXULUSSaveDefaultSetting,
                EXULUSSetPhaseStrokeMode,
                EXULUSSetScreenHorizontalFlip,
                EXULUSSetScreenVerticalFlip,
                EXULUSSetTestPatternStatus,
            )
            from Thorlabs_EXULUS_CGHCalculate import (  # type: ignore[import-not-found]
                CghCoreCalc,
                CghCoreClose,
                CghCoreCreate,
                CghCoreInit,
                CghCoreUpdateAll,
                CghImageResize,
            )
            from Thorlabs_EXULUS_CGHDisplay import (  # type: ignore[import-not-found]
                CghDisplayCloseWindow,
                CghDisplayCreateWindow,
                CghDisplayGetMonitorCount,
                CghDisplaySetWindowInfo,
                CghDisplayShowWindow,
            )
        finally:
            os.chdir(old_cwd)

        self._dev = {
            "list": EXULUSListDevices,
            "open": EXULUSOpen,
            "close": EXULUSClose,
            "check": EXULUSCheckCommunication,
            "set_hflip": EXULUSSetScreenHorizontalFlip,
            "get_hflip": EXULUSGetScreenHorizontalFlip,
            "set_vflip": EXULUSSetScreenVerticalFlip,
            "get_vflip": EXULUSGetScreenVerticalFlip,
            "set_stroke": EXULUSSetPhaseStrokeMode,
            "get_stroke": EXULUSGetPhaseStrokeMode,
            "set_test": EXULUSSetTestPatternStatus,
            "get_test": EXULUSGetTestPatternStatus,
            "save": EXULUSSaveDefaultSetting,
        }
        self._cgh = {
            "resize": CghImageResize,
            "init": CghCoreInit,
            "create": CghCoreCreate,
            "update": CghCoreUpdateAll,
            "calc": CghCoreCalc,
            "close": CghCoreClose,
        }
        self._disp = {
            "count": CghDisplayGetMonitorCount,
            "create": CghDisplayCreateWindow,
            "info": CghDisplaySetWindowInfo,
            "show": CghDisplayShowWindow,
            "close": CghDisplayCloseWindow,
        }

    # ---- device ----------------------------------------------------------
    def list_devices(self) -> list[tuple[str, str]]:
        """Enumerate connected EXULUS devices.

        Returns:
            List of ``(serial_number, device_type)`` tuples.
        """
        return [(d[0], d[1]) for d in self._dev["list"]()]

    def open(self, serial: str, baud: int, timeout: int) -> int:
        """Open a serial connection to the device.

        Args:
            serial: Device serial number.
            baud: Serial baud rate.
            timeout: Connection timeout in seconds.

        Returns:
            Non-negative device handle.

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        hdl = self._dev["open"](serial, baud, timeout)
        if hdl < 0:
            raise RuntimeError(f"EXULUSOpen({serial!r}) -> {hdl}")
        return hdl

    def close(self, hdl: int) -> int:
        """Close an open device connection.

        Args:
            hdl: Open device handle.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["close"](hdl)

    def check_communication(self, hdl: int) -> int:
        """Send a probe byte and read the acknowledge code.

        Args:
            hdl: Open device handle.

        Returns:
            ``6`` Ack, ``9`` Nak, ``187`` SPI busy.
        """
        ack = [0]
        self._dev["check"](hdl, ack)
        return ack[0]

    def set_hflip(self, hdl: int, on: bool) -> int:
        """Enable/disable horizontal image flip.

        Args:
            hdl: Open device handle.
            on: ``True`` to mirror the displayed image horizontally.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["set_hflip"](hdl, int(on))

    def get_hflip(self, hdl: int) -> int:
        """Read the current horizontal-flip state.

        Args:
            hdl: Open device handle.

        Returns:
            ``0`` off, ``1`` on.
        """
        v = [0]
        self._dev["get_hflip"](hdl, v)
        return v[0]

    def set_vflip(self, hdl: int, on: bool) -> int:
        """Enable/disable vertical image flip.

        Args:
            hdl: Open device handle.
            on: ``True`` to mirror the displayed image vertically.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["set_vflip"](hdl, int(on))

    def get_vflip(self, hdl: int) -> int:
        """Read the current vertical-flip state.

        Args:
            hdl: Open device handle.

        Returns:
            ``0`` off, ``1`` on.
        """
        v = [0]
        self._dev["get_vflip"](hdl, v)
        return v[0]

    def set_phase_stroke(self, hdl: int, mode: int) -> int:
        """Set phase-stroke mode.

        Args:
            hdl: Open device handle.
            mode: ``0`` full wave, ``1`` half wave.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["set_stroke"](hdl, mode)

    def get_phase_stroke(self, hdl: int) -> int:
        """Read the current phase-stroke mode.

        Args:
            hdl: Open device handle.

        Returns:
            ``0`` full wave, ``1`` half wave.
        """
        v = [0]
        self._dev["get_stroke"](hdl, v)
        return v[0]

    def set_test_pattern(self, hdl: int, on: bool) -> int:
        """Toggle the built-in test pattern.

        Args:
            hdl: Open device handle.
            on: ``True`` to display the internal test pattern.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["set_test"](hdl, int(on))

    def get_test_pattern(self, hdl: int) -> int:
        """Read whether the built-in test pattern is on.

        Args:
            hdl: Open device handle.

        Returns:
            ``0`` off, ``1`` on.
        """
        v = [0]
        self._dev["get_test"](hdl, v)
        return v[0]

    def save_default_setting(self, hdl: int) -> int:
        """Persist the current device settings to EEPROM.

        Args:
            hdl: Open device handle.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._dev["save"](hdl)

    # ---- CGH -------------------------------------------------------------
    def cgh_image_resize(
        self,
        src: np.ndarray,
        width: int,
        height: int,
        mode: int,
        background: int,
    ) -> np.ndarray:
        """Resize a grayscale image into the SLM screen buffer.

        Args:
            src: Source grayscale image as ``uint8`` ndarray.
            width: Target width (pixels).
            height: Target height (pixels).
            mode: Resize strategy forwarded to ``CghImageResize``.
            background: Padding color for ``CENTER``/``FILL`` modes.

        Returns:
            ``uint8`` ndarray of shape ``(height, width)``.

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        flat = np.ascontiguousarray(src, dtype=np.uint8).flatten()
        src_buf = (c_ubyte * len(flat))(*flat)
        dst_buf = (c_ubyte * (width * height))()
        rc = self._cgh["resize"](
            src_buf,
            src.shape[1],
            src.shape[0],
            dst_buf,
            width,
            height,
            mode,
            background,
        )
        if rc < 0:
            raise RuntimeError(f"CghImageResize -> {rc}")
        return np.asarray(dst_buf, dtype=np.uint8).reshape(height, width)

    def cgh_init(self) -> int:
        """Initialise the CGH library.

        Returns:
            ``0`` on success.

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        rc = self._cgh["init"]()
        if rc < 0:
            raise RuntimeError(f"CghCoreInit -> {rc}")
        return rc

    def cgh_create(self) -> int:
        """Create a new CGH compute core.

        Returns:
            Non-negative CGH core handle.

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        hdl = self._cgh["create"]()
        if hdl < 0:
            raise RuntimeError(f"CghCoreCreate -> {hdl}")
        return hdl

    def cgh_update_all(
        self,
        hdl: int,
        width: int,
        height: int,
        pixel_pitch_m: float,
        distance_m: float,
        wavelength_m: float,
    ) -> int:
        """Push optical parameters to a CGH core.

        Args:
            hdl: CGH core handle from :meth:`cgh_create`.
            width: SLM width in pixels.
            height: SLM height in pixels.
            pixel_pitch_m: SLM pixel pitch in meters.
            distance_m: Focal distance in meters.
            wavelength_m: Laser wavelength in meters.

        Returns:
            SDK return code (``0`` on success).

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        rc = self._cgh["update"](
            hdl, width, height, pixel_pitch_m, distance_m, wavelength_m
        )
        if rc < 0:
            raise RuntimeError(f"CghCoreUpdateAll -> {rc}")
        return rc

    def cgh_calc(self, hdl: int, buffer: np.ndarray, stroke_m: float) -> int:
        """Compute the CGH phase pattern into ``buffer`` (modified in place).

        Args:
            hdl: CGH core handle.
            buffer: ``uint8`` 1-D buffer of length ``width * height``.
                Will be overwritten with the phase pattern.
            stroke_m: Effective phase stroke in meters.

        Returns:
            SDK return code (``0`` on success).

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        rc = self._cgh["calc"](hdl, buffer, stroke_m)
        if rc < 0:
            raise RuntimeError(f"CghCoreCalc -> {rc}")
        return rc

    def cgh_close(self, hdl: int) -> int:
        """Release a CGH core.

        Args:
            hdl: CGH core handle.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._cgh["close"](hdl)

    # ---- display ---------------------------------------------------------
    def display_get_monitor_count(self) -> int:
        """Return the number of monitors the SDK can use for display.

        Returns:
            Positive count on success, negative on failure.
        """
        return self._disp["count"]()

    def display_create_window(
        self, monitor: int, width: int, height: int, title: str
    ) -> int:
        """Create a fullscreen display window on a given monitor.

        Args:
            monitor: 1-based monitor index.
            width: Window width in pixels.
            height: Window height in pixels.
            title: Window title.

        Returns:
            Non-negative display-window handle.
        """
        return self._disp["create"](monitor, width, height, title)

    def display_set_window_info(
        self, hdl: int, width: int, height: int, channels: int
    ) -> int:
        """Set window format information.

        Args:
            hdl: Display-window handle.
            width: Window width in pixels.
            height: Window height in pixels.
            channels: ``1`` for grayscale, ``3`` for RGB.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._disp["info"](hdl, width, height, channels)

    def display_show(self, hdl: int, buffer: np.ndarray) -> int:
        """Push a frame to the display window.

        Args:
            hdl: Display-window handle.
            buffer: ``uint8`` ndarray of shape ``(height, width)`` for
                grayscale or ``(height, width, 3)`` for RGB.

        Returns:
            SDK return code (``0`` on success).

        Raises:
            RuntimeError: If the SDK returns a negative status.
        """
        flat = np.ascontiguousarray(buffer, dtype=np.uint8).flatten()
        buf = (c_ubyte * len(flat))(*flat)
        rc = self._disp["show"](hdl, buf)
        if rc < 0:
            raise RuntimeError(f"CghDisplayShowWindow -> {rc}")
        return rc

    def display_close_window(self, hdl: int) -> int:
        """Close and free a display window.

        Args:
            hdl: Display-window handle.

        Returns:
            SDK return code (``0`` on success).
        """
        return self._disp["close"](hdl)


# --------------------------------------------------------------------------- #
# Mock backend (macOS / Linux / unit tests)                                    #
# --------------------------------------------------------------------------- #
class _MockBackend:
    """In-memory backend used when Thorlabs DLLs are unavailable.

    Records every call so unit tests can introspect behaviour. Implements
    the same :class:`SLMBackend` contract as :class:`_RealBackend`.

    Attributes:
        devices: List of ``(serial, type)`` tuples exposed by
            :meth:`list_devices`.
        open_calls: Log of every ``(serial, baud, timeout)`` passed to
            :meth:`open`.
        cgh_runs: Log of ``(hdl, width, height)`` triples passed to
            :meth:`cgh_update_all`.
        last_phase: The most recent phase array passed to
            :meth:`display_show` (or ``None`` if nothing was shown yet).
        monitor_count: Value returned by :meth:`display_get_monitor_count`.
        state: Mutable mapping of device settings for round-trip checks.
    """

    def __init__(self) -> None:
        self._next_dev: int = 1000
        self._next_disp: int = 3000
        self.devices: list[tuple[str, str]] = [("MOCK0001", "EXULUS-Mock")]
        self.open_calls: list[tuple[str, int, int]] = []
        self.cgh_runs: list[tuple[int, int, int]] = []
        self.last_phase: Optional[np.ndarray] = None
        self.monitor_count: int = 1
        self.state: dict[str, int] = {
            "hflip": 0,
            "vflip": 0,
            "stroke": 0,
            "test": 0,
        }

    # ---- device ----------------------------------------------------------
    def list_devices(self) -> list[tuple[str, str]]:
        """Return the mocked device list (a defensive copy)."""
        return list(self.devices)

    def open(self, serial: str, baud: int, timeout: int) -> int:
        """Record the call and return a deterministic synthetic handle."""
        self.open_calls.append((serial, baud, timeout))
        hdl = self._next_dev
        self._next_dev += 1
        return hdl

    def close(self, hdl: int) -> int:
        """No-op close."""
        return 0

    def check_communication(self, hdl: int) -> int:
        """Always return ``6`` (Ack)."""
        return 6

    def set_hflip(self, hdl: int, on: bool) -> int:
        """Store horizontal-flip state for later inspection."""
        self.state["hflip"] = int(on)
        return 0

    def get_hflip(self, hdl: int) -> int:
        """Return stored horizontal-flip state."""
        return self.state["hflip"]

    def set_vflip(self, hdl: int, on: bool) -> int:
        """Store vertical-flip state for later inspection."""
        self.state["vflip"] = int(on)
        return 0

    def get_vflip(self, hdl: int) -> int:
        """Return stored vertical-flip state."""
        return self.state["vflip"]

    def set_phase_stroke(self, hdl: int, mode: int) -> int:
        """Store phase-stroke mode for later inspection."""
        self.state["stroke"] = int(mode)
        return 0

    def get_phase_stroke(self, hdl: int) -> int:
        """Return stored phase-stroke mode."""
        return self.state["stroke"]

    def set_test_pattern(self, hdl: int, on: bool) -> int:
        """Store test-pattern state for later inspection."""
        self.state["test"] = int(on)
        return 0

    def get_test_pattern(self, hdl: int) -> int:
        """Return stored test-pattern state."""
        return self.state["test"]

    def save_default_setting(self, hdl: int) -> int:
        """No-op save."""
        return 0

    # ---- CGH -------------------------------------------------------------
    def cgh_image_resize(
        self,
        src: np.ndarray,
        width: int,
        height: int,
        mode: int,
        background: int,
    ) -> np.ndarray:
        """Resize via OpenCV (mock ignores ``mode`` and ``background``)."""
        return cv2.resize(src, (width, height), interpolation=cv2.INTER_AREA)

    def cgh_init(self) -> int:
        """No-op initialisation."""
        return 0

    def cgh_create(self) -> int:
        """Return a deterministic CGH handle (2000 + number of runs)."""
        return 2000 + len(self.cgh_runs)

    def cgh_update_all(
        self,
        hdl: int,
        width: int,
        height: int,
        pixel_pitch_m: float,
        distance_m: float,
        wavelength_m: float,
    ) -> int:
        """Record the optical parameters; ignore them otherwise."""
        self.cgh_runs.append((hdl, width, height))
        return 0

    def cgh_calc(self, hdl: int, buffer: np.ndarray, stroke_m: float) -> int:
        """Invert the buffer in place so the result is visibly different."""
        view = np.asarray(buffer, dtype=np.uint8)
        view[:] = 255 - view
        return 0

    def cgh_close(self, hdl: int) -> int:
        """No-op close."""
        return 0

    # ---- display ---------------------------------------------------------
    def display_get_monitor_count(self) -> int:
        """Return the configured ``monitor_count``."""
        return self.monitor_count

    def display_create_window(
        self, monitor: int, width: int, height: int, title: str
    ) -> int:
        """Return a deterministic display handle."""
        hdl = self._next_disp
        self._next_disp += 1
        return hdl

    def display_set_window_info(
        self, hdl: int, width: int, height: int, channels: int
    ) -> int:
        """No-op set-info."""
        return 0

    def display_show(self, hdl: int, buffer: np.ndarray) -> int:
        """Cache a defensive copy of the buffer for later assertions."""
        self.last_phase = np.array(buffer, copy=True)
        return 0

    def display_close_window(self, hdl: int) -> int:
        """No-op close."""
        return 0


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #
def _get_backend() -> SLMBackend:
    """Pick a backend based on environment and platform.

    Returns:
        :class:`_MockBackend` when ``LASERLAB_MOCK=1``, otherwise a
        freshly-constructed :class:`_RealBackend`.

    Raises:
        RuntimeError: If the real SDK cannot be loaded on this platform.
    """
    if os.environ.get("LASERLAB_MOCK") == "1":
        return _MockBackend()
    try:
        return _RealBackend()
    except (RuntimeError, OSError, ImportError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Thorlabs EXULUS SDK unavailable. "
            "Set LASERLAB_MOCK=1 to use the mock backend. Cause: " + str(exc)
        ) from exc


# --------------------------------------------------------------------------- #
# High-level API                                                              #
# --------------------------------------------------------------------------- #
class EXULUS:
    """High-level Thorlabs EXULUS SLM controller.

    Args:
        serial: Device serial number. ``None`` picks the first device
            returned by :meth:`list_devices`.
        baud: Serial baud rate forwarded to the SDK.
        timeout: Connection timeout in seconds.
        width: SLM panel width in pixels.
        height: SLM panel height in pixels.
        pixel_pitch_m: SLM pixel pitch in meters.
        wavelength_m: Laser wavelength in meters.
        distance_m: Focal distance in meters.
        stroke_m: Effective phase stroke in meters.

    The default optical parameters match the SDK's example: 6.4 µm panel
    pitch, 1550 nm laser, 0.25 m focal distance, 5.162 µm phase stroke.
    """

    # Resize modes (forwarded to CghImageResize)
    RESIZE_FILL = 0     # stretch to fill
    RESIZE_FIT = 1      # fit inside, pad with background
    RESIZE_STRETCH = 2  # alias for fill in the SDK

    def __init__(
        self,
        serial: Optional[str] = None,
        *,
        baud: int = 38400,
        timeout: int = 3,
        width: int = 1920,
        height: int = 1080,
        pixel_pitch_m: float = 6.4e-6,
        wavelength_m: float = 1.55e-6,
        distance_m: float = 0.25,
        stroke_m: float = 5.162e-6,
    ) -> None:
        self._backend: SLMBackend = _get_backend()
        self._serial: Optional[str] = serial
        self._baud: int = baud
        self._timeout: int = timeout

        self.width: int = width
        self.height: int = height
        self.pixel_pitch_m: float = pixel_pitch_m
        self.wavelength_m: float = wavelength_m
        self.distance_m: float = distance_m
        self.stroke_m: float = stroke_m

        self._dev_hdl: Optional[int] = None
        self._disp_hdl: Optional[int] = None
        self._monitor: Optional[int] = None

    # ---- context manager / lifecycle -------------------------------------
    def __enter__(self) -> "EXULUS":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def connect(self) -> int:
        """Open the device connection.

        Returns:
            The non-negative device handle.

        Raises:
            RuntimeError: If no devices are available or the SDK fails
                to open the requested serial number.
        """
        if self._dev_hdl is not None:
            return self._dev_hdl
        serial: Optional[str] = self._serial
        if not serial:
            devices = self._backend.list_devices()
            if not devices:
                raise RuntimeError("No EXULUS device found")
            serial = devices[0][0]
            self._serial = serial
        self._dev_hdl = self._backend.open(serial, self._baud, self._timeout)
        return self._dev_hdl

    def close(self) -> None:
        """Release the display window and the device handle.

        All exceptions from the backend are swallowed so :meth:`close`
        is safe to call from ``__exit__`` even after a partial failure.
        """
        if self._disp_hdl is not None:
            try:
                self._backend.display_close_window(self._disp_hdl)
            except Exception:
                pass
            self._disp_hdl = None
        if self._dev_hdl is not None:
            try:
                self._backend.close(self._dev_hdl)
            except Exception:
                pass
            self._dev_hdl = None

    @property
    def serial(self) -> Optional[str]:
        """Serial number used (or auto-detected) on :meth:`connect`."""
        return self._serial

    @property
    def device_handle(self) -> Optional[int]:
        """Currently open device handle, or ``None``."""
        return self._dev_hdl

    @property
    def display_handle(self) -> Optional[int]:
        """Currently open display handle, or ``None``."""
        return self._disp_hdl

    @property
    def backend(self) -> SLMBackend:
        """Active backend (mostly for tests and diagnostics)."""
        return self._backend

    # ---- device configuration --------------------------------------------
    def check_communication(self) -> int:
        """Send a probe byte and read the acknowledge code.

        Returns:
            ``6`` Ack, ``9`` Nak, ``187`` SPI busy.

        Raises:
            RuntimeError: If the device is not connected.
        """
        return self._backend.check_communication(self._require_device())

    def set_hflip(self, on: bool) -> None:
        """Enable or disable horizontal image flip on the SLM panel.

        Args:
            on: ``True`` to mirror the displayed image horizontally.

        Raises:
            RuntimeError: If the device is not connected.
        """
        self._backend.set_hflip(self._require_device(), on)

    def get_hflip(self) -> int:
        """Read the current horizontal-flip state.

        Returns:
            ``0`` off, ``1`` on.

        Raises:
            RuntimeError: If the device is not connected.
        """
        return self._backend.get_hflip(self._require_device())

    def set_vflip(self, on: bool) -> None:
        """Enable or disable vertical image flip on the SLM panel.

        Args:
            on: ``True`` to mirror the displayed image vertically.

        Raises:
            RuntimeError: If the device is not connected.
        """
        self._backend.set_vflip(self._require_device(), on)

    def get_vflip(self) -> int:
        """Read the current vertical-flip state.

        Returns:
            ``0`` off, ``1`` on.

        Raises:
            RuntimeError: If the device is not connected.
        """
        return self._backend.get_vflip(self._require_device())

    def set_phase_stroke(self, mode: int) -> None:
        """Set phase-stroke mode.

        Args:
            mode: ``0`` for full wave, ``1`` for half wave.

        Raises:
            RuntimeError: If the device is not connected.
        """
        self._backend.set_phase_stroke(self._require_device(), mode)

    def get_phase_stroke(self) -> int:
        """Read the current phase-stroke mode.

        Returns:
            ``0`` for full wave, ``1`` for half wave.

        Raises:
            RuntimeError: If the device is not connected.
        """
        return self._backend.get_phase_stroke(self._require_device())

    def set_test_pattern(self, on: bool) -> None:
        """Toggle the built-in test pattern.

        Args:
            on: ``True`` to display the internal test pattern.

        Raises:
            RuntimeError: If the device is not connected.
        """
        self._backend.set_test_pattern(self._require_device(), on)

    def get_test_pattern(self) -> int:
        """Read whether the built-in test pattern is on.

        Returns:
            ``0`` off, ``1`` on.

        Raises:
            RuntimeError: If the device is not connected.
        """
        return self._backend.get_test_pattern(self._require_device())

    def save_default_setting(self) -> None:
        """Persist the current device settings to EEPROM.

        Raises:
            RuntimeError: If the device is not connected.
        """
        self._backend.save_default_setting(self._require_device())

    # ---- image loading ----------------------------------------------------
    def load_image(
        self,
        path: str | Path,
        resize_mode: int = RESIZE_FILL,
        background: int = 0,
    ) -> np.ndarray:
        """Read an image file, convert to grayscale and resize to SLM screen.

        Args:
            path: Path to a PNG / JPG / etc. readable by OpenCV.
            resize_mode: One of :attr:`RESIZE_FILL`, :attr:`RESIZE_FIT`,
                :attr:`RESIZE_STRETCH`.
            background: Padding colour (0-255) for fitting modes.

        Returns:
            ``uint8`` ndarray of shape ``(self.height, self.width)``.

        Raises:
            FileNotFoundError: If OpenCV cannot read ``path``.
        """
        path_str = str(path)
        raw = cv2.imread(path_str, cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise FileNotFoundError(f"Failed to load image: {path_str}")
        return self._backend.cgh_image_resize(
            raw, self.width, self.height, resize_mode, background
        )

    # ---- CGH calculation --------------------------------------------------
    def compute_cgh(self, image: np.ndarray) -> np.ndarray:
        """Run the Thorlabs CGH pipeline on a grayscale image.

        Args:
            image: ``uint8`` grayscale array of shape
                ``(self.height, self.width)``. Modified in place.

        Returns:
            The phase pattern (``uint8``, shape ``(height, width)``).

        Raises:
            ValueError: If ``image`` is not 2-D or its shape does not
                match the SLM screen.
        """
        if image.ndim != 2:
            raise ValueError(f"image must be 2D, got shape {image.shape}")
        if image.shape != (self.height, self.width):
            raise ValueError(
                f"image shape {image.shape} != SLM screen "
                f"({self.height}, {self.width})"
            )

        # ``buffer`` is filled in place by the SDK.
        buffer = np.ascontiguousarray(image, dtype=np.uint8).reshape(-1)
        self._backend.cgh_init()
        cgh_hdl: int = self._backend.cgh_create()
        try:
            self._backend.cgh_update_all(
                cgh_hdl,
                self.width,
                self.height,
                self.pixel_pitch_m,
                self.distance_m,
                self.wavelength_m,
            )
            self._backend.cgh_calc(cgh_hdl, buffer, self.stroke_m)
        finally:
            self._backend.cgh_close(cgh_hdl)
        return buffer.reshape(self.height, self.width)

    # ---- display ----------------------------------------------------------
    def open_display(
        self,
        monitor: int = 1,
        title: str = "EXULUS SLM",
        channels: int = 1,
    ) -> int:
        """Create the SLM display window on a monitor.

        Args:
            monitor: 1-based monitor index reported by the SDK.
            title: Window title.
            channels: ``1`` for grayscale, ``3`` for RGB.

        Returns:
            Non-negative display-window handle.

        Raises:
            RuntimeError: If no monitors are detected or the SDK fails.
            ValueError: If ``monitor`` is out of range.
        """
        count = self._backend.display_get_monitor_count()
        if count <= 0:
            raise RuntimeError("No monitors detected for SLM display")
        if not 1 <= monitor <= count:
            raise ValueError(f"monitor {monitor} out of range 1..{count}")
        self._monitor = monitor
        hdl = self._backend.display_create_window(
            monitor, self.width, self.height, title
        )
        if hdl < 0:
            raise RuntimeError(f"CghDisplayCreateWindow -> {hdl}")
        self._backend.display_set_window_info(hdl, self.width, self.height, channels)
        self._disp_hdl = hdl
        return hdl

    def show_phase(self, phase: np.ndarray) -> None:
        """Display a precomputed phase pattern on the SLM.

        Opens the display window automatically on the first call.

        Args:
            phase: ``uint8`` ndarray of shape
                ``(self.height, self.width)``.

        Raises:
            ValueError: If ``phase`` has the wrong dtype or shape.
            RuntimeError: If the SDK fails to display the frame.
        """
        if phase.dtype != np.uint8 or phase.shape != (self.height, self.width):
            raise ValueError(
                f"phase must be uint8 ({self.height}, {self.width}); "
                f"got {phase.shape} {phase.dtype}"
            )
        disp_hdl = self._require_display()
        self._backend.display_show(disp_hdl, phase)

    def show_array(
        self,
        image: np.ndarray,
        *,
        resize_mode: int = RESIZE_FILL,
        background: int = 0,
    ) -> np.ndarray:
        """Compute the CGH from a numpy image and display it.

        Args:
            image: Grayscale (``H x W``) or BGR (``H x W x 3``) image.
            resize_mode: One of :attr:`RESIZE_FILL`, :attr:`RESIZE_FIT`,
                :attr:`RESIZE_STRETCH`.
            background: Padding colour for fitting modes.

        Returns:
            The computed phase pattern.
        """
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.shape != (self.height, self.width):
            image = self._backend.cgh_image_resize(
                image, self.width, self.height, resize_mode, background
            )
        phase = self.compute_cgh(image)
        self.show_phase(phase)
        return phase

    def show_image(
        self,
        path: str | Path,
        *,
        resize_mode: int = RESIZE_FILL,
        background: int = 0,
        monitor: int = 1,
        title: str = "EXULUS SLM",
    ) -> np.ndarray:
        """End-to-end: read image file -> compute CGH -> display on SLM.

        Opens the display window on the first call.

        Args:
            path: Image file readable by OpenCV.
            resize_mode: One of :attr:`RESIZE_FILL`, :attr:`RESIZE_FIT`,
                :attr:`RESIZE_STRETCH`.
            background: Padding colour for fitting modes.
            monitor: 1-based monitor index for :meth:`open_display`.
            title: Window title for :meth:`open_display`.

        Returns:
            The computed phase pattern.
        """
        gray = self.load_image(path, resize_mode=resize_mode, background=background)
        if self._disp_hdl is None:
            self.open_display(monitor=monitor, title=title)
        phase = self.compute_cgh(gray)
        self.show_phase(phase)
        return phase

    # ---- internals --------------------------------------------------------
    def _require_device(self) -> int:
        """Return the open device handle or raise.

        Returns:
            The non-negative device handle.

        Raises:
            RuntimeError: If :meth:`connect` has not succeeded.
        """
        hdl = self._dev_hdl
        if hdl is None:
            raise RuntimeError("Device is not connected. Call connect() first.")
        return hdl

    def _require_display(self) -> int:
        """Return the open display handle or lazily create one.

        Returns:
            The non-negative display handle.

        Raises:
            RuntimeError: If the SDK fails to create a display window.
        """
        disp_hdl = self._disp_hdl
        if disp_hdl is None:
            return self.open_display(monitor=self._monitor or 1)
        return disp_hdl