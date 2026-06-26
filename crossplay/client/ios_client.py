"""iOS backend — drives the real Crossplay app on an iPhone via Appium/XCUITest.

All iOS specifics live here: accessibility-tree parsing, @Nx pixel math, popup
dismissal, keep-alive taps, blank-tile selection, and the Play/More/submit taps.

Per-device geometry (pixel scale, rack-slot boxes, button coordinates) is loaded
from DeviceConfig (data/calibration/calibration.json), configurable via the
dashboard's device-setup UI — no code edits needed for a new device. Defaults match
the original @3x iPhone values.
"""
import time
from xml.etree import ElementTree

from crossplay.client.base import CrossplayClient, Observation
from crossplay.client.device_config import DeviceConfig
from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.input import tap, drag_and_drop
from crossplay.vision.calibration import Calibration
from crossplay.vision.accessibility_board import parse_board_and_rack_accessibility

CAL_PATH = "data/calibration/calibration.json"

# Only confirmed modal dismiss buttons — keep narrow so we don't tap persistent UI.
_DISMISS_BUTTONS = {'Okay', 'OK', 'Ok', 'okay', 'ok'}


class IOSClient(CrossplayClient):
    def __init__(self, cal_path: str = CAL_PATH):
        self._cal_path = cal_path
        self._driver = None
        self._cal = None
        self._dev = None     # DeviceConfig: pixel_scale, rack_cells, buttons
        # Cached from the most recent observe(), consumed by play_move().
        self._rack_letters = None
        self._rack_positions = None
        self._board_dx = 0.0
        self._board_dy = 0.0

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self._cal = Calibration.load(self._cal_path)
        self._dev = DeviceConfig.load(self._cal_path)
        self._driver = CrossplayDriver.from_env().start()

    def close(self) -> None:
        if self._driver:
            self._driver.stop()
            self._driver = None

    @property
    def _session(self):
        return self._driver.session

    # ── Accessibility helpers ─────────────────────────────────────────────────

    def _page_tree(self):
        return ElementTree.fromstring(self._session.page_source)

    def _is_our_turn(self) -> bool:
        for el in self._page_tree().iter():
            if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == 'Play':
                return el.get('enabled', 'false').lower() == 'true'
        return False

    def _game_is_over(self) -> bool:
        for el in self._page_tree().iter():
            if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == 'Play':
                return False
        return True

    def _dismiss_popups(self) -> bool:
        any_dismissed = False
        for _ in range(5):
            dismissed = False
            for el in self._page_tree().iter():
                if el.get('type') == 'XCUIElementTypeButton' and el.get('name') in _DISMISS_BUTTONS:
                    name = el.get('name', '')
                    try:
                        x = int(float(el.get('x', 0)) + float(el.get('width', 0)) / 2)
                        y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                        print(f"  [popup] tapping {name!r} at ({x},{y})")
                        tap(self._session, x, y)
                        time.sleep(0.8)
                        dismissed = True
                        any_dismissed = True
                    except Exception:
                        pass
                    break
            if not dismissed:
                break
        return any_dismissed

    def _select_blank_letter(self, letter: str) -> None:
        print(f"  Selecting blank as {letter!r}...")
        deadline = time.time() + 5.0
        while time.time() < deadline:
            for el in self._page_tree().iter():
                if el.get('type') == 'XCUIElementTypeButton' and el.get('name') == letter:
                    x = int(float(el.get('x', 0)) + float(el.get('width', 0)) / 2)
                    y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                    tap(self._session, x, y)
                    time.sleep(0.3)
                    return
            time.sleep(0.3)
        print(f"  [!] Blank letter popup: button {letter!r} not found")

    def _keepalive_tap(self) -> None:
        try:
            tap(self._session, *self._dev.keepalive)
        except Exception:
            pass

    # ── Interface ─────────────────────────────────────────────────────────────

    def wait_for_turn(self, timeout: float = 300) -> bool:
        print("Waiting for our turn...", end="", flush=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._keepalive_tap()
            try:
                if self._is_our_turn():
                    print(" our turn.")
                    self._dismiss_popups()
                    return True
            except Exception:
                pass
            print(".", end="", flush=True)
            time.sleep(2.0)
        print(" timed out.")
        return False

    def observe(self) -> Observation:
        game_over = self._game_is_over()
        board_grid, rack_letters, rack_positions, board_dx, board_dy = \
            parse_board_and_rack_accessibility(
                self._session, self._cal, self._dev.rack_cells, scale=self._dev.pixel_scale,
            )
        self._rack_letters = rack_letters
        self._rack_positions = rack_positions
        self._board_dx = board_dx
        self._board_dy = board_dy
        return Observation(
            board=board_grid,
            rack=rack_letters,
            is_our_turn=not game_over,
            game_over=game_over,
        )

    def play_move(self, move: dict) -> bool:
        ok = self._execute_move(move)
        if ok:
            tap(self._session, *self._dev.submit)
        return ok

    def pass_turn(self) -> None:
        tap(self._session, *self._dev.more)
        time.sleep(1.0)
        for el in self._page_tree().iter():
            if el.get('type') == 'XCUIElementTypeButton':
                label = (el.get('label') or el.get('name') or '').lower()
                if 'pass' in label or 'skip' in label:
                    x = int(float(el.get('x', 0)) + float(el.get('width', 0)) / 2)
                    y = int(float(el.get('y', 0)) + float(el.get('height', 0)) / 2)
                    tap(self._session, x, y)
                    return
        tap(self._session, *self._dev.more)   # close the menu if no Pass found

    # ── Move execution ─────────────────────────────────────────────────────────

    def _execute_move(self, move: dict) -> bool:
        rack_letters = self._rack_letters
        rack_positions = self._rack_positions
        board_dx, board_dy = self._board_dx, self._board_dy
        scale = self._dev.pixel_scale
        rack_cells = self._dev.rack_cells

        word = move["word"]
        row, col = move["row"], move["col"]
        horizontal = move["horizontal"]
        consumed: set[int] = set()
        blanks = move.get("blanks", {})

        for idx in sorted(move["tiles_played"]):
            letter = word[idx]
            is_blank = idx in blanks
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

            pos = rack_positions[rack_slot] if rack_slot < len(rack_positions) else None
            if pos:
                rack_lx, rack_ly = pos
            else:
                rx, ry, rw, rh = rack_cells[rack_slot]
                rack_lx = (rx + rw // 2) // scale
                rack_ly = (ry + rh // 2) // scale

            target_r = row if horizontal else row + idx
            target_c = col + idx if horizontal else col
            bx_px, by_px = self._cal.cell_center_pixel(target_r, target_c)
            board_lx = bx_px // scale + round(board_dx)
            board_ly = by_px // scale + round(board_dy)

            drag_and_drop(self._session, rack_lx, rack_ly, board_lx, board_ly)
            time.sleep(0.5)

            if is_blank:
                self._select_blank_letter(letter)
            time.sleep(0.7)

        return True
