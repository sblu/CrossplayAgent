"""
Crossplay bot entry point.

Before running:
1. Start Appium:  appium
2. Open Xcode and run WebDriverAgent on the iPhone (Product > Test with WebDriverAgentRunner scheme)
3. Confirm .env has APPIUM_HOST, DEVICE_UDID, BUNDLE_ID, WDA_URL

Usage:
    python main.py
"""
import json
import time
from pathlib import Path
from xml.etree import ElementTree
from dotenv import load_dotenv

from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.input import tap, drag_and_drop
from crossplay.vision.calibration import Calibration
from crossplay.vision.accessibility_board import parse_board_and_rack_accessibility
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.board import Board
from crossplay.strategy.greedy import GreedyAgent

DICT_PATH = "data/dictionary/nwl23.txt"
CAL_PATH  = "data/calibration/calibration.json"

# Screenshots at native 3x resolution; Appium touch uses logical points → divide by 3.
PIXEL_SCALE = 3

# Physical pixel bounding boxes (x, y, w, h) for each of the 7 rack slots.
RACK_CELLS = [
    (12,   2133, 156, 157),
    (183,  2133, 156, 157),
    (353,  2133, 157, 157),
    (524,  2133, 157, 157),
    (695,  2133, 157, 157),
    (866,  2133, 156, 157),
    (1037, 2133, 156, 157),
]

# Logical-point coordinates (confirmed from accessibility tree).
_SUBMIT_LX = 311   # Play button center x  (pos=(236,788) size=150x45 → cx=311)
_SUBMIT_LY = 810   # Play button center y
_MORE_LX   = 38    # More button center x  (pos=(16,781) size=44x59 → cx=38)
_MORE_LY   = 810   # More button center y
# Score display area — safe neutral coordinate for keepalive taps (no buttons nearby).
# Back button: x=0-44. Chat: x=378-386,y=74-83. Tile bag: x=175-227,y=114-167.
_KEEPALIVE_LX = 300
_KEEPALIVE_LY = 130


# ── Accessibility helpers ──────────────────────────────────────────────────────

def _page_tree(session):
    return ElementTree.fromstring(session.page_source)


def _is_our_turn(session) -> bool:
    """True when the Play button is present and enabled in the accessibility tree."""
    for el in _page_tree(session).iter():
        if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == 'Play':
            return el.get('enabled', 'false').lower() == 'true'
    return False


def _game_is_over(session) -> bool:
    """True when the Play button has disappeared (game-over screen)."""
    for el in _page_tree(session).iter():
        if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == 'Play':
            return False
    return True


# Only the confirmed modal dismiss buttons — keep this list narrow so we don't
# accidentally tap persistent UI elements (xmark banner, Close nav button, etc.).
_DISMISS_BUTTONS = {'Okay', 'OK', 'Ok', 'okay', 'ok'}

def _dismiss_popups(session) -> bool:
    """Close any modal overlays (last-turn popup, etc.).

    Loops until no more dismissable buttons are found, handling stacked popups.
    Returns True if at least one button was tapped.
    """
    any_dismissed = False
    for _ in range(5):
        dismissed = False
        for el in _page_tree(session).iter():
            if el.get('type') == 'XCUIElementTypeButton' and el.get('name') in _DISMISS_BUTTONS:
                name = el.get('name', '')
                try:
                    x = int(float(el.get('x', 0)) + float(el.get('width',  0)) / 2)
                    y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                    print(f"  [popup] tapping {name!r} at ({x},{y})")
                    tap(session, x, y)
                    time.sleep(0.8)
                    dismissed = True
                    any_dismissed = True
                except Exception:
                    pass
                break
        if not dismissed:
            break
    return any_dismissed


def _select_blank_letter(session, letter: str) -> None:
    """Tap the correct letter in the blank-tile letter-selection popup."""
    print(f"  Selecting blank as {letter!r}...")
    deadline = time.time() + 5.0
    while time.time() < deadline:
        for el in _page_tree(session).iter():
            if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == letter:
                x = int(float(el.get('x', 0)) + float(el.get('width',  0)) / 2)
                y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                tap(session, x, y)
                time.sleep(0.3)
                return
        time.sleep(0.3)
    print(f"  [!] Blank letter popup: button {letter!r} not found")


def _pass_turn(session) -> None:
    """Open the More menu and tap Pass."""
    tap(session, _MORE_LX, _MORE_LY)
    time.sleep(1.0)
    # After the menu opens, find the Pass button via accessibility.
    for el in _page_tree(session).iter():
        if el.get('type') == 'XCUIElementTypeButton':
            label = (el.get('label') or el.get('name') or '').lower()
            if 'pass' in label or 'skip' in label:
                x = int(float(el.get('x', 0)) + float(el.get('width',  0)) / 2)
                y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                tap(session, x, y)
                return
    # Menu didn't expose a Pass element — tap More again to close it
    tap(session, _MORE_LX, _MORE_LY)


def _keepalive_sleep(session, duration: float, interval: float = 1.5) -> None:
    """Sleep for duration seconds, tapping a neutral screen area every interval seconds."""
    end = time.time() + duration
    while time.time() < end:
        try:
            tap(session, _KEEPALIVE_LX, _KEEPALIVE_LY)
        except Exception:
            pass
        remaining = end - time.time()
        if remaining > 0:
            time.sleep(min(interval, remaining))


def _wait_for_our_turn(session, timeout: int = 300, poll: float = 2.0) -> bool:
    """Poll until the Play button is enabled. Returns False on timeout.

    Keeps the display awake with periodic taps but does NOT dismiss popups —
    popup handling lives in the main loop so a full restart cycle runs after
    any dismissal.
    """
    print("Waiting for our turn...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            tap(session, _KEEPALIVE_LX, _KEEPALIVE_LY)
        except Exception:
            pass
        try:
            if _is_our_turn(session):
                print(" our turn.")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(poll)
    print(" timed out.")
    return False


# ── Move execution ─────────────────────────────────────────────────────────────

def _execute_move(
    session, move: dict, cal: Calibration,
    rack_letters: list, rack_positions: list,
    board_dx: float = 0.0, board_dy: float = 0.0,
) -> bool:
    """Drag each rack tile to its board target. Zooms out after each drag.

    rack_positions: (lx, ly) centres from the accessibility tree — more accurate
    than RACK_CELLS. Falls back to RACK_CELLS if a slot wasn't captured.
    board_dx/dy: measured board scroll offset (logical pts) — added to calibration
    targets so placement stays accurate even when a popup has scrolled the board.
    """
    word       = move["word"]
    row, col   = move["row"], move["col"]
    horizontal = move["horizontal"]
    consumed: set[int] = set()

    blanks = move.get("blanks", {})  # {word_idx: assigned_letter}

    for idx in sorted(move["tiles_played"]):
        letter = word[idx]
        is_blank = idx in blanks

        # For blank tiles, find the '?' in the rack; for regular tiles, match the letter.
        search = '?' if is_blank else letter
        try:
            rack_slot = next(
                j for j, l in enumerate(rack_letters)
                if l == search and j not in consumed
            )
        except StopIteration:
            desc = "blank tile (?)" if is_blank else f"letter {letter!r}"
            print(f"  [!] {desc} not found in rack — aborting move.")
            return False
        consumed.add(rack_slot)

        # Rack position: prefer accessibility-tree coords; fall back to RACK_CELLS.
        pos = rack_positions[rack_slot] if rack_slot < len(rack_positions) else None
        if pos:
            rack_lx, rack_ly = pos
        else:
            rx, ry, rw, rh = RACK_CELLS[rack_slot]
            rack_lx = (rx + rw // 2) // PIXEL_SCALE
            rack_ly = (ry + rh // 2) // PIXEL_SCALE

        target_r = row      if horizontal else row + idx
        target_c = col + idx if horizontal else col
        bx_px, by_px = cal.cell_center_pixel(target_r, target_c)
        board_lx = bx_px // PIXEL_SCALE + round(board_dx)
        board_ly = by_px // PIXEL_SCALE + round(board_dy)

        drag_and_drop(session, rack_lx, rack_ly, board_lx, board_ly)
        time.sleep(0.5)

        if is_blank:
            # Letter selection popup appears after placing a blank tile.
            _select_blank_letter(session, letter)

        time.sleep(0.7)

    return True


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    dictionary = Dictionary.load(DICT_PATH)
    agent = GreedyAgent(dictionary)
    print("Agent: Greedy")

    cal = Calibration.load(CAL_PATH)

    consecutive_timeouts = 0
    final_turn           = False

    with CrossplayDriver.from_env() as driver:
        print("Connected to iPhone. Starting game loop...")

        while True:
            if not _wait_for_our_turn(driver.session):
                if _game_is_over(driver.session):
                    print("Game over — exiting.")
                    break
                consecutive_timeouts += 1
                if consecutive_timeouts >= 3:
                    print("Too many consecutive timeouts — exiting.")
                    break
                print("Retrying...")
                continue

            consecutive_timeouts = 0

            # Dismiss any modal overlays (e.g. Last Turn popup).
            # If something was tapped, restart the full cycle so the board has
            # time to settle — same flow as a normal turn start.
            popped = _dismiss_popups(driver.session)
            if popped:
                final_turn = True
                _keepalive_sleep(driver.session, 2)
                continue

            _keepalive_sleep(driver.session, 1)

            # Read board and rack from the accessibility tree.
            board_grid, rack_letters, rack_positions, board_dx, board_dy = \
                parse_board_and_rack_accessibility(
                    driver.session, cal, RACK_CELLS, scale=PIXEL_SCALE,
                )


            rack = [l for l in rack_letters if l is not None]  # includes '?' for blanks
            blank_count = rack.count('?')
            print(f"\nRack: {rack}" + (f"  ({blank_count} blank)" if blank_count else ""))
            if abs(board_dy) > 2 or abs(board_dx) > 2:
                print(f"  [board offset dx={board_dx:+.1f} dy={board_dy:+.1f} logical pts]")
            print("Board:")
            for r in range(15):
                if any(board_grid[r]):
                    print("  {:2d}: {}".format(r, "".join(c or "." for c in board_grid[r])))

            # Write live state for the web dashboard.
            state_path = Path("data/game_state.json")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({
                "board": board_grid,
                "rack": rack_letters,
                "last_move": None,
                "timestamp": time.strftime("%H:%M:%S"),
            }))

            board = Board()
            board.load_from_grid(board_grid)
            # Tap before move generation — it can take several seconds on a full board.
            try:
                tap(driver.session, _KEEPALIVE_LX, _KEEPALIVE_LY)
            except Exception:
                pass
            move = agent.choose_move(board, rack)

            if move is None:
                print("No valid moves — passing.")
                _pass_turn(driver.session)
                state_path.write_text(json.dumps({
                    "board": board_grid,
                    "rack": rack_letters,
                    "last_move": {"action": "pass"},
                    "timestamp": time.strftime("%H:%M:%S"),
                }))
            else:
                print(f"Playing {move['word']} at ({move['row']},{move['col']}) "
                      f"{'H' if move['horizontal'] else 'V'}  score={move['score']}")
                ok = _execute_move(driver.session, move, cal, rack_letters, rack_positions,
                                   board_dx, board_dy)
                if ok:
                    tap(driver.session, _SUBMIT_LX, _SUBMIT_LY)
                    state_path.write_text(json.dumps({
                        "board": board_grid,
                        "rack": rack_letters,
                        "last_move": move,
                        "timestamp": time.strftime("%H:%M:%S"),
                    }))
                else:
                    print("Move execution failed — passing instead.")
                    _pass_turn(driver.session)

            # Let animations finish before polling again.
            _keepalive_sleep(driver.session, 2)

            if final_turn:
                print("Game complete.")
                break


if __name__ == "__main__":
    main()
