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

import numpy as np
import pytesseract
from PIL import Image

from crossplay.client.base import CrossplayClient, Observation
from crossplay.client.device_config import DeviceConfig
from crossplay.automation.android_driver import AndroidDriver
from crossplay.automation.input import tap, android_drag
from crossplay.automation.screenshot import capture_screenshot
from crossplay.vision.calibration import Calibration
from crossplay.vision.android_vision import parse_board_and_rack

CAL_PATH = "data/calibration/calibration.json"

# The Compose app exposes no accessibility text, so turn state is read by OCR'ing
# the action button: "Play" (our turn) vs "Their Turn". Game-over screens swap it
# for a rematch/play-again control.
_OVER_KEYWORDS = ("rematch", "game over", "play again")


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

    # ── Screen helpers ─────────────────────────────────────────────────────────

    def _zoom_out(self) -> None:
        """Pinch the board back to full view (it zooms in while placing tiles)."""
        try:
            self._session.execute_script("mobile: pinchCloseGesture", {
                "left": self._cal.board_x, "top": self._cal.board_y,
                "width": self._cal.board_width, "height": self._cal.board_height,
                "percent": 0.75,
            })
            time.sleep(0.4)
        except Exception:
            pass

    def _read(self):
        """Zoom to full board, screenshot, OCR → (board, rack, rack_positions)."""
        self._zoom_out()
        img = capture_screenshot(self._session)
        return parse_board_and_rack(img, self._cal, self._dev.rack_cells)

    def _button_text(self) -> str:
        """OCR the action button (Play / Their Turn / Rematch …), lowercased."""
        img = capture_screenshot(self._session)
        sx, sy = self._dev.submit
        crop = img[max(0, sy - 68):sy + 42, max(0, sx - 260):sx + 260]
        if crop.size == 0:
            return ""
        g = Image.fromarray(crop).convert("L")
        g = g.resize((g.width * 2, g.height * 2))
        return pytesseract.image_to_string(g, config="--psm 7").strip().lower()

    def _select_blank_letter(self, letter: str) -> bool:
        """Tap `letter` in the 'Choose a letter' popup shown after placing a blank.

        The popup is a 7-wide alphabetical grid of bright-blue buttons over a dimmed
        board; detect the bright-blue cluster's bounding box and index by position.
        Short rows (V–Z) are centre-aligned, so offset partial rows.
        """
        img = capture_screenshot(self._session)
        r, g, b = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
        bright = (b > 180) & (g > 90) & (g < 190) & (r < 120) & (b - r > 80)
        ys, xs = np.where(bright)
        if len(xs) < 500:
            print(f"  [!] blank-letter popup not found (can't assign {letter!r})")
            return False
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        cw, ch = (x1 - x0) / 7, (y1 - y0) / 4
        idx = ord(letter.upper()) - 65
        row, col = idx // 7, idx % 7
        offset = (7 - min(7, 26 - row * 7)) / 2     # centre short rows
        cx = int(x0 + (offset + col + 0.5) * cw)
        cy = int(y0 + (row + 0.5) * ch)
        tap(self._session, cx, cy)
        time.sleep(0.6)
        return True

    def _play_enabled(self) -> bool:
        """True when the Play button is dark (a valid move is staged)."""
        img = capture_screenshot(self._session)
        sx, sy = self._dev.submit
        crop = img[max(0, sy - 40):sy + 40, max(0, sx - 120):sx + 120]
        return crop.size > 0 and crop.reshape(-1, 3).mean() < 110

    def _is_our_turn(self) -> bool:
        text = self._button_text()
        return "play" in text and "their" not in text

    def _game_is_over(self) -> bool:
        return any(k in self._button_text() for k in _OVER_KEYWORDS)

    # ── Interface ─────────────────────────────────────────────────────────────

    def wait_for_turn(self, timeout: float = 300) -> bool:
        print("Waiting for our turn...", end="", flush=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self._is_our_turn():
                    print(" our turn.")
                    return True
            except Exception:
                pass
            print(".", end="", flush=True)
            time.sleep(2.5)
        print(" timed out.")
        return False

    def observe(self) -> Observation:
        board, rack_letters, rack_positions = self._read()
        self._rack_letters = rack_letters
        self._rack_positions = rack_positions
        return Observation(
            board=board,
            rack=rack_letters,
            is_our_turn=self._is_our_turn(),
            game_over=self._game_is_over(),
        )

    def play_move(self, move: dict) -> bool:
        if not self._execute_move(move):
            return False
        # Wait for the board to register a valid staged move (Play goes dark).
        deadline = time.time() + 6
        while time.time() < deadline and not self._play_enabled():
            time.sleep(0.5)
        tap(self._session, *self._dev.submit)
        # Wait for the move to be accepted and the turn to pass, so the next
        # wait_for_turn doesn't catch a stale "Play" and read a transitioning board.
        deadline = time.time() + 8
        while time.time() < deadline:
            time.sleep(1.0)
            if "play" not in self._button_text():
                break
        return True

    def pass_turn(self) -> None:
        # TODO(device): confirm the More→Pass flow on Android (capture via android_dump).
        tap(self._session, *self._dev.more)

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
            # The board zooms in as tiles are placed, which drifts later targets;
            # reset to full view before every drag so calibration stays valid.
            self._zoom_out()
            android_drag(self._session, rack_x, rack_y, bx // scale, by // scale)
            time.sleep(0.6)
            if is_blank:
                self._select_blank_letter(letter)
            time.sleep(0.4)
        return True
