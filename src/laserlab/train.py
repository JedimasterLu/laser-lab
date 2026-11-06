"""On-hardware SAC + HER training for LaserTrapEnv.

State is Trackpy (x, y) only — no raw images. Each episode is 60 s, then the
beam is forced off so the PCL film can cool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.her.her_replay_buffer import HerReplayBuffer

from laserlab import LaserTrapEnv, NikonDSFi3Camera, ProScanStage, SC30Shutter, SimLaserEnv, TrackpyDetector

STAGE_PORT = "COM3"
SHUTTER_PORT = "COM6"
CAMERA_DLL = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"
UM_PER_PIXEL = 1.0  # set from calibration
TOTAL_TIMESTEPS = 50_000
SAVE_PATH = Path("models/sac_her_laser")


class _FakeCamera:
    shape = (64, 64)

    def get_image(self) -> np.ndarray:
        return np.zeros(self.shape, dtype=np.uint8)

    def close(self) -> None:
        return None


class _FakeStage:
    steps_per_micron = 1.0

    def __init__(self) -> None:
        self.position = (0.0, 0.0)

    def move_by(self, dx: float, dy: float) -> None:
        x, y = self.position
        self.position = (x + float(dx), y + float(dy))

    def wait(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeDetector:
    """Fixed laser (0) and Au particle (1) in pixel xy."""

    def detect(self, image: np.ndarray) -> np.ndarray:
        del image
        return np.array([[32.0, 32.0], [36.0, 32.0]], dtype=np.float32)


def make_sim_env(**kwargs) -> Monitor:
    kwargs.setdefault("render_mode", "rgb_array")
    return Monitor(SimLaserEnv(**kwargs))


def make_env(*, dummy: bool = False, **kwargs) -> Monitor:
    if dummy:
        env = LaserTrapEnv(
            camera=_FakeCamera(),
            stage=_FakeStage(),
            detector=_FakeDetector(),
            um_per_pixel=1.0,
            episode_s=1e9,
            cooldown_s=0.0,
            max_episode_steps=4,
            wait_after_move=False,
            **kwargs,
        )
        return Monitor(env)

    camera = NikonDSFi3Camera(dll_path=CAMERA_DLL, camera_index=0, exposure_s=1 / 30)
    stage = ProScanStage(port=STAGE_PORT)
    shutter = SC30Shutter(port=SHUTTER_PORT)
    env = LaserTrapEnv(
        camera=camera,
        stage=stage,
        shutter=shutter,
        detector=TrackpyDetector(diameter=11, minmass=100.0),
        um_per_pixel=UM_PER_PIXEL,
        reset_radius_um=(3.0, 5.0),
        episode_s=60.0,
        cooldown_s=10.0,
        **kwargs,
    )
    return Monitor(env)


class RolloutEarlyStopCallback(BaseCallback):
    """Stop if mean episode reward worsens for `patience` log cycles; save best."""

    def __init__(
        self,
        save_path: Path,
        patience: int = 8,
        min_cycles: int = 5,
        check_every_episodes: int = 4,
        min_delta: float = 10.0,
        verbose: int = 1,
    ):
        super().__init__(verbose=verbose)
        self.save_path = Path(save_path)
        self.patience = int(patience)
        self.min_cycles = int(min_cycles)
        self.check_every_episodes = int(check_every_episodes)
        self.min_delta = float(min_delta)
        self._last_ep = 0
        self.n_cycles = 0
        self.n_worse = 0
        self._last_score: float | None = None
        self.best_score = -float("inf")
        self.saved_best = False

    def _score(self) -> float | None:
        buf = self.model.ep_info_buffer
        if buf is None or len(buf) == 0:
            return None
        return float(np.mean([float(ep["r"]) for ep in buf]))

    def _save_best(self, score: float) -> None:
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save(str(self.save_path))
        self.saved_best = True
        if self.verbose:
            print(f"saved best model ep_rew_mean={score:.1f} -> {self.save_path}")

    def _on_step(self) -> bool:
        n_ep = int(getattr(self.model, "_episode_num", 0))
        if n_ep < self._last_ep + self.check_every_episodes:
            return True
        self._last_ep = n_ep
        score = self._score()
        if score is None:
            return True
        self.n_cycles += 1
        if score > self.best_score + self.min_delta:
            self.best_score = score
            self.n_worse = 0
            self._save_best(score)
        elif self._last_score is not None and score < self._last_score - self.min_delta:
            self.n_worse += 1
            if self.verbose:
                print(f"rollout worse {self.n_worse}/{self.patience} ep_rew_mean={score:.1f}")
        else:
            self.n_worse = 0
        self._last_score = score
        if self.n_cycles >= self.min_cycles and self.n_worse >= self.patience:
            if self.verbose:
                print(f"early stop after {self.n_worse} worse cycles, best={self.best_score:.1f}")
            return False
        return True


def make_model(env: Monitor, *, learning_starts: int = 2000, use_her: bool = False) -> SAC:
    kwargs: dict[str, Any] = dict(learning_starts=learning_starts, verbose=1)
    if use_her:
        kwargs["replay_buffer_class"] = HerReplayBuffer
        kwargs["replay_buffer_kwargs"] = dict(
            n_sampled_goal=4,
            goal_selection_strategy="future",
            copy_info_dict=True,
        )
    return SAC("MultiInputPolicy", env, **kwargs)


def _close_hw(env: Monitor) -> None:
    raw = env.unwrapped
    env.close()
    for obj in (getattr(raw, "camera", None), getattr(raw, "stage", None), getattr(raw, "shutter", None)):
        if obj is not None and hasattr(obj, "close"):
            obj.close()


def _bgr(frame: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def eval_model(
    env: Monitor,
    model: SAC,
    *,
    episodes: int = 5,
    window: bool = False,
    video: Path | None = None,
    fps: int = 15,
) -> None:
    """Roll out a saved policy; optional OpenCV window and/or mp4."""
    import cv2

    writer = None
    wins = 0
    try:
        for ep in range(episodes):
            obs, info = env.reset()
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                del reward
                done = bool(terminated or truncated)
                frame = env.render()
                if frame is None:
                    continue
                bgr = _bgr(np.asarray(frame))
                if window:
                    cv2.imshow("laserlab-eval", bgr)
                    if cv2.waitKey(max(1, int(1000 / fps))) in (27, ord("q")):
                        return
                if video is not None:
                    if writer is None:
                        video.parent.mkdir(parents=True, exist_ok=True)
                        h, w = bgr.shape[:2]
                        fourcc = getattr(cv2, "VideoWriter_fourcc")(*"avc1")
                        writer = cv2.VideoWriter(str(video), fourcc, fps, (w, h))
                    writer.write(bgr)
            wins += int(bool(info.get("is_success")))
            print(f"episode {ep + 1}/{episodes} success={info.get('is_success')} dist={info.get('distance_um')}")
        print(f"success_rate={wins / max(episodes, 1):.2f}")
    finally:
        if writer is not None:
            writer.release()
            print(f"wrote {video}")
        if window:
            cv2.destroyAllWindows()


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dummy", action="store_true", help="train on fake hardware")
    p.add_argument("--sim", action="store_true", help="train on simulated 1000x1000 laser image")
    p.add_argument("--timesteps", type=int, default=TOTAL_TIMESTEPS)
    p.add_argument("--eval", action="store_true", help="roll out a saved model instead of training")
    p.add_argument("--window", action="store_true", help="show a live OpenCV window during --eval")
    p.add_argument("--video", nargs="?", const="videos/sim_eval.mp4", help="save eval rollout mp4")
    p.add_argument("--episodes", type=int, default=5)
    p.add_argument("--model", type=Path, default=SAVE_PATH)
    p.add_argument("--her", action="store_true", help="use HerReplayBuffer (default is standard SAC)")
    p.add_argument("--patience", type=int, default=8, help="stop after this many worse log cycles")
    p.add_argument("--min-cycles", type=int, default=5, help="log cycles before early-stop can fire")
    p.add_argument("--no-early-stop", action="store_true", help="train the full --timesteps")
    args = p.parse_args()

    if args.sim:
        env = make_sim_env()
        starts = 256
    else:
        env = make_env(dummy=args.dummy)
        starts = 8 if args.dummy else 2000
    try:
        if args.eval:
            zip_path = args.model if args.model.suffix else args.model.with_suffix(".zip")
            if not zip_path.exists():
                raise SystemExit(f"no model at {zip_path} — train first")
            model = SAC.load(str(args.model), env=env)
            video = Path(args.video) if args.video else None
            eval_model(
                env,
                model,
                episodes=args.episodes,
                window=args.window or video is None,
                video=video,
            )
            return
        model = make_model(env, learning_starts=starts, use_her=args.her)
        cb = None
        if not args.no_early_stop:
            cb = RolloutEarlyStopCallback(
                SAVE_PATH,
                patience=args.patience,
                min_cycles=args.min_cycles,
            )
        model.learn(total_timesteps=args.timesteps, callback=cb)
        SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if cb is None or not cb.saved_best:
            model.save(str(SAVE_PATH))
        else:
            model.save(str(SAVE_PATH) + "_last")
    finally:
        _close_hw(env)


if __name__ == "__main__":
    main()
