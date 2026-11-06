# laserlab

Python control utilities for the laser lab, including SLM, stage, shutter, laser, and camera hardware wrappers.

This document covers:

1. the **refactored Nikon DS-Fi3 camera wrapper** (`NikonDSFi3Camera`)
2. the **Thorlabs EXULUS SLM wrapper** (`EXULUS`)

Both are `ctypes` bindings to the vendor SDKs. The camera wrapper also integrates with the [`slmsuite`](https://github.com/slmsuite/slmsuite) `Camera` base class.

---

## Nikon DS-Fi3 Camera (`NikonDSFi3Camera`)

### Overview

`laserlab.camera.NikonDSFi3Camera` wraps the Nikon DSCam SDK (`DSCam.dll`) and exposes a `slmsuite`-compatible camera interface:

| Method | Purpose |
|---|---|
| `set_exposure(seconds)` | Set exposure time in **seconds** |
| `get_exposure()` | Read exposure time in **seconds** |
| `get_image(timeout_s=...)` | Capture one frame as a NumPy array |
| `close()` | Stop transfer and close the camera handle |

Internally, the wrapper follows the official DSCam acquisition flow from the SDK headers and the `KsCamExample` sample:

1. `CAM_OpenDevices`
2. `CAM_Open(device_index, handle, errmsg...)`
3. `CAM_SetFeatures` (ExposureMode = Manual, ExposureTime in **microseconds**)
4. `CAM_Command(CAM_CMD_GET_FRAMESIZE)`
5. `CAM_Command(CAM_CMD_START_FRAMETRANSFER, buffer_num)`
6. `CAM_GetImage(handle, newest=True, image, remained)`
7. `CAM_Command(CAM_CMD_STOP_FRAMETRANSFER)` / `CAM_Close`

### Requirements

- **OS**: Windows (the Nikon DSCam SDK is Windows-only)
- **Python**: 3.13+ (see `pyproject.toml`)
- **Packages**:
  - `slmsuite`
  - `numpy`
  - `matplotlib` (optional, for display)
- **Nikon DSCam SDK** installed, including `DSCam.dll`

Typical DLL path used in this lab:

```text
C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll
```

Official headers (useful for debugging / extending the wrapper):

```text
C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\include\
  DSCam.h
  DSCamFeature.h
  DSCamCommand.h
  DSCamImage.h
  DSCamEvent.h
```

### Install this package

From the repository root:

```bash
pip install -e .
```

Or with the project environment manager you already use for this repo.

Import path:

```python
from laserlab import NikonDSFi3Camera
# or
from laserlab.camera import NikonDSFi3Camera
```

---

## Quick start

```python
from laserlab.camera import NikonDSFi3Camera
import matplotlib.pyplot as plt

DLL_PATH = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"

# Open the first enumerated camera (usually the real DS-Fi3 at index 0)
camera = NikonDSFi3Camera(
    dll_path=DLL_PATH,
    camera_index=0,
    exposure_s=0.05,   # 50 ms, applied at open
    gain=100,          # optional analog gain
    verbose=True,
)

print("shape:", camera.shape)          # (height, width), e.g. (1024, 1440)
print("bitdepth:", camera.bitdepth)
print("exposure [s]:", camera.get_exposure())

# Set exposure (seconds) and capture one frame
camera.set_exposure(0.05)
frame = camera.get_image()

print(frame.shape, frame.dtype, frame.min(), frame.max(), frame.mean())

plt.imshow(frame, cmap="gray")
plt.title("Nikon DS-Fi3")
plt.axis("off")
plt.show()

camera.close()
```

With `verbose=True`, opening the camera typically prints something like:

```text
Loading Nikon DLL from ...\DSCam.dll... success
CAM_OpenDevices: 5 device(s)
  [0] type=5 name='DS-Fi3' serial=...
  [1] type=2 name='DS-Ri2(Sim)' serial=2
  ...
CAM_Open ok, handle=1
Format: color=1 mode=3
Frame transfer started (buffers=3)
ImageInfo: 1440x1024 color=1 exposure_us=50000 gain=100 frame_no=...
```

---

## Constructor reference

```python
NikonDSFi3Camera(
    dll_path: str,
    camera_index: int = 0,
    resolution: tuple[int, int] | None = None,
    bitdepth: int = 12,
    pitch_um: tuple[float, float] | None = None,
    name: str = "Nikon DS-Fi3",
    verbose: bool = True,
    image_buffer_num: int = 3,
    exposure_s: float | None = None,   # seconds; default 0.1
    exposure_mode: int | None = 2,     # Manual; None keeps camera default
    gain: int | None = None,
    trigger_mode: int | None = None,
    format_color: int | None = None,
    format_mode: int | None = None,
    **kwargs,  # forwarded to slmsuite.hardware.cameras.camera.Camera
)
```

### Parameters

| Parameter | Description |
|---|---|
| `dll_path` | Absolute path to `DSCam.dll`. Required. |
| `camera_index` | Index into the device list returned by `CAM_OpenDevices`. Real DS-Fi3 is usually `0`. Simulator devices may also appear. |
| `resolution` | Optional `(width, height)`. If omitted, the wrapper auto-detects from the camera `Format` feature (preferred) or frame-size heuristics. If a provided value disagrees with the SDK format, the **SDK format wins**. |
| `bitdepth` | Optical/sensor bit depth reported to `slmsuite`. For RGB24/YUV formats the wrapper may lower the default `12` to `8` because the packed stream is 8-bit. |
| `pitch_um` | Optional pixel pitch `(dx_um, dy_um)` for `slmsuite` calibrations. |
| `name` | Camera name used by `slmsuite`. |
| `verbose` | Print open/format/transfer/ImageInfo diagnostics. |
| `image_buffer_num` | Driver image buffer count for `CAM_CMD_START_FRAMETRANSFER` (SDK sample uses `3`; clamped to `1..128`). |
| `exposure_s` | Exposure time in **seconds**, applied immediately after `CAM_Open`. Default `0.1`. |
| `exposure_mode` | DSCam `eExposureMode`. Default `2` (Manual). Pass `None` to leave the camera mode unchanged. |
| `gain` | Optional analog gain (`eGain`). Omitted values are left at the camera default. |
| `trigger_mode` | Optional `eTriggerMode` (`0` Off, `1` Hard, `2` Soft). |
| `format_color` / `format_mode` | Optional image format (`eFormat`). If omitted, the current camera format is kept. |
| `**kwargs` | Extra `slmsuite.Camera` options such as `capture_attempts`, `averaging`, `hdr`, `rot`, `fliplr`, `flipud`, `exposure_bounds_s`. |

### What happens during `__init__`

1. Load `DSCam.dll` once (class-level shared SDK handle).
2. Call `CAM_OpenDevices` (shared across instances in-process).
3. Open the selected device with `CAM_Open`.
4. Apply constructor camera features **before the first capture**: format, trigger, exposure mode, exposure time, gain.
5. Detect image format / resolution.
6. Allocate a frame buffer large enough for `uiFrameSize`.
7. Call `slmsuite.Camera.__init__`, which may capture a probe frame to determine `dtype`.

---

## Device enumeration and camera index

On open, the SDK may list both the physical camera and built-in simulators, for example:

```text
[0] DS-Fi3              <- real camera
[1] DS-Ri2(Sim)
[2] DS-Qi2(Sim)
[3] DS-Fi3(Sim)
[4] Digital Sight 10(Sim)
```

Choose the correct index:

```python
camera = NikonDSFi3Camera(dll_path=DLL_PATH, camera_index=0)  # real DS-Fi3
# camera = NikonDSFi3Camera(dll_path=DLL_PATH, camera_index=3)  # DS-Fi3 simulator
```

If `camera_index` is out of range, an `IndexError` is raised.

---

## Exposure control

Exposure is exposed to the user in **seconds**, matching `slmsuite`.

```python
camera.set_exposure(0.01)     # 10 ms
print(camera.get_exposure())  # ~0.01
```

### Important SDK details

- The DSCam feature API stores exposure as **`eExposureTime` in microseconds**.
- The wrapper converts:
  - set: `seconds -> microseconds`
  - get: `microseconds -> seconds`
- Exposure mode defaults to **Manual** (`eExposureMode = 2`) on open; override with `exposure_mode=...` or pass `None` to keep the camera setting.
- Values are clamped roughly to `[100 us, 120 s]`.
- For exposures `>= 1 ms`, the value is quantized to whole milliseconds (SDK-friendly rounding).

Examples:

```python
camera.set_exposure(0.0005)   # 500 us
camera.set_exposure(0.033)    # ~33 ms
camera.set_exposure(1.0)      # 1 s
```

If the image is too bright/dark:

1. Adjust microscope illumination / shutter first.
2. Then tune `set_exposure(...)`.
3. Gain is currently readable from the SDK feature set but not yet wrapped as a public helper; default gain observed on DS-Fi3 is often `100`.

---

## Nikon Ti2 autofocus (`NikonTi2`)

`NikonTi2.autofocus_with_camera()` performs a software contrast autofocus scan. It moves the Z stage through explicit positions, captures one image at each position, evaluates the image with a built-in Laplacian-variance sharpness metric, and optionally moves to the position with the highest score.

The camera object must provide `get_image()`. The default usage is:

```python
result = microscope.autofocus_with_camera(
    camera,
    scan_half_range_um=50,       # scan current Z +/- 50 um
    scan_steps=40,               # capture 40 frames / positions
    stop_on_sharpness_drop=True, # stop after two consecutive decreases
    move_to_best=True,
)

print(result.best_z_um, result.best_score)
```

To use a different metric, pass `sharpness_function=your_function`. The function receives one image and returns a numeric score. The built-in metric is also available as `NikonTi2.calculate_sharpness(image)`.

Important parameters:

| Parameter | Description |
|---|---|
| `scan_half_range_um` | Half-width of the scan around the current Z position. The range is clipped to the configured hard limits. |
| `scan_steps` | Number of Z positions and, consequently, maximum number of captured frames. Must be at least 2. |
| `stop_on_sharpness_drop` | If enabled, stop after two consecutive strictly lower scores returned by the sharpness function. |
| `move_to_best` | Move to the best measured Z position after scanning. |

For a faster coarse-to-fine scan, use `quick_autofocus_with_camera()`. It runs a coarse scan followed by a fine scan centered on the coarse result and returns both `AutofocusCameraResult` objects:

```python
coarse, fine = microscope.quick_autofocus_with_camera(
    camera,
    coarse_half_range_um=100,
    coarse_steps=10,
    fine_half_range_um=20,
    fine_steps=20,
    stop_on_sharpness_drop=True,
)
print(fine.best_z_um, fine.best_score)
```

Each result contains `sharpness`, `z_positions_um`, `best_index`, `best_score`, and `best_z_um`. These software autofocus methods do not depend on Nikon TTL AF indices.

---

## Capturing images

### Basic capture

```python
frame = camera.get_image()
# frame: numpy.ndarray, typically shape (H, W), dtype uint16
```

### Capture with timeout

```python
# timeout_s is the wait budget used by slmsuite around the hardware call.
# The wrapper also keeps a small floor so the first frame after transfer start can arrive.
frame = camera.get_image(timeout_s=2.0)
```

### Recommended capture loop

```python
camera.set_exposure(0.05)

for i in range(5):
    frame = camera.get_image()
    print(i, frame.shape, int(frame.min()), int(frame.max()), float(frame.mean()))
```

### Display

```python
import matplotlib.pyplot as plt

frame = camera.get_image()
plt.figure(figsize=(8, 6))
plt.imshow(frame, cmap="gray")
plt.title("Nikon DS-Fi3 capture")
plt.axis("off")
plt.tight_layout()
plt.show()
```

### Return format notes

- On DS-Fi3, the live stream is commonly **RGB24** at **1440×1024** (`Format color=1, mode=3`).
- The wrapper converts RGB/YUV frames to a **single-channel grayscale** array for `slmsuite` by averaging color channels.
- Mono16 / Y16 / Raw16 streams are returned as `uint16` images when present.
- Frame metadata (`CAM_ImageInfo`) is parsed from the buffer footer and, when `verbose=True`, prints width/height/color/exposure/gain/frame number.

Observed DS-Fi3 defaults in this lab:

| Item | Typical value |
|---|---|
| Format color | `1` = RGB24 |
| Format mode | `3` = `ecfmH1440x1024` (1/2 average) |
| Resolution | `1440 × 1024` |
| `shape` in `slmsuite` | `(1024, 1440)` = `(height, width)` |
| Frame buffer size | ~`4428000` bytes |
| Image payload | `1440 * 1024 * 3` bytes |

---

## Diagnostic helpers

These helpers are useful while validating the SDK path:

```python
print(camera.camera_handle)          # non-zero handle after successful open
print(camera.get_frame_size_info())  # dict with uiFrameSize / interval / width / height
print(camera.is_transfer_started())  # True/False/None
```

Example:

```python
{
  "uiFrameSize": 4428000,
  "uiFrameInterval": 133,
  "width": 1440,
  "height": 1024,
}
```

---

## Lifecycle and cleanup

Always close the camera when finished:

```python
camera.close()
```

`close()` will:

1. Stop frame transfer (`CAM_CMD_STOP_FRAMETRANSFER`)
2. Close the camera handle (`CAM_Close`)
3. Release the local image buffer

A destructor also attempts `close()`, but explicit cleanup is preferred in notebooks and scripts.

### Notebook tip

If you re-run an open cell repeatedly, make sure the previous instance is closed first:

```python
try:
    camera.close()
except Exception:
    pass

camera = NikonDSFi3Camera(dll_path=DLL_PATH, camera_index=0)
```

---

## Integration with `slmsuite`

`NikonDSFi3Camera` subclasses `slmsuite.hardware.cameras.camera.Camera`, so standard `slmsuite` camera methods work:

```python
camera.get_exposure()
camera.set_exposure(0.02)
camera.get_image()
camera.flush()          # discard stale frames
# camera.autoexposure() # if desired, depending on scene / bounds
```

Notes about the base class:

- During `Camera.__init__`, `slmsuite` may call `_get_image_hw()` once to infer `dtype`.
- The wrapper accepts `timeout_s=None` for that path and retries while the SDK returns “no frame ready yet”.
- `capture_attempts` (default `5`) controls how many times `slmsuite` retries a failed hardware capture.

---

## Minimal end-to-end example

```python
from laserlab.camera import NikonDSFi3Camera
import matplotlib.pyplot as plt

DLL_PATH = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"

with_context = False  # wrapper currently uses explicit close(), not context manager

camera = NikonDSFi3Camera(
    dll_path=DLL_PATH,
    camera_index=0,
    verbose=True,
    image_buffer_num=3,
)

try:
    print("Opened:", camera.name)
    print("Handle:", camera.camera_handle)
    print("Shape:", camera.shape)
    print("Frame info:", camera.get_frame_size_info())

    camera.set_exposure(0.02)
    print("Exposure [s]:", camera.get_exposure())

    frame = camera.get_image(timeout_s=2.0)
    print(
        "Frame:",
        frame.shape,
        frame.dtype,
        "min=", int(frame.min()),
        "max=", int(frame.max()),
        "mean=", float(frame.mean()),
    )

    plt.imshow(frame, cmap="gray")
    plt.axis("off")
    plt.show()
finally:
    camera.close()
```

---

## Troubleshooting

### Black / all-zero frames

This was the main failure mode of the old wrapper. The refactored path should return non-zero data when the microscope is illuminated.

If frames are still dark:

1. Confirm the real camera index (not a simulator, unless intentional).
2. Increase exposure: `camera.set_exposure(0.1)` or higher.
3. Check microscope lamp / shutter / light path.
4. Inspect stats: `frame.min()`, `frame.max()`, `frame.mean()`.
5. Enable `verbose=True` and confirm `ImageInfo` prints a non-zero `exposure_us`.

### `CAM_Open failed` / handle errors

- Ensure no other application is exclusively holding the camera.
- Ensure `dll_path` points to a valid `DSCam.dll`.
- `LX_ERR_HANDLE (-7)` means an invalid camera handle; this usually indicates open/close order problems or a stale object.

### Timeout waiting for frames

`CAM_GetImage` may temporarily return `LX_ERR_ACCESSDENIED (-10)` while no frame is ready. The wrapper retries until timeout.

If timeouts persist:

- Increase `timeout_s` in `get_image(...)`.
- Verify transfer started: `camera.is_transfer_started()`.
- Confirm exposure is not extremely long relative to the timeout.
- Re-open the camera after closing other DSCam clients.

### Wrong resolution

Do **not** hardcode `2880×2048` unless the camera format mode is actually full resolution.

On the lab DS-Fi3, mode `3` is commonly active:

- `ecfmH1440x1024` → **1440×1024**

The wrapper auto-detects this from the Format feature. If you pass a conflicting `resolution=...`, the detected SDK format is used and a warning is printed.

### Re-import / reload issues in notebooks

After editing `laserlab.camera`, restart the kernel or reload carefully and recreate the camera object. Avoid leaving an old transfer session open.

---

## Implementation notes (for developers)

Source file: `src/laserlab/camera.py`

Key design choices:

- **Official SDK signatures only** — open/feature/command/image paths match `DSCam*.h` and `KsCamExample`.
- **Feature-based exposure** — there is no reliable exported `SetExposure` symbol; exposure is set through `CAM_SetFeatures(eExposureTime)`.
- **Shared device open state** — `CAM_OpenDevices` is cached at class level for the process.
- **Lazy transfer start** — frame transfer starts on the first capture and stays active until `close()`.
- **RGB → gray conversion** — keeps the `slmsuite` camera pipeline single-channel.
- **ImageInfo footer parsing** — uses the official `CAM_ImageInfo` layout appended after the image payload.

Relevant SDK error codes:

| Code | Name | Meaning in practice |
|---:|---|---|
| `0` | `LX_OK` | Success |
| `-7` | `LX_ERR_HANDLE` | Invalid camera handle |
| `-10` | `LX_ERR_ACCESSDENIED` | No frame ready yet; retry |

---

## Related files

| Path | Description |
|---|---|
| `src/laserlab/camera.py` | `NikonDSFi3Camera` implementation |
| `src/laserlab/__init__.py` | package exports |
| `slmsuite-test.ipynb` | interactive capture / display tests |
| `docs/DSCamAPI-E.html` | Nikon API manual (HTML layout; headers/sample are more authoritative) |

---

# Thorlabs EXULUS SLM (`EXULUS`)

## Overview

`laserlab.slm.EXULUS` is a high-level wrapper around the Thorlabs EXULUS Python/C SDK:

| SDK module | Role |
|---|---|
| `EXULUS_COMMAND_LIB` | serial device control (flip, phase-stroke mode, test pattern, …) |
| `Thorlabs_EXULUS_CGHCalculate` | image resize + computer-generated hologram (CGH) phase calculation |
| `Thorlabs_EXULUS_CGHDisplay` | fullscreen display window on the SLM monitor |

The wrapper exposes a single class with a practical lab workflow:

| Method | Purpose |
|---|---|
| `connect()` | open the serial connection to the EXULUS controller |
| `set_phase_stroke(mode)` / `get_phase_stroke()` | full-wave (`0`) or half-wave (`1`) mode |
| `set_hflip(on)` / `set_vflip(on)` | panel image orientation |
| `load_image(path)` | load a file, convert to grayscale, resize to the SLM panel |
| `compute_cgh(image)` | run the Thorlabs CGH pipeline |
| `open_display(monitor=...)` | create the fullscreen SLM window |
| `show_phase(phase)` | push a precomputed phase frame |
| `show_array(image)` | resize (if needed) → CGH → display |
| `show_image(path)` | end-to-end file → CGH → display |
| `close_display()` | close only the fullscreen window (blanks the SLM) |
| `close()` | close display + serial device |

Internally the display path follows the official Thorlabs sample:

1. `CghDisplayGetMonitorCount`
2. `CghDisplayCreateWindow(monitor, width, height, title)`
3. `CghDisplaySetWindowInfo(handle, width, height, channels)`
4. `CghDisplayShowWindow(handle, buffer)`
5. keep the window open while the pattern should remain visible
6. `CghDisplayCloseWindow(handle)` when finished

### Critical lifetime rule

The last frame remains visible **only while the display window handle is alive**.

- `CghDisplayShowWindow` does **not** permanently program the panel independently of the window.
- Calling `close_display()`, `close()`, leaving a `with EXULUS() as slm:` block, or exiting the process closes the window and **immediately blanks the SLM**.
- This is SDK behaviour, not a bug in the wrapper.

If you need a pattern to stay up, keep the Python process and the `EXULUS` object alive.

---

## Requirements

- **OS**: Windows for real hardware (Thorlabs ships `.dll` binaries only)
- **Python**: 3.13+ (see `pyproject.toml`)
- **Packages**:
  - `numpy`
  - `opencv-python`
- **Thorlabs EXULUS SDK files** vendored in this repo under:

```text
src/Thorlabs_EXULUS_PythonSDK/
  EXULUS_COMMAND_LIB.py
  Thorlabs_EXULUS_CGHCalculate.py
  Thorlabs_EXULUS_CGHDisplay.py
  exulus_command_library.dll
  cgh_lib.dll
  cgh_display.dll
  cgh_lib.h
  cgh_display.h
  ...
```

### Mock backend for development

On macOS / Linux, or whenever the DLLs are unavailable, force the in-memory mock backend:

```bash
# PowerShell
$env:LASERLAB_MOCK = "1"
python examples/slm_series.py

# bash
export LASERLAB_MOCK=1
python examples/slm_series.py
```

With `LASERLAB_MOCK=1`, no physical SLM is required. Device calls are recorded in memory and CGH is replaced by a simple buffer transform so unit tests and offline development still work.

---

## Install / import

From the repository root:

```bash
pip install -e .
```

Import path:

```python
from laserlab import EXULUS
# or
from laserlab.slm import EXULUS
```

---

## Quick start (recommended)

Prefer explicit `connect()` / `close()` when you want the pattern to remain visible after display:

```python
from laserlab import EXULUS

# Optical parameters should match your setup.
# Defaults in the class match the Thorlabs sample:
#   pixel_pitch_m = 6.4e-6
#   wavelength_m  = 1.55e-6
#   distance_m    = 0.25
#   stroke_m      = 5.162e-6
slm = EXULUS(
    wavelength_m=532e-9,   # e.g. 532 nm laser
    distance_m=2.0,        # focal / reconstruction distance [m]
)

slm.connect()
try:
    # Device configuration (serial path)
    slm.set_phase_stroke(0)   # 0 = full wave, 1 = half wave
    slm.set_hflip(False)
    slm.set_vflip(False)

    # End-to-end: load image -> compute CGH -> open display -> show frame
    # Pick the monitor index of the physical SLM panel (often 2).
    phase = slm.show_image(
        "assets/grad_01.png",
        monitor=2,
        resize_mode=EXULUS.RESIZE_FILL,
        background=0,
    )

    print("phase shape:", phase.shape, phase.dtype)
    print("ack:", slm.check_communication())  # 6 = Acknowledge

    # Keep the process alive; the pattern stays on the SLM until close().
    input("Pattern is on the SLM. Press Enter to close the window...")
finally:
    slm.close()  # blanks the SLM
```

### Why not always use `with`?

```python
with EXULUS(...) as slm:
    slm.show_image("target.png", monitor=2)
# <-- window is closed here, SLM goes black immediately
```

`with` is fine for short tests if you also pass `hold_seconds=...` or block inside the block. For continuous display, use explicit lifecycle control as in the recommended example.

---

## Constructor reference

```python
EXULUS(
    serial: str | None = None,
    *,
    baud: int = 38400,
    timeout: int = 3,
    width: int = 1920,
    height: int = 1080,
    pixel_pitch_m: float = 6.4e-6,
    wavelength_m: float = 1.55e-6,
    distance_m: float = 0.25,
    stroke_m: float = 5.162e-6,
)
```

### Parameters

| Parameter | Description |
|---|---|
| `serial` | EXULUS serial number. `None` auto-selects the first device from `list_devices()`. |
| `baud` | Serial baud rate (Thorlabs sample uses `38400`). |
| `timeout` | Serial open timeout in seconds. |
| `width` / `height` | SLM panel resolution in pixels. Default `1920×1080`. |
| `pixel_pitch_m` | Physical pixel pitch in meters (default `6.4 µm`). |
| `wavelength_m` | Laser wavelength in meters. |
| `distance_m` | Focus / reconstruction distance in meters for CGH. |
| `stroke_m` | Effective phase stroke in meters used by `CghCoreCalc`. |

These optical parameters are pushed to the CGH core through:

```text
cgh_core_update_all(hdl, w_pixel, h_pixel, pix_size_m, distance, wavelength)
```

Parameter order follows `cgh_lib.h`. Note that the official Thorlabs Python example appears to swap the last two floats; this wrapper uses the C header order.

---

## Device connection and configuration

### Connect

```python
slm = EXULUS()
handle = slm.connect()
print("serial:", slm.serial)
print("device handle:", slm.device_handle)
```

If no device is found (and mock mode is off), `connect()` raises `RuntimeError`.

### Communication check

```python
ack = slm.check_communication()
# 6   = Acknowledge
# 9   = Not Acknowledge
# 187 = SPI busy
```

### Orientation and phase-stroke mode

```python
slm.set_hflip(True)          # mirror horizontally
slm.set_vflip(False)
print(slm.get_hflip(), slm.get_vflip())

slm.set_phase_stroke(0)      # 0 full wave, 1 half wave
print(slm.get_phase_stroke())

slm.set_test_pattern(False)  # disable built-in test pattern
# slm.save_default_setting() # persist current settings to EEPROM
```

These calls require an open device handle (`connect()` first).

---

## Image loading and resize modes

`load_image()` reads a file with OpenCV, converts it to grayscale, and resizes it to `(height, width)` using the Thorlabs resize modes from `cgh_lib.h`:

| Constant | Value | Behaviour |
|---|---:|---|
| `EXULUS.RESIZE_CENTER` | `0` | place at native size, center, pad with `background` |
| `EXULUS.RESIZE_FIT` | `1` | fit inside panel, preserve aspect, pad with `background` |
| `EXULUS.RESIZE_FILL` | `2` | stretch to fill panel (default) |
| `EXULUS.RESIZE_STRETCH` | `3` | stretch mode (SDK enum) |

```python
gray = slm.load_image(
    "assets/grad_01.png",
    resize_mode=EXULUS.RESIZE_FIT,
    background=0,
)
print(gray.shape, gray.dtype)  # (1080, 1920) uint8
```

These enum values **must** match the SDK. Using the wrong integer silently selects a different resize strategy.

---

## CGH calculation

```python
import numpy as np

# gray must already be shape (slm.height, slm.width), dtype suitable for uint8 cast
phase = slm.compute_cgh(gray)
print(phase.shape, phase.dtype)  # (1080, 1920) uint8
```

Pipeline used by the wrapper:

1. `cgh_lib_init()` once per `EXULUS` instance
2. `cgh_core_create()`
3. `cgh_core_update_all(...)` with panel + optical parameters
4. `cgh_core_calc(hdl, buffer, stroke_m)` — in-place phase write
5. `cgh_core_close(hdl)`

`compute_cgh()` returns a new contiguous `uint8` array and does not modify the input image.

### Display order matters

To avoid a long black fullscreen flash:

1. load / prepare the image
2. **compute CGH first**
3. open the display window
4. show the phase

`show_image()` and `show_array()` already use this order. Avoid calling `open_display()` long before the phase is ready unless you intentionally want the black window up early.

---

## Displaying patterns

### Show a precomputed phase

```python
slm.open_display(monitor=2, title="EXULUS SLM", channels=1)
slm.show_phase(phase)
# pattern remains until close_display() / close()
```

`show_phase()` will auto-open the display on the first call if needed.

### Show from a NumPy array

```python
import numpy as np

img = np.zeros((1080, 1920), dtype=np.uint8)
img[200:400, 300:600] = 255

phase = slm.show_array(
    img,
    monitor=2,
    resize_mode=EXULUS.RESIZE_FILL,
    hold_seconds=0.0,  # optional sleep after show; does not replace close()
)
```

Accepts grayscale `H×W` or BGR `H×W×3` arrays. Color images are converted with OpenCV.

### Show from an image file

```python
phase = slm.show_image(
    "assets/grad_01.png",
    monitor=2,
    resize_mode=EXULUS.RESIZE_FILL,
    background=0,
    title="EXULUS SLM",
    hold_seconds=0.0,
)
```

`hold_seconds` only blocks the caller after the frame is pushed. It does **not** keep the window open after `close()`.

### Choosing the monitor index

The SDK creates a **fullscreen** window on a 1-based monitor index:

```python
# monitor=1 -> primary display
# monitor=2 -> secondary display (common for the SLM panel)
slm.show_image("target.png", monitor=2)
```

If you point `monitor` at the desktop instead of the SLM, that desktop goes black/fullscreen. Start with `1`, then try `2` if the SLM is the secondary output. This matches the Thorlabs display sample, which uses monitor `2`.

---

## Lifecycle and cleanup

### Explicit lifecycle (recommended for continuous display)

```python
slm = EXULUS(wavelength_m=532e-9, distance_m=2.0)
slm.connect()
try:
    slm.show_image("assets/grad_01.png", monitor=2)
    input("Press Enter to blank the SLM...")
finally:
    slm.close()
```

### Close only the window

```python
slm.close_display()  # blanks SLM, keeps serial device open
# ... later ...
slm.show_image("next.png", monitor=2)
slm.close()          # close display (if any) + device
```

### Context manager

```python
with EXULUS(wavelength_m=532e-9, distance_m=2.0) as slm:
    slm.set_phase_stroke(0)
    slm.show_image("assets/grad_01.png", monitor=2, hold_seconds=5.0)
# display + device closed here
```

Use `hold_seconds` or another blocking call inside the `with` block if you need to observe the pattern before cleanup.

### Process exit

Live instances are also registered for `atexit` cleanup so orphaned fullscreen windows are less likely if a script crashes. Prefer explicit `close()` anyway.

---

## Minimal end-to-end example

```python
from laserlab import EXULUS
import numpy as np

MONITOR = 2  # set to the SLM panel index on your PC

slm = EXULUS(
    wavelength_m=532e-9,
    distance_m=2.0,
    # stroke_m=5.162e-6,  # override if your calibration differs
)
slm.connect()

try:
    print("serial:", slm.serial)
    print("panel:", slm.width, "x", slm.height)
    print("ack:", slm.check_communication())

    slm.set_phase_stroke(0)
    slm.set_hflip(False)
    slm.set_vflip(False)

    # 1) file-based path
    phase = slm.show_image(
        "assets/grad_01.png",
        monitor=MONITOR,
        resize_mode=EXULUS.RESIZE_FILL,
    )
    print("file phase:", phase.shape, phase.dtype, int(phase.min()), int(phase.max()))

    # 2) array-based path (reuses the open display window)
    canvas = np.zeros((slm.height, slm.width), dtype=np.uint8)
    canvas[::40, :] = 255
    phase2 = slm.show_array(canvas, monitor=MONITOR)
    print("array phase:", phase2.shape, phase2.dtype)

    input("SLM is displaying the last pattern. Press Enter to close...")
finally:
    slm.close()
```

A ready-made script lives at:

```text
examples/slm_series.py
```

It cycles through `CENTER` / `FIT` / `FILL` / `STRETCH` and waits for Enter before closing the window.

---

## Architecture notes

### Real vs mock backend

| Backend | When selected | Behaviour |
|---|---|---|
| `_RealBackend` | default on Windows when DLLs load | calls Thorlabs SDK |
| `_MockBackend` | `LASERLAB_MOCK=1`, or forced in tests | in-memory fake device / display |

If the real SDK cannot be loaded and mock mode is not set, construction raises:

```text
RuntimeError: Thorlabs EXULUS SDK unavailable. Set LASERLAB_MOCK=1 ...
```

### Why black flashes used to happen

Two common mistakes in earlier usage:

1. **Open display before CGH**  
   Fullscreen window appears black while `compute_cgh()` runs.
2. **Close the window too early**  
   Leaving `with` / calling `close()` / ending the script blanks the SLM immediately after show.

The current wrapper:

- computes CGH before opening/showing when using `show_image` / `show_array`
- pins the last displayed frame in memory
- reuses an existing display handle on the same monitor
- documents that continuous display requires keeping the window open

A very brief black frame can still occur at the exact moment the SDK creates the first fullscreen window; that is inherent to `CghDisplayCreateWindow`.

### Return-code note

In `cgh_lib.h`, success is:

```c
enum result { SUCCESS = 1, ... };
```

Negative values are failures. The wrapper treats `rc < 0` as an error and does not require `rc == 0`.

---

## Troubleshooting

### Pattern appears then disappears

- You closed the display window (`close()`, `close_display()`, or exited `with`).
- Keep the process blocked (`input()`, GUI loop, long-running experiment code) until you intentionally blank the SLM.

### Desktop goes black instead of the SLM

- Wrong `monitor` index.
- Try `monitor=1`, then `monitor=2`.
- Confirm Windows identifies the EXULUS panel as an extended display.

### Long black screen before the pattern

- Avoid calling `open_display()` before CGH is ready.
- Prefer `show_image()` / `show_array()`, which compute first.
- First-time CGH init can take longer; subsequent frames reuse the initialized library state.

### `No EXULUS device found` / open failures

- Check USB/serial connection to the EXULUS controller.
- Confirm no other process holds the serial port.
- On non-Windows machines, set `LASERLAB_MOCK=1` for development.

### `Thorlabs EXULUS SDK unavailable`

- Ensure you are on Windows with the vendored DLLs present under `src/Thorlabs_EXULUS_PythonSDK/`.
- Or set `LASERLAB_MOCK=1`.

### Image geometry looks wrong

- Check `resize_mode` (`CENTER` / `FIT` / `FILL` / `STRETCH`).
- Verify `width` / `height` match the panel.
- Try `set_hflip` / `set_vflip` if the reconstruction is mirrored.

### Communication not acknowledged

```python
print(slm.check_communication())
```

- `6` is healthy.
- `9` / `187` suggest the controller is busy or not responding; power-cycle / reconnect and reopen.

---

## Related files

| Path | Description |
|---|---|
| `src/laserlab/slm.py` | `EXULUS` implementation (real + mock backends) |
| `src/Thorlabs_EXULUS_PythonSDK/` | vendored Thorlabs Python bindings + DLLs + headers |
| `examples/slm_series.py` | end-to-end display example with resize-mode sweep |
| `src/Thorlabs_EXULUS_PythonSDK/cgh_display.h` | display API (`create` / `show` / `close`) |
| `src/Thorlabs_EXULUS_PythonSDK/cgh_lib.h` | CGH API + resize modes + `SUCCESS=1` |

---

## Other hardware modules

This package also includes wrappers for:

- `ProScanStage` (`laserlab.stage`)
- `SC30Shutter` (`laserlab.shutter`)
- `LaserControl` (`laserlab.laser`)
- serial port helper `print_ports` (`laserlab.utils`)

Camera and SLM usage above are the documented paths for the refactored Nikon DS-Fi3 and Thorlabs EXULUS integrations.

---

## LaserScan for Windows

Releases are built by GitHub Actions ([build-windows.yml](.github/workflows/build-windows.yml)). Pushing a
tag such as `v0.1.0` (it must match `laserscan.__version__`) builds a one-folder PyInstaller bundle,
smoke-tests it (`LaserScan.exe --self-test` imports every lazily loaded module and loads the web UI in
QtWebEngine), and attaches `LaserScan-<version>-windows-x64.zip` to the GitHub Release. Run the workflow
manually to get the zip as a build artifact.

To build locally on Windows:

```powershell
uv sync --no-dev --extra scan --group build
uv run --no-sync pyinstaller packaging/laserscan.spec --noconfirm   # output: dist/LaserScan/
```

Unzip and run `LaserScan.exe`. The windowed build has no console; console output and startup errors go to
`%LOCALAPPDATA%\LaserScan\laserscan.log`. Size is kept down by excluding unused packages and Qt parts in
[packaging/laserscan.spec](packaging/laserscan.spec) (translations, all Chromium locales but en-US, DevTools,
software OpenGL) and by stripping docstrings from bytecode.
