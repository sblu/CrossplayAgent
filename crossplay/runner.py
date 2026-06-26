"""Backend-agnostic game loop.

`run()` drives any `CrossplayClient` with any `Agent`. It contains no device
specifics — the same loop runs against a real iPhone, an Android emulator, or the
headless simulator. All device quirks (popups, keep-alive, pixel math, opponent
simulation) live inside the client.
"""
import json
import time
from pathlib import Path

from crossplay.client.base import CrossplayClient
from crossplay.engine.board import Board
from crossplay.strategy.base import Agent

_STATE_PATH = Path("data/game_state.json")


def _write_dashboard(board_grid, rack, last_move) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps({
        "board": board_grid,
        "rack": rack,
        "last_move": last_move,
        "timestamp": time.strftime("%H:%M:%S"),
    }))


def _print_state(obs) -> None:
    rack = [t for t in obs.rack if t]
    blank_count = rack.count('?')
    print(f"\nRack: {rack}" + (f"  ({blank_count} blank)" if blank_count else ""))
    print("Board:")
    for r in range(15):
        if any(obs.board[r]):
            print("  {:2d}: {}".format(r, "".join(c or "." for c in obs.board[r])))


def run(
    client: CrossplayClient,
    agent: Agent,
    *,
    max_timeouts: int = 3,
    write_dashboard: bool = True,
    verbose: bool = True,
) -> None:
    with client:
        if verbose:
            print("Connected. Starting game loop...")
        consecutive_timeouts = 0

        while True:
            if not client.wait_for_turn():
                if client.observe().game_over:
                    if verbose:
                        print("Game over — exiting.")
                    break
                consecutive_timeouts += 1
                if consecutive_timeouts >= max_timeouts:
                    if verbose:
                        print("Too many consecutive timeouts — exiting.")
                    break
                if verbose:
                    print("Retrying...")
                continue

            consecutive_timeouts = 0
            obs = client.observe()
            if obs.game_over:
                if verbose:
                    print("Game over — exiting.")
                break

            if verbose:
                _print_state(obs)

            board = Board()
            board.load_from_grid(obs.board)
            rack = [t for t in obs.rack if t]
            move = agent.choose_move(board, rack)

            if move is None:
                if verbose:
                    print("No valid moves — passing.")
                client.pass_turn()
                if write_dashboard:
                    _write_dashboard(obs.board, obs.rack, {"action": "pass"})
            else:
                if verbose:
                    print(f"Playing {move['word']} at ({move['row']},{move['col']}) "
                          f"{'H' if move['horizontal'] else 'V'}  score={move['score']}")
                ok = client.play_move(move)
                if write_dashboard:
                    _write_dashboard(obs.board, obs.rack, move if ok else {"action": "pass"})
                if not ok and verbose:
                    print("Move execution failed.")
