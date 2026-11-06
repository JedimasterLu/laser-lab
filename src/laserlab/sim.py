"""Simulated 1000x1000 laser-particle gym. Laser is fixed at the image center."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

IMG = 1000
UM_PER_PX = 50.0 / 229.0  # lab calibration
LASER_UM = 0.5  # kick if particle-laser distance is below this
CENTER = 0.5 * (IMG - 1)
FOV_UM = CENTER * UM_PER_PX


def _stamp(img: np.ndarray, x: float, y: float, amp: int = 255, sig: float = 2.0) -> None:
    r = int(3 * sig) + 1
    xi, yi = int(round(x)), int(round(y))
    y0, y1 = max(0, yi - r), min(IMG, yi + r + 1)
    x0, x1 = max(0, xi - r), min(IMG, xi + r + 1)
    if y0 >= y1 or x0 >= x1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    blob = amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sig * sig))
    img[y0:y1, x0:x1] = np.clip(img[y0:y1, x0:x1].astype(np.int16) + blob.astype(np.int16), 0, 255).astype(np.uint8)


_LASER = np.zeros((IMG, IMG), np.uint8)
_stamp(_LASER, CENTER, CENTER)


class SimLaserEnv(gym.Env):
    """One particle + one goal. Camera xy in um, origin at the fixed laser.

    The laser is optically fixed at the image center. Action is a microscope
    stage move (um): the sample (particle and goal) shifts in the camera FOV,
    so the whole image content moves while the laser spot stays put. If the
    laser path comes within LASER_UM of the particle during the stage move,
    the particle jumps a short random distance in a 45-deg outward cone.
    """

    metadata = {"render_modes": ["rgb_array"], "render_fps": 30}

    def __init__(
        self,
        max_episode_steps: int = 64,
        success_um: float = 0.5,
        jump_um: tuple[float, float] = (1.0, 2.0),
        action_um: float = 2.0,
        spawn_um: tuple[float, float] = (2.0, 10.0),
        approach_w: float = 1.0,
        progress_w: float = 2.0,
        success_w: float = 50.0,
        fail_w: float = 50.0,
        render_mode: str | None = None,
    ):
        super().__init__()
        self.max_episode_steps = int(max_episode_steps)
        self.success_um = float(success_um)
        self.jump_um = (float(jump_um[0]), float(jump_um[1]))
        self.spawn_um = (float(spawn_um[0]), float(spawn_um[1]))
        self.approach_w = float(approach_w)
        self.progress_w = float(progress_w)
        self.success_w = float(success_w)
        self.fail_w = float(fail_w)
        self.render_mode = render_mode
        xy = spaces.Box(-np.inf, np.inf, shape=(2,), dtype=np.float32)
        self.observation_space = spaces.Dict(
            {"observation": xy, "achieved_goal": xy, "desired_goal": xy}
        )
        self.action_space = spaces.Box(-action_um, action_um, shape=(2,), dtype=np.float32)
        self._action_low = np.full(2, -float(action_um), dtype=np.float32)
        self._action_high = np.full(2, float(action_um), dtype=np.float32)
        self._p = np.zeros(2, dtype=np.float32)
        self._g = np.zeros(2, dtype=np.float32)
        self._img = _LASER.copy()
        self._n = 0

    def _rand_xy(self, r0: float, r1: float) -> np.ndarray:
        ang = float(self.np_random.uniform(0.0, 2.0 * np.pi))
        r = float(self.np_random.uniform(r0, r1))
        return np.array([r * np.cos(ang), r * np.sin(ang)], dtype=np.float32)

    def _kick_from(self, p: np.ndarray) -> np.ndarray:
        d = float(np.linalg.norm(p))
        base = (
            float(np.arctan2(p[1], p[0]))
            if d > 1e-6
            else float(self.np_random.uniform(-np.pi, np.pi))
        )
        ang = base + float(self.np_random.uniform(-np.pi / 8.0, np.pi / 8.0))
        mag = float(self.np_random.uniform(*self.jump_um))
        return np.asarray(p, dtype=np.float32) + mag * np.array(
            [np.cos(ang), np.sin(ang)], dtype=np.float32
        )

    def _first_hit_t(self, p0: np.ndarray, a: np.ndarray) -> float | None:
        """First t in [0, 1] where |p0 + t a| <= LASER_UM, else None."""
        r2 = LASER_UM * LASER_UM
        if float(np.dot(p0, p0)) <= r2:
            return 0.0
        aa = float(np.dot(a, a))
        if aa < 1e-18:
            return None
        b = 2.0 * float(np.dot(p0, a))
        c = float(np.dot(p0, p0)) - r2
        disc = b * b - 4.0 * aa * c
        if disc < 0.0:
            return None
        root = float(np.sqrt(disc))
        hits = [t for t in ((-b - root) / (2.0 * aa), (-b + root) / (2.0 * aa)) if 0.0 <= t <= 1.0]
        return min(hits) if hits else None

    def _stage_and_drive(self, a: np.ndarray) -> bool:
        """Translate sample by a; kick if the laser path hits the particle."""
        p0 = np.asarray(self._p, dtype=np.float64)
        a64 = np.asarray(a, dtype=np.float64)
        self._g = self._g + a
        t_hit = self._first_hit_t(p0, a64)
        if t_hit is None:
            self._p = (p0 + a64).astype(np.float32)
            return False
        p_hit = p0 + t_hit * a64
        # Kick is relative to the laser at the instant of contact, then the
        # remaining stage translation is applied to the whole sample.
        self._p = self._kick_from(p_hit.astype(np.float32))
        rest = ((1.0 - t_hit) * a64).astype(np.float32)
        self._p = self._p + rest
        if float(np.linalg.norm(self._p)) < LASER_UM:
            self._p = self._kick_from(self._p)
        return True

    def _in_fov(self, xy: np.ndarray) -> bool:
        lim = FOV_UM - 4.0 * UM_PER_PX
        return bool(np.all(np.abs(xy) <= lim))

    def _obs_from_image(self) -> np.ndarray:
        img = _LASER.copy()
        _stamp(img, CENTER + self._p[0] / UM_PER_PX, CENTER + self._p[1] / UM_PER_PX, 220)
        self._img = img
        resid = img.astype(np.int16) - _LASER.astype(np.int16)
        bright = resid > 8
        if not np.any(bright):
            return np.zeros(2, dtype=np.float32)
        ys, xs = np.nonzero(bright)
        w = resid[bright].astype(np.float64)
        px = float(np.dot(xs, w) / w.sum())
        py = float(np.dot(ys, w) / w.sum())
        return np.array([(px - CENTER) * UM_PER_PX, (py - CENTER) * UM_PER_PX], dtype=np.float32)

    def _pack(self, p: np.ndarray) -> dict[str, np.ndarray]:
        p = np.asarray(p, dtype=np.float32)
        return {"observation": p, "achieved_goal": p, "desired_goal": self._g.copy()}

    def compute_reward(
        self,
        achieved_goal: np.ndarray,
        desired_goal: np.ndarray,
        info: dict[str, Any] | list[dict[str, Any]],
    ) -> np.ndarray:
        ag = np.atleast_2d(np.asarray(achieved_goal, dtype=np.float32))
        dg = np.atleast_2d(np.asarray(desired_goal, dtype=np.float32))
        n = ag.shape[0]
        d_goal = np.linalg.norm(ag - dg, axis=-1)
        to_goal = dg - ag
        gnorm = np.linalg.norm(to_goal, axis=-1, keepdims=True)
        hat = np.divide(to_goal, np.maximum(gnorm, 1e-6))
        # Strike point behind particle along -hat; laser approaches this position.
        strike_pt = ag - LASER_UM * hat
        d_strike = np.linalg.norm(strike_pt, axis=-1)
        r = -0.05 - 0.1 * self.approach_w * d_strike
        infos = [info] if isinstance(info, dict) else [x if isinstance(x, dict) else {} for x in info]
        delta = np.zeros_like(ag)
        for i, inf in enumerate(infos[:n]):
            dlt = inf.get("delta_p_um")
            if dlt is not None:
                delta[i] = np.asarray(dlt, dtype=np.float32).reshape(-1)[:2]
        v_toward = np.sum(delta * hat, axis=-1)
        r = r + self.progress_w * v_toward
        # Goal-independent FOV failure; keep in compute_reward so HER relabeling
        # cannot turn an out-of-view step into a virtual success.
        oob = np.zeros(n, dtype=np.float32)
        for i, inf in enumerate(infos[:n]):
            if inf.get("out_of_view"):
                oob[i] = 1.0
        succ = (d_goal < self.success_um).astype(np.float32) * (1.0 - oob)
        r = r + self.success_w * succ
        r = r - self.fail_w * oob
        return np.asarray(r, dtype=np.float32).reshape(-1)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)
        opt = options or {}
        self._p = np.asarray(opt["particle"], dtype=np.float32) if "particle" in opt else self._rand_xy(*self.spawn_um)
        self._g = np.asarray(opt["goal"], dtype=np.float32) if "goal" in opt else self._rand_xy(*self.spawn_um)
        self._n = 0
        p = self._obs_from_image()
        dist = float(np.linalg.norm(p - self._g))
        return self._pack(p), {"is_success": dist < self.success_um, "distance_um": dist}

    def step(self, action: np.ndarray) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        a = np.clip(np.asarray(action, dtype=np.float32).reshape(2), self._action_low, self._action_high)
        p0 = self._p.copy()
        kicked = self._stage_and_drive(a)
        # Sample-frame particle motion (stage translation cancelled); nonzero only on kick.
        delta_p = (self._p - p0 - a).astype(np.float32)
        p = self._obs_from_image() if self._in_fov(self._p) else self._p.copy()
        dist = float(np.linalg.norm(p - self._g))
        out = (not self._in_fov(self._p)) or (not self._in_fov(self._g))
        success = (not out) and dist < self.success_um
        info = {
            "is_success": success,
            "distance_um": dist,
            "laser_dist_um": float(np.linalg.norm(p)),
            "kicked": kicked,
            "delta_p_um": delta_p,
            "behind": bool(np.dot(p, self._g - p) >= 0.0),
            "out_of_view": out,
        }
        reward = float(self.compute_reward(p, self._g, info)[0])
        self._n += 1
        terminated = bool(success or out)
        truncated = (not terminated) and self._n >= self.max_episode_steps
        return self._pack(p), reward, terminated, truncated, info

    def render(self) -> np.ndarray | None:
        """Cropped RGB view: cyan=laser (fixed center), green=particle, red=goal."""
        import cv2

        rgb = np.stack([self._img, self._img, self._img], axis=-1)
        def um2px(xy: np.ndarray | tuple[float, float]) -> tuple[int, int]:
            return (int(round(CENTER + float(xy[0]) / UM_PER_PX)), int(round(CENTER + float(xy[1]) / UM_PER_PX)))

        lp, pp, gp = um2px((0.0, 0.0)), um2px(self._p), um2px(self._g)
        cv2.circle(rgb, lp, max(2, int(round(LASER_UM / UM_PER_PX))), (255, 255, 0), 1)
        cv2.circle(rgb, lp, 6, (0, 255, 255), 2)  # cyan: laser, always image center
        cv2.circle(rgb, pp, 8, (80, 255, 80), 2)  # green: particle
        cv2.drawMarker(rgb, gp, (255, 60, 60), cv2.MARKER_CROSS, 16, 2)  # red: goal on sample
        half, c = 256, int(CENTER)
        crop = rgb[c - half : c + half, c - half : c + half].copy()
        dist = float(np.linalg.norm(self._p - self._g))
        cv2.putText(
            crop,
            f"goal={dist:.2f}um laser={float(np.linalg.norm(self._p)):.2f}um step={self._n}",
            (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return crop
