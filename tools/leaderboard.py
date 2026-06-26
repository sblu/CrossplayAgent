#!/usr/bin/env python3
"""View the self-play leaderboard or render its HTML progress report.

    python tools/leaderboard.py                          # print standings
    python tools/leaderboard.py --html data/leaderboard.html   # write chart report

Populate the leaderboard first with, e.g.:
    python selfplay.py --games 50 --mirror --agent-a greedy --agent-b weak --leaderboard
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from crossplay.leaderboard import Leaderboard
from crossplay.leaderboard_report import render_standings, write_html_report


def main():
    p = argparse.ArgumentParser(description="View / export the Crossplay leaderboard")
    p.add_argument("--file", default="data/leaderboard.json", help="ratings store path")
    p.add_argument("--html", nargs="?", const="data/leaderboard.html", default=None,
                   help="write an HTML progress report (default data/leaderboard.html)")
    args = p.parse_args()

    if not Path(args.file).exists():
        raise SystemExit(f"{args.file} not found — run selfplay.py with --leaderboard first.")

    board = Leaderboard.load(args.file)
    print(render_standings(board))

    if args.html:
        write_html_report(board, args.html)
        print(f"\nwrote HTML report → {args.html}")


if __name__ == "__main__":
    main()
