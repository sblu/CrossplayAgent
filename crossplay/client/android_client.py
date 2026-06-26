"""Android backend — drives the Crossplay app on an Android device via Appium
UiAutomator2. OS-agnostic: runs the same on macOS and Ubuntu.

Reuses the device-agnostic pieces: DeviceConfig (geometry/taps), input.py (W3C
taps/drags are platform-neutral), and the CrossplayClient interface, so the same
runner loop and agents drive it unchanged.

Perception (`vision/android_board.parse_board_and_rack`) maps single-letter UI
nodes to board cells / rack slots using the calibrated geometry. The geometry and
move execution are device-agnostic; what needs tuning once a Pixel is attached
(run tools/android_dump.py) is marked TODO: the exact turn/game-over indicators,
the Play/More button labels, and blank-tile handling.

Android note: UiAutomator2 taps use real device pixels, so set pixel_scale = 1 in
the device config (the board/rack geometry and taps then share one coordinate
space).
"""
import time
from xml.etree import ElementTree

from crossplay.client.base import CrossplayClient, Observation
from crossplay.client.device_config import DeviceConfig
from crossplay.automation.android_driver import AndroidDriver
from crossplay.automation.input import tap, drag_and_drop
from crossplay.vision.calibration import Calibration
from crossplay.vision.android_board import parse_board_and_rack

CAL_PATH = "data/calibration/calibration.json"

# TODO(device): confirm against tools/android_dump.py output.
_TURN_KEYWORDS = ("play", "submit")
_PASS_KEYWORDS = ("pass", "skip")
_MORE_KEYWORDS = ("more", "options", "menu")
_OVER_KEYWORDS = ("game over", "rematch", "final", "you won", "you lost")


class AndroidClient(CrossplayClient):
    def __init__(self, cal_path: str = CAL_PATH):
        self._cal_path = cal_path
        self._driver = None
        self._cal = None
        self._dev = None
        self._rack_letters = None
        self._rack_positions = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self._cal = Calibration.load(self._cal_path)
        self._dev = DeviceConfig.load(self._cal_path)
        self._driver = AndroidDriver.from_env().start()

    def close(self) -> None:
        if self._driver:
            self._driver.stop()
            self._driver = None

    @property
    def _session(self):
        return self._driver.session

    # ── Hierarchy helpers ─────────────────────────────────────────────────────

    def _nodes(self):
        return ElementTree.fromstring(self._session.page_source).iter("node")

    def _find_tappable(self, keywords) -> tuple[int, int] | None:
        """Center (device px) of the first clickable node whose label matches."""
        from crossplay.vision.android_board import _parse_bounds
        for node in self._nodes():
            label = (node.get("text", "") + " " + node.get("content-desc", "")).lower()
            if any(k in label for k in keywords):
                b = _parse_bounds(node.get("bounds", ""))
                if b:
                    x, y, w, h = b
                    return x + w // 2, y + h // 2
        return None

    def _is_our_turn(self) -> bool:
        for node in self._nodes():
            label = (node.get("text", "") + " " + node.get("content-desc", "")).lower()
            if any(k in label for k in _TURN_KEYWORDS):
                return node.get("enabled", "true").lower() == "true"
        return False

    def _game_is_over(self) -> bool:
        src = self._session.page_source.lower()
        return any(k in src for k in _OVER_KEYWORDS)

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
                    return True
            except Exception:
                pass
            print(".", end="", flush=True)
            time.sleep(2.0)
        print(" timed out.")
        return False

    def observe(self) -> Observation:
        game_over = self._game_is_over()
        board, rack_letters, rack_positions = parse_board_and_rack(
            self._session.page_source, self._cal, self._dev.rack_cells,
        )
        self._rack_letters = rack_letters
        self._rack_positions = rack_positions
        return Observation(
            board=board,
            rack=rack_letters,
            is_our_turn=not game_over,
            game_over=game_over,
        )

    def play_move(self, move: dict) -> bool:
        ok = self._execute_move(move)
        if ok:
            target = self._find_tappable(_TURN_KEYWORDS) or self._dev.submit
            tap(self._session, *target)
        return ok

    def pass_turn(self) -> None:
        more = self._find_tappable(_MORE_KEYWORDS) or self._dev.more
        tap(self._session, *more)
        time.sleep(1.0)
        pass_btn = self._find_tappable(_PASS_KEYWORDS)
        if pass_btn:
            tap(self._session, *pass_btn)

    # ── Move execution ─────────────────────────────────────────────────────────

    def _execute_move(self, move: dict) -> bool:
        scale = self._dev.pixel_scale
        word = move["word"]
        row, col = move["row"], move["col"]
        horizontal = move["horizontal"]
        consumed: set[int] = set()
        blanks = move.get("blanks", {})

        for idx in sorted(move["tiles_played"]):
            letter = word[idx]
            is_blank = idx in blanks
            search = '?' if is_blank else letter   # TODO(device): blank tiles in rack
            try:
                slot = next(j for j, l in enumerate(self._rack_letters)
                            if l == search and j not in consumed)
            except StopIteration:
                desc = "blank tile (?)" if is_blank else f"letter {letter!r}"
                print(f"  [!] {desc} not found in rack — aborting move.")
                return False
            consumed.add(slot)

            pos = self._rack_positions[slot] if slot < len(self._rack_positions) else None
            if pos:
                rack_x, rack_y = pos[0] // scale, pos[1] // scale
            else:
                rx, ry, rw, rh = self._dev.rack_cells[slot]
                rack_x, rack_y = (rx + rw // 2) // scale, (ry + rh // 2) // scale

            target_r = row if horizontal else row + idx
            target_c = col + idx if horizontal else col
            bx, by = self._cal.cell_center_pixel(target_r, target_c)
            drag_and_drop(self._session, rack_x, rack_y, bx // scale, by // scale)
            time.sleep(0.5)
            if is_blank:
                pass  # TODO(device): handle Android blank-letter selection popup
            time.sleep(0.4)
        return True
