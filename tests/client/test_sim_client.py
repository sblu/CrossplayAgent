import pytest

from crossplay.client.base import Observation
from crossplay.client.sim_client import SimClient
from crossplay.engine.dictionary import Dictionary
from crossplay.runner import run
from crossplay.strategy.greedy import GreedyAgent


@pytest.fixture
def tiny_dict(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("CAT\nAT\nCATS\nBAT\nTAB\nDOG\nGO\n")
    return Dictionary.load(str(f))


def test_observe_reports_our_seat(tiny_dict):
    client = SimClient(GreedyAgent(tiny_dict), our_seat=0, seed=1)
    obs = client.observe()
    assert isinstance(obs, Observation)
    assert len(obs.rack) == 7
    assert not obs.game_over


def test_same_loop_runs_against_simulator_to_completion(tiny_dict):
    # The exact backend-agnostic runner drives the simulator with no device.
    client = SimClient(GreedyAgent(tiny_dict), seed=3)
    run(client, GreedyAgent(tiny_dict), write_dashboard=False, verbose=False)

    assert client.state.is_over()
    final = client.state.final_scores()
    assert len(final) == 2
    assert all(isinstance(s, int) for s in final)


def test_seed_is_reproducible(tiny_dict):
    def play():
        c = SimClient(GreedyAgent(tiny_dict), seed=42)
        run(c, GreedyAgent(tiny_dict), write_dashboard=False, verbose=False)
        return c.state.final_scores()
    assert play() == play()
