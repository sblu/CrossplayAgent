#!/usr/bin/env python3
"""
Diagnostic: tap the Okay popup button then print the board state at several
intervals so we can see whether the board representation stabilises.

Run with the Last Turn popup visible:
    python3 tools/test_final.py
"""
import os, sys, time
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.input import tap
from crossplay.vision.calibration import Calibration
from crossplay.vision.accessibility_board import parse_board_and_rack_accessibility

CAL_PATH  = "data/calibration/calibration.json"
RACK_CELLS = [
    (12,   2133, 156, 157),
    (183,  2133, 156, 157),
    (353,  2133, 157, 157),
    (524,  2133, 157, 157),
    (695,  2133, 157, 157),
    (866,  2133, 156, 157),
    (1037, 2133, 156, 157),
]
PIXEL_SCALE = 3


def _find_okay(session):
    """Return (x, y) logical centre of the Okay button, or None."""
    root = ElementTree.fromstring(session.page_source)
    for el in root.iter():
        if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == 'Okay':
            x = float(el.get('x', 0)) + float(el.get('width',  0)) / 2
            y = float(el.get('y', 0)) + float(el.get('height', 0)) / 2
            return int(x), int(y)
    return None


def _print_board(board, rack, board_dx, board_dy, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  board offset  dx={board_dx:+.1f}  dy={board_dy:+.1f}  logical pts")
    print(f"  Rack: {[l for l in rack if l is not None]}")
    print("  Board:")
    for r in range(15):
        row_str = "".join(c or "." for c in board[r])
        marker = " <--" if any(board[r]) else ""
        print(f"    {r:2d}: {row_str}{marker}")
    print()


def main():
    cal = Calibration.load(CAL_PATH)

    with CrossplayDriver.from_env() as driver:
        session = driver.session

        # ── Step 1: find and tap Okay ──────────────────────────────────────────
        pos = _find_okay(session)
        if pos is None:
            print("No Okay button found. Make sure the Last Turn popup is visible.")
            board, rack, _, dx, dy = parse_board_and_rack_accessibility(
                session, cal, RACK_CELLS, scale=PIXEL_SCALE)
            _print_board(board, rack, dx, dy, "Board BEFORE tap (no popup found)")
            return

        print(f"Found Okay button at logical {pos}. Tapping...")
        tap(session, *pos)

        # ── Step 2: read board at several intervals after the tap ──────────────
        for delay in (0.5, 1.0, 2.0, 3.0):
            time.sleep(0.5)   # incremental sleep (total = delay)
            board, rack, _, dx, dy = parse_board_and_rack_accessibility(
                session, cal, RACK_CELLS, scale=PIXEL_SCALE)
            _print_board(board, rack, dx, dy, f"Board {delay:.1f}s after Okay tap")

        print("Done.")


if __name__ == "__main__":
    main()
