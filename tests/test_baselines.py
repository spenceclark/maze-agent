"""Baseline policies driven through the real reducer (spec §6.1, §14)."""

import asyncio

import pytest
from helpers import RULES

from maze_lab.agent_contracts import AGENT_IDS, AgentId, Move
from maze_lab.config import BaselinePolicyName, RulesConfig
from maze_lab.domain.generator import generate_maze
from maze_lab.domain.maze import MazeDefinition
from maze_lab.domain.reducer import Submission, resolve
from maze_lab.domain.rng import KeyedSampler
from maze_lab.domain.state import WorldState, initial_state
from maze_lab.observation import observe, public_rules
from maze_lab.policies.baselines import make_baseline

NO_NOTEBOOK = RulesConfig(notebook_enabled=False, notebook_cap_bytes=0, notebook_insert_bytes=0)
TINY_NOTEBOOK = RulesConfig(notebook_cap_bytes=4, notebook_insert_bytes=4)


def run(
    name: BaselinePolicyName, maze: MazeDefinition, horizon: int, rules: RulesConfig = RULES
) -> tuple[WorldState, list[dict[AgentId, Move]]]:
    """Play until the objective is met or the horizon; check every action is accepted."""
    policies = {a: make_baseline(name, KeyedSampler(f"test:{a}")) for a in AGENT_IDS}
    public = public_rules(rules)

    async def play() -> tuple[WorldState, list[dict[AgentId, Move]]]:
        state, moves = initial_state(maze), []
        while state.tick < horizon and state.objective_met_tick is None:
            subs: dict[AgentId, Submission] = {}
            for a in AGENT_IDS:
                obs = observe(maze, rules, state, a)
                attempt = await policies[a].decide(obs, public)
                again = await policies[a].decide(obs, public)
                assert attempt == again  # no hidden state
                assert attempt.action is not None and attempt.action.tick == obs.decision_tick
                assert attempt.action.radio is None
                subs[a] = Submission(action=attempt.action, failure=None)
            state = resolve(maze, rules, state, subs).state
            moves.append({a: m.action.move for a, m in subs.items() if m.action})
            for agent in state.agents:
                receipt = agent.last_receipt
                assert receipt.notebook.status != "rejected", receipt
                assert receipt.movement.outcome in ("moved", "stayed"), receipt
        return state, moves

    return asyncio.run(play())


@pytest.mark.parametrize("name", ["wall_follower_v1", "dfs_bounded_v1"])
@pytest.mark.parametrize(("seed", "size"), [(s, 8) for s in range(31)] + [(s, 15) for s in range(5)])
def test_memory_baselines_bring_everyone_to_the_exit(name: BaselinePolicyName, seed: int, size: int):
    # A spanning-tree walk visits every cell within 2 * cells moves.
    state, _ = run(name, generate_maze(seed, size, size), horizon=2 * size * size)
    assert state.objective_met_tick is not None


@pytest.mark.parametrize("name", ["random_open_v1", "wall_follower_v1", "dfs_bounded_v1"])
@pytest.mark.parametrize("rules", [RULES, NO_NOTEBOOK, TINY_NOTEBOOK])
@pytest.mark.parametrize("seed", range(5))
def test_actions_are_always_accepted(name: BaselinePolicyName, rules: RulesConfig, seed: int):
    run(name, generate_maze(seed, 6, 5, extra_open_edges=4), horizon=60, rules=rules)


def test_random_open_is_deterministic_per_key_and_memoryless():
    maze = generate_maze(11, 8, 8)
    first, moves = run("random_open_v1", maze, horizon=80)
    second, again = run("random_open_v1", maze, horizon=80)
    assert moves == again and first == second
    assert all(a.notebook.revision == 0 for a in first.agents)


def test_dfs_log_is_one_letter_per_successful_move():
    state, _ = run("dfs_bounded_v1", generate_maze(4, 8, 8), horizon=128)
    for agent in state.agents:
        # The final move is logged on the next tick, which a finished run never plays.
        assert len(agent.notebook.text) in (agent.successful_moves - 1, agent.successful_moves)
        assert set(agent.notebook.text) <= set("NESW")
