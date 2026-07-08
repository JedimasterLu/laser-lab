"""Mock-backed unit tests for :mod:`laserlab.slm`.

Run with::

    LASERLAB_MOCK=1 pytest test/test_slm.py -q

or::

    LASERLAB_MOCK=1 python test/test_slm.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure the package under ``src/`` is importable and the mock backend
# is selected before the SLM module is loaded.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
os.environ.setdefault("LASERLAB_MOCK", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from laserlab.slm import EXULUS, _MockBackend  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """Create a small grayscale PNG with a diagonal gradient."""
    gradient = np.tile(np.linspace(0, 255, 80, dtype=np.uint8), (60, 1))
    path = tmp_path / "sample.png"
    assert cv2.imwrite(str(path), gradient)
    return path


@pytest.fixture
def slm() -> EXULUS:
    slm = EXULUS()
    slm.connect()
    return slm


# --------------------------------------------------------------------------- #
# Lifecycle / connection                                                      #
# --------------------------------------------------------------------------- #
def test_connect_then_close_releases_handle() -> None:
    slm = EXULUS()
    assert slm.device_handle is None
    hdl = slm.connect()
    assert isinstance(hdl, int) and hdl > 0
    assert slm.device_handle == hdl
    slm.close()
    assert slm.device_handle is None


def test_context_manager_connects_and_closes() -> None:
    with EXULUS() as slm:
        assert slm.device_handle is not None
    assert slm.device_handle is None


def test_connect_auto_picks_first_device_when_no_serial() -> None:
    with EXULUS() as slm:
        assert slm.serial == "MOCK0001"


def test_connect_respects_explicit_serial() -> None:
    with EXULUS(serial="ABC1234") as slm:
        assert slm.serial == "ABC1234"
        assert slm.backend.open_calls[-1][0] == "ABC1234"


# --------------------------------------------------------------------------- #
# Device configuration                                                        #
# --------------------------------------------------------------------------- #
def test_check_communication_returns_ack(slm: EXULUS) -> None:
    assert slm.check_communication() == 6  # ACK


def test_hflip_roundtrip(slm: EXULUS) -> None:
    slm.set_hflip(True)
    assert slm.get_hflip() == 1
    slm.set_hflip(False)
    assert slm.get_hflip() == 0


def test_vflip_roundtrip(slm: EXULUS) -> None:
    slm.set_vflip(True)
    assert slm.get_vflip() == 1
    slm.set_vflip(False)
    assert slm.get_vflip() == 0


def test_phase_stroke_full_and_half_wave(slm: EXULUS) -> None:
    slm.set_phase_stroke(1)
    assert slm.get_phase_stroke() == 1
    slm.set_phase_stroke(0)
    assert slm.get_phase_stroke() == 0


def test_test_pattern_toggle(slm: EXULUS) -> None:
    slm.set_test_pattern(True)
    assert slm.get_test_pattern() == 1
    slm.set_test_pattern(False)
    assert slm.get_test_pattern() == 0


def test_save_default_setting_runs_cleanly(slm: EXULUS) -> None:
    slm.save_default_setting()  # should not raise


def test_device_command_before_connect_raises() -> None:
    slm = EXULUS()
    with pytest.raises(RuntimeError, match="not connected"):
        slm.set_hflip(True)


# --------------------------------------------------------------------------- #
# Image loading                                                               #
# --------------------------------------------------------------------------- #
def test_load_image_returns_screen_sized_uint8(slm: EXULUS, sample_png: Path) -> None:
    gray = slm.load_image(sample_png)
    assert gray.shape == (slm.height, slm.width)
    assert gray.dtype == np.uint8


def test_load_image_missing_file_raises(slm: EXULUS, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        slm.load_image(tmp_path / "does-not-exist.png")


# --------------------------------------------------------------------------- #
# CGH calculation                                                             #
# --------------------------------------------------------------------------- #
def test_compute_cgh_shape_and_dtype(slm: EXULUS) -> None:
    img = np.full((slm.height, slm.width), 128, dtype=np.uint8)
    phase = slm.compute_cgh(img)
    assert phase.shape == (slm.height, slm.width)
    assert phase.dtype == np.uint8


def test_compute_cgh_wrong_shape_raises(slm: EXULUS) -> None:
    bad = np.zeros((10, 10), dtype=np.uint8)
    with pytest.raises(ValueError, match="shape"):
        slm.compute_cgh(bad)


def test_compute_cgh_wrong_ndim_raises(slm: EXULUS) -> None:
    bad = np.zeros((slm.height, slm.width, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="2D"):
        slm.compute_cgh(bad)


# --------------------------------------------------------------------------- #
# Display                                                                     #
# --------------------------------------------------------------------------- #
def test_open_display_validates_monitor(slm: EXULUS) -> None:
    with pytest.raises(ValueError, match="out of range"):
        slm.open_display(monitor=99)


def test_show_phase_wrong_shape_raises(slm: EXULUS) -> None:
    with pytest.raises(ValueError, match="uint8"):
        slm.show_phase(np.zeros((10, 10), dtype=np.uint8))


def test_show_phase_records_last_image(slm: EXULUS) -> None:
    slm.open_display(monitor=1, title="unit-test")
    phase = np.full((slm.height, slm.width), 200, dtype=np.uint8)
    slm.show_phase(phase)
    backend: _MockBackend = slm.backend  # type: ignore[assignment]
    assert backend.last_phase is not None
    assert backend.last_phase.shape == phase.shape
    np.testing.assert_array_equal(backend.last_phase, phase)


# --------------------------------------------------------------------------- #
# End-to-end                                                                  #
# --------------------------------------------------------------------------- #
def test_show_image_end_to_end(sample_png: Path) -> None:
    with EXULUS() as slm:
        phase = slm.show_image(sample_png, monitor=1, title="e2e")

    assert phase.shape == (slm.height, slm.width)
    assert phase.dtype == np.uint8
    # mock inverts the input, so we expect non-trivial content
    assert int(phase.max()) > 0


def test_show_array_with_bgr_image_runs(slm: EXULUS) -> None:
    bgr = np.zeros((slm.height, slm.width, 3), dtype=np.uint8)
    bgr[:, :, 0] = 64  # B channel only
    phase = slm.show_array(bgr)
    assert phase.shape == (slm.height, slm.width)


def test_backend_is_mock_under_test_env() -> None:
    assert isinstance(EXULUS().backend, _MockBackend)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))