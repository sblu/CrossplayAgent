"""
Captures a live screenshot from Crossplay and analyses the rack + button region.
Run with Appium running and Crossplay open mid-game.

Usage:
    python tools/capture_calibration.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from crossplay.automation.driver import CrossplayDriver
from crossplay.automation.screenshot import capture_screenshot
from PIL import Image
import numpy as np

load_dotenv()

print("Connecting to iPhone...")
with CrossplayDriver.from_env() as drv:
    img = capture_screenshot(drv.session)

out_path = "data/calibration/live_screenshot.png"
Image.fromarray(img).save(out_path)
h, w = img.shape[:2]
print(f"Screenshot saved: {out_path}  ({w}x{h})")

# Analyse the bottom half of the screen for the rack area
# The rack sits below the board; board ends ~y=1940, screen height ~2622
print(f"\nBoard ends at approximately y=1940 (known from blank board analysis).")
print(f"Screen height: {h}px  — rack area is roughly y=1940 to y=2300")
print(f"\nSampling colors in the rack region (y=1950-2300, center column x={w//2}):")
for y in range(1950, 2300, 15):
    p = img[y, w // 2]
    sat = int(max(p)) - int(min(p))
    print(f"  y={y:4d}: RGB({p[0]:3d},{p[1]:3d},{p[2]:3d})  sat={sat}")

print(f"\nTo refine rack and button positions:")
print(f"  Open {out_path} in Preview")
print(f"  Use Tools → Show Inspector (Cmd+I) to hover over each rack tile centre")
print(f"  and the Submit/Pass buttons and read the (x, y) coordinates.")
