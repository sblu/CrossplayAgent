"""Unit tests for the Android OCR tile-detection logic.

The full screenshot→letters path is validated live on the device; here we lock down
the colour discriminator that separates placed tiles from premium squares / empty
cells, since that's the part that's pure logic and easy to regress.
"""
import cv2
import numpy as np

from crossplay.vision import android_vision
from crossplay.vision.android_vision import (
    _bottom_bar_coverage, _bottom_right_tail, _detect_rack_tiles, _has_tile,
    _ocr_letter, _top_right_inked, find_modal_close)


def _tile(rgb=(70, 95, 180)):
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    img[:, :] = rgb
    return img


def _ef_glyph(crop, *, bottom_bar):
    """Draw a white E (bottom_bar=True) or F (False) onto a blue tile crop.

    E and F are identical apart from the bottom stroke — the exact ambiguity the
    discriminator resolves.
    """
    crop[8:52, 18:24] = 255          # left stem
    crop[8:14, 18:44] = 255          # top bar
    crop[27:33, 18:40] = 255         # middle bar
    if bottom_bar:
        crop[46:52, 18:44] = 255     # bottom bar (E only)
    return crop


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


def test_bottom_bar_coverage_separates_e_from_f():
    # The pure-geometry discriminator: an E's bottom band is inked across nearly
    # every column; an F's holds only the left stem.
    e = _ef_glyph(_tile(), bottom_bar=True)
    f = _ef_glyph(_tile(), bottom_bar=False)
    # Extract just the white letter mask (drop the blue background) for each.
    e_mask = np.all(e > 150, axis=2).astype(np.uint8)
    f_mask = np.all(f > 150, axis=2).astype(np.uint8)
    e_cov = _bottom_bar_coverage(e_mask[8:52, 18:44])
    f_cov = _bottom_bar_coverage(f_mask[8:52, 18:44])
    assert e_cov > 0.5 > f_cov


def test_e_glyph_misread_as_f_is_corrected(monkeypatch):
    # The reported bug: tesseract drops E's bottom stroke and returns 'F'. The
    # bottom-bar check must override that back to 'E' for a glyph that has the bar.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "F")
    assert _ocr_letter(_ef_glyph(_tile(), bottom_bar=True)) == "E"


def test_real_f_not_flipped_to_e(monkeypatch):
    # Inverse guard: a genuine F (no bottom bar) stays F even if tesseract says 'E',
    # so the discriminator doesn't over-correct.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "E")
    assert _ocr_letter(_ef_glyph(_tile(), bottom_bar=False)) == "F"


def _m_glyph(crop):
    """A white M on a blue tile: two full-height stems joined by a top bar (so both
    top corners are inked) plus the middle V — the shape tesseract reads as 'L'."""
    crop[8:52, 14:20] = 255          # left stem (full height)
    crop[8:52, 40:46] = 255          # right stem (full height)
    crop[8:14, 14:46] = 255          # top bar — fills both top corners
    crop[14:32, 26:34] = 255         # middle V down-stroke
    return crop


def _oq_glyph(crop, *, tail):
    """A white O ring (tail=False) or Q (ring + a bottom-right tail, tail=True)."""
    cv2.ellipse(crop, (30, 30), (15, 20), 0, 0, 360, (255, 255, 255), 6)
    if tail:
        cv2.line(crop, (33, 33), (47, 51), (255, 255, 255), 5)   # bottom-right tail
    return crop


def test_top_right_inked_separates_m_from_l():
    # Geometry: M fills the top-right corner; L leaves it empty.
    m = np.all(_m_glyph(_tile()) > 150, axis=2).astype(np.uint8)
    l = _tile()
    l[8:52, 22:28] = 255             # vertical stroke
    l[46:52, 22:44] = 255            # bottom foot
    l = np.all(l > 150, axis=2).astype(np.uint8)
    ys, xs = np.where(m); m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ys, xs = np.where(l); l = l[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    assert _top_right_inked(m) > 0.4 > _top_right_inked(l)


def test_m_glyph_misread_as_l_is_corrected(monkeypatch):
    # The reported bug: tesseract reads an M as 'L'. The top-right-corner check must
    # override that back to 'M'.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "L")
    assert _ocr_letter(_m_glyph(_tile())) == "M"


def test_real_l_not_flipped_to_m(monkeypatch):
    # Inverse guard: a genuine L (empty top-right) stays L even when tesseract says
    # 'L', so the M override doesn't over-correct.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "L")
    crop = _tile()
    crop[8:52, 22:28] = 255
    crop[46:52, 22:44] = 255
    assert _ocr_letter(crop) == "L"


def test_bottom_right_tail_separates_q_from_o():
    # Geometry: Q's tail inks the bottom-right corner; O stays symmetric.
    q = np.all(_oq_glyph(_tile(), tail=True) > 150, axis=2).astype(np.uint8)
    o = np.all(_oq_glyph(_tile(), tail=False) > 150, axis=2).astype(np.uint8)
    ys, xs = np.where(q); q = q[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ys, xs = np.where(o); o = o[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    assert _bottom_right_tail(q) > 0.06 > _bottom_right_tail(o)


def test_q_glyph_misread_as_o_is_corrected(monkeypatch):
    # The reported bug: tesseract drops Q's tail and returns 'O'. The tail check
    # must override that back to 'Q'.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "O")
    assert _ocr_letter(_oq_glyph(_tile(), tail=True)) == "Q"


def test_real_o_not_flipped_to_q(monkeypatch):
    # Inverse guard: a genuine O (symmetric ring) stays O even when tesseract says
    # 'O', so the Q override doesn't over-correct.
    monkeypatch.setattr(android_vision.pytesseract, "image_to_string",
                        lambda *a, **k: "O")
    assert _ocr_letter(_oq_glyph(_tile(), tail=False)) == "O"


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
