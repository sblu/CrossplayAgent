# Device Abstraction & Self-Play — Design

## Motivation

The valuable, hard part of this project is the **Crossplay-playing algorithm**. The
phone is just a means of getting the bot's moves into a real game. Today the bot
is welded to one specific delivery mechanism (an iPhone driven over Appium/XCUITest
with hard-coded @3x pixel coordinates), which:

- blocks us on hardware/OS compatibility (the current iOS/Xcode/Mac mismatch),
- makes the bot impossible to exercise without a physical device, and
- prevents the bot from playing *itself* for testing and training data.

This design decouples the **brain** (board reading → move choice) from the
**hands & eyes** (a specific device), behind a small, game-level interface. Any
number of backends can implement that interface:

- **iOS** — the existing Appium/XCUITest path (refactored, not rewritten).
- **Android** — Appium/UiAutomator2. Note: the Crossplay app runs on the
  **Android emulator**, which runs on this Intel Mac — a path that sidesteps the
  physical-device problem entirely.
- **Simulated** — a pure-Python implementation of Crossplay's rules. No device,
  no app. Enables self-play: bot-vs-bot, version-vs-version, and self-play
  training-data generation.

## What already supports this

These layers are **already device-agnostic** and need no changes:

- `crossplay/engine/board.py` — board, premium squares, letter values, tile
  distribution (100 tiles), cell types.
- `crossplay/engine/scorer.py` — `score_move()` incl. cross-words + 40-pt bingo.
- `crossplay/engine/move_generator.py` — `generate_moves(board, rack, dict)`.
- `crossplay/engine/dictionary.py` — word/prefix lookups.
- `crossplay/strategy/base.py` — `Agent.choose_move(board, rack) -> move | None`.
- `crossplay/strategy/greedy.py` — a concrete agent.

The simulator **reuses all of these** rather than reimplementing the rules.

What is iOS-coupled and must move behind the interface:

- `main.py` — the whole turn loop is laced with iOS specifics (accessibility-tree
  XML parsing, @3x pixel math, `"Play"`/`"More"`/`"Okay"` button names, pinch
  zoom, keepalive taps, popup dismissal).
- `crossplay/automation/` — Appium driver, taps/drags, screenshots.
- `crossplay/vision/` — accessibility-tree + image-based board/rack parsing.

## Canonical data types

A single, device-independent move schema flows between brain and hands. It already
exists as the dict produced by `move_generator` / consumed by `scorer`:

```python
Move = {
    "word": str,            # full word incl. existing board tiles
    "row": int, "col": int, # start cell of the word
    "horizontal": bool,
    "tiles_played": list[int],   # indices into `word` of NEW tiles from the rack
    "blanks": dict[int, str],    # {word_idx: assigned_letter} for blanks, else {}
    "score": int,
}
```

We keep this dict as the canonical form (zero churn for engine/scorer). A thin
`Move` dataclass with `.to_dict()/.from_dict()` is an optional later polish.

The interface speaks in two game-level structures:

```python
@dataclass
class Observation:
    board: list[list[str | None]]   # 15x15 grid, letters or None
    rack:  list[str | None]         # up to 7 entries; '?' = blank
    is_our_turn: bool
    game_over: bool
```

## The port: `CrossplayClient`

```python
# crossplay/client/base.py
class CrossplayClient(ABC):
    def __enter__(self) -> "CrossplayClient": ...   # connect / start a game
    def __exit__(self, *exc) -> None: ...           # disconnect / teardown

    @abstractmethod
    def wait_for_turn(self, timeout: float = 300) -> bool:
        """Block until it's our move. Backend handles its own keep-alive,
        opponent simulation, popups, etc. False on timeout/game-over."""

    @abstractmethod
    def observe(self) -> Observation:
        """Current board + rack + turn/over flags, in game terms."""

    @abstractmethod
    def play_move(self, move: dict) -> bool:
        """Execute a move (place tiles, assign blanks, submit). False on failure."""

    @abstractmethod
    def pass_turn(self) -> None: ...
```

Everything device-specific — pixels, accessibility XML, popups, pinch-zoom,
keepalive, opponent simulation — lives *inside* an implementation and never leaks
into the loop or the agent.

## The backend-agnostic loop

`main.py` collapses to roughly this (behavior-preserving for iOS):

```python
def run(client: CrossplayClient, agent: Agent):
    with client:
        while True:
            if not client.wait_for_turn():
                if client.observe().game_over:
                    break
                continue                      # timeout/retry policy
            obs = client.observe()
            if obs.game_over:
                break
            board = Board(); board.load_from_grid(obs.board)
            rack  = [t for t in obs.rack if t]
            move  = agent.choose_move(board, rack)
            if move is None:
                client.pass_turn()
            else:
                client.play_move(move)
```

The agent and loop are now identical across iOS, Android, and simulation.

## Adapters

### `ios_client.py`
All current `main.py` iOS logic moves here verbatim, behind the interface:
`_is_our_turn`/`_game_is_over` (accessibility tree), `_dismiss_popups`,
`_wait_for_our_turn` + keepalive taps, `_execute_move` (drag tiles, `_select_blank_letter`),
`_pass_turn`, submit tap. Uses `crossplay/automation` + `crossplay/vision`. The
W3C tap/drag in `automation/input.py` are already platform-neutral.

### `android_client.py`
Appium UiAutomator2. Same shape as the iOS client, different perception:
Android's UiAutomator XML (`bounds="[x,y][x2,y2]"`, `content-desc`, `text`) instead
of XCUITest XML. Taps/drags reuse the existing W3C `input.py` unchanged. Board/rack
bounds come from a small Android calibration. **Runs against the Android emulator on
this Mac**, so it needs no physical device.

### `sim_client.py`
Wraps the simulator (below) to present the single-seat `CrossplayClient` for "our"
seat, auto-playing the opponent between our turns:
- `wait_for_turn()` → step the opponent agent until it's our seat (or game over).
- `observe()` → build `Observation` from `GameState` for our seat.
- `play_move()` → apply our move to `GameState`.

This lets the **exact same `run()` loop** execute headless with no device — a
real integration test of the loop and a zero-hardware smoke test.

### `factory.py`
`build_client(config) -> CrossplayClient` selects iOS / Android / sim from an env
var (`CROSSPLAY_BACKEND`) or `--backend` flag.

## The simulator: `crossplay/game/`

The authoritative, headless implementation of a full Crossplay game. Reuses the
engine for all rules/scoring.

```python
# game/bag.py
class TileBag:
    def __init__(self, seed: int | None = None): ...   # seedable → reproducible
    def draw(self, n: int) -> list[str]: ...
    def remaining(self) -> int: ...
# Built from board.TILE_DISTRIBUTION (incl. 3 blanks → '?').

# game/state.py
@dataclass
class GameState:
    board: Board
    bag: TileBag
    racks: list[list[str]]     # one rack per seat
    scores: list[int]
    turn: int                  # seat to move
    passes_in_row: int

    @classmethod
    def new(cls, n_players=2, seed=None) -> "GameState": ...
    def rack(self, seat: int) -> list[str]: ...
    def apply_move(self, move: dict, seat: int) -> None:   # validate→place→score→refill→advance
    def pass_turn(self, seat: int) -> None:
    def is_over(self) -> bool:   # bag empty & a rack empty, OR 2*N consecutive passes
    def final_scores(self) -> list[int]:   # subtract leftover rack values; bonus on empty rack
```

Move legality is validated by reusing engine primitives (tiles come from the rack,
word fits/connects, cross-words valid) — cheap insurance against buggy agents and
the contract for adversarial testing. Seeding the bag makes games reproducible,
which is essential for *fair* A/B comparisons (paired/mirror seeds remove
tile-luck and first-move bias).

## Self-play harness: `selfplay.py`

For bulk evaluation and training data, bypass the single-seat client and drive both
seats directly against `GameState` (fast, symmetric, fully logged):

```
for g in range(N):
    state  = GameState.new(2, seed=base+g)
    agents = [A, B]                         # any two Agent instances/versions
    while not state.is_over():
        seat = state.turn
        move = agents[seat].choose_move(state.board, state.rack(seat))
        log(game=g, seat=seat, board, rack, move, move_score)
        state.apply_move(move, seat) if move else state.pass_turn(seat)
    finalize(state); write per-game summary
report: win-rate, avg score, avg margin   # optionally swap seats per seed (mirror)
```

**Training-data format** — JSONL, one decision per line:

```json
{"game_id": 0, "seed": 1234, "seat": 0, "turn_no": 3,
 "board": [...], "rack": ["A","E","I",...], "bag_remaining": 58,
 "scores": [120, 96], "legal_move_count": 47,
 "chosen": { ...Move... }, "chosen_score": 31}
```

Plus a per-game summary line (final scores, winner, total turns, seed). This
supports: A/B win-rate eval of two strategy versions; supervised imitation
(predict the expert move from state); and RL (state, action, reward = final
margin).

## Proposed file layout (additive; engine/strategy untouched)

```
crossplay/
  engine/            # UNCHANGED
  strategy/          # UNCHANGED (+ future agents)
  game/              # NEW — simulator (bag, state, rules) — reuses engine
  client/            # NEW — port + adapters
    base.py          #   CrossplayClient, Observation
    ios_client.py    #   refactored out of main.py
    android_client.py#   Appium UiAutomator2 (emulator-friendly)
    sim_client.py    #   single-seat wrapper over GameState
    factory.py       #   backend selection
  automation/        # iOS low-level (used by ios_client)
  vision/            # iOS perception (used by ios_client)
main.py              # thin: build_client + run(); backend-agnostic
selfplay.py          # NEW — A-vs-B tournaments + JSONL logging
```

## Migration phases (each independently testable, low-risk)

- **P0** — Add `client/base.py` (`Observation`, `CrossplayClient`). No behavior change.
- **P1** — Extract `IOSClient` from `main.py`; `main.py` becomes the thin loop. iOS
  behavior preserved; logic unit-testable without a device.
- **P2** — Build `game/` (bag, state, rules) on top of the engine; unit tests for
  scoring/refill/end-conditions/reproducibility.
- **P3** — `SimClient`; run the **same** `run()` loop headless against the sim
  (integration test, no hardware).
- **P4** — `selfplay.py` + JSONL logging + A/B report.
- **P5** — `AndroidClient` against the Android emulator (optionally retires the
  physical-device dependency).

P0–P4 need **no hardware** and deliver immediate value: a testable bot, self-play,
and training data. P5 can unblock real-game play on this Mac via the emulator.
```
