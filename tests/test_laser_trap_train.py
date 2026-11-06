"""Offline checks for LaserTrapEnv + SAC/HER wiring."""

from __future__ import annotations

import numpy as np

from laserlab.train import make_env, make_model


def test_her_obs_and_reward() -> None:
    env = make_env(dummy=True)
    try:
        obs, info = env.reset()
        assert set(obs) == {"observation", "achieved_goal", "desired_goal"}
        assert obs["observation"].shape == (2,)
        r = env.unwrapped.compute_reward(obs["achieved_goal"], obs["desired_goal"], info)
        assert r.shape == (1,)
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        assert np.isscalar(reward) or np.asarray(reward).shape == ()
        assert "is_success" in info
        del terminated, truncated
    finally:
        env.close()


def test_sac_her_dummy_learn() -> None:
    env = make_env(dummy=True)
    try:
        model = make_model(env, learning_starts=8)
        model.learn(total_timesteps=16)
    finally:
        env.close()


if __name__ == "__main__":
    test_her_obs_and_reward()
    test_sac_her_dummy_learn()
    print("ok")
