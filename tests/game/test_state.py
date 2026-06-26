import pytest

from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.game.bag import TileBag
from crossplay.game.state import GameState


@pytest.fixture
def tiny_dict(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("CAT\nAT\nCATS\nBAT\nTAB\n")
    return Dictionary.load(str(f))


def make_state(racks, *, bag_seed=0, scores=None):
    bag = TileBag(seed=bag_seed)
    return GameState(
        board=Board(),
        bag=bag,
        racks=[list(r) for r in racks],
        scores=list(scores) if scores else [0] * len(racks),
    )


def test_apply_move_scores_consumes_refills_and_advances(tiny_dict):
    state = make_state([["C", "A", "T", "X", "Y", "Z", "Q"], ["E"] * 7])
    cat = next(m for m in generate_moves(state.board, state.rack(0), tiny_dict)
               if m["word"] == "CAT")

    score = state.apply_move(cat, 0)

    assert score == cat["score"] > 0
    assert state.scores[0] == score
    assert state.turn == 1                       # advanced to next seat
    assert len(state.rack(0)) == 7               # 3 played, 3 refilled
    assert state.board.get(7, 7) is not None     # opening move covers center


def test_apply_move_rejects_wrong_seat(tiny_dict):
    state = make_state([["C", "A", "T", "X", "Y", "Z", "Q"], ["E"] * 7])
    cat = next(m for m in generate_moves(state.board, state.rack(0), tiny_dict)
               if m["word"] == "CAT")
    with pytest.raises(ValueError):
        state.apply_move(cat, 1)                  # turn is seat 0


def test_apply_move_consumes_blank_and_scores_zero_for_it():
    state = make_state([["?", "A", "T", "X", "X", "X", "X"], ["E"] * 7])
    move = {"word": "CAT", "row": 7, "col": 7, "horizontal": True,
            "tiles_played": [0, 1, 2], "blanks": {0: "C"}}

    score = state.apply_move(move, 0)

    assert state.board.get(7, 7) == "C"          # blank stored as assigned letter
    assert (7, 7) in state.blank_cells
    assert state.rack(0).count("?") == 0         # blank consumed
    assert score == 3                            # blank C=0 + A=1 + T(DL at 7,9)=2


def test_going_out_ends_game_with_rack_adjustment():
    empty_bag = TileBag(seed=0)
    empty_bag.draw(100)
    state = GameState(board=Board(), bag=empty_bag,
                      racks=[["C", "A", "T"], ["E", "Q"]], scores=[10, 5])
    move = {"word": "CAT", "row": 7, "col": 7, "horizontal": True,
            "tiles_played": [0, 1, 2], "blanks": {}}

    state.apply_move(move, 0)

    assert state.rack(0) == []                   # played all, empty bag → no refill
    assert state.is_over()
    # seat0: 10 + CAT(C3+A1+T(DL)2 = 6) = 16, +opp rack (E1+Q10=11) → 27
    # seat1: 5 - own rack (11) → -6
    assert state.final_scores() == [27, -6]
    assert state.winner() == 0


def test_consecutive_passes_end_game():
    state = make_state([["A"], ["B"]])
    for _ in range(2 * state.n_players):
        state.pass_turn(state.turn)
    assert state.is_over()


def test_pass_rejects_wrong_seat():
    state = make_state([["A"], ["B"]])
    with pytest.raises(ValueError):
        state.pass_turn(1)                        # turn is seat 0
