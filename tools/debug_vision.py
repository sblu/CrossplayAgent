"""
Debug tool: dumps what the bot actually sees for the rack and board.

Run with Appium + WDA running and Crossplay open on iPhone:
    python tools/debug_vision.py

Outputs to data/debug/:
  rack_0.png ... rack_6.png   — cropped rack slot images
  board_overlay.png           — board grid drawn on screenshot
  rack_overlay.png            — rack cells drawn on screenshot
  rack_summary.txt            — detected letter for each slot
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import cv2
import pytesseract

from dotenv import load_dotenv
from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.screenshot import capture_screenshot
from crossplay.vision.calibration import Calibration
from crossplay.vision.tile_detector import detect_letter

load_dotenv()

RACK_CELLS = [
    (12,   2133, 156, 157),
    (183,  2133, 156, 157),
    (353,  2133, 157, 157),
    (524,  2133, 157, 157),
    (695,  2133, 157, 157),
    (866,  2133, 156, 157),
    (1037, 2133, 156, 157),
]

CAL_PATH = "data/calibration/calibration.json"
OUT_DIR = "data/debug"

print("Connecting to iPhone...")
with CrossplayDriver.from_env() as drv:
    img = capture_screenshot(drv.session)
print(f"Screenshot captured: {img.shape[1]}x{img.shape[0]}")

# ── Rack slot crops ───────────────────────────────────────────────────────────
print("\n=== Rack slots ===")
lines = []
for i, (x, y, w, h) in enumerate(RACK_CELLS):
    crop = img[y:y+h, x:x+w]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    std = gray.std()
    letter = detect_letter(crop)

    # Show top-3 template match scores so we can tune the threshold
    from crossplay.vision.tile_detector import _get_templates, _to_canonical, _ncc
    templates = _get_templates()
    canonical = _to_canonical(gray)
    scores = sorted(
        [(ltr, _ncc(canonical, t)) for ltr, t in templates.items() if ltr != "blank"],
        key=lambda x: -x[1],
    )[:3]
    scores_str = "  ".join(f"{ltr}={s:.3f}" for ltr, s in scores)

    line = f"  slot {i}: std={std:.1f}  detect_letter={letter!r}  top3=[{scores_str}]"
    print(line)
    lines.append(line)

    out_path = f"{OUT_DIR}/rack_{i}.png"
    Image.fromarray(crop).save(out_path)

# ── Board cell samples (rows 0-2 + row 7) ───────────────────────────────────
print("\n=== Board cells ===")
cal = Calibration.load(CAL_PATH)
cell_w = cal.board_width // cal.grid_size
cell_h = cal.board_height // cal.grid_size

from crossplay.vision.board_parser import _has_tile, parse_board

# Print corner brightness for row 0 to help tune _TILE_MAX
print("  Row 0 corners (board bg ≈ neutral white; tile face ≈ warm tan R>B):")
for col in range(15):
    x0 = cal.board_x + col * cell_w
    y0 = cal.board_y + 0 * cell_h
    cell = img[y0:y0+cell_h, x0:x0+cell_w]
    h, w = cell.shape[:2]
    p = 5
    corners = np.concatenate([
        cell[0:p, 0:p].reshape(-1, 3),
        cell[0:p, w-p:w].reshape(-1, 3),
        cell[h-p:h, 0:p].reshape(-1, 3),
        cell[h-p:h, w-p:w].reshape(-1, 3),
    ])
    mean_rgb = corners.mean(axis=0)
    bri = mean_rgb.mean()
    warmth = mean_rgb[0] - mean_rgb[2]
    print(f"    ({0},{col:2d}): RGB=({mean_rgb[0]:.0f},{mean_rgb[1]:.0f},{mean_rgb[2]:.0f})  bri={bri:.1f}  warmth={warmth:.1f}  has_tile={_has_tile(cell)}")

print()
print("  Row 7 corners (should show warmth for IRKED tiles):")
for col in range(15):
    x0 = cal.board_x + col * cell_w
    y0 = cal.board_y + 7 * cell_h
    cell = img[y0:y0+cell_h, x0:x0+cell_w]
    h, w = cell.shape[:2]
    p = 5
    corners = np.concatenate([
        cell[0:p, 0:p].reshape(-1, 3),
        cell[0:p, w-p:w].reshape(-1, 3),
        cell[h-p:h, 0:p].reshape(-1, 3),
        cell[h-p:h, w-p:w].reshape(-1, 3),
    ])
    mean_rgb = corners.mean(axis=0)
    bri = mean_rgb.mean()
    warmth = mean_rgb[0] - mean_rgb[2]
    print(f"    ({7},{col:2d}): RGB=({mean_rgb[0]:.0f},{mean_rgb[1]:.0f},{mean_rgb[2]:.0f})  bri={bri:.1f}  warmth={warmth:.1f}  has_tile={_has_tile(cell)}")

print()
board_grid = parse_board(img, cal)
for row in [0, 1, 2, 7]:
    row_str = "".join(c or "." for c in board_grid[row])
    print(f"  row {row}: {row_str}")

# ── Rack overlay ──────────────────────────────────────────────────────────────
pil = Image.fromarray(img)
draw = ImageDraw.Draw(pil)
for i, (x, y, w, h) in enumerate(RACK_CELLS):
    draw.rectangle([x, y, x+w, y+h], outline=(255, 0, 0), width=4)
    draw.text((x+4, y+4), str(i), fill=(255, 0, 0))
pil.save(f"{OUT_DIR}/rack_overlay.png")

# ── Board overlay ─────────────────────────────────────────────────────────────
pil2 = Image.fromarray(img)
draw2 = ImageDraw.Draw(pil2)
for row in range(15):
    for col in range(15):
        x0 = cal.board_x + col * cell_w
        y0 = cal.board_y + row * cell_h
        draw2.rectangle([x0, y0, x0+cell_w, y0+cell_h], outline=(0, 200, 0), width=2)
pil2.save(f"{OUT_DIR}/board_overlay.png")

# ── Save summary ──────────────────────────────────────────────────────────────
with open(f"{OUT_DIR}/rack_summary.txt", "w") as f:
    f.write("\n".join(lines))

print(f"\nImages saved to {OUT_DIR}/")
print("  rack_0.png ... rack_6.png  — crop for each slot")
print("  rack_overlay.png           — red boxes showing rack cell boundaries")
print("  board_overlay.png          — green grid drawn over board area")
print("\nOpen rack_overlay.png and board_overlay.png in Preview to check alignment.")
