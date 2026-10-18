"""Strict action parsing and observation invariants (spec §7)."""

import json

import pytest
from pydantic import ValidationError

from maze_lab.agent_contracts import (
    InvalidActionError,
    MovementReceipt,
    Notebook,
    TurnAction,
    parse_turn_action,
)
from maze_lab.config import RunConfig

VALID = {
    "schema_version": "1.0",
    "tick": 10,
    "move": "E",
    "notebook_edit": {"expected_revision": 0, "start": 0, "end": 0, "text": "My origin is the spawn."},
    "radio": "I am exploring east.",
}


def test_spec_example_action_parses():
    action = parse_turn_action(json.dumps(VALID))
    assert isinstance(action, TurnAction) and action.move == "E" and action.notebook_edit is not None


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":"1.0","tick":1,"tick":2,"move":"N","notebook_edit":null,"radio":null}',
        '{"schema_version":"1.0","tick":NaN,"move":"N","notebook_edit":null,"radio":null}',
        '{"schema_version":"1.0","tick":1,"move":"N","notebook_edit":null,"radio":null} trailing',
        '{"schema_version":"1.0","tick":1,"move":"N","notebook_edit":null,"radio":null,"extra":1}',
        '{"schema_version":"1.0","tick":1,"move":"N","notebook_edit":null,"radio":"\\ud800"}',
        '{"schema_version":"1.0","tick":"1","move":"N","notebook_edit":null,"radio":null}',
        '{"schema_version":"1.0","tick":1,"move":"n","notebook_edit":null,"radio":null}',
        '{"schema_version":"1.0","tick":1,"move":"N"}',
        "[1]",
        "",
    ],
    ids=[
        "duplicate-key",
        "nan",
        "trailing-prose",
        "extra-field",
        "lone-surrogate",
        "string-tick",
        "lowercase-move",
        "missing-fields",
        "not-object",
        "empty",
    ],
)
def test_malformed_actions_rejected(raw: str):
    with pytest.raises(InvalidActionError):
        parse_turn_action(raw)


def test_oversized_output_rejected():
    big = dict(VALID, radio="x" * (64 * 1024))
    with pytest.raises(InvalidActionError, match="64 KiB"):
        parse_turn_action(json.dumps(big))


def test_arrival_side_must_oppose_move():
    MovementReceipt(attempted="E", outcome="moved", arrived_from="W", cause=None)
    with pytest.raises(ValidationError):
        MovementReceipt(attempted="E", outcome="moved", arrived_from="E", cause=None)
    with pytest.raises(ValidationError):
        MovementReceipt(attempted="E", outcome="blocked", arrived_from="W", cause="wall")


def test_notebook_lengths_must_match_text():
    assert Notebook.of("A", 0, "héllo").utf8_bytes == 6
    with pytest.raises(ValidationError):
        Notebook(owner="A", revision=0, text="abc", utf8_bytes=2, codepoints=3)


def test_spec_run_creation_example_validates():
    example = {
        "schema_version": "1.0",
        "root_seed": 20261017,
        "condition": "baseline_random_default",
        "maze": {
            "width": 15,
            "height": 15,
            "generator": "dfs_v1",
            "extra_open_edges": 0,
            "exit_policy": "uniform_perimeter_cell",
            "spawn_policy": "uniform_distinct_non_exit",
            "landmark_count": 0,
            "checkpoint_count": 0,
        },
        "agents": [
            {
                "id": a,
                "kind": "baseline",
                "policy": "random_open_v1",
                "adapter": None,
                "provider": None,
                "model": None,
                "sampling": {},
                "max_output_tokens": 2048,
            }
            for a in "ABC"
        ],
        "rules": {
            "version": "rules_v1",
            "objective": "all_reach_exit",
            "allow_stay": True,
            "notebook_enabled": True,
            "notebook_cap_bytes": 8192,
            "notebook_insert_bytes": 1024,
            "radio_enabled": True,
            "radio_message_bytes": 280,
            "radio_cooldown_ticks": 5,
            "meeting_notebooks_enabled": True,
            "distance_sensors": "exit_and_peers",
            "distance_quantization": "tenths",
        },
        "timing": {"mode": "fixed_deadline", "decision_window_ms": 30000},
        "horizon_ticks": 500,
        "prompt_version": "maze_agent_v1",
        "max_provider_requests_per_turn": 1,
        "snapshot_interval_ticks": 25,
    }
    config = RunConfig.model_validate_json(json.dumps(example))
    dumped = config.model_dump(mode="json")
    for agent in dumped["agents"]:
        assert agent.pop("sampling") == {"temperature": None, "top_p": None, "seed": None}
    for agent in example["agents"]:
        agent.pop("sampling")
    assert (
        dumped["rules"].pop("notebook_ops") == "splice"
    )  # later rules variant, resolved to the spec's splice
    assert dumped == example  # every default resolved explicitly


@pytest.mark.parametrize(
    "change",
    [
        {"agents": "AB"},
        {"agents": "ACB"},
        {"rules": {"notebook_enabled": False}},
        {"rules": {"radio_enabled": False}},
        {"maze": {"width": 1}},
        {"root_seed": 2**64},
    ],
    ids=["two-agents", "wrong-order", "notebook-off-with-cap", "radio-off-with-budget", "tiny", "seed-range"],
)
def test_contradictory_configs_rejected(change: dict[str, object]):
    base: dict[str, object] = {"root_seed": 1, "condition": "x"}
    ids = change.pop("agents", "ABC")
    base["agents"] = [{"id": a, "kind": "baseline", "policy": "random_open_v1"} for a in str(ids)]
    base.update(change)
    with pytest.raises(ValidationError):
        RunConfig.model_validate_json(json.dumps(base))


def test_llm_agent_requires_model_and_no_policy():
    agents = [{"id": a, "kind": "baseline", "policy": "random_open_v1"} for a in "AB"]
    bad = {
        "id": "C",
        "kind": "llm",
        "policy": "random_open_v1",
        "adapter": "pydantic_ai",
        "provider": "anthropic",
    }
    with pytest.raises(ValidationError):
        RunConfig.model_validate_json(
            json.dumps({"root_seed": 1, "condition": "x", "agents": [*agents, bad]})
        )


def test_omitted_horizon_scales_with_maze_size():
    agents = [{"id": a, "kind": "baseline", "policy": "random_open_v1"} for a in "ABC"]
    base: dict[str, object] = {"root_seed": 1, "condition": "x", "agents": agents}
    assert RunConfig.model_validate(base).horizon_ticks == 500  # spec reference, 15x15
    assert RunConfig.model_validate({**base, "maze": {"width": 12, "height": 12}}).horizon_ticks == 320
    assert RunConfig.model_validate({**base, "maze": {"width": 7, "height": 7}}).horizon_ticks == 109
    assert RunConfig.model_validate({**base, "horizon_ticks": 80}).horizon_ticks == 80  # explicit wins
