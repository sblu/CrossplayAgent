#!/usr/bin/env python3
"""Standalone live spectator of simulated Crossplay games.

A thin wrapper around `crossplay.web.spectator`. For the unified dashboard (this
plus the leaderboard and the device-debug tools), use tools/dashboard.py instead.

    python tools/live_server.py --a greedy --b weak --delay 0.8
    open http://localhost:8770
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from crossplay.engine.dictionary import Dictionary
from crossplay.web.spectator import AGENTS, attach_spectator


def main():
    p = argparse.ArgumentParser(description="Live Crossplay self-play spectator")
    p.add_argument("--a", default="greedy", choices=list(AGENTS))
    p.add_argument("--b", default="weak", choices=list(AGENTS))
    p.add_argument("--dict", default="data/dictionary/nwl23.txt")
    p.add_argument("--delay", type=float, default=1.2, help="seconds between moves")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--leaderboard", nargs="?", const="data/leaderboard.json", default=None)
    args = p.parse_args()

    try:
        dictionary = Dictionary.load(args.dict)
    except FileNotFoundError:
        print(f"[!] {args.dict} not found — falling back to data/sample_words.txt")
        dictionary = Dictionary.load("data/sample_words.txt")

    app = Flask(__name__)
    attach_spectator(
        app, page_route="/", state_route="/state",
        agent_specs=(args.a, args.b), dictionary=dictionary,
        delay=args.delay, seed=args.seed, leaderboard_path=args.leaderboard,
    )
    print(f"Watch at http://localhost:{args.port}   ({args.a} vs {args.b}, {args.delay}s/move)")
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
