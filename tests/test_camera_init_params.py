"""Unit tests for NikonDSFi3Camera constructor camera settings."""

from __future__ import annotations

import inspect

from laserlab.camera import NikonDSFi3Camera, ecemManual, ectmOff


def test_exposure_s_to_usec_rounding_and_clamp() -> None:
    assert NikonDSFi3Camera._exposure_s_to_usec(0.05) == 50_000
    assert NikonDSFi3Camera._exposure_s_to_usec(0.1) == 100_000
    assert NikonDSFi3Camera._exposure_s_to_usec(0.00005) == 100  # min 100 us
    assert NikonDSFi3Camera._exposure_s_to_usec(0.0015) == 1000  # >=1 ms quantized


def test_constructor_accepts_camera_feature_kwargs() -> None:
    params = inspect.signature(NikonDSFi3Camera.__init__).parameters
    for name in (
        "exposure_s",
        "exposure_mode",
        "gain",
        "trigger_mode",
        "format_color",
        "format_mode",
    ):
        assert name in params, name


def test_apply_startup_features_order_and_optional_skip() -> None:
    calls: list[tuple] = []

    class FakeCamera:
        verbose = False

        def _set_format_hw(self, format_color, format_mode):
            calls.append(("format", format_color, format_mode))

        def _set_feature_uint32(self, feature_id, value):
            calls.append(("feature", int(feature_id), int(value)))

        def _set_exposure_hw(self, exposure_s):
            calls.append(("exposure", float(exposure_s)))

        def _set_gain_hw(self, gain):
            calls.append(("gain", int(gain)))

    fake = FakeCamera()
    NikonDSFi3Camera._apply_startup_features(
        fake,
        exposure_s=0.02,
        exposure_mode=ecemManual,
        gain=100,
        trigger_mode=ectmOff,
        format_color=1,
        format_mode=3,
    )
    assert calls[0] == ("format", 1, 3)
    assert ("exposure", 0.02) in calls
    assert ("gain", 100) in calls

    calls.clear()
    NikonDSFi3Camera._apply_startup_features(
        fake,
        exposure_s=0.1,
        exposure_mode=None,
        gain=None,
        trigger_mode=None,
        format_color=None,
        format_mode=None,
    )
    assert calls == [("exposure", 0.1)]


def test_context_manager_protocol() -> None:
    closed = []

    class DummyCam:
        def close(self):
            closed.append(True)

    dummy = DummyCam()
    entered = NikonDSFi3Camera.__enter__(dummy)  # type: ignore
    assert entered is dummy
    NikonDSFi3Camera.__exit__(dummy, None, None, None)  # type: ignore
    assert closed == [True]


if __name__ == "__main__":
    test_exposure_s_to_usec_rounding_and_clamp()
    test_constructor_accepts_camera_feature_kwargs()
    test_apply_startup_features_order_and_optional_skip()
    test_context_manager_protocol()
    print("ok")
