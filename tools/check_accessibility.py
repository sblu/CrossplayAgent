#!/usr/bin/env python3
"""
Dump the iOS accessibility tree.
Run during active gameplay to identify board cell elements.
Run: python3 tools/check_accessibility.py
"""
import os, sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from crossplay.automation.driver import CrossplayDriver

# Board area in logical points (physical px / 3): x≈9, y≈267, w≈386, h≈383
# Rack area: y≈711
_BOARD_LX0, _BOARD_LY0 = 9,   267
_BOARD_LX1, _BOARD_LY1 = 395, 650

def _in_board(x, y):
    return _BOARD_LX0 <= x <= _BOARD_LX1 and _BOARD_LY0 <= y <= _BOARD_LY1

def dump_tree():
    with CrossplayDriver.from_env() as driver:
        src = driver.session.page_source
        Path("tools/accessibility_dump.xml").write_text(src)
        print(f"Full XML written to tools/accessibility_dump.xml ({len(src):,} bytes)\n")

        root = ElementTree.fromstring(src)

        # ── 1. All elements with labels/values ────────────────────────────────
        print("=== Elements with non-empty label or value ===")
        found = 0
        for el in root.iter():
            label   = el.get("label",   "").strip()
            value   = el.get("value",   "").strip()
            name    = el.get("name",    "").strip()
            typ     = el.get("type",    "")
            enabled = el.get("enabled", "")
            if label or value:
                found += 1
                print(f"  type={typ:35s}  name={name!r:20s}  label={label!r:20s}  value={value!r}  enabled={enabled!r}")
        print(f"\n{found} elements with labels/values.\n")

        # ── 2. Single-letter tiles ────────────────────────────────────────────
        print("=== Single uppercase letter labels (board/rack tiles) ===")
        for el in root.iter():
            label = el.get("label", "").strip()
            if len(label) == 1 and label.isupper():
                x = el.get("x"); y = el.get("y")
                w = el.get("width"); h = el.get("height")
                print(f"  {label!r}  at ({x},{y}) size {w}×{h}  type={el.get('type')}  name={el.get('name')!r}")

        # ── 3. All element types × sizes (find consistent-size collections) ──
        print("\n=== Element type × size histogram (top 30) ===")
        counts = Counter()
        for el in root.iter():
            try:
                w = int(float(el.get("width",  0)))
                h = int(float(el.get("height", 0)))
                counts[(el.get("type", "?"), f"{w}×{h}")] += 1
            except Exception:
                pass
        for (typ, sz), n in counts.most_common(30):
            print(f"  {n:4d}  {typ:45s}  {sz}")

        # ── 4. Elements inside the board area ─────────────────────────────────
        print("\n=== All elements inside the board area (logical coords) ===")
        board_els = []
        for el in root.iter():
            try:
                x = float(el.get("x", -1))
                y = float(el.get("y", -1))
                w = float(el.get("width",  0))
                h = float(el.get("height", 0))
            except Exception:
                continue
            if x < 0 or w <= 0:
                continue
            cx = x + w / 2
            cy = y + h / 2
            if _in_board(cx, cy):
                board_els.append((el.get("type", "?"), x, y, w, h,
                                  el.get("label", ""), el.get("name", "")))
        if not board_els:
            print("  (none found — check board coordinate constants at top of script)")
        else:
            # Group by type
            by_type = Counter(t for t, *_ in board_els)
            print(f"  {len(board_els)} total elements in board area:")
            for typ, n in by_type.most_common():
                print(f"    {n:4d}  {typ}")
            # Print a sample of each type
            seen_types = set()
            print("\n  Sample (first 3 of each type):")
            sample_counts = Counter()
            for (typ, x, y, w, h, label, name) in board_els:
                if sample_counts[typ] < 3:
                    sample_counts[typ] += 1
                    enabled = ""
                    print(f"    [{typ}]  at ({x:.0f},{y:.0f}) size {w:.0f}×{h:.0f}  label={label!r}  name={name!r}")

        # ── 5b. All buttons (enabled/disabled status) ────────────────────────
        print("\n=== All XCUIElementTypeButton elements ===")
        for el in root.iter():
            if el.get("type") != "XCUIElementTypeButton":
                continue
            name    = el.get("name",    "")
            label   = el.get("label",   "")
            enabled = el.get("enabled", "?")
            x = el.get("x", "?"); y = el.get("y", "?")
            w = el.get("width", "?"); h = el.get("height", "?")
            print(f"  name={name!r:20s}  label={label!r:20s}  enabled={enabled}  at ({x},{y}) size {w}×{h}")

        # ── 5. Board-cell-sized elements (~25×25 logical pts) ─────────────────
        print("\n=== Elements sized ~22–30 px (expected board cell size) ===")
        cell_els = []
        for el in root.iter():
            try:
                w = float(el.get("width",  0))
                h = float(el.get("height", 0))
                x = float(el.get("x", 0))
                y = float(el.get("y", 0))
            except Exception:
                continue
            if 22 <= w <= 30 and 22 <= h <= 30:
                cell_els.append((el.get("type","?"), x, y, w, h,
                                 el.get("label",""), el.get("name","")))
        if cell_els:
            print(f"  Found {len(cell_els)} elements:")
            for typ, x, y, w, h, label, name in cell_els[:30]:
                print(f"    {typ:45s}  at ({x:.0f},{y:.0f}) {w:.0f}×{h:.0f}  label={label!r}  name={name!r}")
        else:
            print("  (none found)")

        # ── 6. ALL elements in the rack y-range (blank tile diagnostic) ───────
        # Run this with a blank tile in your rack to see exactly what element
        # the blank exposes — the broad-scan fallback in accessibility_board.py
        # needs to know the type/size to find it reliably.
        _RACK_Y_CENTER = 737   # logical pts  (RACK_CELLS physical centre y / 3)
        _RACK_Y_TOL    = 30
        print(f"\n=== ALL elements at rack y-range ({_RACK_Y_CENTER}±{_RACK_Y_TOL} logical pts) ===")
        rack_area = []
        for el in root.iter():
            try:
                x = float(el.get("x", 0))
                y = float(el.get("y", 0))
                w = float(el.get("width", 0))
                h = float(el.get("height", 0))
            except Exception:
                continue
            if w <= 0 or h <= 0:
                continue
            cy = y + h / 2
            if abs(cy - _RACK_Y_CENTER) <= _RACK_Y_TOL:
                rack_area.append((el.get("type","?"), x, y, w, h,
                                  el.get("label",""), el.get("name","")))
        if rack_area:
            print(f"  {len(rack_area)} elements:")
            for typ, x, y, w, h, label, name in rack_area:
                print(f"    {typ:45s}  at ({x:.0f},{y:.0f}) {w:.0f}×{h:.0f}  label={label!r}  name={name!r}")
        else:
            print("  (none found — check _RACK_Y_CENTER constant)")


if __name__ == "__main__":
    dump_tree()
