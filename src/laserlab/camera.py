"""Camera wrappers for Nikon DS-Fi3 / DSCam SDK devices."""

from __future__ import annotations

import ctypes as ct
import os
import time
from typing import Any

import numpy as np

from slmsuite.hardware.cameras.camera import Camera


# ---------------------------------------------------------------------------
# SDK constants (from DSCam.h / DSCamFeature.h / DSCamCommand.h / DSCamImage.h)
# ---------------------------------------------------------------------------

LX_OK = 0
LX_ERR_UNEXPECTED = -1
LX_ERR_NOTIMPL = -2
LX_ERR_OUTOFMEMORY = -3
LX_ERR_INVALIDARG = -4
LX_ERR_NOINTERFACE = -5
LX_ERR_POINTER = -6
LX_ERR_HANDLE = -7
LX_ERR_ABORT = -8
LX_ERR_FAIL = -9
LX_ERR_ACCESSDENIED = -10

CAM_DEVICE_MAX = 32
CAM_ERRMSG_MAX = 256
CAM_VERSION_MAX = 16
CAM_NAME_MAX = 32
CAM_FEA_CAPACITY = 64
CAM_FEA_VARIANT_MAX = 256
CAM_FEA_MULTIEXPOSURETIME_MAX = 15
CAM_FEA_FRAME_SIZE_MAX = 143460000
DEF_DRIVER_BUFFER_NUM = 3

# ECamFeatureId
eUnknown = 0
eExposureMode = 1
eExposureBias = 2
eExposureTime = 3
eGain = 4
eFormat = 80
eRoiPosition = 81
eTriggerMode = 82
eRoiSize = 83

# ECamExposureMode
ecemContinuousAE = 0
ecemOnePushAE = 1
ecemManual = 2
ecemMultiExposureTime = 3

# ECamTriggerMode
ectmOff = 0
ectmHard = 1
ectmSoft = 2

# ECamVariantRunType
evrt_unknown = 0
evrt_int32 = 1
evrt_uint32 = 2
evrt_int64 = 3
evrt_uint64 = 4
evrt_double = 5
evrt_bool = 6
evrt_voidptr = 7
evrt_wstr = 8
evrt_Area = 9
evrt_Position = 10
evrt_TriggerOption = 11
evrt_MultiExposureTime = 12
evrt_Format = 13
evrt_Size = 14

# ECamFormatColor
ecfcUnknown = 0
ecfcRgb24 = 1
ecfcYuv444 = 2
ecfcMono16 = 3
ecfcRgb48 = 4
ecfcY16 = 5
ecfcRaw16 = 6

# DS-Fi3 / DS-Ri2 style format modes (ECamFormatMode, camera-dependent)
ecfmH2880x2048 = 1
ecfmH1440x1024Roi = 2
ecfmH1440x1024 = 3

# Common DS-Fi3 mode -> (width, height)
_DSFI3_FORMAT_MODE_SIZE = {
    ecfmH2880x2048: (2880, 2048),
    ecfmH1440x1024Roi: (1440, 1024),
    ecfmH1440x1024: (1440, 1024),
}

# Commands (wide strings)
CAM_CMD_GET_FRAMESIZE = "CAM_CMD_GET_FRAMESIZE"
CAM_CMD_START_FRAMETRANSFER = "CAM_CMD_START_FRAMETRANSFER"
CAM_CMD_STOP_FRAMETRANSFER = "CAM_CMD_STOP_FRAMETRANSFER"
CAM_CMD_IS_TRANSFER_STARTED = "CAM_CMD_IS_TRANSFER_STARTED"
CAM_CMD_ONEPUSH_SOFTTRIGGER = "CAM_CMD_ONEPUSH_SOFTTRIGGER"

_LX_ERROR_NAMES = {
    LX_OK: "LX_OK",
    LX_ERR_UNEXPECTED: "LX_ERR_UNEXPECTED",
    LX_ERR_NOTIMPL: "LX_ERR_NOTIMPL",
    LX_ERR_OUTOFMEMORY: "LX_ERR_OUTOFMEMORY",
    LX_ERR_INVALIDARG: "LX_ERR_INVALIDARG",
    LX_ERR_NOINTERFACE: "LX_ERR_NOINTERFACE",
    LX_ERR_POINTER: "LX_ERR_POINTER",
    LX_ERR_HANDLE: "LX_ERR_HANDLE",
    LX_ERR_ABORT: "LX_ERR_ABORT",
    LX_ERR_FAIL: "LX_ERR_FAIL",
    LX_ERR_ACCESSDENIED: "LX_ERR_ACCESSDENIED",
}


def _lx_name(code: int) -> str:
    return _LX_ERROR_NAMES.get(int(code), f"UNKNOWN({code})")


# ---------------------------------------------------------------------------
# ctypes structures matching the official headers
# ---------------------------------------------------------------------------


class CAM_Device(ct.Structure):
    _fields_ = [
        ("eCamDeviceType", ct.c_int),
        ("uiSerialNo", ct.c_uint32),
        ("wszFwVersion", ct.c_wchar * CAM_VERSION_MAX),
        ("wszFpgaVersion", ct.c_wchar * CAM_VERSION_MAX),
        ("wszUsbDcVersion", ct.c_wchar * CAM_VERSION_MAX),
        ("wszUsbVersion", ct.c_wchar * CAM_VERSION_MAX),
        ("wszDriverVersion", ct.c_wchar * CAM_VERSION_MAX),
        ("wszCameraName", ct.c_wchar * CAM_NAME_MAX),
    ]


class CAM_Area(ct.Structure):
    _fields_ = [
        ("uiLeft", ct.c_uint32),
        ("uiTop", ct.c_uint32),
        ("uiWidth", ct.c_uint32),
        ("uiHeight", ct.c_uint32),
    ]


class CAM_Position(ct.Structure):
    _fields_ = [
        ("uiX", ct.c_uint32),
        ("uiY", ct.c_uint32),
    ]


class CAM_Size(ct.Structure):
    _fields_ = [
        ("uiWidth", ct.c_uint32),
        ("uiHeight", ct.c_uint32),
    ]


class CAM_TriggerOption(ct.Structure):
    _fields_ = [
        ("uiFrameCount", ct.c_uint32),
        ("iDelayTime", ct.c_int32),
    ]


class CAM_MultiExposureTime(ct.Structure):
    _fields_ = [
        ("uiNum", ct.c_uint32),
        ("uiExposureTime", ct.c_uint32 * CAM_FEA_MULTIEXPOSURETIME_MAX),
    ]


class CAM_Format(ct.Structure):
    _fields_ = [
        ("eColor", ct.c_int),
        ("eMode", ct.c_int),
    ]


class CAM_VariantUnion(ct.Union):
    _fields_ = [
        ("i32Value", ct.c_int32),
        ("ui32Value", ct.c_uint32),
        ("i64Value", ct.c_int64),
        ("ui64Value", ct.c_uint64),
        ("dValue", ct.c_double),
        ("bValue", ct.c_bool),
        ("pValue", ct.c_void_p),
        ("wszValue", ct.c_wchar * CAM_FEA_VARIANT_MAX),
        ("stArea", CAM_Area),
        ("stPosition", CAM_Position),
        ("stSize", CAM_Size),
        ("stTriggerOption", CAM_TriggerOption),
        ("stMultiExposureTime", CAM_MultiExposureTime),
        ("stFormat", CAM_Format),
    ]


class CAM_Variant(ct.Structure):
    _fields_ = [
        ("eVarType", ct.c_int),
        ("u", CAM_VariantUnion),
    ]


class CAM_FeatureValue(ct.Structure):
    _fields_ = [
        ("uiFeatureId", ct.c_uint32),
        ("stVariant", CAM_Variant),
        ("ucTransSize", ct.c_uint8),
    ]


class Vector_CAM_FeatureValue(ct.Structure):
    _fields_ = [
        ("uiCountUsed", ct.c_uint32),
        ("uiCapacity", ct.c_uint32),
        ("uiPauseTransfer", ct.c_uint32),
        ("pstFeatureValue", ct.POINTER(CAM_FeatureValue)),
    ]


class CAM_Image(ct.Structure):
    _fields_ = [
        ("pDataBuffer", ct.c_void_p),
        ("uiDataBufferSize", ct.c_uint32),
        ("uiImageSize", ct.c_uint32),
        ("uiEndTime", ct.c_uint32),
        ("uiEndTime64", ct.c_uint64),
        ("uiFrameCount", ct.c_uint64),
        ("uiRefCount", ct.c_uint32),
    ]


class CAM_CMD_GetFrameSize(ct.Structure):
    _fields_ = [
        ("uiFrameSize", ct.c_uint32),
        ("uiFrameInterval", ct.c_uint32),
        ("uiRShutterDelay", ct.c_uint32),
    ]


class CAM_CMD_StartFrameTransfer(ct.Structure):
    _fields_ = [
        ("uiImageBufferNum", ct.c_uint32),
    ]


class CAM_CMD_IsTransferStarted(ct.Structure):
    _fields_ = [
        ("bStarted", ct.c_bool),
    ]


class CAM_ImageInfo(ct.Structure):
    _pack_ = 1
    _fields_ = [
        ("usFrameNo", ct.c_uint16),
        ("usTrggerOptionNo", ct.c_uint16),
        ("usMultiExposureTimeNo", ct.c_uint16),
        ("ucReserve006", ct.c_uint8 * 2),
        ("uiExposureTime", ct.c_uint32),
        ("uiFocusLevelR", ct.c_uint32),
        ("uiFocusLevelGr", ct.c_uint32),
        ("uiFocusLevelGb", ct.c_uint32),
        ("uiFocusLevelB", ct.c_uint32),
        ("ucReserve028", ct.c_uint8 * 36),
        ("ucCameraType", ct.c_uint8),
        ("ucImageMode", ct.c_uint8),
        ("ucImageColor", ct.c_uint8),
        ("ucTriggerMode", ct.c_uint8),
        ("uiSerialNo", ct.c_uint32),
        ("uiFwVersion", ct.c_uint32),
        ("uiFpgaVersion", ct.c_uint32),
        ("usUsbDcVersion", ct.c_uint16),
        ("ucReserve082", ct.c_uint8 * 2),
        ("usImageWidth", ct.c_uint16),
        ("usImageHeight", ct.c_uint16),
        ("usRoiLeft", ct.c_uint16),
        ("usRoiTop", ct.c_uint16),
        ("uiFrameSize", ct.c_uint32),
        ("ucExposureMode", ct.c_uint8),
        ("cExposureBias", ct.c_int8),
        ("ucTone", ct.c_uint8),
        ("ucScene", ct.c_uint8),
        ("ucReserve100", ct.c_uint8 * 4),
        ("usGain", ct.c_uint16),
        ("sBrightness", ct.c_int16),
        ("cSharpness", ct.c_int8),
        ("ucCaptureMode", ct.c_uint8),
        ("ucAeStay", ct.c_uint8),
        ("ucMeteringMode", ct.c_uint8),
        ("usMeteringAreaLeft", ct.c_uint16),
        ("usMeteringAreaTop", ct.c_uint16),
        ("usMeteringAreaWidth", ct.c_uint16),
        ("usMeteringAreaHeight", ct.c_uint16),
        ("sHue", ct.c_int16),
        ("sSaturation", ct.c_int16),
        ("usWhiteBalanceRed", ct.c_uint16),
        ("usWhiteBalanceBlue", ct.c_uint16),
        ("usDefect", ct.c_uint16),
        ("usWhiteBalanceGreen", ct.c_uint16),
        ("ucReserve132", ct.c_uint8 * 4),
        ("ucReserve136", ct.c_uint8 * 4),
        ("cWhiteBalance", ct.c_int8),
        ("ucReserve140", ct.c_uint8 * 1),
        ("usAutoWhiteBalanceRed", ct.c_uint16),
        ("usAutoWhiteBalanceGreen", ct.c_uint16),
        ("usAutoWhiteBalanceBlue", ct.c_uint16),
        ("usAutoWhiteBalanceX", ct.c_uint16),
        ("usAutoWhiteBalanceY", ct.c_uint16),
        ("ucReserve152", ct.c_int8),
        ("cIrcfAdaptor", ct.c_int8),
        ("usDefect2", ct.c_uint16),
        ("ucReserve156", ct.c_uint8 * 4),
        ("ucReserve160", ct.c_uint8 * 96),
    ]


CAM_IMG_INFO_SIZE = ct.sizeof(CAM_ImageInfo)


class NikonDSFi3Camera(Camera):
    """ctypes wrapper for Nikon DSCam SDK (DS-Fi3 and related cameras).

    Correct acquisition flow (from official headers / KsCamExample):
      1. CAM_OpenDevices
      2. CAM_Open(device_index, handle, errmsg...)
      3. CAM_SetFeatures (e.g. ExposureMode=Manual, ExposureTime in usec)
      4. CAM_Command(GET_FRAMESIZE)
      5. CAM_Command(START_FRAMETRANSFER, buffer_num)
      6. CAM_GetImage(handle, newest, CAM_Image, remained)
      7. CAM_Command(STOP_FRAMETRANSFER) / CAM_Close / CAM_CloseDevices
    """

    sdk = None
    _devices_opened = False
    _device_count = 0
    _device_array_ptr = None

    _default_exposure_s = 0.1

    def __init__(
        self,
        dll_path: str,
        camera_index: int = 0,
        resolution: tuple[int, int] | None = None,
        bitdepth: int = 12,
        pitch_um: tuple[float, float] | None = None,
        function_map: dict[str, str] | None = None,
        name: str = "Nikon DS-Fi3",
        verbose: bool = True,
        image_buffer_num: int = DEF_DRIVER_BUFFER_NUM,
        **kwargs: Any,
    ):
        dll_path = os.fspath(dll_path)
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"DLL not found: {dll_path}")

        if NikonDSFi3Camera.sdk is None or getattr(NikonDSFi3Camera.sdk, "_dll_path", None) != os.path.abspath(dll_path):
            if verbose:
                print(f"Loading Nikon DLL from {dll_path}... ", end="")
            NikonDSFi3Camera.sdk = ct.WinDLL(dll_path)
            setattr(NikonDSFi3Camera.sdk, "_dll_path", os.path.abspath(dll_path))
            self._configure_sdk_prototypes(NikonDSFi3Camera.sdk)
            if verbose:
                print("success")

        self.dll = NikonDSFi3Camera.sdk
        self.camera_index = int(camera_index)
        self.verbose = bool(verbose)
        self.image_buffer_num = max(1, min(128, int(image_buffer_num)))
        self._cached_exposure_s = float(self._default_exposure_s)
        self._handle = ct.c_uint32(0)
        self._transfer_started = False
        self._frame_size = 0
        self._frame_interval = 0
        self._image_width = 0
        self._image_height = 0
        self._image_color = ecfcUnknown
        self._format_mode = 0
        self._raw_buffer = None
        self._function_map = dict(function_map or {})
        # Used by slmsuite Camera._get_image_hw_tolerant during super().__init__.
        self.capture_attempts = int(kwargs.get("capture_attempts", 5))

        self._open_devices()
        self._open_camera()

        try:
            self._set_feature_uint32(eExposureMode, ecemManual)
        except Exception as error:
            if verbose:
                print(f"Warning: could not set ExposureMode=Manual: {error}")

        try:
            self._set_exposure_hw(self._cached_exposure_s)
        except Exception as error:
            if verbose:
                print(f"Warning: could not apply default exposure: {error}")

        detected = self._detect_resolution_hw()
        if resolution is None:
            if detected is None:
                raise ValueError(
                    "resolution must be provided because the camera format could not be detected"
                )
            resolution = detected
        elif detected is not None and tuple(resolution) != tuple(detected):
            if verbose:
                print(
                    f"Warning: requested resolution {resolution} differs from "
                    f"SDK format {detected}; using SDK format."
                )
            resolution = detected

        self._image_width = int(resolution[0])
        self._image_height = int(resolution[1])
        self._ensure_frame_buffer()

        # RGB24/YUV from DS-Fi3 are 8-bit packed; mono/raw are 16-bit containers.
        if bitdepth == 12 and self._image_color in (ecfcRgb24, ecfcYuv444):
            bitdepth = 8

        super().__init__(
            resolution,
            bitdepth=bitdepth,
            pitch_um=pitch_um,
            name=name,
            **kwargs,
        )

    @staticmethod
    def _configure_sdk_prototypes(dll) -> None:
        dll.CAM_OpenDevices.argtypes = [ct.POINTER(ct.c_uint32), ct.POINTER(ct.POINTER(CAM_Device))]
        dll.CAM_OpenDevices.restype = ct.c_int32

        dll.CAM_CloseDevices.argtypes = []
        dll.CAM_CloseDevices.restype = ct.c_int32

        dll.CAM_Open.argtypes = [ct.c_uint32, ct.POINTER(ct.c_uint32), ct.c_uint32, ct.c_wchar_p]
        dll.CAM_Open.restype = ct.c_int32

        dll.CAM_Close.argtypes = [ct.c_uint32]
        dll.CAM_Close.restype = ct.c_int32

        dll.CAM_GetAllFeatures.argtypes = [ct.c_uint32, ct.POINTER(Vector_CAM_FeatureValue)]
        dll.CAM_GetAllFeatures.restype = ct.c_int32

        dll.CAM_GetFeatures.argtypes = [ct.c_uint32, ct.POINTER(Vector_CAM_FeatureValue)]
        dll.CAM_GetFeatures.restype = ct.c_int32

        dll.CAM_SetFeatures.argtypes = [ct.c_uint32, ct.POINTER(Vector_CAM_FeatureValue)]
        dll.CAM_SetFeatures.restype = ct.c_int32

        dll.CAM_GetImage.argtypes = [
            ct.c_uint32,
            ct.c_bool,
            ct.POINTER(CAM_Image),
            ct.POINTER(ct.c_uint32),
        ]
        dll.CAM_GetImage.restype = ct.c_int32

        dll.CAM_Command.argtypes = [ct.c_uint32, ct.c_wchar_p, ct.c_void_p]
        dll.CAM_Command.restype = ct.c_int32

    @staticmethod
    def info(verbose: bool = True):
        return []

    def close(self):
        try:
            self._stop_transfer_hw()
        except Exception:
            pass

        handle = int(self._handle.value) if self._handle is not None else 0
        if handle:
            try:
                result = self.dll.CAM_Close(handle)
                if self.verbose and result != LX_OK:
                    print(f"CAM_Close returned {_lx_name(result)}")
            except Exception as error:
                if self.verbose:
                    print(f"CAM_Close failed: {error}")
        self._handle = ct.c_uint32(0)
        self._raw_buffer = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def camera_handle(self) -> int:
        return int(self._handle.value)

    def get_frame_size_info(self) -> dict[str, int]:
        self._refresh_frame_size()
        return {
            "uiFrameSize": int(self._frame_size),
            "uiFrameInterval": int(self._frame_interval),
            "width": int(self._image_width),
            "height": int(self._image_height),
        }

    def is_transfer_started(self) -> bool | None:
        return self._is_transfer_started_hw()

    def _get_exposure_hw(self):
        try:
            usec = self._get_feature_uint32(eExposureTime)
            self._cached_exposure_s = float(usec) * 1e-6
            return self._cached_exposure_s
        except Exception:
            return float(self._cached_exposure_s)

    def _set_exposure_hw(self, exposure_s):
        exposure_s = float(exposure_s)
        usec = int(round(exposure_s * 1e6))
        usec = max(100, min(120_000_000, usec))
        if usec >= 1000:
            usec = (usec // 1000) * 1000
        self._set_feature_uint32(eExposureTime, usec)
        self._cached_exposure_s = usec * 1e-6

    def _get_image_hw(self, timeout_s=None):
        self._start_transfer_hw()
        self._ensure_frame_buffer()

        if timeout_s is None:
            timeout_s = max(1.0, self._cached_exposure_s * 3.0 + 1.0)
        else:
            # slmsuite adds exposure outside; still keep a small floor for first frame.
            timeout_s = max(0.2, float(timeout_s))

        deadline = time.time() + timeout_s
        last_result = LX_ERR_FAIL
        remained = ct.c_uint32(0)

        while time.time() <= deadline:
            image = CAM_Image()
            image.pDataBuffer = ct.cast(self._raw_buffer, ct.c_void_p)
            image.uiDataBufferSize = ct.c_uint32(self._frame_size)

            last_result = self.dll.CAM_GetImage(
                self._handle,
                True,
                ct.byref(image),
                ct.byref(remained),
            )
            # LX_ERR_ACCESSDENIED is returned while no frame is ready yet.
            if last_result == LX_OK and image.uiImageSize > 0:
                return self._buffer_to_array(image)

            time.sleep(0.02)

        raise RuntimeError(
            "CAM_GetImage did not return a frame before timeout. "
            f"last_result={_lx_name(last_result)}, frame_size={self._frame_size}, "
            f"transfer_started={self._is_transfer_started_hw()}"
        )

    def _open_devices(self) -> None:
        if NikonDSFi3Camera._devices_opened and NikonDSFi3Camera._device_count > 0:
            return

        count = ct.c_uint32(0)
        devices = ct.POINTER(CAM_Device)()
        result = self.dll.CAM_OpenDevices(ct.byref(count), ct.byref(devices))
        if result != LX_OK:
            raise RuntimeError(f"CAM_OpenDevices failed: {_lx_name(result)}")
        if count.value <= 0:
            raise RuntimeError("CAM_OpenDevices found no cameras (including simulators).")

        NikonDSFi3Camera._devices_opened = True
        NikonDSFi3Camera._device_count = int(count.value)
        NikonDSFi3Camera._device_array_ptr = devices

        if self.verbose:
            print(f"CAM_OpenDevices: {count.value} device(s)")
            for index in range(count.value):
                device = devices[index]
                print(
                    f"  [{index}] type={device.eCamDeviceType} "
                    f"name={device.wszCameraName!r} serial={device.uiSerialNo}"
                )

    def _open_camera(self) -> None:
        if self.camera_index < 0 or self.camera_index >= NikonDSFi3Camera._device_count:
            raise IndexError(
                f"camera_index={self.camera_index} out of range "
                f"(device_count={NikonDSFi3Camera._device_count})"
            )

        handle = ct.c_uint32(0)
        err_msg = ct.create_unicode_buffer(CAM_ERRMSG_MAX)
        result = self.dll.CAM_Open(
            ct.c_uint32(self.camera_index),
            ct.byref(handle),
            ct.c_uint32(CAM_ERRMSG_MAX),
            err_msg,
        )
        if result != LX_OK or handle.value == 0:
            raise RuntimeError(
                f"CAM_Open failed: {_lx_name(result)} message={err_msg.value!r}"
            )

        self._handle = handle
        if self.verbose:
            print(f"CAM_Open ok, handle={handle.value}")

    def _make_feature_vector(self, feature_id: int, var_type: int, set_value=None):
        values = (CAM_FeatureValue * 1)()
        values[0].uiFeatureId = ct.c_uint32(feature_id)
        values[0].stVariant.eVarType = var_type
        values[0].ucTransSize = 0
        if set_value is not None:
            if var_type == evrt_uint32:
                values[0].stVariant.u.ui32Value = ct.c_uint32(int(set_value))
            elif var_type == evrt_int32:
                values[0].stVariant.u.i32Value = ct.c_int32(int(set_value))
            else:
                raise NotImplementedError(f"Unsupported feature variant type {var_type}")

        vector = Vector_CAM_FeatureValue()
        vector.uiCountUsed = 1
        vector.uiCapacity = 1
        vector.uiPauseTransfer = 0
        vector.pstFeatureValue = ct.cast(values, ct.POINTER(CAM_FeatureValue))
        return vector, values

    def _get_feature_uint32(self, feature_id: int) -> int:
        vector, values = self._make_feature_vector(feature_id, evrt_uint32)
        result = self.dll.CAM_GetFeatures(self._handle, ct.byref(vector))
        if result != LX_OK:
            raise RuntimeError(f"CAM_GetFeatures({feature_id}) failed: {_lx_name(result)}")
        return int(values[0].stVariant.u.ui32Value)

    def _set_feature_uint32(self, feature_id: int, value: int) -> None:
        vector, _values = self._make_feature_vector(feature_id, evrt_uint32, set_value=value)
        result = self.dll.CAM_SetFeatures(self._handle, ct.byref(vector))
        if result != LX_OK:
            raise RuntimeError(
                f"CAM_SetFeatures(feature={feature_id}, value={value}) failed: {_lx_name(result)}"
            )

    def _get_format_hw(self):
        vector, values = self._make_feature_vector(eFormat, evrt_Format)
        result = self.dll.CAM_GetFeatures(self._handle, ct.byref(vector))
        if result != LX_OK:
            raise RuntimeError(f"CAM_GetFeatures(Format) failed: {_lx_name(result)}")
        fmt = values[0].stVariant.u.stFormat
        self._image_color = int(fmt.eColor)
        self._format_mode = int(fmt.eMode)
        return self._image_color, self._format_mode

    def _detect_resolution_hw(self):
        try:
            color, mode = self._get_format_hw()
            if self.verbose:
                print(f"Format: color={color} mode={mode}")
            size = _DSFI3_FORMAT_MODE_SIZE.get(mode)
            if size is not None:
                self._image_width, self._image_height = size
                return size
        except Exception as error:
            if self.verbose:
                print(f"Warning: Format feature unavailable: {error}")

        try:
            self._refresh_frame_size()
        except Exception:
            pass

        if self._frame_size > 0:
            # uiFrameSize is a driver buffer size; image payload is often slightly smaller.
            # Prefer exact RGB24 / mono16 matches against known DS-Fi3 sizes.
            candidates = [
                (2880, 2048),
                (1440, 1024),
                (2048, 1536),
                (1608, 1608),
                (2454, 1632),
                (4908, 3264),
            ]
            for width, height in candidates:
                rgb24 = width * height * 3
                mono16 = width * height * 2
                if abs(int(self._frame_size) - (rgb24 + CAM_IMG_INFO_SIZE)) <= 8192 or abs(
                    int(self._frame_size) - rgb24
                ) <= 8192:
                    self._image_width = width
                    self._image_height = height
                    if self._image_color == ecfcUnknown:
                        self._image_color = ecfcRgb24
                    return (width, height)
                if abs(int(self._frame_size) - (mono16 + CAM_IMG_INFO_SIZE)) <= 8192 or abs(
                    int(self._frame_size) - mono16
                ) <= 8192:
                    self._image_width = width
                    self._image_height = height
                    if self._image_color == ecfcUnknown:
                        self._image_color = ecfcMono16
                    return (width, height)
        return None

    def _command(self, command: str, data_ptr=None) -> int:
        return int(
            self.dll.CAM_Command(
                self._handle,
                command,
                ct.c_void_p(None) if data_ptr is None else data_ptr,
            )
        )

    def _refresh_frame_size(self) -> None:
        frame = CAM_CMD_GetFrameSize()
        result = self._command(CAM_CMD_GET_FRAMESIZE, ct.byref(frame))
        if result != LX_OK:
            raise RuntimeError(f"CAM_CMD_GET_FRAMESIZE failed: {_lx_name(result)}")
        self._frame_size = int(frame.uiFrameSize)
        self._frame_interval = int(frame.uiFrameInterval)
        if self.verbose:
            print(
                f"FrameSize={self._frame_size} Interval={self._frame_interval} "
                f"RShutterDelay={frame.uiRShutterDelay}"
            )

    def _ensure_frame_buffer(self) -> None:
        if self._frame_size <= 0:
            self._refresh_frame_size()
        if self._frame_size <= 0:
            self._frame_size = min(
                CAM_FEA_FRAME_SIZE_MAX,
                max(1, self._image_width * self._image_height * 2 + CAM_IMG_INFO_SIZE),
            )
        if self._raw_buffer is None or len(self._raw_buffer) < self._frame_size:
            self._raw_buffer = (ct.c_uint8 * self._frame_size)()

    def _start_transfer_hw(self) -> bool:
        started = self._is_transfer_started_hw()
        if started:
            self._transfer_started = True
            return True

        self._refresh_frame_size()
        self._ensure_frame_buffer()

        cmd = CAM_CMD_StartFrameTransfer()
        cmd.uiImageBufferNum = ct.c_uint32(self.image_buffer_num)
        result = self._command(CAM_CMD_START_FRAMETRANSFER, ct.byref(cmd))
        if result != LX_OK:
            raise RuntimeError(
                f"CAM_CMD_START_FRAMETRANSFER failed: {_lx_name(result)} "
                f"(requested buffers={self.image_buffer_num}, allocatable={cmd.uiImageBufferNum})"
            )
        self._transfer_started = True
        if self.verbose:
            print(f"Frame transfer started (buffers={cmd.uiImageBufferNum})")
        time.sleep(max(0.05, min(0.5, self._cached_exposure_s)))
        return True

    def _stop_transfer_hw(self) -> bool:
        if not self._handle or int(self._handle.value) == 0:
            self._transfer_started = False
            return False
        result = self._command(CAM_CMD_STOP_FRAMETRANSFER, None)
        self._transfer_started = False
        if result not in (LX_OK, LX_ERR_HANDLE):
            if self.verbose:
                print(f"CAM_CMD_STOP_FRAMETRANSFER returned {_lx_name(result)}")
            return False
        return result == LX_OK

    def _is_transfer_started_hw(self):
        if not self._handle or int(self._handle.value) == 0:
            return False
        status = CAM_CMD_IsTransferStarted()
        result = self._command(CAM_CMD_IS_TRANSFER_STARTED, ct.byref(status))
        if result != LX_OK:
            return None
        return bool(status.bStarted)

    def _buffer_to_array(self, image: CAM_Image) -> np.ndarray:
        image_size = int(image.uiImageSize)
        if image_size <= 0:
            raise RuntimeError("CAM_GetImage returned uiImageSize=0")
        if not image.pDataBuffer:
            raise RuntimeError("CAM_GetImage returned null pDataBuffer")

        # Full buffer includes image payload + CAM_ImageInfo footer.
        total_size = max(int(image.uiDataBufferSize), image_size + CAM_IMG_INFO_SIZE)
        buf = ct.cast(image.pDataBuffer, ct.POINTER(ct.c_uint8 * total_size)).contents
        raw = np.frombuffer(buf, dtype=np.uint8, count=total_size)

        width = self._image_width
        height = self._image_height
        color = self._image_color

        if total_size >= image_size + CAM_IMG_INFO_SIZE:
            info = CAM_ImageInfo.from_buffer_copy(bytes(raw[image_size : image_size + CAM_IMG_INFO_SIZE]))
            if info.usImageWidth > 0 and info.usImageHeight > 0:
                width = int(info.usImageWidth)
                height = int(info.usImageHeight)
                self._image_width = width
                self._image_height = height
            if info.ucImageColor:
                color = int(info.ucImageColor)
                self._image_color = color
            if self.verbose:
                print(
                    f"ImageInfo: {width}x{height} color={color} "
                    f"exposure_us={info.uiExposureTime} gain={info.usGain} "
                    f"frame_no={info.usFrameNo}"
                )

        pixels = width * height
        if pixels <= 0:
            raise RuntimeError("Invalid image dimensions from camera")

        payload = raw[:image_size]
        if color in (ecfcMono16, ecfcY16, ecfcRaw16, ecfcUnknown):
            if image_size >= pixels * 2:
                return np.frombuffer(payload[: pixels * 2].tobytes(), dtype=np.uint16).reshape(height, width).copy()
        if color == ecfcRgb24:
            if image_size >= pixels * 3:
                arr = np.frombuffer(payload[: pixels * 3].tobytes(), dtype=np.uint8).reshape(height, width, 3)
                return arr.mean(axis=2).astype(np.uint16)
        if color == ecfcRgb48:
            if image_size >= pixels * 6:
                arr = np.frombuffer(payload[: pixels * 6].tobytes(), dtype=np.uint16).reshape(height, width, 3)
                return arr.mean(axis=2).astype(np.uint16)

        if image_size == pixels * 2:
            return np.frombuffer(payload.tobytes(), dtype=np.uint16).reshape(height, width).copy()
        if image_size == pixels:
            return np.frombuffer(payload.tobytes(), dtype=np.uint8).reshape(height, width).astype(np.uint16)

        raise RuntimeError(
            f"Unsupported image packing: size={image_size}, shape=({height},{width}), color={color}"
        )
