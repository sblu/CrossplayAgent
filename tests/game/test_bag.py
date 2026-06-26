from crossplay.engine.board import TILE_DISTRIBUTION
from crossplay.game.bag import TileBag


def test_bag_has_full_distribution():
    bag = TileBag(seed=1)
    assert len(bag) == sum(TILE_DISTRIBUTION.values()) == 100


def test_blanks_represented_as_question_marks():
    drawn = TileBag(seed=1).draw(100)
    assert drawn.count('?') == TILE_DISTRIBUTION[' ']
    assert ' ' not in drawn


def test_same_seed_is_reproducible():
    assert TileBag(seed=7).draw(100) == TileBag(seed=7).draw(100)


def test_different_seeds_differ():
    assert TileBag(seed=1).draw(100) != TileBag(seed=2).draw(100)


def test_draw_decrements_and_empties():
    bag = TileBag(seed=3)
    bag.draw(7)
    assert bag.remaining() == 93
    rest = bag.draw(1000)          # over-draw returns only what's left
    assert len(rest) == 93
    assert bag.remaining() == 0
