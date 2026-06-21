"""
Diagnose why _detect_I fails on the saved rack 'I' tile crop.
Run with: python tools/debug_detect_i.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cv2
import numpy as np
from PIL import Image

PATH = "data/debug/rack_4.png"
img = np.array(Image.open(PATH).convert("RGB"))
gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

h, w = gray.shape
print(f"Shape: {h}×{w}")
print(f"Gray std: {gray.std():.2f}  (should be > 15)")
print(f"Gray range: {gray.min()}–{gray.max()}  median: {np.median(gray):.0f}")

# Step 1 — background fill
bg_value = int(np.median(gray))
region = gray.copy()
region[:int(h * 0.28), int(w * 0.68):] = bg_value
print(f"\nbg_value (median): {bg_value}")
print(f"Masked rows 0–{int(h*0.28)}, cols {int(w*0.68)}–{w}")

# Step 2 — threshold
_, binary = cv2.threshold(region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
unique, counts = np.unique(binary, return_counts=True)
print(f"\nBinary values after OTSU INV: {dict(zip(unique.tolist(), counts.tolist()))}")
dark_frac = (binary == 0).mean()
print(f"Fraction dark (letter) pixels: {dark_frac:.3f}")

# Step 3 — top-band check (T/Y exclusion)
top = binary[:int(h * 0.30), :]
top_col_dark = (top == 0).mean(axis=0)
top_dark = np.where(top_col_dark > 0.35)[0]
top_span = int(top_dark[-1]) - int(top_dark[0]) + 1 if len(top_dark) > 0 else 0
print(f"\nTop-band check: top_dark_cols={len(top_dark)}  span={top_span}  threshold={w*0.45:.1f}")
print(f"  → Would return None (T/Y blocked): {top_span > w * 0.45}")

# Step 4 — dark column analysis
col_dark_frac = (binary == 0).mean(axis=0)
dark_cols = np.where(col_dark_frac > 0.40)[0]
print(f"\nDark cols (frac > 0.40): {len(dark_cols)} columns")
print(f"  col_dark_frac range: {col_dark_frac.min():.3f}–{col_dark_frac.max():.3f}")

if len(dark_cols) > 0:
    span = int(dark_cols[-1]) - int(dark_cols[0]) + 1
    center = (int(dark_cols[0]) + int(dark_cols[-1])) / 2.0
    print(f"  span={span}  threshold={w*0.30:.1f}  → too wide: {span > w*0.30}")
    print(f"  center={center:.1f}  w/2={w/2:.1f}  diff={abs(center-w/2):.1f}  threshold={w*0.20:.1f}  → off-center: {abs(center-w/2) > w*0.20}")

    strip = binary[:, dark_cols[0]:dark_cols[-1] + 1]
    coverage = float((strip == 0).mean())
    print(f"  coverage={coverage:.3f}  → insufficient: {coverage <= 0.50}")
    print(f"\n_detect_I would return: {'I' if coverage > 0.50 else 'None'}")
else:
    print("  → No dark cols found, _detect_I returns None")

# Save binary image for inspection
Image.fromarray(binary).save("data/debug/i_tile_binary.png")
print("\nBinary image saved: data/debug/i_tile_binary.png")

# Also save the column dark-fraction profile as text
print("\nColumn dark fractions (every 5th col):")
for c in range(0, w, 5):
    bar = "#" * int(col_dark_frac[c] * 20)
    print(f"  col {c:3d}: {col_dark_frac[c]:.3f} {bar}")
