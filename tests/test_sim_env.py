"""Offline checks for SimLaserEnv physics and SAC/HER wiring."""

from __future__ import annotations

import numpy as np

from laserlab.sim import CENTER, IMG, LASER_UM, SimLaserEnv
from laserlab.train import make_model, make_sim_env


def test_image_and_center_origin() -> None:
    env = SimLaserEnv()
    obs, _ = env.reset(seed=0, options={"particle": [8.0, -4.0], "goal": [10.0, 0.0]})
    assert env._img.shape == (IMG, IMG)
    assert env._img[int(CENTER), int(CENTER)] > 200
    p = obs["observation"]
    np.testing.assert_allclose(p, [8.0, -4.0], atol=0.15)
    np.testing.assert_allclose(obs["desired_goal"], [10.0, 0.0])


def test_stage_shifts_sample_not_laser() -> None:
    env = SimLaserEnv(max_episode_steps=2)
    env.reset(seed=0, options={"particle": [8.0, -4.0], "goal": [10.0, 0.0]})
    obs, *_ = env.step(np.array([1.0, 0.5], dtype=np.float32))
    np.testing.assert_allclose(obs["observation"], [9.0, -3.5], atol=0.15)
    np.testing.assert_allclose(obs["desired_goal"], [11.0, 0.5], atol=0.15)
    assert env._img[int(CENTER), int(CENTER)] > 200


def test_laser_kick_away() -> None:
    env = SimLaserEnv(max_episode_steps=2, jump_um=(1.0, 1.2))
    env.reset(seed=1, options={"particle": [0.15, 0.0], "goal": [10.0, 0.0]})
    obs, _, _, _, info = env.step(np.zeros(2, dtype=np.float32))
    p = obs["observation"]
    assert info["kicked"]
    assert float(np.linalg.norm(p)) > LASER_UM
    assert p[0] > 0.8
    assert abs(float(np.arctan2(p[1], p[0]))) < np.deg2rad(30.0)


def test_laser_kick_along_stage_path() -> None:
    env = SimLaserEnv(max_episode_steps=2, jump_um=(1.0, 1.2))
    env.reset(seed=2, options={"particle": [1.2, 0.0], "goal": [10.0, 0.0]})
    obs, _, _, _, info = env.step(np.array([-2.0, 0.0], dtype=np.float32))
    assert info["kicked"]
    p = obs["observation"]
    assert float(np.linalg.norm(p)) > LASER_UM
    assert abs(p[1]) < 1.0


def test_approach_reward() -> None:
    env = SimLaserEnv(approach_w=1.0, progress_w=0.0)
    env.reset(seed=0, options={"particle": [8.0, 0.0], "goal": [10.0, 0.0]})
    # Same |p| and |p-g|: backside (laser opposite goal) scores higher than front.
    r_back = float(env.compute_reward(np.array([3.0, 0.0]), np.array([5.0, 0.0]), {})[0])
    r_front = float(env.compute_reward(np.array([3.0, 0.0]), np.array([1.0, 0.0]), {})[0])
    assert r_back > r_front
    # On the backside, closer laser scores higher.
    r_far = float(env.compute_reward(np.array([8.0, 0.0]), np.array([10.0, 0.0]), {})[0])
    r_near = float(env.compute_reward(np.array([1.0, 0.0]), np.array([3.0, 0.0]), {})[0])
    assert r_near > r_far


def test_progress_velocity_penalty() -> None:
    env = SimLaserEnv(approach_w=0.0, progress_w=1.0)
    p = np.array([3.0, 0.0], dtype=np.float32)
    g = np.array([8.0, 0.0], dtype=np.float32)
    r_go = float(env.compute_reward(p, g, {"delta_p_um": [1.0, 0.0]})[0])
    r_stop = float(env.compute_reward(p, g, {"delta_p_um": [0.0, 0.0]})[0])
    r_away = float(env.compute_reward(p, g, {"delta_p_um": [-1.0, 0.0]})[0])
    assert r_go > r_stop > r_away


def test_step_delta_without_kick() -> None:
    env = SimLaserEnv(max_episode_steps=2)
    env.reset(seed=0, options={"particle": [8.0, 0.0], "goal": [10.0, 0.0]})
    _, _, _, _, info = env.step(np.array([1.0, 0.0], dtype=np.float32))
    assert not info["kicked"]
    np.testing.assert_allclose(info["delta_p_um"], [0.0, 0.0], atol=1e-5)
    assert info["behind"]


def test_out_of_view_terminates() -> None:
    env = SimLaserEnv(max_episode_steps=8, fail_w=50.0, progress_w=0.0, approach_w=0.0)
    env.reset(seed=0, options={"particle": [107.0, 0.0], "goal": [108.0, 0.0]})
    p = np.array([109.0, 0.0], dtype=np.float32)
    g = np.array([110.0, 0.0], dtype=np.float32)
    r_ok = float(env.compute_reward(p, g, {})[0])
    r_oob = float(env.compute_reward(p, g, {"out_of_view": True})[0])
    assert r_oob < r_ok - 40.0
    # HER relabel ag==dg must not erase the FOV failure.
    r_relabel = float(env.compute_reward(p, p, {"out_of_view": True})[0])
    assert r_relabel < -40.0
    obs, reward, terminated, truncated, info = env.step(np.array([2.0, 0.0], dtype=np.float32))
    assert info["out_of_view"]
    assert not info["is_success"]
    assert terminated and not truncated
    assert reward < r_ok - 40.0
    assert not env._in_fov(obs["observation"]) or not env._in_fov(obs["desired_goal"])


def test_render_overlay() -> None:
    env = SimLaserEnv(render_mode="rgb_array")
    env.reset(seed=0, options={"particle": [8.0, -4.0], "goal": [10.0, 0.0]})
    frame = env.render()
    assert frame is not None
    assert frame.shape == (512, 512, 3)
    assert frame.dtype == np.uint8


def test_sac_her_sim_learn() -> None:
    env = make_sim_env(max_episode_steps=4)
    try:
        model = make_model(env, learning_starts=8)
        model.learn(total_timesteps=16)
    finally:
        env.close()


def test_rollout_early_stop_saves_and_stops(tmp_path) -> None:
    from collections import deque
    from pathlib import Path

    from laserlab.train import RolloutEarlyStopCallback

    save = Path(tmp_path) / "best_model"
    cb = RolloutEarlyStopCallback(
        save,
        patience=2,
        min_cycles=2,
        check_every_episodes=4,
        min_delta=1.0,
        verbose=0,
    )

    class FakeModel:
        def __init__(self) -> None:
            self._episode_num = 0
            self.ep_info_buffer = deque(maxlen=100)

        def save(self, path: str) -> None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("ok")

    model = FakeModel()
    cb.model = model

    def cycle(n_ep: int, reward: float) -> bool:
        model._episode_num = n_ep
        model.ep_info_buffer.clear()
        model.ep_info_buffer.append({"r": reward})
        return cb._on_step()

    assert cycle(4, -100.0) is True
    assert save.exists()
    assert cycle(8, -80.0) is True
    assert cycle(12, -90.0) is True
    assert cycle(16, -110.0) is False
    assert cb.best_score == -80.0


def test_eval_writes_video(tmp_path) -> None:
    from pathlib import Path

    from laserlab.train import eval_model

    env = make_sim_env(max_episode_steps=3)
    try:
        model = make_model(env, learning_starts=8)
        out = Path(tmp_path) / "eval.mp4"
        eval_model(env, model, episodes=1, window=False, video=out, fps=10)
        assert out.exists() and out.stat().st_size > 0
    finally:
        env.close()


if __name__ == "__main__":
    from pathlib import Path
    from tempfile import TemporaryDirectory

    test_image_and_center_origin()
    test_stage_shifts_sample_not_laser()
    test_laser_kick_away()
    test_laser_kick_along_stage_path()
    test_approach_reward()
    test_progress_velocity_penalty()
    test_step_delta_without_kick()
    test_out_of_view_terminates()
    test_render_overlay()
    test_sac_her_sim_learn()
    with TemporaryDirectory() as d:
        test_rollout_early_stop_saves_and_stops(Path(d))
        test_eval_writes_video(Path(d))
    print("ok")
