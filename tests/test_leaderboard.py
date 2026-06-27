from crossplay.leaderboard import DEFAULT_RATING, Leaderboard
from crossplay.leaderboard_report import render_standings, write_html_report


def test_record_game_updates_tallies_and_elo():
    b = Leaderboard()
    b.record_game("greedy", "weak", 400, 200)   # greedy wins

    g, w = b.agents["greedy"], b.agents["weak"]
    assert g.games == w.games == 1
    assert g.wins == 1 and w.losses == 1
    assert g.score_for == 400 and g.score_against == 200
    assert g.rating > DEFAULT_RATING > w.rating   # winner up, loser down
    # Elo is zero-sum with equal start ratings.
    assert round((g.rating - DEFAULT_RATING) + (w.rating - DEFAULT_RATING), 6) == 0


def test_tie_keeps_equal_ratings():
    b = Leaderboard()
    b.record_game("a", "b", 300, 300)
    assert b.agents["a"].ties == 1 and b.agents["b"].ties == 1
    assert b.agents["a"].rating == b.agents["b"].rating == DEFAULT_RATING


def test_self_game_skips_elo_but_counts():
    b = Leaderboard()
    b.record_game("greedy", "greedy", 300, 200)
    assert b.agents["greedy"].games == 2          # both seats are the same agent
    assert b.agents["greedy"].rating == DEFAULT_RATING


def test_standings_sorted_by_rating():
    b = Leaderboard()
    for _ in range(5):
        b.record_game("strong", "weak", 400, 100)
    names = [name for name, _ in b.standings()]
    assert names == ["strong", "weak"]


def test_head_to_head_tracks_per_pair_and_is_symmetric():
    b = Leaderboard()
    b.record_game("greedy", "weak", 400, 200)   # greedy wins
    b.record_game("weak", "greedy", 350, 300)   # weak wins (sides swapped)
    b.record_game("greedy", "weak", 300, 300)   # tie

    g = b.matchup("greedy", "weak")
    assert g == {"games": 3, "wins": 1, "losses": 1, "ties": 1}
    # Same record, viewed from the other side: wins/losses flip.
    w = b.matchup("weak", "greedy")
    assert w == {"games": 3, "wins": 1, "losses": 1, "ties": 1}


def test_head_to_head_unknown_pair_is_empty():
    b = Leaderboard()
    b.record_game("greedy", "weak", 400, 200)
    assert b.matchup("greedy", "heuristic") == {"games": 0, "wins": 0, "losses": 0, "ties": 0}


def test_self_game_skips_head_to_head():
    b = Leaderboard()
    b.record_game("greedy", "greedy", 300, 200)
    assert b.matchup("greedy", "greedy")["games"] == 0


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "lb.json")
    b = Leaderboard()
    b.record_game("greedy", "weak", 400, 200)
    b.snapshot(run="r1")
    b.save(path)

    loaded = Leaderboard.load(path)
    assert loaded.agents["greedy"].wins == 1
    assert len(loaded.history) == 2               # one point per agent
    assert loaded.agents["greedy"].rating == b.agents["greedy"].rating
    # Head-to-head record survives the round trip.
    assert loaded.matchup("greedy", "weak") == {"games": 1, "wins": 1, "losses": 0, "ties": 0}


def test_html_report_is_self_contained(tmp_path):
    b = Leaderboard()
    b.record_game("greedy", "weak", 400, 200)
    b.snapshot(run="r1")
    out = str(tmp_path / "report.html")
    write_html_report(b, out)
    html = open(out).read()
    assert "Crossplay Leaderboard" in html
    assert "chart.js" in html.lower()
    assert "greedy" in html
    # standings table renders without error
    assert "Win%" in render_standings(b)
