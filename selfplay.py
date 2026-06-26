"""Self-play harness: pit two agents against each other over many headless games.

Drives both seats directly against `GameState` (no client, no device) for speed and
symmetric logging. Use it to:

  * A/B compare two strategy versions (win rate, avg score, avg margin), and
  * generate training data — one JSONL line per decision (state, chosen move),
    plus a per-game summary line carrying the final margin (usable as a reward).

Reproducibility: each game uses a fixed bag seed. With --mirror, every seed is
played twice with seats swapped, cancelling first-move and tile-luck bias so the
comparison reflects strategy, not luck.

Examples:
    python selfplay.py --games 50 --dict data/sample_words.txt
    python selfplay.py --games 200 --mirror --out data/selfplay.jsonl
"""
import argparse
import json
import time

from crossplay.engine.dictionary import Dictionary
from crossplay.game.state import GameState
from crossplay.leaderboard import Leaderboard
from crossplay.leaderboard_report import render_standings
from crossplay.strategy.registry import AGENTS, build_agent


def play_game(agents, agent_names, seed, *, game_id, mirror, log):
    """Play one game; append decision records to `log`. Returns a summary dict."""
    state = GameState.new(n_players=len(agents), seed=seed)
    turn_no = 0
    while not state.is_over():
        seat = state.turn
        rack = list(state.rack(seat))
        move = agents[seat].choose_move(state.board, rack)
        if log is not None:
            log.append({
                "type": "decision",
                "game_id": game_id, "seed": seed, "mirror": mirror,
                "seat": seat, "agent": agent_names[seat], "turn_no": turn_no,
                "board": [row[:] for row in state.board.grid],
                "rack": rack,
                "bag_remaining": state.bag.remaining(),
                "scores": list(state.scores),
                "action": "pass" if move is None else "play",
                "move": move,
                "move_score": 0 if move is None else move["score"],
            })
        if move is None:
            state.pass_turn(seat)
        else:
            state.apply_move(move, seat)
        turn_no += 1

    final = state.final_scores()
    winner = state.winner()
    summary = {
        "type": "game", "game_id": game_id, "seed": seed, "mirror": mirror,
        "agents": list(agent_names),
        "final_scores": final,
        "winner_seat": winner,
        "winner_agent": agent_names[winner] if winner is not None else None,
        "turns": turn_no,
    }
    if log is not None:
        log.append(summary)
    return summary


def main():
    p = argparse.ArgumentParser(description="Crossplay self-play / A-B harness")
    p.add_argument("--games", type=int, default=20)
    p.add_argument("--seed", type=int, default=0, help="base seed; game g uses seed+g")
    p.add_argument("--dict", default="data/dictionary/nwl23.txt",
                   help="word list (falls back to data/sample_words.txt if missing)")
    p.add_argument("--agent-a", default="greedy", choices=list(AGENTS))
    p.add_argument("--agent-b", default="greedy", choices=list(AGENTS))
    p.add_argument("--mirror", action="store_true",
                   help="replay each seed with seats swapped to cancel bias")
    p.add_argument("--out", default=None, help="write JSONL decision+game log here")
    p.add_argument("--leaderboard", nargs="?", const="data/leaderboard.json", default=None,
                   help="accumulate Elo/ratings into this file (default data/leaderboard.json)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    try:
        dictionary = Dictionary.load(args.dict)
        dict_path = args.dict
    except FileNotFoundError:
        dict_path = "data/sample_words.txt"
        print(f"[!] {args.dict} not found — falling back to {dict_path}")
        dictionary = Dictionary.load(dict_path)

    agent_a = build_agent(args.agent_a, dictionary)
    agent_b = build_agent(args.agent_b, dictionary)

    board = Leaderboard.load(args.leaderboard) if args.leaderboard else None

    log = [] if args.out else None
    # Track A and B by seat position (robust even when both use the same label).
    wins_a = wins_b = ties = 0
    score_a_sum = score_b_sum = 0
    margins = []  # (A final) - (B final), per game
    n_games = 0

    t0 = time.time()
    for g in range(args.games):
        seed = args.seed + g
        # Arrangement: (seat agents, seat labels, seat index occupied by A, mirror?).
        # With --mirror, replay the same seed with A and B swapped between seats.
        arrangements = [((agent_a, agent_b), (args.agent_a, args.agent_b), 0, False)]
        if args.mirror:
            arrangements.append(((agent_b, agent_a), (args.agent_b, args.agent_a), 1, True))

        for agents, names, a_seat, mirror in arrangements:
            summary = play_game(agents, names, seed, game_id=n_games,
                                mirror=mirror, log=log)
            final = summary["final_scores"]
            a_final = final[a_seat]
            b_final = final[1 - a_seat]
            if board is not None:
                board.record_game(args.agent_a, args.agent_b, a_final, b_final)
            score_a_sum += a_final
            score_b_sum += b_final
            margins.append(a_final - b_final)
            if a_final > b_final:
                wins_a += 1
            elif b_final > a_final:
                wins_b += 1
            else:
                ties += 1
            n_games += 1

    elapsed = time.time() - t0

    if board is not None:
        run_label = f"{args.agent_a}-vs-{args.agent_b}:{n_games}g"
        board.snapshot(run=run_label)
        board.save(args.leaderboard)

    if args.out:
        with open(args.out, "w") as f:
            for rec in log:
                f.write(json.dumps(rec) + "\n")

    if not args.quiet:
        print(f"\n=== Self-play report ({n_games} games, {elapsed:.1f}s, dict={dict_path}) ===")
        print(f"A = {args.agent_a!r}   B = {args.agent_b!r}")
        print(f"A wins: {wins_a}   B wins: {wins_b}   ties: {ties}")
        print(f"avg score   A: {score_a_sum/n_games:6.1f}   "
              f"B: {score_b_sum/n_games:6.1f}")
        print(f"avg margin (A - B): {sum(margins)/len(margins):+.1f}")
        if args.out:
            print(f"wrote {len(log)} log records to {args.out}")
        if board is not None:
            print(f"\n{render_standings(board)}")
            print(f"updated leaderboard → {args.leaderboard}")


if __name__ == "__main__":
    main()
