"""Tests for the named-algorithm config layer (data/agents.json)."""
import json

import pytest

from crossplay.engine.dictionary import Dictionary
from crossplay.strategy.agent_config import (
    DEFAULT_AGENT_CONFIGS, build_configured_agent, load_agent_configs,
)
from crossplay.strategy.heuristic import HeuristicAgent


@pytest.fixture
def dictionary():
    return Dictionary.load("data/sample_words.txt")


def test_load_creates_file_with_defaults(tmp_path):
    path = tmp_path / "agents.json"
    cfgs = load_agent_configs(path)
    assert path.exists()
    assert set(cfgs) == set(DEFAULT_AGENT_CONFIGS)
    assert cfgs["heuristic"]["params"]["leave_weight"] == 1.0


def test_build_each_default_profile(dictionary, tmp_path):
    cfgs = load_agent_configs(tmp_path / "agents.json")
    for name in cfgs:
        agent = build_configured_agent(name, dictionary, cfgs)
        assert agent.choose_move is not None


def test_heuristic_params_flow_through(dictionary):
    # A custom profile's params must reach the constructor.
    cfgs = {"hot": {"type": "heuristic", "params": {"leave_weight": 0.25}}}
    agent = build_configured_agent("hot", dictionary, cfgs)
    assert isinstance(agent, HeuristicAgent)
    assert agent._leave_weight == 0.25


def test_unknown_profile_falls_back_to_registry_type(dictionary):
    # A bare type name not present as a profile still builds (back-compat).
    agent = build_configured_agent("greedy", dictionary, configs={})
    assert type(agent).__name__ == "GreedyAgent"


def test_unknown_name_raises(dictionary):
    with pytest.raises(ValueError):
        build_configured_agent("nope", dictionary, configs={})


def test_bad_type_in_profile_raises(dictionary):
    cfgs = {"x": {"type": "does-not-exist"}}
    with pytest.raises(ValueError):
        build_configured_agent("x", dictionary, cfgs)
