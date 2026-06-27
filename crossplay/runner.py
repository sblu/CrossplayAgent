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
from crossplay.engine.scorer import score_move
from crossplay.strategy.base import Agent, move_key

_STATE_PATH = Path("data/game_state.json")


def _empty_grid() -> list[list]:
    return [[None for _ in range(15)] for _ in range(15)]


def _write_dashboard(board_grid, rack, last_move, scores=None, history=None,
                     phase="") -> None:
    """Snapshot the live game to data/game_state.json for the /device-live view."""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps({
        "board": board_grid,
        "rack": rack,
        "last_move": last_move,
        "scores": scores or {},
        "history": history or [],
        "phase": phase,
        "timestamp": time.strftime("%H:%M:%S"),
    }))


def _reset_dashboard() -> None:
    """Clear the live-view state at the start of a game so the previous game's
    board, rack, scores and play history don't linger in /device-live."""
    _write_dashboard(_empty_grid(), [], None,
                     {"bot": 0, "opponent": 0}, [], phase="Starting game…")


def _apply_move_to_grid(grid, move):
    """Overlay a move's letters onto a copy of `grid` (so the live view shows the
    just-played word immediately, instead of waiting for the next OCR read)."""
    new = [list(row) for row in grid]
    word, row, col, horizontal = (
        move["word"], move["row"], move["col"], move["horizontal"])
    for i, ch in enumerate(word):
        r = row if horizontal else row + i
        c = col + i if horizontal else col
        if 0 <= r < 15 and 0 <= c < 15:
            new[r][c] = ch
    return new


def _reconstruct_move(prev_grid, new_grid):
    """Diff two board grids to recover the move that produced `new_grid`.

    Returns a move dict (word/row/col/horizontal/tiles_played) for the newly
    placed tiles, or None if the change isn't a single clean line (e.g. OCR noise
    or nothing changed). Used to log the opponent's plays for the live view.
    """
    cells = [(r, c) for r in range(15) for c in range(15)
             if new_grid[r][c] and not prev_grid[r][c]]
    if not cells:
        return None

    rows = {r for r, _ in cells}
    cols = {c for _, c in cells}
    if len(cells) == 1:
        r, c = cells[0]
        # A single new tile extends an existing word; pick the axis with neighbours.
        horiz_neighbour = ((c > 0 and new_grid[r][c - 1]) or
                           (c < 14 and new_grid[r][c + 1]))
        horizontal = bool(horiz_neighbour)
    elif len(rows) == 1:
        horizontal = True
    elif len(cols) == 1:
        horizontal = False
    else:
        return None   # not a single line — can't cleanly reconstruct

    if horizontal:
        r = next(iter(rows)) if len(rows) == 1 else cells[0][0]
        c0 = min(c for _, c in cells)
        while c0 - 1 >= 0 and new_grid[r][c0 - 1]:
            c0 -= 1
        c1 = max(c for _, c in cells)
        while c1 + 1 < 15 and new_grid[r][c1 + 1]:
            c1 += 1
        word = "".join((new_grid[r][c] or "?") for c in range(c0, c1 + 1))
        tiles_played = sorted(c - c0 for _, c in cells)
        return {"word": word, "row": r, "col": c0, "horizontal": True,
                "tiles_played": tiles_played, "blanks": {}}
    else:
        c = next(iter(cols)) if len(cols) == 1 else cells[0][1]
        r0 = min(r for r, _ in cells)
        while r0 - 1 >= 0 and new_grid[r0 - 1][c]:
            r0 -= 1
        r1 = max(r for r, _ in cells)
        while r1 + 1 < 15 and new_grid[r1 + 1][c]:
            r1 += 1
        word = "".join((new_grid[r][c] or "?") for r in range(r0, r1 + 1))
        tiles_played = sorted(r - r0 for r, _ in cells)
        return {"word": word, "row": r0, "col": c, "horizontal": False,
                "tiles_played": tiles_played, "blanks": {}}


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
    max_moves: int | None = None,
    max_failures: int = 4,
    max_passes: int = 3,
    write_dashboard: bool = True,
    verbose: bool = True,
) -> None:
    with client:
        if verbose:
            print("Connected. Starting game loop...")
        consecutive_timeouts = 0
        consecutive_failures = 0
        consecutive_passes = 0
        failed_moves: set = set()   # moves the device rejected this turn
        moves_played = 0

        # Live-view state: running scores and a chronological play log. prev_grid is
        # the board after our last action, so diffing it against the next read
        # recovers what the opponent played.
        history: list[dict] = []
        bot_score = 0
        opp_score = 0
        prev_grid = _empty_grid()
        scores = {"bot": 0, "opponent": 0}
        cur_rack: list = []
        last_move_disp = None
        if write_dashboard:
            _reset_dashboard()   # clear last game's board/scores/play list

        def publish(phase, board=None, rack=None, last_move="__keep__"):
            """Push a live-view update with the bot's current phase. Defaults reuse
            the last known board/rack so phase-only ticks don't blank the display."""
            nonlocal last_move_disp
            if not write_dashboard:
                return
            if last_move != "__keep__":
                last_move_disp = last_move
            _write_dashboard(
                prev_grid if board is None else board,
                cur_rack if rack is None else rack,
                last_move_disp, scores, history, phase)

        while True:
            publish("Waiting for opponent's move…", board=prev_grid, rack=[])
            if not client.wait_for_turn():
                if client.observe().game_over:
                    if verbose:
                        print("Game over — exiting.")
                    publish("Game over", board=prev_grid)
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
            publish("Reading the board…")
            obs = client.observe()
            cur_rack = obs.rack
            if obs.game_over:
                if verbose:
                    print("Game over — exiting.")
                publish("Game over", board=obs.board, rack=obs.rack)
                break

            # Recover and log the opponent's move from the board diff.
            opp_move = _reconstruct_move(prev_grid, obs.board)
            if opp_move and opp_move["word"]:
                try:
                    b = Board()
                    b.load_from_grid(prev_grid)
                    opp_move["score"] = score_move(b, opp_move)
                except Exception:
                    opp_move["score"] = None
                opp_score += opp_move["score"] or 0
                history.append({"player": "Opponent", "word": opp_move["word"],
                                "score": opp_move["score"]})
            prev_grid = [list(r) for r in obs.board]
            scores = {"bot": bot_score, "opponent": opp_score}

            # Push the opponent's move to the live view straight away, before we
            # spend time thinking, so the board never looks several moves stale.
            opp_label = (f"Opponent played {opp_move['word']}"
                         if opp_move and opp_move.get("word") else "Our turn")
            publish(opp_label, board=obs.board, rack=obs.rack, last_move=opp_move)

            if verbose:
                _print_state(obs)

            board = Board()
            board.load_from_grid(obs.board)
            rack = [t for t in obs.rack if t]
            publish(f"Thinking… (rack: {' '.join(rack) or '—'})",
                    board=obs.board, rack=obs.rack)
            move = agent.choose_move(board, rack, exclude=failed_moves)

            if move is None:
                if verbose:
                    print("No valid moves — passing.")
                publish("No valid move — passing", board=obs.board, rack=obs.rack)
                client.pass_turn()
                failed_moves = set()
                history.append({"player": "Bot", "word": "(pass)", "score": 0})
                publish("Passed", board=obs.board, rack=obs.rack,
                        last_move={"action": "pass"})
                # Repeated passes mean the game is over or we're stuck reading the
                # board (e.g. an end-game rack we can't OCR). Don't loop forever —
                # if a pass doesn't advance the turn we'd otherwise spin here.
                consecutive_passes += 1
                if consecutive_passes >= max_passes:
                    if verbose:
                        print(f"Passed {consecutive_passes} turns in a row — "
                              "ending (game over or stuck).")
                    break
            else:
                if verbose:
                    print(f"Playing {move['word']} at ({move['row']},{move['col']}) "
                          f"{'H' if move['horizontal'] else 'V'}  score={move['score']}")
                publish(f"Placing {move['word']} for {move['score']}…",
                        board=obs.board, rack=obs.rack)
                ok = client.play_move(move)
                if ok:
                    consecutive_failures = 0
                    consecutive_passes = 0
                    failed_moves = set()
                    bot_score += move.get("score", 0)
                    scores = {"bot": bot_score, "opponent": opp_score}
                    history.append({"player": "Bot", "word": move["word"],
                                    "score": move.get("score")})
                    # Show our word on the board immediately (don't wait for OCR).
                    prev_grid = _apply_move_to_grid(obs.board, move)
                    publish(f"Played {move['word']} for {move['score']}",
                            board=prev_grid, rack=obs.rack, last_move=move)
                else:
                    failed_moves.add(move_key(move))   # don't re-pick this move
                    consecutive_failures += 1
                    publish("Move rejected — trying another…",
                            board=obs.board, rack=obs.rack,
                            last_move={"action": "pass"})
                    if verbose:
                        print(f"Move execution failed ({consecutive_failures}/{max_failures}).")
                    if consecutive_failures >= max_failures:
                        if verbose:
                            print("Too many failed moves — exiting.")
                        break
                    continue   # retry the turn with the next-best move

            moves_played += 1
            if max_moves is not None and moves_played >= max_moves:
                if verbose:
                    print(f"Reached max_moves ({max_moves}) — stopping.")
                break
