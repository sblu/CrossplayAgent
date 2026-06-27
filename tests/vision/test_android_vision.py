"""Unit tests for the Android OCR tile-detection logic.

The full screenshot→letters path is validated live on the device; here we lock down
the colour discriminator that separates placed tiles from premium squares / empty
cells, since that's the part that's pure logic and easy to regress.
"""
import numpy as np

from crossplay.vision.android_vision import (
    _detect_rack_tiles, _has_tile, _ocr_letter, find_modal_close)


def _tile(rgb=(70, 95, 180)):
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    img[:, :] = rgb
    return img


def test_thin_bar_reads_as_I_not_L():
    # A uniform thin vertical bar must resolve to I — this was misread as L,
    # which corrupted move generation. Shape (aspect) decides, not tesseract.
    crop = _tile()
    crop[8:52, 27:33] = 255          # 6 wide x 44 tall → aspect ~0.14
    assert _ocr_letter(crop) == "I"


def test_foot_shape_reads_as_L():
    # Vertical stroke + bottom foot → L (wide aspect).
    crop = _tile()
    crop[8:52, 22:28] = 255          # vertical stroke
    crop[46:52, 22:44] = 255         # bottom foot
    assert _ocr_letter(crop) == "L"


def test_blank_tile_reads_as_question():
    # A blank rack tile has no letter, only a small mark — its biggest blob is
    # short (<40% of tile height), so it must read '?' not a misread letter.
    crop = _tile()
    crop[8:22, 26:34] = 255          # small mark, height 14 of 60 (~0.23)
    assert _ocr_letter(crop) == "?"


def test_wide_top_not_forced_to_I():
    # A T (wide top bar + stem) must NOT be overridden to I — the thin-bar rule
    # only applies to genuinely narrow blobs. This is the I-misread-as-T guard's
    # inverse: don't over-correct.
    crop = _tile()
    crop[8:14, 14:46] = 255          # wide top bar
    crop[8:52, 27:33] = 255          # stem
    assert _ocr_letter(crop) != "I"


def test_modal_close_detected_on_dimmed_board():
    # A modal is up: board dimmed to dark grey, a centered pure-white card with a
    # dark X in its top-right. find_modal_close must return a tap target inside
    # that X region.
    img = np.full((2404, 1080, 3), 96, dtype=np.uint8)     # dimmed board
    img[1065:1411, 150:929] = 255                          # white modal card
    img[1085:1150, 880:930] = 40                           # dark close X glyph
    pt = find_modal_close(img)
    assert pt is not None
    x, y = pt
    assert 860 <= x <= 935 and 1065 <= y <= 1170


def test_no_modal_on_normal_board():
    # A normal board with cream cells (~245) and no white card must NOT be seen as
    # a modal — cream stays below the pure-white threshold.
    img = np.full((2404, 1080, 3), 245, dtype=np.uint8)    # cream board, no overlay
    assert find_modal_close(img) is None


def test_centered_partial_rack_detected_by_position():
    # The app centers a partial rack instead of left-aligning it. Detection must
    # find the tiles by their actual blue blobs (not fixed cells), or a half-cell
    # offset slices each tile into a thin sliver that OCRs as 'I'. Two royal-blue
    # tiles placed in the middle of a 7-cell band must yield exactly 2 detections
    # near their real centres.
    cells = [[78 + i * 132, 1997, 132, 119] for i in range(7)]
    img = np.full((2404, 1080, 3), 250, dtype=np.uint8)        # cream background
    centers = []
    for k in range(2):
        x = 400 + k * 140                                       # centred, off-grid
        img[2010:2105, x:x + 110] = [70, 95, 180]              # royal-blue tile
        centers.append(x + 55)
    letters, positions = _detect_rack_tiles(img, cells)
    assert len(positions) == 2
    xs = sorted(p[0] for p in positions)
    for got, want in zip(xs, centers):
        assert abs(got - want) <= 20


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
