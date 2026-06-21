import cv2
import numpy as np
import pytesseract
from pathlib import Path

_EMPTY_STD_THRESHOLD = 15.0
_SCALE = 3
_WHITELIST = "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SCORE_H_FRAC = 0.28
_SCORE_W_FRAC = 0.32

# ── Template matching ─────────────────────────────────────────────────────────
_TEMPLATE_DIR = Path("data/templates")
_BOARD_TEMPLATE_DIR = Path("data/board_templates")
_CANONICAL_SIZE = (48, 48)
_MATCH_THRESHOLD = 0.60        # NCC threshold for rack templates
_BOARD_MATCH_THRESHOLD = 0.65  # board templates are true binary so correct letter hits ~0.95+
_BOARD_MARGIN_MIN = 0.05       # correct letter vs second-best margin (E/F safety net)

_templates: dict[str, np.ndarray] | None = None
_board_templates: dict[str, np.ndarray] | None = None


def _load_templates_from(directory: Path) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    if not directory.exists():
        return out
    for path in directory.glob("*.png"):
        name = path.stem
        if name == "blank" or (len(name) == 1 and name.isupper()):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                out[name] = img
    return out


def _get_templates() -> dict[str, np.ndarray]:
    global _templates
    if _templates is None:
        _templates = _load_templates_from(_TEMPLATE_DIR)
    return _templates


def _get_board_templates() -> dict[str, np.ndarray]:
    global _board_templates
    if _board_templates is None:
        _board_templates = _load_templates_from(_BOARD_TEMPLATE_DIR)
    return _board_templates


def reload_board_templates() -> None:
    """Force reload of board templates from disk (call after saving new templates)."""
    global _board_templates
    _board_templates = None


_CORNER_SZ = 8  # triangle side: clear this many rows/cols from TL and BR corners

# Board tiles are white letters on dark navy background (~gray 130).
# A fixed threshold between navy and white is more consistent than Otsu,
# which can vary when cell sizes are small (~76px) or underlying premium
# square colors bleed into the edge pixels.
_BOARD_LETTER_THRESH = 170  # gray > 170 → white letter; gray < 170 → navy background


def _to_canonical(gray: np.ndarray) -> np.ndarray:
    """Convert rack tile gray image to 48×48 canonical binary (consistent with templates)."""
    h, w = gray.shape
    bg = int(np.median(gray))
    region = gray.copy()
    region[:int(h * _SCORE_H_FRAC), int(w * (1 - _SCORE_W_FRAC)):] = bg
    _, binary = cv2.threshold(region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    out = cv2.resize(binary, _CANONICAL_SIZE, interpolation=cv2.INTER_AREA)
    # Remove rounded-corner artifacts that are identical across all tile crops.
    # These shared dark pixels inflate NCC for wrong-letter pairs.
    for r in range(_CORNER_SZ):
        n = _CORNER_SZ - r
        out[r, :n] = 255             # top-left triangle
        out[47 - r, 48 - n:] = 255  # bottom-right triangle
    return out


def _to_canonical_board(gray: np.ndarray) -> np.ndarray:
    """Convert board tile gray image to 48×48 canonical binary.

    Resize to 48×48 FIRST (grayscale INTER_AREA), then apply fixed threshold.
    Resizing grayscale before thresholding makes the output truly binary (0/255)
    and stable regardless of input cell size — a 76px vs 77px input produces
    nearly identical canonicals, so NCC stays near 1.0 for the correct letter.
    """
    h, w = gray.shape
    region = gray.copy()
    # Mask score area to dark so bright score digits don't survive the threshold.
    region[:int(h * _SCORE_H_FRAC), int(w * (1 - _SCORE_W_FRAC)):] = 0
    # Resize grayscale first, then threshold — order matters for size-robustness.
    small = cv2.resize(region, _CANONICAL_SIZE, interpolation=cv2.INTER_AREA)
    # Fixed threshold: white letter (>170) → 0 (dark), navy background (<170) → 255 (white)
    _, out = cv2.threshold(small, _BOARD_LETTER_THRESH, 255, cv2.THRESH_BINARY_INV)
    for r in range(_CORNER_SZ):
        n = _CORNER_SZ - r
        out[r, :n] = 255
        out[47 - r, 48 - n:] = 255
    return out


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized cross-correlation; invariant to overall brightness offset and inversion."""
    af = a.flatten().astype(np.float64)
    bf = b.flatten().astype(np.float64)
    af -= af.mean()
    bf -= bf.mean()
    denom = np.linalg.norm(af) * np.linalg.norm(bf)
    return float(np.dot(af, bf) / denom) if denom > 1e-6 else 0.0


def _match_canonical(
    canonical: np.ndarray,
    templates: dict[str, np.ndarray],
    threshold: float = _MATCH_THRESHOLD,
    min_margin: float = 0.0,
) -> tuple[str, float] | tuple[None, float]:
    """NCC match a pre-computed canonical against a template dict.

    threshold  – minimum NCC to accept any match.
    min_margin – best score must exceed second-best by at least this much.
                 Use to reject ambiguous matches between similar letters (E vs F).
    """
    if not templates:
        return None, 0.0
    scores: list[tuple[float, str]] = []
    for letter, tmpl in templates.items():
        if letter == "blank":
            continue
        t = cv2.resize(tmpl, _CANONICAL_SIZE) if tmpl.shape[:2] != _CANONICAL_SIZE else tmpl
        scores.append((_ncc(canonical, t), letter))
    scores.sort(reverse=True)
    best_score, best_letter = scores[0]
    if best_score < threshold:
        return None, best_score
    if min_margin > 0 and len(scores) > 1:
        second_score = scores[1][0]
        if best_score - second_score < min_margin:
            return None, best_score  # too similar to second-best → ambiguous
    return best_letter, best_score


def _template_match(gray: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str, float] | tuple[None, float]:
    """Return (best_letter, score) or (None, score) if below threshold (rack path)."""
    return _match_canonical(_to_canonical(gray), templates)


# ── Public API ────────────────────────────────────────────────────────────────

def detect_letter(cell_img: np.ndarray, board: bool = False) -> str | None:
    """Return the letter on a tile cell, or None if the cell is empty.

    board=True uses board-scale templates (data/board_templates/) with a
    fixed-threshold canonical pipeline tuned for white-on-navy board tiles.
    board=False (default) uses rack templates (data/templates/) with the
    Otsu canonical pipeline.
    Falls through to geometric I-detection and OCR if no template matches.
    """
    gray = cv2.cvtColor(cell_img, cv2.COLOR_RGB2GRAY)
    if gray.std() < _EMPTY_STD_THRESHOLD:
        return None

    # 1. Template matching — exact match; NCC invariant to polarity.
    if board:
        canonical = _to_canonical_board(gray)
        letter, _ = _match_canonical(
            canonical, _get_board_templates(),
            threshold=_BOARD_MATCH_THRESHOLD,
            min_margin=_BOARD_MARGIN_MIN,
        )
    else:
        letter, _ = _template_match(gray, _get_templates())
    if letter is not None:
        return letter

    # 2. Geometric 'I' detector — OCR reliably misreads the thin bar as 'L'.
    i = _detect_I(gray)
    if i:
        return i

    # 3. OCR fallback — handles anything the templates don't cover yet.
    h, w = gray.shape
    upscaled = cv2.resize(gray, (w * _SCALE, h * _SCALE), interpolation=cv2.INTER_CUBIC)
    uh, uw = upscaled.shape
    for invert in (True, False):
        flag = (cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU) if invert else (cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, thresh = cv2.threshold(upscaled, 0, 255, flag)
        masked = thresh.copy()
        masked[:int(uh * _SCORE_H_FRAC), int(uw * (1 - _SCORE_W_FRAC)):] = 255
        for psm in (8, 10, 7):
            text = pytesseract.image_to_string(masked, config=f"--psm {psm} {_WHITELIST}").strip()
            if len(text) == 1 and text.isupper():
                return text

    return None


def _detect_I(gray: np.ndarray) -> str | None:
    """Return 'I' if the cell contains a thin centered vertical dark stripe."""
    h, w = gray.shape
    bg_value = int(np.median(gray))
    region = gray.copy()
    region[:int(h * 0.28), int(w * 0.68):] = bg_value
    _, binary = cv2.threshold(region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Reject any letter whose top 30% has a WIDE dark horizontal extent —
    # covers G (arc), T (crossbar), E, F, etc.  Threshold lowered from 0.45 → 0.30
    # so that T's crossbar (which spans ~50% but renders narrower at board scale)
    # is still caught.
    top = binary[:int(h * 0.30), :]
    top_col_dark = (top == 0).mean(axis=0)
    top_dark = np.where(top_col_dark > 0.35)[0]
    if len(top_dark) > 0 and (top_dark[-1] - top_dark[0] + 1) > w * 0.30:
        return None

    col_dark_frac = (binary == 0).mean(axis=0)
    dark_cols = np.where(col_dark_frac > 0.40)[0]
    if len(dark_cols) == 0:
        return None

    span = int(dark_cols[-1]) - int(dark_cols[0]) + 1
    center = (int(dark_cols[0]) + int(dark_cols[-1])) / 2.0
    if span > w * 0.30 or abs(center - w / 2.0) > w * 0.20:
        return None

    # Require a very solid fill — the I bar is nearly 100% dark in its strip.
    # Raised from 0.40 → 0.60 so that letters with partial vertical strokes
    # (G's left stem, T below the crossbar) don't qualify.
    strip = binary[:, dark_cols[0]:dark_cols[-1] + 1]
    if float((strip == 0).mean()) > 0.60:
        return "I"
    return None
