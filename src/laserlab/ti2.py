"""Nikon Ti2 control via Ti2_Mic_Driver.dll (Windows only).

Z is in micrometres. Autofocus uses SDK contrast AF / Auto Focus FLUO (RUN_AF family).
PFS functions are kept as independent helpers (pfs_on / pfs_off / pfs_wait).
"""

from __future__ import annotations

import collections.abc as cabc
import ctypes as ct
import dataclasses
import os
import time
from typing import Any

import cv2
import numpy as np

LX_OK = 0
_ERR = {
    0: "LX_OK",
    -1: "LX_ERR_UNEXPECTED",
    -2: "LX_ERR_NOTIMPL",
    -3: "LX_ERR_OUTOFMEMORY",
    -4: "LX_ERR_INVALIDARG",
    -5: "LX_ERR_NOINTERFACE",
    -6: "LX_ERR_POINTER",
    -7: "LX_ERR_HANDLE",
    -8: "LX_ERR_ABORT",
    -9: "LX_ERR_FAIL",
    -10: "LX_ERR_ACCESSDENIED",
}

MASK_Z = 0x1
MASK_TURRET1 = 0x10
MASK_TURRET1_SH = 0x20
MASK_TURRET2 = 0x40
MASK_TURRET2_SH = 0x80
MASK_PFS_SWITCH = 0x10000
MASK_PFS_OFFSET = 0x20000
MASK_PFS_STATUS = 0x40000
MASK_PFS_DM = 0x80000
MASK_FILTER1 = 0x1000000
MASK_FILTER2 = 0x2000000
MASK_DIA_SW = 0x4000000
MASK_DIA_POS = 0x8000000
MASK_EPI_UNIT = 0x4000000000
MASK_EPI_POS = 0x8000000000
MASK_EPI_SW = 0x10000000000

PFS_ON_FOCUS = 1 << 8
CMD_PFS_SEARCH = "RUN_PFS_SEARCH_OFFSET"
CMD_WAIT_PFS = "WaitForPFS"

# Dedicated contrast autofocus commands (Auto Focus FLUO in Ti2 workflow)
CMD_RUN_AF = "RUN_AF"
CMD_STOP_AF = "STOP_AF"
CMD_STOP_AF_ZPRIN = "STOP_AF_ZPRIN"
CMD_RUN_AF_ZPRINT = "RUN_AF_ZPRINT"
CMD_GET_AF_ZPRINT = "GET_AF_ZPRINT"
CMD_GET_AF_ZPOSITION = "GET_AF_ZPOSITION"
CMD_MOVE_AF_ZPRINT_POS = "MOVE_AF_ZPRINT_POS"
CMD_RESET_AF_TIMESTAMP = "RESET_AF_TIMESTAMP"
CMD_SET_IO_CONTROL_BOX = "SET_IO_CONTROL_BOX"
CMD_SET_IO_CONTROLBOX_TRIGGER_EDGE = "SET_IO_CONTROLBOX_TRIGGER_EDGE"

# Objective Z-height hard limits in micrometres (um)
DEFAULT_Z_MIN_UM: float = 500.0
DEFAULT_Z_MAX_UM: float = 2600.0

_DEFAULT_DLL = r"C:\Program Files\Nikon\Ti2-SDK\Bin\Ti2_Mic_Driver.dll"


class Ti2Error(RuntimeError):
    pass


@dataclasses.dataclass
class AutofocusCameraResult:
    """Sharpness measurements and selected position from a camera autofocus scan."""

    sharpness: list[float]
    z_positions_um: list[float]
    best_index: int
    best_score: float
    best_z_um: float


def _check(code: int, fn: str) -> None:
    if int(code) != LX_OK:
        raise Ti2Error(f"{fn} failed: {_ERR.get(int(code), code)}")


class _Tail(ct.Union):
    """1024-byte TIRF/DLED union; uint64 forces 8-byte alignment."""

    _fields_ = [("Reserve", ct.c_char * 1024), ("_u64", ct.c_uint64)]


class MIC_Data(ct.Structure):
    """Layout matches new_mic_sdk2.h MIC_Data (MSVC x64)."""

    _fields_ = [
        ("uiDataUsageMask", ct.c_uint64),
        ("uiMicOperationCounter", ct.c_uint64),
        ("uiIOforTrigger", ct.c_uint64),
        ("iZPOSITION", ct.c_int32),
        ("iZPOSITIONSpeed", ct.c_int32),
        ("iZPOSITIONTolerance", ct.c_int32),
        ("iXPOSITION", ct.c_int32),
        ("iXPOSITIONSpeed", ct.c_int32),
        ("iXPOSITIONTolerance", ct.c_int32),
        ("iYPOSITION", ct.c_int32),
        ("iYPOSITIONSpeed", ct.c_int32),
        ("iYPOSITIONTolerance", ct.c_int32),
        ("iNOSEPIECE", ct.c_int32),
        ("iTURRET1POS", ct.c_int32),
        ("iTURRET1SHUTTER", ct.c_int32),
        ("iTURRET2POS", ct.c_int32),
        ("iTURRET2SHUTTER", ct.c_int32),
        ("iCONDENSER", ct.c_int32),
        ("iFILTERWHEEL_BARRIER1", ct.c_int32),
        ("iFILTERWHEEL_BARRIER2", ct.c_int32),
        ("iLIGHTPATH", ct.c_int32),
        ("iSHUTTER_EPI", ct.c_int32),
        ("iSHUTTER_DIA", ct.c_int32),
        ("iSHUTTER_AUX", ct.c_int32),
        ("iDIA_LAMP_Switch", ct.c_int32),
        ("iDIA_LAMP_Pos", ct.c_int32),
        ("iINTENSILIGHT_POS", ct.c_int32),
        ("iINTENSILIGHT_SHUTTER", ct.c_int32),
        ("iINTENSILIGHT_SWITCH", ct.c_int32),
        ("iEPI_LEDPos", ct.c_int32 * 4),
        ("iEPI_LEDUnit", ct.c_int32),
        ("iEPI_LEDSwitch", ct.c_int32 * 4),
        ("iPFS_SWITCH", ct.c_int32),
        ("iPFS_OFFSET", ct.c_int32),
        ("iPFS_DM", ct.c_int32),
        ("iPFS_STATUS", ct.c_int32),
        ("iEYEPIECE_TUBEBASECamPort", ct.c_int32),
        ("iEYEPIECE_TUBEBASETurret", ct.c_int32),
        ("iLAPP_MAINBranch1", ct.c_int32),
        ("iLAPP_MAINBranch2", ct.c_int32),
        ("iLAPP_SUBBranch", ct.c_int32),
        ("iCORRECTION_COLLAR", ct.c_int32),
        ("iDIC_PRISM", ct.c_int32),
        ("iDIC_POLARIZER", ct.c_int32),
        ("iOPTZOOM", ct.c_int32),
        ("iZEscape", ct.c_int32),
        ("iANALYZER_SLOT", ct.c_int32),
        ("iANALYZER_POS", ct.c_int32),
        ("iBertrandLens", ct.c_int32),
        ("iCamera", ct.c_int32),
        ("iCORRECTION_COLLAR_Limit", ct.c_int32),
        ("iZLimit", ct.c_int32),
        ("iXLimit", ct.c_int32),
        ("iYLimit", ct.c_int32),
        ("iMirrorSwitch", ct.c_int32),
        ("iZReset", ct.c_int32),
        ("iXReset", ct.c_int32),
        ("iYReset", ct.c_int32),
        ("iPWSS_Switch", ct.c_int32),
        ("iPWSS_Speed", ct.c_int32),
        ("iPWSA_Switch", ct.c_int32),
        ("iPWSA_Speed", ct.c_int32),
        ("_tail", _Tail),
    ]

    def __init__(self) -> None:
        super().__init__()
        # -1 keeps the previous speed / tolerance
        self.iZPOSITIONSpeed = self.iXPOSITIONSpeed = self.iYPOSITIONSpeed = -1
        self.iZPOSITIONTolerance = self.iXPOSITIONTolerance = self.iYPOSITIONTolerance = -1


class MIC_Command(ct.Structure):
    _fields_ = [("wszCommandString", ct.c_wchar * 256), ("pCommandData", ct.c_void_p)]


class MIC_AFZBuffer(ct.Structure):
    """AF Z position history buffer matching SDK new_mic_sdk2_DedicatedCommand.h."""

    _fields_ = [
        ("DataCount", ct.c_long),
        ("Time", ct.c_long * 6000),       # usec zero-based, -1 = invalid
        ("ZPosition", ct.c_long * 6000),  # ZPos, -999000 = invalid
    ]


def _resolve_dll(dll_path: str | None) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.normpath(os.path.join(here, "..", "..", "docs", "Ti2-SDK", "bin", "Ti2_Mic_Driver.dll"))
    for path in (dll_path, bundled, _DEFAULT_DLL):
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    raise FileNotFoundError("Ti2_Mic_Driver.dll not found; pass dll_path=")


class NikonTi2:
    """Minimal ctypes wrapper for Nikon Ti2-E / Ti2-A."""

    _dll = None
    _dll_path = None

    def __init__(
        self,
        dll_path: str | None = None,
        device_index: int = 0,
        simulator: bool = False,
        z_min_um: float = DEFAULT_Z_MIN_UM,
        z_max_um: float = DEFAULT_Z_MAX_UM,
    ) -> None:
        if float(z_min_um) > float(z_max_um):
            raise ValueError(f"z_min_um ({z_min_um}) cannot be greater than z_max_um ({z_max_um})")
        self.z_min_um = float(z_min_um)
        self.z_max_um = float(z_max_um)
        path = _resolve_dll(dll_path)
        if NikonTi2._dll is None or NikonTi2._dll_path != path:
            NikonTi2._dll = ct.CDLL(path)
            NikonTi2._dll_path = path
            self._bind(NikonTi2._dll)
        self.dll = NikonTi2._dll
        self.accessory_mask = 0
        self._open = False
        self._connect(device_index, simulator)

    @staticmethod
    def _bind(dll) -> None:
        dll.MIC_GetDeviceList.argtypes = [ct.POINTER(ct.c_uint32), ct.POINTER(ct.POINTER(ct.c_int32))]
        dll.MIC_GetDeviceList.restype = ct.c_int32
        dll.MIC_Open.argtypes = [ct.c_int32, ct.POINTER(ct.c_uint64), ct.c_uint32, ct.c_wchar_p]
        dll.MIC_Open.restype = ct.c_int32
        dll.MIC_SimulatorOpen.argtypes = [ct.c_int32, ct.POINTER(ct.c_uint64), ct.c_uint32, ct.c_wchar_p]
        dll.MIC_SimulatorOpen.restype = ct.c_int32
        dll.MIC_Close.argtypes = []
        dll.MIC_Close.restype = ct.c_int32
        dll.MIC_DataSet.argtypes = [ct.POINTER(MIC_Data), ct.POINTER(MIC_Data), ct.c_bool]
        dll.MIC_DataSet.restype = ct.c_int32
        dll.MIC_DataGet.argtypes = [ct.POINTER(MIC_Data)]
        dll.MIC_DataGet.restype = ct.c_int32
        dll.MIC_DedicatedCommand.argtypes = [ct.POINTER(MIC_Command), ct.c_void_p]
        dll.MIC_DedicatedCommand.restype = ct.c_int32
        dll.MIC_Convert_Dev2Phys.argtypes = [ct.c_uint64, ct.c_int32, ct.POINTER(ct.c_double)]
        dll.MIC_Convert_Dev2Phys.restype = ct.c_int32
        dll.MIC_Convert_Phys2Dev.argtypes = [ct.c_uint64, ct.c_double, ct.POINTER(ct.c_int32)]
        dll.MIC_Convert_Phys2Dev.restype = ct.c_int32

    def _connect(self, device_index: int, simulator: bool) -> None:
        count = ct.c_uint32(0)
        types = ct.POINTER(ct.c_int32)()
        _check(self.dll.MIC_GetDeviceList(ct.byref(count), ct.byref(types)), "MIC_GetDeviceList")
        mask = ct.c_uint64(0)
        err = ct.create_unicode_buffer(256)
        use_sim = simulator or count.value == 0
        if use_sim and not simulator and count.value == 0:
            raise Ti2Error("no Ti2 device; retry with simulator=True")
        opener = self.dll.MIC_SimulatorOpen if use_sim else self.dll.MIC_Open
        code = opener(int(device_index), ct.byref(mask), 256, err)
        if code != LX_OK:
            raise Ti2Error(f"{'MIC_SimulatorOpen' if use_sim else 'MIC_Open'} failed: {err.value or _ERR.get(int(code), code)}")
        self.accessory_mask = int(mask.value)
        self._open = True

    def close(self) -> None:
        if self._open:
            self.dll.MIC_Close()
            self._open = False

    def __enter__(self) -> NikonTi2:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _get(self, mask: int) -> MIC_Data:
        data = MIC_Data()
        data.uiDataUsageMask = mask
        _check(self.dll.MIC_DataGet(ct.byref(data)), "MIC_DataGet")
        return data

    def _set(self, data: MIC_Data) -> MIC_Data:
        out = MIC_Data()
        _check(self.dll.MIC_DataSet(ct.byref(data), ct.byref(out), True), "MIC_DataSet")
        return out

    def _to_dev(self, mask: int, phys: float) -> int:
        dev = ct.c_int32(0)
        _check(self.dll.MIC_Convert_Phys2Dev(mask, float(phys), ct.byref(dev)), "MIC_Convert_Phys2Dev")
        return int(dev.value)

    def _to_phys(self, mask: int, dev: int) -> float:
        phys = ct.c_double(0.0)
        _check(self.dll.MIC_Convert_Dev2Phys(mask, int(dev), ct.byref(phys)), "MIC_Convert_Dev2Phys")
        return float(phys.value)

    def _cmd(self, name: str, data, out=None) -> None:
        cmd = MIC_Command()
        cmd.wszCommandString = name
        cmd.pCommandData = ct.cast(ct.byref(data), ct.c_void_p) if data is not None else None
        ptr = ct.cast(out, ct.c_void_p) if out is not None else None
        _check(self.dll.MIC_DedicatedCommand(ct.byref(cmd), ptr), name)

    # --- Z (um) ---

    def get_z(self) -> float:
        return self._to_phys(MASK_Z, self._get(MASK_Z).iZPOSITION)

    def set_z(self, um: float, speed: int = 1, tolerance: int = 0) -> float:
        um = float(um)
        if not (self.z_min_um <= um <= self.z_max_um):
            raise ValueError(
                f"Target Z position {um:.2f} um is out of safe hard limits [{self.z_min_um:.2f}, {self.z_max_um:.2f}] um"
            )
        data = MIC_Data()
        data.uiDataUsageMask = MASK_Z
        data.iZPOSITION = self._to_dev(MASK_Z, um)
        data.iZPOSITIONSpeed = int(speed)
        data.iZPOSITIONTolerance = int(tolerance)
        return self._to_phys(MASK_Z, self._set(data).iZPOSITION)

    @staticmethod
    def calculate_sharpness(image: np.ndarray) -> float:
        """Calculate focus sharpness using the variance of the Laplacian."""
        if image.dtype == np.uint16:
            image_8u = (image >> 4).astype(np.uint8)
        else:
            image_8u = image.astype(np.uint8)
        return float(cv2.Laplacian(image_8u, cv2.CV_64F).var())

    # --- LED: DIA lamp (0-100%) and EPI LED (channel 1-4, level 1-6 = 10-100%) ---

    def get_dia_lamp(self) -> tuple[bool, float]:
        d = self._get(MASK_DIA_SW | MASK_DIA_POS)
        return bool(d.iDIA_LAMP_Switch), self._to_phys(MASK_DIA_POS, d.iDIA_LAMP_Pos)

    def set_dia_lamp(self, on: bool | None = None, percent: float | None = None) -> tuple[bool, float]:
        data = MIC_Data()
        if on is not None:
            data.uiDataUsageMask |= MASK_DIA_SW
            data.iDIA_LAMP_Switch = 1 if on else 0
        if percent is not None:
            data.uiDataUsageMask |= MASK_DIA_POS
            data.iDIA_LAMP_Pos = self._to_dev(MASK_DIA_POS, float(percent))
        if not data.uiDataUsageMask:
            raise ValueError("set on and/or percent")
        out = self._set(data)
        return bool(out.iDIA_LAMP_Switch), self._to_phys(MASK_DIA_POS, out.iDIA_LAMP_Pos)

    def get_epi_led(self, channel: int) -> tuple[bool, int]:
        if channel not in (1, 2, 3, 4):
            raise ValueError("EPI channel must be 1-4")
        d = self._get(MASK_EPI_SW | MASK_EPI_POS)
        i = channel - 1
        return bool(d.iEPI_LEDSwitch[i]), int(d.iEPI_LEDPos[i])

    def set_epi_led(self, channel: int, on: bool | None = None, level: int | None = None) -> tuple[bool, int]:
        if channel not in (1, 2, 3, 4):
            raise ValueError("EPI channel must be 1-4")
        data = MIC_Data()
        data.iEPI_LEDUnit = channel
        data.uiDataUsageMask = MASK_EPI_UNIT
        i = channel - 1
        if on is not None:
            data.uiDataUsageMask |= MASK_EPI_SW
            data.iEPI_LEDSwitch[i] = 1 if on else 0
        if level is not None:
            if not 1 <= int(level) <= 6:
                raise ValueError("EPI level must be 1-6 (10-100%)")
            data.uiDataUsageMask |= MASK_EPI_POS
            data.iEPI_LEDPos[i] = int(level)
        out = self._set(data)
        return bool(out.iEPI_LEDSwitch[i]), int(out.iEPI_LEDPos[i])

    # --- Turret 1-2 (pos 1-6) and barrier filter wheels 1-2 (pos 1-7) ---

    def get_turret(self, turret: int) -> int:
        if turret == 1:
            return int(self._get(MASK_TURRET1).iTURRET1POS)
        if turret == 2:
            return int(self._get(MASK_TURRET2).iTURRET2POS)
        raise ValueError("turret must be 1 or 2")

    def set_turret(self, turret: int, position: int | None = None, shutter: bool | None = None) -> int:
        data = MIC_Data()
        if turret == 1:
            pos_m, sh_m, pos_f, sh_f = MASK_TURRET1, MASK_TURRET1_SH, "iTURRET1POS", "iTURRET1SHUTTER"
        elif turret == 2:
            pos_m, sh_m, pos_f, sh_f = MASK_TURRET2, MASK_TURRET2_SH, "iTURRET2POS", "iTURRET2SHUTTER"
        else:
            raise ValueError("turret must be 1 or 2")
        if position is not None:
            if not 1 <= int(position) <= 6:
                raise ValueError("turret position must be 1-6")
            data.uiDataUsageMask |= pos_m
            setattr(data, pos_f, int(position))
        if shutter is not None:
            data.uiDataUsageMask |= sh_m
            setattr(data, sh_f, 1 if shutter else 0)
        if not data.uiDataUsageMask:
            raise ValueError("set position and/or shutter")
        out = self._set(data)
        return int(getattr(out, pos_f))

    def get_filter(self, wheel: int) -> int:
        if wheel == 1:
            return int(self._get(MASK_FILTER1).iFILTERWHEEL_BARRIER1)
        if wheel == 2:
            return int(self._get(MASK_FILTER2).iFILTERWHEEL_BARRIER2)
        raise ValueError("filter wheel must be 1 or 2")

    def set_filter(self, wheel: int, position: int) -> int:
        if not 1 <= int(position) <= 7:
            raise ValueError("filter position must be 1-7")
        data = MIC_Data()
        if wheel == 1:
            data.uiDataUsageMask = MASK_FILTER1
            data.iFILTERWHEEL_BARRIER1 = int(position)
            field = "iFILTERWHEEL_BARRIER1"
        elif wheel == 2:
            data.uiDataUsageMask = MASK_FILTER2
            data.iFILTERWHEEL_BARRIER2 = int(position)
            field = "iFILTERWHEEL_BARRIER2"
        else:
            raise ValueError("filter wheel must be 1 or 2")
        return int(getattr(self._set(data), field))

    # --- PFS (Perfect Focus System) helpers ---

    def pfs_on(self) -> None:
        data = MIC_Data()
        data.uiDataUsageMask = MASK_PFS_SWITCH | MASK_PFS_DM
        data.iPFS_SWITCH = 1
        data.iPFS_DM = 2  # dichroic IN
        self._set(data)

    def pfs_off(self) -> None:
        data = MIC_Data()
        data.uiDataUsageMask = MASK_PFS_SWITCH
        data.iPFS_SWITCH = 0
        self._set(data)

    def pfs_status(self) -> int:
        return int(self._get(MASK_PFS_STATUS).iPFS_STATUS)

    def pfs_search_offset(self, stop_level: int = 0) -> None:
        self._cmd(CMD_PFS_SEARCH, ct.c_int32(int(stop_level)))

    def pfs_wait(self, timeout_ms: int = 10000) -> tuple[int, int]:
        """Block until PFS settles. Returns (offset, status)."""
        out = (ct.c_int32 * 2)()
        self._cmd(CMD_WAIT_PFS, ct.c_int32(int(timeout_ms)), out)
        return int(out[0]), int(out[1])

    # --- Contrast Autofocus / Auto Focus FLUO (RUN_AF family) ---

    def af_setup_io(self, io_mask: int = 0x00, falling_edge_mask: int = 0x100) -> None:
        """Configure Control Box I/O ports and trigger edges for AF.

        Defaults match SDK Example8 (Run_Example8):
          - IO1~IO8 as Input (0x00)
          - IO1 trigger on falling edge (0x100 = bit8)
        """
        val_io = (ct.c_uint32 * 1)(int(io_mask) & 0xFF)
        self._cmd(CMD_SET_IO_CONTROL_BOX, val_io)

        val_edge = (ct.c_uint32 * 1)(int(falling_edge_mask) & 0xFFFF)
        self._cmd(CMD_SET_IO_CONTROLBOX_TRIGGER_EDGE, val_edge)

    def af_start(
        self,
        io_channel: int = 1,
        z_relative_dev: int = 500000,
        speed: int = 9,
    ) -> None:
        """Arm contrast autofocus and start Z-print motion.

        Parameters
        ----------
        io_channel : int
            1-8 for ControlBox I/O, 9-25 for ExtensionBox.
        z_relative_dev : int
            Relative Z travel in device linear units (e.g. 500000 as in sample).
        speed : int
            Z scan speed (1-19, sample uses 9).
        """
        io_arg = (ct.c_int32 * 1)(int(io_channel))
        self._cmd(CMD_RUN_AF, io_arg)
        self._cmd(CMD_RESET_AF_TIMESTAMP, None)

        zprint_arg = (ct.c_int32 * 2)(int(z_relative_dev), int(speed))
        self._cmd(CMD_RUN_AF_ZPRINT, zprint_arg)

    def af_stop_zprint(self) -> None:
        """Stop active AF Z-print motion."""
        self._cmd(CMD_STOP_AF_ZPRIN, None)

    def af_stop(self) -> None:
        """Terminate AF mode on the microscope controller."""
        self._cmd(CMD_STOP_AF, None)

    def af_get_z_positions(self) -> list[tuple[int, int]]:
        """Retrieve recorded Z positions and timestamps from AF buffer.

        Returns list of (time_usec, z_position_dev).
        """
        buf = MIC_AFZBuffer()
        self._cmd(CMD_GET_AF_ZPOSITION, None, out=ct.byref(buf))
        records = []
        for i in range(max(0, min(buf.DataCount, 6000))):
            t = int(buf.Time[i])
            z = int(buf.ZPosition[i])
            if t >= 0 and z != -999000:
                records.append((t, z))
        return records

    def af_get_zprint_pos(self, index: int) -> tuple[int, int]:
        """Read linear-scale position for AF slice index (1-5000).

        Returns (index, pos_dev).
        """
        if not 1 <= int(index) <= 5000:
            raise ValueError("AF index must be between 1 and 5000")
        arg = (ct.c_int32 * 1)(int(index))
        out = (ct.c_int32 * 2)()
        self._cmd(CMD_GET_AF_ZPRINT, arg, out=out)
        return int(out[0]), int(out[1])

    def af_move_to_index(self, index: int, speed: int = 1, tolerance: int = 0) -> None:
        """Move Z drive to recorded best AF position index (1-5000)."""
        if not 1 <= int(index) <= 5000:
            raise ValueError("AF index must be between 1 and 5000")
        try:
            _, pos_dev = self.af_get_zprint_pos(index)
            pos_um = self._to_phys(MASK_Z, pos_dev)
            if not (self.z_min_um <= pos_um <= self.z_max_um):
                raise ValueError(
                    f"AF target position {pos_um:.2f} um for index {index} is out of safe hard limits [{self.z_min_um:.2f}, {self.z_max_um:.2f}] um"
                )
        except Exception as e:
            if isinstance(e, ValueError) and "safe hard limits" in str(e):
                raise
        arg = (ct.c_int32 * 3)(int(index), int(speed), int(tolerance))
        self._cmd(CMD_MOVE_AF_ZPRINT_POS, arg)

    def autofocus(
        self,
        io_channel: int = 1,
        z_relative_dev: int | None = None,
        speed: int = 9,
        scan_duration_s: float = 1.0,
        live_callback: cabc.Callable[[], Any] | None = None,
        best_index: int | None = 1,
        move_to_best: bool = True,
        scan_half_range_um: float = 50.0,
        scan_steps: int = 40,
        stop_on_sharpness_drop: bool = False,
    ) -> bool:
        """Run Ti2 SDK contrast AF / Auto Focus FLUO sequence.

        Follows dedicated command sequence from Nikon Ti2 SDK:
          1. Configure I/O port trigger edge (SET_IO_CONTROL_BOX / SET_IO_CONTROLBOX_TRIGGER_EDGE).
          2. Move to the lower end of the physical scan range.
          3. Arm RUN_AF on specified exposure I/O channel.
          4. Reset AF timestamp and start RUN_AF_ZPRINT search.
          5. Wait for camera exposure triggers during live_callback / scan_duration_s.
          6. STOP_AF_ZPRIN.
          7. Move to target focus index (MOVE_AF_ZPRINT_POS) if requested.
          8. STOP_AF.

        Parameters
        ----------
        io_channel : int
            Camera exposure signal I/O port (1-8 control box).
        speed : int
            AF Z-drive speed (default 9).
        scan_duration_s : float
            Time in seconds to wait for frame trigger collection if live_callback is not provided.
        live_callback : callable, optional
            Optional hook invoked while AF-ZPRINT is acquiring triggers (e.g. camera capture loop).
        best_index : int, optional
            Best contrast slice index (1-5000). If provided and move_to_best is True,
            drives stage to that position.
        move_to_best : bool
            Whether to call MOVE_AF_ZPRINT_POS after stopping Z-print.
        scan_half_range_um : float
            Half-width of the physical Z scan range around the current position.
            The default scans from current Z - 50 um to current Z + 50 um.
        scan_steps : int
            Number of frames and Z positions in a software scan.
        stop_on_sharpness_drop : bool
            Stop a software scan after two consecutive decreases in the numeric
            value returned by ``live_callback``.
        z_relative_dev : int, optional
            Retained for API compatibility; the physical scan range controls travel.

        Returns
        -------
        bool
            True if the AF sequence completed without error.
        """
        if scan_half_range_um <= 0:
            raise ValueError("scan_half_range_um must be greater than zero")
        if scan_steps < 2:
            raise ValueError("scan_steps must be at least 2")

        current_z = self.get_z()
        scan_start_um = max(self.z_min_um, current_z - float(scan_half_range_um))
        scan_end_um = min(self.z_max_um, current_z + float(scan_half_range_um))
        if scan_start_um >= scan_end_um:
            raise ValueError("Autofocus scan range does not contain positive Z travel")

        # Software scoring needs each image to correspond to a known Z position.
        # The SDK Z-print command is asynchronous, so use explicit stage steps
        # when a live callback is supplied instead of racing that command.
        if live_callback is not None:
            previous_score: float | None = None
            consecutive_drops = 0
            for step_index in range(scan_steps):
                fraction = step_index / (scan_steps - 1)
                position_um = scan_start_um + (scan_end_um - scan_start_um) * fraction
                self.set_z(position_um, speed=1)
                callback_result = live_callback()
                if stop_on_sharpness_drop and isinstance(callback_result, (int, float)):
                    score = float(callback_result)
                    if previous_score is not None and score < previous_score:
                        consecutive_drops += 1
                    else:
                        consecutive_drops = 0
                    previous_score = score
                    if consecutive_drops >= 2:
                        break
                if scan_duration_s > 0:
                    time.sleep(float(scan_duration_s) / scan_steps)
            return True

        scan_start_dev = self._to_dev(MASK_Z, scan_start_um)
        scan_end_dev = self._to_dev(MASK_Z, scan_end_um)
        z_relative_dev = abs(scan_end_dev - scan_start_dev)
        if z_relative_dev <= 0:
            raise ValueError("Autofocus scan range is smaller than one Z device unit")

        try:
            self.set_z(scan_start_um, speed=1)
            self.af_start(
                io_channel=io_channel,
                z_relative_dev=z_relative_dev,
                speed=speed,
            )
            if scan_duration_s > 0:
                time.sleep(float(scan_duration_s))
            self.af_stop_zprint()
            if move_to_best and best_index is not None:
                self.af_move_to_index(best_index)
            return True
        finally:
            try:
                self.af_stop()
            except Exception:
                pass

    def autofocus_with_camera(
        self,
        camera: Any,
        sharpness_function: cabc.Callable[[Any], float] | None = None,
        *,
        speed: int = 1,
        scan_duration_s: float = 1.0,
        scan_half_range_um: float = 50.0,
        scan_steps: int = 40,
        stop_on_sharpness_drop: bool = False,
        move_to_best: bool = True,
    ) -> AutofocusCameraResult:
        """Run a software autofocus scan using a camera-like object.

        ``camera`` must provide ``get_image()``. By default, sharpness is
        calculated with :meth:`calculate_sharpness`; pass a custom function to
        use another metric.
        """
        if sharpness_function is None:
            sharpness_function = self.calculate_sharpness
        sharpness: list[float] = []
        z_positions_um: list[float] = []

        def capture_and_score() -> float:
            image = camera.get_image()
            score = float(sharpness_function(image))
            sharpness.append(score)
            z_positions_um.append(self.get_z())
            return score

        self.autofocus(
            speed=speed,
            scan_duration_s=scan_duration_s,
            scan_half_range_um=scan_half_range_um,
            scan_steps=scan_steps,
            stop_on_sharpness_drop=stop_on_sharpness_drop,
            live_callback=capture_and_score,
            move_to_best=False,
        )

        best_index = max(range(len(sharpness)), key=sharpness.__getitem__)
        best_z_um = z_positions_um[best_index]
        if move_to_best:
            self.set_z(best_z_um, speed=1)
        return AutofocusCameraResult(
            sharpness=sharpness,
            z_positions_um=z_positions_um,
            best_index=best_index,
            best_score=sharpness[best_index],
            best_z_um=best_z_um,
        )

    def quick_autofocus_with_camera(
        self,
        camera: Any,
        sharpness_function: cabc.Callable[[Any], float] | None = None,
        *,
        speed: int = 1,
        scan_duration_s: float = 1.0,
        coarse_half_range_um: float = 100.0,
        coarse_steps: int = 10,
        fine_half_range_um: float = 20.0,
        fine_steps: int = 20,
        stop_on_sharpness_drop: bool = True,
    ) -> tuple[AutofocusCameraResult, AutofocusCameraResult]:
        """Run coarse and fine camera autofocus scans.

        The coarse scan uses the current Z position as its center. The fine
        scan then uses the coarse best position as its center.
        """
        coarse_result = self.autofocus_with_camera(
            camera,
            sharpness_function,
            speed=speed,
            scan_duration_s=scan_duration_s,
            scan_half_range_um=coarse_half_range_um,
            scan_steps=coarse_steps,
            stop_on_sharpness_drop=False,
            move_to_best=True,
        )
        fine_result = self.autofocus_with_camera(
            camera,
            sharpness_function,
            speed=speed,
            scan_duration_s=scan_duration_s,
            scan_half_range_um=fine_half_range_um,
            scan_steps=fine_steps,
            stop_on_sharpness_drop=stop_on_sharpness_drop,
            move_to_best=True,
        )
        return coarse_result, fine_result
