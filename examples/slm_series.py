"""Minimal EXULUS SLM example.
"""
import os
from PIL import Image
import laserlab  # noqa: E402


def main() -> None:
    cwd = os.getcwd()
    target = os.path.join(cwd, "assets/grad_01.png")

    with laserlab.EXULUS(wavelength_m=532e-9, distance_m=2) as slm:
        slm.set_phase_stroke(0)
        slm.set_hflip(False)

        phase = slm.show_image(
            target,
            resize_mode=laserlab.EXULUS.RESIZE_FILL,
            background=0,
            monitor=2
        )
        ack = slm.check_communication()
        print(f"comm ack: {ack} (6 = Ack)")
        print(f"phase: shape={phase.shape} dtype={phase.dtype}")
        print(f"showing: {target}")


if __name__ == "__main__":
    main()
