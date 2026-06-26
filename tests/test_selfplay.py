import pytest

from crossplay.engine.dictionary import Dictionary
from selfplay import build_agent, play_game


@pytest.fixture
def tiny_dict(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("CAT\nAT\nCATS\nBAT\nTAB\nDOG\nGO\n")
    return Dictionary.load(str(f))


def test_play_game_returns_summary_and_logs_decisions(tiny_dict):
    a = build_agent("greedy", tiny_dict)
    b = build_agent("greedy", tiny_dict)
    log = []
    summary = play_game([a, b], ("greedy", "greedy"), seed=1,
                        game_id=0, mirror=False, log=log)

    assert summary["type"] == "game"
    assert len(summary["final_scores"]) == 2
    assert summary["turns"] >= 1
    decisions = [r for r in log if r["type"] == "decision"]
    assert len(decisions) == summary["turns"]
    assert all("board" in d and "rack" in d and "move" in d for d in decisions)


def test_unknown_agent_raises(tiny_dict):
    with pytest.raises(ValueError):
        build_agent("nope", tiny_dict)
