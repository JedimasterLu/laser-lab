"""Nikon Ti2 control via Ti2_Mic_Driver.dll (Windows only).

Z is in micrometres. Autofocus uses PFS (Perfect Focus), not contrast AF.
"""

from __future__ import annotations

import ctypes as ct
import os

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

_DEFAULT_DLL = r"C:\Program Files\Nikon\Ti2-SDK\Bin\Ti2_Mic_Driver.dll"


class Ti2Error(RuntimeError):
    pass


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
    ) -> None:
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
        data = MIC_Data()
        data.uiDataUsageMask = MASK_Z
        data.iZPOSITION = self._to_dev(MASK_Z, um)
        data.iZPOSITIONSpeed = int(speed)
        data.iZPOSITIONTolerance = int(tolerance)
        return self._to_phys(MASK_Z, self._set(data).iZPOSITION)

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

    # --- PFS autofocus ---

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

    def autofocus(self, timeout_ms: int = 10000, search_offset: bool = False) -> bool:
        """Enable PFS and wait. Returns True if on-focus (status bit 8)."""
        self.pfs_on()
        if search_offset:
            self.pfs_search_offset()
        _, status = self.pfs_wait(timeout_ms)
        return bool(status & PFS_ON_FOCUS)
