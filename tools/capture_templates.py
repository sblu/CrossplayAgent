"""
Capture letter templates directly from live rack tiles.

Run with Appium + WDA running and Crossplay open on iPhone:
    python3 tools/capture_templates.py

For each rack slot that contains a tile, the script saves a template to
data/templates/{LETTER}.png using the live crop (same size/rendering as
what detect_letter will see at runtime).  After running a few times across
different turns you'll have all 26 letters covered.

Usage tip: put unusual letters (Q, X, Z, J) on your rack if possible.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cv2
import numpy as np
from PIL import Image, ImageDraw

from dotenv import load_dotenv
from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.screenshot import capture_screenshot
from crossplay.vision.tile_detector import _to_canonical

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

TEMPLATE_DIR = "data/templates"
os.makedirs(TEMPLATE_DIR, exist_ok=True)
CANONICAL_SIZE = (48, 48)
EMPTY_STD_THRESHOLD = 15.0

ALL_LETTERS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def rack_has_tile(gray_crop: np.ndarray) -> bool:
    return float(gray_crop.std()) >= EMPTY_STD_THRESHOLD


def already_have(letter: str) -> bool:
    return os.path.exists(os.path.join(TEMPLATE_DIR, f"{letter}.png"))


def save_template(letter: str, crop_rgb: np.ndarray):
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    binary = _to_canonical(gray)
    Image.fromarray(binary).save(os.path.join(TEMPLATE_DIR, f"{letter}.png"))
    print(f"  Saved template for '{letter}'")


def show_rack_overlay(img: np.ndarray, crops: list) -> None:
    pil = Image.fromarray(img)
    draw = ImageDraw.Draw(pil)
    for i, (x, y, w, h) in enumerate(RACK_CELLS):
        draw.rectangle([x, y, x+w, y+h], outline=(255, 0, 0), width=4)
        draw.text((x+4, y+4), str(i), fill=(255, 0, 0))
    out = "data/debug/rack_overlay_capture.png"
    pil.save(out)
    print(f"  Rack overlay saved → {out}")
    print("  Open it in Preview to see which slot is which.")


def main():
    already_have_letters = {l for l in ALL_LETTERS if already_have(l)}
    missing = ALL_LETTERS - already_have_letters
    print(f"Templates already captured ({len(already_have_letters)}): {''.join(sorted(already_have_letters))}")
    print(f"Still needed ({len(missing)}): {''.join(sorted(missing))}")
    print()

    print("Connecting to iPhone...")
    with CrossplayDriver.from_env() as drv:
        img = capture_screenshot(drv.session)
    print(f"Screenshot captured: {img.shape[1]}x{img.shape[0]}")

    crops = []
    tile_slots = []
    for i, (x, y, w, h) in enumerate(RACK_CELLS):
        crop = img[y:y+h, x:x+w]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if rack_has_tile(gray):
            crops.append((i, crop))
            tile_slots.append(i)

    if not tile_slots:
        print("No tiles detected in rack. Is the rack visible?")
        return

    show_rack_overlay(img, crops)

    print(f"\nTiles detected in slots: {tile_slots}")
    print("Enter the letters for each slot (or '.' for empty/skip, '?' for blank tile).")
    print("Type just the letters in slot order, e.g. 'EIMYRK.' for 7 slots.\n")

    user_input = input("Letters: ").strip().upper()
    if len(user_input) != 7:
        print(f"Expected 7 characters, got {len(user_input)}. Re-run and try again.")
        return

    saved = 0
    skipped = 0
    for slot_idx, (x, y, w, h) in enumerate(RACK_CELLS):
        ch = user_input[slot_idx]
        crop = img[y:y+h, x:x+w]
        if ch in ('.', '?'):
            skipped += 1
            continue
        if ch not in ALL_LETTERS:
            print(f"  slot {slot_idx}: skipping unknown char '{ch}'")
            skipped += 1
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if not rack_has_tile(gray):
            print(f"  slot {slot_idx}: no tile detected, skipping '{ch}'")
            skipped += 1
            continue
        if already_have(ch):
            print(f"  slot {slot_idx}: overwriting existing template for '{ch}'")
        save_template(ch, crop)
        saved += 1

    print(f"\nSaved {saved} templates, skipped {skipped}.")
    now_have = {l for l in ALL_LETTERS if already_have(l)}
    still_need = ALL_LETTERS - now_have
    print(f"Total templates: {len(now_have)}/26")
    if still_need:
        print(f"Still needed: {''.join(sorted(still_need))}")
    else:
        print("All 26 letters captured!")


if __name__ == "__main__":
    main()
