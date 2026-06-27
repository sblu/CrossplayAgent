"""Tests for the controllable arena Spectator (start/stop + reconfigurable matchup).

These exercise the control surface directly without spinning up the background
thread, so they're deterministic.
"""
import pytest

from crossplay.engine.dictionary import Dictionary
from crossplay.strategy.heuristic import HeuristicAgent
from crossplay.web.spectator import Spectator


@pytest.fixture
def dictionary():
    return Dictionary.load("data/sample_words.txt")


def test_builds_agents_from_named_profiles(dictionary):
    spec = Spectator(("greedy", "weak"), dictionary)
    assert spec.names == ["greedy", "weak"]
    assert type(spec._agents[0]).__name__ == "GreedyAgent"
    assert type(spec._agents[1]).__name__ == "WeakAgent"


def test_autostart_controls_initial_running(dictionary):
    assert Spectator(("greedy", "weak"), dictionary, autostart=True).is_running()
    assert not Spectator(("greedy", "weak"), dictionary, autostart=False).is_running()


def test_set_running_toggles(dictionary):
    spec = Spectator(("greedy", "weak"), dictionary, autostart=False)
    spec.set_running(True)
    assert spec.is_running()
    spec.set_running(False)
    assert not spec.is_running()


def test_configure_queues_matchup_until_next_game(dictionary):
    spec = Spectator(("greedy", "weak"), dictionary, autostart=False)
    spec.configure("heuristic", "greedy", start=True)
    # Pending, not yet applied: still showing the old matchup.
    assert spec.status() == {"running": True, "names": ["greedy", "weak"],
                             "pending": ["heuristic", "greedy"]}
    # Applying the reconfigure (as the loop does at a game boundary) swaps agents.
    spec._maybe_reconfigure()
    assert spec.names == ["heuristic", "greedy"]
    assert isinstance(spec._agents[0], HeuristicAgent)
    assert spec.status()["pending"] is None


def test_idle_snapshot_reports_not_running(dictionary):
    spec = Spectator(("greedy", "weak"), dictionary, autostart=False)
    spec._publish_idle()
    snap = spec.snapshot()
    assert snap["running"] is False and snap["names"] == ["greedy", "weak"]
