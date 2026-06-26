"""Unit tests for the Android OCR tile-detection logic.

The full screenshot→letters path is validated live on the device; here we lock down
the colour discriminator that separates placed tiles from premium squares / empty
cells, since that's the part that's pure logic and easy to regress.
"""
import numpy as np

from crossplay.vision.android_vision import _has_tile


def _fill(rgb):
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    img[:, :] = rgb
    return img


def test_royal_blue_tile_detected():
    assert _has_tile(_fill([70, 95, 180]))                   # saturated royal blue


def test_pale_2w_premium_square_rejected():
    assert not _has_tile(_fill([190, 205, 235]))             # high red → not a tile


def test_empty_cream_cell_rejected():
    assert not _has_tile(_fill([245, 245, 240]))


def test_blank_tile_detected_even_without_white_letter():
    # A blank is a royal-blue tile with no big white letter — still a tile.
    assert _has_tile(_fill([70, 95, 180]))


def test_tile_with_white_letter_detected():
    img = _fill([70, 95, 180])
    img[10:30, 14:26] = [255, 255, 255]   # white letter region
    assert _has_tile(img)
