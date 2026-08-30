"""Gymnasium environment for camera-guided nanoparticle stage control.

Each step moves the stage, captures a camera frame, and extracts particle
positions with a replaceable detector (trackpy by default). Reward / training
logic is intentionally left as a placeholder.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from numpy.typing import NDArray

ParticleXY = NDArray[np.float32]
DetectFn = Callable[[np.ndarray], np.ndarray]


@runtime_checkable
class ParticleDetector(Protocol):
    """Replaceable bright-spot detector.

    Implementations must return an ``(N, 2)`` array of ``(x, y)`` pixel
    coordinates. ``N`` may be zero.
    """

    def detect(self, image: np.ndarray) -> np.ndarray: ...


class TrackpyDetector:
    """Default detector: trackpy.locate on grayscale frames."""

    def __init__(self, diameter: int = 11, minmass: float = 100.0, **locate_kwargs: Any):
        if diameter % 2 == 0:
            raise ValueError("trackpy diameter must be an odd integer")
        self.diameter = int(diameter)
        self.minmass = float(minmass)
        self.locate_kwargs = locate_kwargs

    def detect(self, image: np.ndarray) -> ParticleXY:
        import trackpy as tp

        gray = _to_gray(image)
        features = tp.locate(
            gray,
            self.diameter,
            minmass=self.minmass,
            **self.locate_kwargs,
        )
        if features is None or len(features) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        return features[["x", "y"]].to_numpy(dtype=np.float32)


def _to_gray(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    return arr


def _as_xy(points: np.ndarray | None) -> ParticleXY:
    arr = np.asarray(points, dtype=np.float32) if points is not None else np.zeros((0, 2), dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float32)
    arr = np.atleast_2d(arr)
    return np.ascontiguousarray(arr[:, :2], dtype=np.float32)


def _as_detector(detector: ParticleDetector | DetectFn | None) -> ParticleDetector:
    if detector is None:
        return TrackpyDetector()
    if isinstance(detector, ParticleDetector):
        return detector
    if callable(detector):
        class _FnDetector:
            def detect(self, image: np.ndarray) -> np.ndarray:
                return detector(image)

        return _FnDetector()
    raise TypeError("detector must be None, a ParticleDetector, or a callable(image) -> (N, 2)")


class NanoparticleStageEnv(gym.Env):
    """Capture particles with the camera and move the stage.

    Action
        Continuous ``(dx, dy)`` relative stage move, same units as
        ``ProScanStage.position`` / ``move_by`` (encoder steps).

    Observation
        ``{"particles": (N, 2) pixel xy, "stage_xy": (2,) stage position}``.
        ``N`` is variable; empty detections are ``(0, 2)``.
    """

    metadata = {"render_modes": ["rgb_array"], "render_fps": 5}

    def __init__(
        self,
        camera: Any,
        stage: Any,
        detector: ParticleDetector | DetectFn | None = None,
        action_low: float | np.ndarray = -50.0,
        action_high: float | np.ndarray = 50.0,
        max_episode_steps: int = 100,
        wait_after_move: bool = True,
        render_mode: str | None = None,
    ):
        super().__init__()
        self.camera = camera
        self.stage = stage
        self.detector = _as_detector(detector)
        self.max_episode_steps = int(max_episode_steps)
        self.wait_after_move = bool(wait_after_move)
        self.render_mode = render_mode

        height, width = self._frame_hw()
        self.action_space = spaces.Box(
            low=action_low,
            high=action_high,
            shape=(2,),
            dtype=np.float32,
        )
        self._action_low = np.broadcast_to(
            np.asarray(action_low, dtype=np.float32), (2,)
        ).copy()
        self._action_high = np.broadcast_to(
            np.asarray(action_high, dtype=np.float32), (2,)
        ).copy()
        # Pixel bounds are slightly padded so sub-pixel detections stay in-space.
        particle_space = spaces.Box(
            low=np.array([-1.0, -1.0], dtype=np.float32),
            high=np.array([float(width + 1), float(height + 1)], dtype=np.float32),
            dtype=np.float32,
        )
        self.observation_space = spaces.Dict(
            {
                "particles": spaces.Sequence(particle_space, stack=True),
                "stage_xy": spaces.Box(-np.inf, np.inf, shape=(2,), dtype=np.float32),
            }
        )

        self._step_count = 0
        self._last_image: np.ndarray | None = None
        self._last_particles: ParticleXY = np.zeros((0, 2), dtype=np.float32)

    def _frame_hw(self) -> tuple[int, int]:
        shape = getattr(self.camera, "shape", None)
        if shape is not None and len(shape) >= 2:
            return int(shape[0]), int(shape[1])
        return 2048, 2880

    def _stage_xy(self) -> np.ndarray:
        x, y = self.stage.position
        return np.array([float(x), float(y)], dtype=np.float32)

    def _capture_obs(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        image = np.asarray(self.camera.get_image())
        particles = _as_xy(self.detector.detect(image))
        self._last_image = image
        self._last_particles = particles
        obs = {
            "particles": particles,
            "stage_xy": self._stage_xy(),
        }
        info = {
            "n_particles": int(particles.shape[0]),
            "image": image,
        }
        return obs, info

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)
        options = options or {}
        if "position" in options:
            x, y = options["position"]
            self.stage.move_to(float(x), float(y))
            if self.wait_after_move:
                self.stage.wait()
        self._step_count = 0
        return self._capture_obs()

    def step(self, action: np.ndarray) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        action = np.asarray(action, dtype=np.float32).reshape(2)
        action = np.clip(action, self._action_low, self._action_high)
        self.stage.move_by(float(action[0]), float(action[1]))
        if self.wait_after_move:
            self.stage.wait()

        self._step_count += 1
        obs, info = self._capture_obs()
        # Placeholder: replace with a task-specific reward later.
        reward = 0.0
        terminated = False
        truncated = self._step_count >= self.max_episode_steps
        return obs, reward, terminated, truncated, info

    def render(self) -> np.ndarray | None:
        if self.render_mode != "rgb_array" or self._last_image is None:
            return None
        gray = _to_gray(self._last_image)
        gray = np.asarray(gray, dtype=np.float32)
        peak = float(gray.max()) if gray.size else 1.0
        if peak <= 0:
            peak = 1.0
        rgb = np.clip(gray * (255.0 / peak), 0, 255).astype(np.uint8)
        return np.stack([rgb, rgb, rgb], axis=-1)

    def close(self) -> None:
        # Hardware lifetime is owned by the caller.
        return None
