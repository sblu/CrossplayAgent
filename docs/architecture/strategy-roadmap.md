# Strategy & Tuning Roadmap

Design notes for two threads of work: (1) stronger move-selection algorithms with
longer look-ahead, and (2) an automated parameter-tuning loop built on the arena.
This is a backlog/brainstorm to implement incrementally — every item is a new class
in `crossplay/strategy/` + a profile in `data/agents.json`, validated in the arena.

---

## Part 1 — Longer look-ahead move algorithms

Greedy (max score this turn) is **not** optimal — in computer Scrabble it's
substantially weaker than the next tier. The whole game is about **equity**, not
points: the value of a move is how much it improves your *expected final margin*,
not the points it scores now. `HeuristicAgent`'s `score + leave_weight * leave_value`
is already a hand-tuned approximation of equity.

Strength ladder (each rung historically beats the one below by a wide margin):

```
greedy (score only)
  → + leave equity (static)         ← heuristic is a hand-tuned version of this
    → + simulation / lookahead       ← the big jump; "Maven"-class play
      → + endgame solver
        → + inference (opponent modeling)
          → ML value net + ISMCTS    ← the ambitious ceiling
```

### Tier 0 — Empirical leave values (cheap, big)
Replace the hand-tuned `_LEAVE_VALUE` table with values **learned from self-play**:
run tens of thousands of games, and for each rack-leave record the average margin
it led to. Small change to `HeuristicAgent` (swap table → learned dict). The
arena+leaderboard proves it beats the hand table. **Do this first.**

### Tier 1 — Monte Carlo simulation (the real look-ahead)
The single biggest leap; essentially how Maven/Quackle play.

```
choose_move(board, rack):
    candidates = top ~15-20 moves by static eval (score + leave)   # cheap prefilter
    for each candidate:
        equity = 0
        repeat N times (rollouts):
            opp_rack = draw 7 from the unseen bag        # tiles not on board, not in my rack
            play candidate; opponent replies (greedy/static);
            optionally play my best reply too            # 2-ply
            equity += (my_points - opp_points) over those plies
        candidate.equity = equity / N
    return argmax equity
```

- **Reuses everything we have**: `generate_moves()`, the headless simulator,
  `Agent.choose_move`. A rollout is the existing engine playing itself.
- **Subsumes all the intuitions automatically**: good leaves emerge because racks
  that score well in rollouts get higher equity; **defense falls out for free**
  because a move that opens a TWS lets the sampled opponent punish it, dropping that
  candidate's equity.
- Already anticipated: `driver.py` sets `new_command_timeout=600` with a comment
  about "Monte Carlo computation."
- Compute knob: `candidates × rollouts × plies`. Start 2-ply, greedy rollout policy.

### Tier 2 — Board awareness + endgame solver
- **Hot-spot eval**: term for open premium squares weighted by reachability
  (cross-sets). Sharpens defense; values our own setup plays.
- **Endgame solver**: once the bag is empty the game is **perfect information**
  (both racks known = bag − board − my rack) → solve exactly with alpha-beta. Top
  engines gain real rating from perfect last-4–6 moves. Self-contained, high ROI.
- **Pre-endgame** (1–5 tiles left): tile-tracking; partial enumeration over sampling.

### Tier 3 — ML ceiling
Crux: Scrabble is **imperfect information** (hidden rack + bag), so vanilla
AlphaZero MCTS doesn't apply directly.
- **ISMCTS**: MCTS that determinizes hidden info per rollout and averages — the
  principled generalization of Tier 1.
- **Value/policy net via self-play**: (board, rack, margin, tiles-left) → expected
  final margin, used as the rollout cutoff. AlphaZero recipe adapted for hidden info.
- **Cheaper ML win**: a leave-equity network (Tier 0 as a small NN).
- **Inference**: model the opponent's rack from their behavior (no bingo → no clean
  7; dumped tiles → infer the keep) and bias the sampled racks.

### Intuition reality-check
- **"Hold high-point letters for premiums" — usually a trap.** Q/Z/J/X parked in the
  rack are often *negative* equity (clog the rack, kill bingos). Play big tiles
  promptly unless a premium is already reachable. The held-Z gambit pays only in
  specific reachable-TLS spots — the nuance simulation finds and a static rule misses.
- **"Hold for a specific letter / keep a stem" — correct (rack synergy).** Bingo-prone
  leaves (SATIRE/RETINA stems, blank, S) are worth more than the sum of their tiles.
- **"Don't open triples/doubles" — correct but secondary.** One term vs. your own
  equity; blind defense costs you. Simulation weighs it correctly.

### Recommended order
1. Empirical leave table (Tier 0).
2. `SimulationAgent` (Tier 1) — few-second 2-ply Monte Carlo.
3. Endgame solver (Tier 2).
4. Decide whether ISMCTS + value-net (Tier 3) is worth it.

---

## Part 2 — Automated parameter tuning (arena sweep)

Goal: agents take weights; sweep parameter combinations, play enough games to decide
statistically whether a candidate beats the leader, promote winners, move on. This is
**noisy game-program tuning** — same playbook as chess-engine testing (Fishtest,
CLOP, SPSA).

### Fix the statistics first — "100 games for 95%" is the wrong model
Games needed depends on **effect size**, not a constant. Margin of error on win rate
≈ `±1/√n`: at n=100 it's ±10%, so a true 55% rate is indistinguishable from 50% —
you'd promote noise. Resolving a 5pp edge needs ~800–1000 games. Three fixes:

1. **Score margin, not win/loss.** Point differential (continuous, paired t-test) has
   far lower variance than binary W/L → ~10× fewer games. `selfplay.py` already logs
   scores.
2. **Common Random Numbers (CRN) — biggest trick.** Play candidate and leader on the
   **same bag orders**; draw luck cancels on a paired basis. ~10× fewer games.
   *Requires a `seed` threaded through the simulator's bag shuffle — the one piece of
   plumbing to add, and everything depends on it.*
3. **SPRT (sequential testing) — "play until confident," done right.** Stop as soon as
   there's enough evidence to accept/reject, with bounded error. Strong candidates
   confirm in tens of games; close calls burn more. This is the principled version of
   the original idea.

### Traps
- **Multiple comparisons**: sweeping 50 combos at 95% → ~2–3 false positives by
  chance. Treat as selection/ranking, raise the bar (Bonferroni), and **re-validate
  the apparent winner** in a fresh batch before promoting.
- **Non-transitivity**: A>B>C>A is possible, so "beats the leader" isn't a total
  order. Use Elo (probabilistic) + a **pool/gauntlet** (greedy, heuristic, past
  champions), not a single-opponent ladder — otherwise you learn to exploit one foe.

### Search strategy (don't grid-sweep blindly)
| Method | When it fits |
|---|---|
| Grid | 1–2 params, intuition |
| Random search | a few params, some irrelevant |
| **CMA-ES** | a continuous weight vector — gradient-free, noise-robust |
| SPSA | many params (Stockfish uses it) |
| **CLOP / Bayesian (Optuna/TPE)** | very expensive evals; models the surface |

Sweet spot here (expensive evals, few continuous weights): **CLOP or CMA-ES.** CLOP
was literally designed for noisy game-program parameter tuning.

### Codebase mapping / what to build
- Profiles already carry `params` → generate `heuristic@lw=0.8`, … programmatically.
- `selfplay.py` is the match runner. **Use the headless harness at full speed
  (parallelized), not the live-rendered arena** — arena is for watching, sweep is for
  throughput.
- Build `tools/sweep.py` (or arena "tuning mode"): takes a search space → runs
  CRN-paired, score-margin games vs the gauntlet under SPRT → promotes survivors into
  `agents.json` + the Elo pool → drives the next candidate via CMA-ES/CLOP.
- Add the **seed** to the simulator (do this first).
- Dashboard "Tuning" view: stream the frontier (candidates, games played, best, SPRT
  verdicts).

### Recommended order
1. Add the simulator **seed** (unlocks CRN).
2. Match evaluator: **CRN-paired + score-margin + SPRT** vs a gauntlet (reusable core).
3. Sweep driver: start grid/random, then CMA-ES/CLOP.
4. Promote into the Elo pool; re-validate before crowning.

**Caveat:** tuning happens against the simulator's opponents, so you optimize to beat
*them* — the final arbiter is still the on-device live game (last validation step,
per the dev-loop doc).

### Follow-up — make the leaderboard Elo trustworthy

Observed in practice: **heuristic showed a higher Elo (1853) than greedy (1755) despite
a losing head-to-head record vs greedy (46.7% win rate over ~7.3k games).** That's not
a bug — it exposes three properties of the current `crossplay/leaderboard.py` Elo worth
fixing before we lean on it to promote tuned agents:

1. **Elo ignores margin — it's pure W/L/tie.** `record_game()` sets `outcome ∈
   {1.0, 0.5, 0.0}` from the score comparison only; the point gap feeds the displayed
   `avg_margin` but never the rating. A 400-point blowout and a 1-point win move Elo
   identically. Part 2's evaluator should score on **margin** (paired t-test), so
   consider a margin-aware rating (e.g. Elo with a score-differential outcome, or fit
   ratings from margins directly) if the leaderboard is to reflect strength, not just
   win counts.
2. **Rating inflation from farming weak opponents.** Greedy beat the `weak` bot 56–0,
   which floated its rating to a ~2094 peak; it then bled down to 1755 over thousands of
   near-even games vs heuristic (an over-rated player who only ties the field loses
   points). Beating a far-weaker agent should barely move the rating (it already
   nearly does), but the *pool composition* skews standings — reinforces the
   **gauntlet/pool** point above, and argues for down-weighting or excluding lopsided
   pairings.
3. **Path dependence + high K = noisy ordering.** With `K=32`, a ~150-game hot streak
   spiked heuristic +80. For a true 53/47 split the Elo equilibrium gap is only ~20
   points, so the current ordering is **within noise** — the two are ~equal and the
   lifetime win rate is the more stable estimate. Lower `K` (or an adaptive/decaying K),
   and judge close pairs by a large fixed head-to-head batch (or SPRT) rather than the
   live, jumpy Elo.

**Concrete asks:** (a) lower/adaptive `K`; (b) optional margin-aware rating update;
(c) guard against weak-opponent inflation in the pool; (d) surface a "confidence"
/ games-played and a recent-vs-lifetime split in the leaderboard view so a streak
isn't mistaken for a ranking. Small, self-contained changes to `leaderboard.py` +
the dashboard leaderboard view.
