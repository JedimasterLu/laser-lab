"""Hardware smoke test for NanoparticleStageEnv.

Runs two full env steps on the real camera and stage. The live frame has no
particles, so two random fake (x, y) coordinates are injected as detections.
Each step moves +500 encoder steps in +x.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from laserlab import NikonDSFi3Camera, NanoparticleStageEnv, ProScanStage

STAGE_PORT = "COM3"
CAMERA_DLL = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"
MOVE_STEPS = 500.0
N_LOOPS = 2
OUT_DIR = Path(__file__).resolve().parent / "gym_test_output"


def log(message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{now}] {message}", flush=True)


class FakeParticleDetector:
    """Always return the two injected particle coordinates."""

    def __init__(self, particles: np.ndarray):
        self.particles = np.asarray(particles, dtype=np.float32).reshape(2, 2)

    def detect(self, image: np.ndarray) -> np.ndarray:
        del image
        return self.particles.copy()


def save_frame(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(image)

    if arr.dtype != np.uint8:
        arr = arr.astype(np.float32)
        lo = float(arr.min())
        hi = float(arr.max())
        if hi > lo:
            arr = ((arr - lo) / (hi - lo) * 255.0).clip(0, 255).astype(np.uint8)
        else:
            arr = np.zeros_like(arr, dtype=np.uint8)

    ok = cv2.imwrite(str(path), arr)
    if not ok:
        raise RuntimeError(f"failed to write image: {path}")


def main() -> None:
    camera = None
    stage = None
    env = None
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        log(f"opening stage on {STAGE_PORT}")
        stage = ProScanStage(port=STAGE_PORT)
        log(f"stage position={stage.position}")

        log(f"opening camera dll={CAMERA_DLL}")
        camera = NikonDSFi3Camera(
            dll_path=CAMERA_DLL,
            camera_index=0,
            exposure_s=3e-3,
            verbose=True,
        )
        height, width = camera.shape
        log(f"camera shape=(H={height}, W={width}) exposure_s={camera.get_exposure()}")

        # Save initial frame to disk for reference.
        image_path = OUT_DIR / "loop_0.png"
        save_frame(image_path, camera.get_image())

        rng = np.random.default_rng()
        fake_particles = np.stack(
            [
                rng.uniform(0.0, float(width), size=2),
                rng.uniform(0.0, float(height), size=2),
            ],
            axis=1,
        ).astype(np.float32)
        log(f"injected fake particles (x, y)={fake_particles.tolist()}")

        env = NanoparticleStageEnv(
            camera=camera,
            stage=stage,
            detector=FakeParticleDetector(fake_particles),
            action_low=-MOVE_STEPS,
            action_high=MOVE_STEPS,
            max_episode_steps=N_LOOPS,
            wait_after_move=True,
        )
        action = np.array([MOVE_STEPS, 0.0], dtype=np.float32)
        log(f"action space={env.action_space} default action={action.tolist()}")

        log("reset()")
        obs, info = env.reset()
        log(
            f"reset done stage_xy={obs['stage_xy'].tolist()} "
            f"particles={np.asarray(obs['particles']).tolist()} "
            f"n_particles={info['n_particles']} image_shape={info['image'].shape}"
        )

        for i in range(1, N_LOOPS + 1):
            log(f"loop {i}/{N_LOOPS} step(action={action.tolist()})")
            obs, reward, terminated, truncated, info = env.step(action)
            image_path = OUT_DIR / f"loop_{i}.png"
            save_frame(image_path, info["image"])
            log(
                f"loop {i}/{N_LOOPS} done stage_xy={obs['stage_xy'].tolist()} "
                f"particles={np.asarray(obs['particles']).tolist()} "
                f"n_particles={info['n_particles']} reward={reward} "
                f"terminated={terminated} truncated={truncated} "
                f"saved={image_path}"
            )
        log("two loops finished")
    finally:
        if env is not None:
            env.close()
            log("env.close()")
        if camera is not None:
            camera.close()
            log("camera.close()")
        if stage is not None:
            stage.close()
            log("stage.close()")


if __name__ == "__main__":
    main()
