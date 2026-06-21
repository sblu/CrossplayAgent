"""
Extract letter tile templates from AllTiles.PNG (the "Tiles Left" screen).
Tiles are in alphabetical order: A-F, G-L, M-R, S-X, Y-Z-blank.

Creates data/templates/{A-Z}.png and data/templates/blank.png.
Each template is a 48×48 greyscale binary image (letter = black, bg = white).

Usage:
    python3 tools/extract_templates.py [--show]

Pass --show to display each extracted template for visual verification.
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cv2
import numpy as np
from PIL import Image
from pathlib import Path

SRC = "AllTiles.PNG"
OUT_DIR = Path("data/templates")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CANONICAL = (48, 48)
LABELS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["blank"]



_CORNER_SZ = 8


def tile_to_binary(crop_rgb: np.ndarray) -> np.ndarray:
    """Convert an RGB tile crop to a canonical binary image (letter=black, bg=white)."""
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    bg = int(np.median(gray))
    region = gray.copy()
    h, w = gray.shape
    # Mask point-value corner (top-right ~28% × 32%)
    region[:int(h * 0.28), int(w * 0.68):] = bg
    _, binary = cv2.threshold(region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    out = cv2.resize(binary, CANONICAL, interpolation=cv2.INTER_AREA)
    # Remove rounded-corner artifacts (same as _to_canonical in tile_detector.py)
    for r in range(_CORNER_SZ):
        n = _CORNER_SZ - r
        out[r, :n] = 255
        out[47 - r, 48 - n:] = 255
    return out


def find_tiles(img_rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) bounding boxes for each tile, sorted top-left → bottom-right."""
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)

    # The tile background is a mid-blue (rack tile blue ≈ RGB 42,84,146)
    # and the lighter blank tile is a paler blue.
    # In HSV (OpenCV 0-180 hue): blue sits around hue 100-130.
    blue_mask = cv2.inRange(hsv,
                            np.array([90,  40, 40]),
                            np.array([140, 255, 220]))

    # Close small gaps within each tile
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    closed = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, kernel)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)

    h_img, w_img = img_rgb.shape[:2]
    min_area = (w_img * h_img) // 2000   # at least 0.05 % of image
    max_area = (w_img * h_img) // 20     # at most 5 % of image

    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (min_area < area < max_area):
            continue
        if not (0.5 < w / h < 2.0):    # roughly square-ish
            continue
        boxes.append((x, y, w, h))

    # Sort: row by row (top→bottom), then left→right within each row
    if not boxes:
        return []

    # Cluster into rows by y-centroid proximity
    boxes_with_cy = [(x, y, w, h, y + h // 2) for x, y, w, h in boxes]
    boxes_with_cy.sort(key=lambda b: b[4])

    rows: list[list] = []
    current_row: list = [boxes_with_cy[0]]
    for box in boxes_with_cy[1:]:
        if abs(box[4] - current_row[-1][4]) < 80:   # same row if cy within 80 px
            current_row.append(box)
        else:
            rows.append(current_row)
            current_row = [box]
    rows.append(current_row)

    sorted_boxes = []
    for row in rows:
        row.sort(key=lambda b: b[0])   # sort by x within each row
        sorted_boxes.extend([(b[0], b[1], b[2], b[3]) for b in row])

    return sorted_boxes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true",
                        help="Open each extracted tile image for visual check")
    args = parser.parse_args()

    img_rgb = np.array(Image.open(SRC).convert("RGB"))
    print(f"Loaded {SRC}: {img_rgb.shape[1]}×{img_rgb.shape[0]} px")

    boxes = find_tiles(img_rgb)
    print(f"Detected {len(boxes)} tile regions (expected 27: A–Z + blank)")

    if len(boxes) != 27:
        print("\nWARNING: expected 27 tiles. Saving debug mask to data/debug/tile_mask.png")
        hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array([90,40,40]), np.array([140,255,220]))
        Image.fromarray(mask).save("data/debug/tile_mask.png")
        # Overlay detected boxes on image for debugging
        overlay = img_rgb.copy()
        for x, y, w, h in boxes:
            cv2.rectangle(overlay, (x, y), (x + w, y + h), (255, 0, 0), 3)
        Image.fromarray(overlay).save("data/debug/tile_detection.png")
        print("Overlay saved to data/debug/tile_detection.png")
        print("\nDetected boxes:")
        for i, (x, y, w, h) in enumerate(boxes):
            print(f"  {i}: ({x},{y}) {w}×{h}")
        if len(boxes) < 27:
            print("\nToo few tiles detected — check tile_detection.png and adjust the HSV range.")
            return

    saved = 0
    for i, label in enumerate(LABELS):
        if i >= len(boxes):
            print(f"  {label}: MISSING (not enough tiles detected)")
            continue
        x, y, w, h = boxes[i]
        crop = img_rgb[y:y + h, x:x + w]
        binary = tile_to_binary(crop)

        out_path = OUT_DIR / f"{label}.png"
        Image.fromarray(binary).save(out_path)
        saved += 1
        print(f"  {label}: box=({x},{y},{w},{h})  saved → {out_path}")

        if args.show:
            pil = Image.fromarray(crop)
            pil.show(title=f"Tile: {label}")
            input("Press Enter for next…")

    print(f"\nSaved {saved}/{len(LABELS)} templates to {OUT_DIR}/")


if __name__ == "__main__":
    main()
