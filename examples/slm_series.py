"""Minimal EXULUS SLM example.

The Thorlabs SDK creates a fullscreen ``CghDisplayCreateWindow`` on the
selected monitor, so the SLM must be the chosen ``monitor`` index — if
it points at the main display, that screen will go black instead of the
SLM.  Run the script first with ``monitor=1``; if the SLM is the
secondary display use ``monitor=2`` (matches the SDK sample).

The previous version of this example disappeared within milliseconds
because ``show_image`` returned immediately and the context manager
then closed the display window.  Pass ``hold_seconds`` to keep the
pattern on the SLM while you verify it.
"""
import os
from PIL import Image
import laserlab  # noqa: E402


def main() -> None:
    cwd = os.getcwd()
    target = os.path.join(cwd, "assets/grad_01.png")

    # Pick the SLM monitor here.  ``monitor=1`` is the safest default;
    # bump to 2 if the SLM is your secondary display.
    monitor = 2
    # How long to keep the CGH pattern on the SLM before returning.
    hold_seconds = 3.0

    with laserlab.EXULUS(wavelength_m=532e-9, distance_m=2) as slm:
        slm.set_phase_stroke(0)
        slm.set_hflip(False)

        # ``monitor`` is forwarded to ``open_display``; the SLM will be
        # the only screen that turns black while the pattern is up.
        slm.open_display(monitor=monitor, title="EXULUS SLM")

        # Iterate the four resize modes so you can see CENTER/FIT/FILL/
        # STRETCH side by side.  Each frame is held for ``hold_seconds``
        # so the previous "image vanished" bug cannot recur.
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
            print(f"mode={name:<8} ack={ack} (6 = Ack) "
                  f"shape={phase.shape} dtype={phase.dtype}")


if __name__ == "__main__":
    main()
