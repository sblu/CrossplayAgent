# Adding an Algorithm

This guide shows how to build a new move-choosing algorithm, register it, test it
against the leaderboard, and promote it to a real device. Read
[Getting Started](getting-started.md) first if you haven't.

---

## 1. The big picture: config vs. logic

There are two layers, and it's important to keep them straight:

```
data/agents.json              profile  →  type + params      (CONFIG — no logic)
        │
crossplay/strategy/registry.py   type   →  Agent class        (the wiring)
        │
crossplay/strategy/<file>.py     class.choose_move(...)        (THE LOGIC)
```

- **`data/agents.json`** names *profiles*. A profile picks an implementation
  `type` and optional constructor `params`. This is where you tune an existing
  algorithm — **no code change**.
- **`crossplay/strategy/registry.py`** maps a `type` string to an `Agent` class.
- **`crossplay/strategy/<your_file>.py`** is where the actual decision logic
  lives. This is the part worth your effort.

`build_configured_agent(name, dictionary)` (in `crossplay/strategy/agent_config.py`)
walks that chain at runtime: read the profile → look up the class → construct it
with the params.

## 2. The Agent contract

Every algorithm subclasses `Agent` (`crossplay/strategy/base.py`) and implements
one method:

```python
def choose_move(self, board: Board, rack: list[str],
                exclude: set | None = None) -> dict | None:
    ...
```

- **`board`** — the current `Board` (15×15). `board.get(r, c)` returns a letter or
  `None`; `board.cell_type(r, c)` gives the premium-square type.
- **`rack`** — your tiles as a list of letters; a blank is `'?'`.
- **`exclude`** — a set of `move_key(...)` tuples to skip: moves already tried and
  rejected by the device this turn. Filter them out (see below).
- **return** — a **move dict**, or `None` if you have no legal play (the runner
  then passes/swaps).

You almost never enumerate moves yourself — call the shared generator:

```python
from crossplay.engine.move_generator import generate_moves
moves = generate_moves(board, rack, self._dictionary)   # list[move dict]
```

### The move dict

`generate_moves` returns dicts with this shape (don't construct these by hand):

| key | meaning |
|-----|---------|
| `word` | the full word formed (incl. tiles already on the board) |
| `row`, `col` | starting cell of the word |
| `horizontal` | `True` = across, `False` = down |
| `tiles_played` | indices into `word` that come **from your rack** this turn |
| `blanks` | `{word_index: assigned_letter}` for any blanks used (`{}` if none) |
| `score` | points this move scores, premiums included |

Your job in `choose_move` is just to **pick one** of these.

## 3. Worked example: the HeuristicAgent

`crossplay/strategy/heuristic.py` is the reference template. Greedy maximizes only
`move["score"]`; the heuristic looks one step ahead by also valuing the **leave**
(the tiles you keep):

```
evaluation = points_this_turn  +  leave_weight * value_of_tiles_left_on_rack
```

```python
def choose_move(self, board, rack, exclude=None):
    moves = generate_moves(board, rack, self._dictionary)
    if exclude:
        moves = [m for m in moves if move_key(m) not in exclude]
    if not moves:
        return None
    # tie-break by raw score so behaviour is deterministic
    return max(moves, key=lambda m: (self._evaluate(m, rack), m["score"]))
```

`_evaluate` adds `leave_weight * _leave_value(leave)` to the score; `_leave_value`
sums a static per-tile "keep" table and penalizes duplicate letters. Crucially,
`leave_weight` is a **constructor parameter** — so you can create several
heuristic profiles at different aggressiveness purely from `agents.json`.

## 4. Step-by-step: add a new algorithm

Say we want a `defensive` agent that avoids opening triple-word squares.

### a. Write the class

Create `crossplay/strategy/defensive.py`:

```python
from crossplay.engine.board import Board, CellType
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.strategy.base import Agent, move_key


class DefensiveAgent(Agent):
    def __init__(self, dictionary: Dictionary, risk_penalty: float = 8.0):
        self._dictionary = dictionary
        self._risk_penalty = risk_penalty          # tunable via agents.json

    def choose_move(self, board: Board, rack: list[str],
                    exclude: set | None = None) -> dict | None:
        moves = generate_moves(board, rack, self._dictionary)
        if exclude:
            moves = [m for m in moves if move_key(m) not in exclude]
        if not moves:
            return None
        return max(moves, key=lambda m: m["score"] - self._risk_penalty * self._risk(board, m))

    def _risk(self, board: Board, move: dict) -> float:
        # ... count nearby exposed triple-word squares, etc.
        return 0.0
```

### b. Register the type

Add it to `crossplay/strategy/registry.py`:

```python
from crossplay.strategy.defensive import DefensiveAgent

AGENTS = {
    "greedy": GreedyAgent,
    "heuristic": HeuristicAgent,
    "weak": WeakAgent,
    "defensive": DefensiveAgent,        # ← new
}
```

That one line makes `defensive` selectable everywhere — `selfplay.py`, the arena,
and the device.

### c. Add a profile (and tune it) in `data/agents.json`

```json
{
  "defensive":      { "type": "defensive", "params": { "risk_penalty": 8.0 },
                      "description": "Greedy, minus a penalty for risky openings." },
  "defensive-tame": { "type": "defensive", "params": { "risk_penalty": 3.0 },
                      "description": "A milder defensive variant." }
}
```

Two profiles, one class — the value of separating config from logic. Tuning
`risk_penalty` from now on needs **no code change**.

> Reminder: the **logic** is in `crossplay/strategy/defensive.py`. `agents.json`
> only chooses the type and the numbers.

## 5. Test it

### Quick batch (CLI)

```bash
python selfplay.py --agent-a defensive --agent-b greedy --games 200 \
    --leaderboard data/leaderboard.json
```

`--mirror` replays each seed with sides swapped to cancel first-move advantage;
`--out runs/defensive.jsonl` logs every decision for analysis.

### In the dashboard (Arena)

Start the dashboard, open **/arena**, choose **defensive** vs **greedy**, press
**Start**. Watch the head-to-head W/L climb and check **/leaderboard** for Elo and
average margin. (The arena and leaderboard both read `data/agents.json`, so your
new profiles appear in the dropdowns automatically.)

The bar to clear: **consistently beat greedy**, the usual leaderboard leader, over
a meaningful number of games.

## 6. Promote to a live game

Once it wins in the arena:

1. Open **/device-live**, expand **Device configuration**, and pick your algorithm
   from the dropdown (this writes `algorithm` into `calibration.json`).
2. With the phone connected and the game on your turn, press **Start bot**.

Equivalently from the CLI: `CROSSPLAY_AGENT=defensive CROSSPLAY_BACKEND=android python main.py`.

## 7. Tips

- **Always honour `exclude`** — on a real device a move can be rejected (an OCR
  misread, an illegal-looking play); the runner re-asks with that move excluded,
  so skipping them prevents an infinite retry loop.
- **Break ties deterministically** (e.g. `key=(evaluation, score)`) so behaviour is
  reproducible across runs and seeds.
- **Prefer a param over a constant.** If you're tempted to hard-code a weight, make
  it a constructor arg instead — then you can sweep it from `agents.json` and let
  the arena tell you the best value.
- **Add a unit test** under `tests/strategy/` for any non-trivial scoring logic;
  run `python -m pytest -q`.
- **Mine the self-play logs.** `selfplay.py --out` writes every decision as JSONL —
  good raw material for learning leave values instead of hand-tuning them.

## See also

- [Getting Started](getting-started.md) — setup, dashboard, the dev loop.
- [Device abstraction — design](architecture/device-abstraction.md) — how the
  brain/hands split works.
- [Android setup](architecture/android-setup.md) — driving a real phone.
