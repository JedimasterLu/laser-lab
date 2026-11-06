"""Minimal EXULUS SLM example.

The Thorlabs SDK creates a fullscreen ``CghDisplayCreateWindow`` on the
selected monitor, so the SLM must be the chosen ``monitor`` index — if
it points at the main display, that screen will go black instead of the
SLM.  Run the script first with ``monitor=1``; if the SLM is the
secondary display use ``monitor=2`` (matches the SDK sample).

Important lifetime rules (from cgh_display.h / SDK example):

* The last frame stays visible only while the display window handle is
  open.  ``close()`` / leaving a ``with`` block blanks the SLM.
* Do **not** open the display before CGH calculation if you want to
  avoid a black flash — ``show_image`` now computes first, then opens.
* For a pattern that stays up until you dismiss it, keep the process
  alive (``input()``) and call ``close()`` yourself.
"""
import os
import laserlab  # noqa: E402


def main() -> None:
    cwd = os.getcwd()
    target = os.path.join(cwd, "assets/grad_01.png")

    # Pick the SLM monitor here.  ``monitor=1`` is the safest default;
    # bump to 2 if the SLM is your secondary display.
    monitor = 2
    # Optional per-frame pause while cycling resize modes.
    hold_seconds = 1.0

    # Do not use ``with`` if you want the final pattern to remain after
    # the loop — ``__exit__`` closes the fullscreen window and blanks
    # the SLM (SDK behaviour).
    slm = laserlab.EXULUS(wavelength_m=532e-9, distance_m=2)
    slm.connect()
    try:
        slm.set_phase_stroke(0)
        slm.set_hflip(False)

        # Iterate the four resize modes.  ``show_image`` computes CGH
        # first, then opens/reuses the fullscreen window, so the black
        # flash is limited to the brief window-create moment.
        for mode, name in [
            (laserlab.EXULUS.RESIZE_CENTER, "CENTER"),
            (laserlab.EXULUS.RESIZE_FIT, "FIT"),
            (laserlab.EXULUS.RESIZE_FILL, "FILL"),
            (laserlab.EXULUS.RESIZE_STRETCH, "STRETCH"),
        ]:
            phase = slm.show_image(
                target,
                resize_mode=mode,
                background=0,
                monitor=monitor,
                hold_seconds=hold_seconds,
            )
            ack = slm.check_communication()
            print(
                f"mode={name:<8} ack={ack} (6 = Ack) "
                f"shape={phase.shape} dtype={phase.dtype}"
            )

        # Keep the last frame on the SLM until the user dismisses it.
        input("Pattern is on the SLM. Press Enter to close the window...")
    finally:
        slm.close()


if __name__ == "__main__":
    main()
