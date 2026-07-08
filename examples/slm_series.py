"""Minimal EXULUS SLM example.

Generates a grayscale target image, computes the CGH phase pattern and
displays it on the SLM panel via :class:`laserlab.EXULUS`.

Run with the mock backend (cross-platform, no hardware required)::

    LASERLAB_MOCK=1 python examples/slm_series.py

On Windows with the Thorlabs USB connection attached, drop the
``LASERLAB_MOCK`` variable and adapt ``serial`` if needed.
"""

import os
from pathlib import Path

os.environ.setdefault("LASERLAB_MOCK", "1")  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import laserlab  # noqa: E402


def generate_target(path: Path, size: int = 256) -> Path:
    """Synthesise a grayscale image with a bright Gaussian spot."""
    x = np.linspace(-1, 1, size)
    y = np.linspace(-1, 1, size)
    xx, yy = np.meshgrid(x, y)
    img = (255 * np.exp(-(xx**2 + yy**2) / 0.05)).clip(0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)
    return path


def main() -> None:
    target = generate_target(Path("/tmp/slm_target.png"))

    with laserlab.EXULUS(serial="MOCK0001") as slm:
        slm.set_phase_stroke(1)    # 0 = full-wave, 1 = half-wave
        slm.set_hflip(False)       # horizontal mirror on the panel

        phase = slm.show_image(
            target,
            resize_mode=laserlab.EXULUS.RESIZE_FIT,
            background=0,
        )
        ack = slm.check_communication()
        print(f"comm ack: {ack} (6 = Ack)")
        print(f"phase: shape={phase.shape} dtype={phase.dtype}")
        print(f"showing: {target}")


if __name__ == "__main__":
    main()
