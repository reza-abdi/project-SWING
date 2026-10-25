"""Single-step GridOptimizeEnv reproducibility and safety tests."""

import numpy as np
import pandapower as pp
import pytest

from modules.optimization_engine.rl_env import GridOptimizeEnv, calculate_reward


@pytest.mark.parametrize("grid_id", ["39", "118"])
def test_seeded_reset_is_repeatable_and_selects_a_valid_facility(grid_id) -> None:
    env = GridOptimizeEnv(grid_id)
    first, first_info = env.reset(seed=1729)
    second, second_info = env.reset(seed=1729)
    assert np.array_equal(first, second)
    assert first_info == second_info
    assert first.shape == (len(env.base_net.line) + len(env.base_net.bus) + 1,)
    assert env.target_bus in env.valid_target_buses
    facilities = env.net.load if env.action_type == "SHED_LOAD" else env.net.gen
    assert (facilities["bus"] == env.target_bus).any()


@pytest.mark.parametrize("action_type", ["SHED_LOAD", "REDISPATCH_GEN"])
@pytest.mark.parametrize("grid_id", ["39", "118"])
def test_one_step_action_is_bounded_and_terminates(grid_id, action_type) -> None:
    env = GridOptimizeEnv(grid_id, action_type=action_type)
    env.reset(seed=91)
    observation, reward, terminated, truncated, info = env.step(np.array([2.0], dtype=np.float32))
    assert observation.shape == env.observation_space.shape
    assert np.isfinite(reward)
    assert terminated and not truncated
    assert info["action_type"] == action_type
    assert info["mw_amount"] == 2.0
    assert env.action_space.contains(np.array([2.0], dtype=np.float32))


def test_solver_failure_gets_maximum_overload_penalty(monkeypatch) -> None:
    env = GridOptimizeEnv("39")
    env.reset(seed=4)

    def fail(*args, **kwargs):
        raise pp.LoadflowNotConverged("test failure")

    monkeypatch.setattr(pp, "runpp", fail)
    observation, reward, terminated, truncated, info = env.step([1.0])
    assert observation.shape == env.observation_space.shape
    assert terminated and not truncated
    assert info["converged"] is False
    assert info["max_loading_percent"] == 999.0
    assert reward < 0


@pytest.mark.parametrize("grid_id", ["39", "118"])
def test_reward_prefers_security_and_penalizes_large_overloads(grid_id) -> None:
    secure = calculate_reward(grid_id, 10.0, 100.0, True, 100.0)
    mild = calculate_reward(grid_id, 10.0, 100.0, True, 105.0)
    severe = calculate_reward(grid_id, 10.0, 100.0, False, 180.0)
    assert secure > mild > severe
