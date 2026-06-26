#!/usr/bin/env python3
"""Dump the Android UI hierarchy for perception tuning.

Run with Appium up, the Crossplay app open mid-game, and .env pointing at the
device (ANDROID_DEVICE_UDID, optionally ANDROID_APP_PACKAGE). Writes the full XML
and prints every node that carries a text/content-desc label plus its bounds — use
this to confirm how tiles, the rack, and the Play/More buttons are exposed, then
adjust crossplay/vision/android_board.py and crossplay/client/android_client.py.

    python tools/android_dump.py
"""
import os
import sys
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from crossplay.automation.android_driver import AndroidDriver


def main():
    with AndroidDriver.from_env() as drv:
        src = drv.session.page_source
    out = Path("tools/android_dump.xml")
    out.write_text(src)
    print(f"Full hierarchy written to {out} ({len(src):,} bytes)\n")

    root = ElementTree.fromstring(src)
    print("=== Labelled nodes (text / content-desc) ===")
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        if not text and not desc:
            continue
        cls = node.get("class", "").split(".")[-1]
        clickable = node.get("clickable", "")
        print(f"  bounds={node.get('bounds',''):24} class={cls:16} "
              f"clickable={clickable:5} text={text!r} desc={desc!r}")


if __name__ == "__main__":
    main()
