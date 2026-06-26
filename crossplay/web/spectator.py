"""Reusable live self-play spectator: runs simulated games in a background thread
and renders a CrossPlay-styled board that updates move-by-move.

`attach_spectator()` mounts the page + JSON-state routes onto any Flask app and
starts the game loop, so both the standalone `tools/live_server.py` and the unified
`tools/dashboard.py` share one implementation.
"""
import threading
import time

from flask import jsonify, render_template_string

from crossplay.engine.board import Board, CellType, LETTER_VALUES
from crossplay.game.state import GameState
from crossplay.leaderboard import Leaderboard
from crossplay.strategy.registry import AGENTS

_PREMIUM_CODE = {
    CellType.TRIPLE_WORD: "3W", CellType.DOUBLE_WORD: "2W",
    CellType.TRIPLE_LETTER: "3L", CellType.DOUBLE_LETTER: "2L",
    CellType.NORMAL: "",
}


def premium_grid() -> list[list[str]]:
    b = Board()
    return [[_PREMIUM_CODE[b.cell_type(r, c)] for c in range(15)] for r in range(15)]


def _move_cells(move: dict) -> list[list[int]]:
    cells = []
    for idx in move["tiles_played"]:
        r = move["row"] if move["horizontal"] else move["row"] + idx
        c = move["col"] + idx if move["horizontal"] else move["col"]
        cells.append([r, c])
    return cells


class Spectator:
    """Owns the background game loop and the latest published state."""

    def __init__(self, agent_specs, dictionary, *, delay=1.2, seed=0, leaderboard_path=None):
        self.names = [agent_specs[0], agent_specs[1]]
        self._agents = [AGENTS[agent_specs[0]](dictionary), AGENTS[agent_specs[1]](dictionary)]
        self._delay = delay
        self._seed = seed
        self._leaderboard_path = leaderboard_path
        self._lock = threading.Lock()
        self._state = {"ready": False}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _publish(self, state, last_cells, status, game_no, move_no, over=False, final=None):
        with self._lock:
            self._state = {
                "ready": True,
                "board": [row[:] for row in state.board.grid],
                "blanks": [list(c) for c in state.blank_cells],
                "racks": [list(state.rack(0)), list(state.rack(1))],
                "scores": list(state.scores),
                "names": list(self.names),
                "turn": state.turn,
                "last_cells": last_cells,
                "status": status,
                "game_no": game_no,
                "move_no": move_no,
                "bag": state.bag.remaining(),
                "over": over,
                "final": list(final) if final else None,
            }

    def run_loop(self):
        board = Leaderboard.load(self._leaderboard_path) if self._leaderboard_path else None
        game_no = 0
        while True:
            game_no += 1
            state = GameState.new(n_players=2, seed=self._seed + game_no)
            self._publish(state, [], "New game — opening move…", game_no, 0)
            time.sleep(self._delay)

            move_no = 0
            while not state.is_over():
                seat = state.turn
                move = self._agents[seat].choose_move(state.board, state.rack(seat))
                move_no += 1
                if move is None:
                    state.pass_turn(seat)
                    self._publish(state, [], f"{self.names[seat]} passed", game_no, move_no)
                else:
                    cells = _move_cells(move)
                    state.apply_move(move, seat)
                    self._publish(
                        state, cells,
                        f"{self.names[seat]} played {move['word']} for {move['score']} points",
                        game_no, move_no)
                time.sleep(self._delay)

            final = state.final_scores()
            winner = state.winner()
            result = "tie" if winner is None else f"{self.names[winner]} wins"
            self._publish(state, [], f"Game over — {result}  ({final[0]} – {final[1]})",
                          game_no, move_no, over=True, final=final)
            if board is not None:
                board.record_game(self.names[0], self.names[1], final[0], final[1])
                board.snapshot(run=f"live:{self.names[0]}-vs-{self.names[1]}")
                board.save(self._leaderboard_path)
            time.sleep(max(self._delay * 3, 2.5))

    def start(self):
        threading.Thread(target=self.run_loop, daemon=True).start()
        return self


def attach_spectator(app, *, page_route, state_route, agent_specs, dictionary,
                     delay=1.2, seed=0, leaderboard_path=None, nav_html=""):
    """Register the spectator page + state routes on `app` and start the loop."""
    spec = Spectator(agent_specs, dictionary, delay=delay, seed=seed,
                     leaderboard_path=leaderboard_path)

    values = {k: v for k, v in LETTER_VALUES.items() if k != ' '}

    def page():
        return render_template_string(
            _PAGE, premium=premium_grid(), values=values,
            state_url=state_route, nav=nav_html,
            title=f"{spec.names[0]} vs {spec.names[1]}",
        )

    def state():
        return jsonify(spec.snapshot())

    app.add_url_rule(page_route, f"spectator_page_{page_route}", page)
    app.add_url_rule(state_route, f"spectator_state_{state_route}", state)
    spec.start()
    return spec


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crossplay — Live</title>
<style>
  :root {
    --tile: #3f5bb0; --tile-new: #6b86d6; --tile-text: #fff;
    --cell: #fbfbf7; --line: #e6e6dd; --bg: #f4f4ef;
    --c2l: #4a90d9; --c3l: #2faa6a; --c2w: #e0a426; --c3w: #c63f93;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg);
         margin: 0; padding: 1rem; color: #222; display: flex; flex-direction: column;
         align-items: center; }
  .wrap { width: min(96vw, 460px); }
  .scores { display: flex; justify-content: space-between; align-items: center;
            background: #fff; border-radius: 14px; padding: .7rem 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .player { text-align: center; flex: 1; }
  .player .name { font-size: .8rem; color: #888; text-transform: capitalize; }
  .player .pts { font-size: 1.6rem; font-weight: 700; }
  .player.turn { color: var(--tile); }
  .player.turn .name { color: var(--tile); font-weight: 600; }
  .vs { color: #bbb; font-weight: 600; padding: 0 .6rem; }
  .status { text-align: center; margin: .7rem 0; font-size: .95rem; min-height: 1.2em; }
  .status b { color: #111; }
  .meta { text-align: center; color: #999; font-size: .75rem; margin-bottom: .6rem; }
  .board { display: grid; grid-template-columns: repeat(15, 1fr); gap: 2px;
           background: var(--line); border: 2px solid var(--line); border-radius: 8px;
           aspect-ratio: 1; }
  .cell { background: var(--cell); position: relative; display: flex;
          align-items: center; justify-content: center; border-radius: 2px;
          font-size: clamp(5px, 1.4vw, 9px); font-weight: 700; }
  .prem-2L { color: var(--c2l); } .prem-3L { color: var(--c3l); }
  .prem-2W { color: var(--c2w); } .prem-3W { color: var(--c3w); }
  .star { color: #c9a227; font-size: 1.3em; }
  .tile { position: absolute; inset: 0; background: var(--tile);
          color: var(--tile-text); border-radius: 3px; display: flex;
          align-items: center; justify-content: center;
          font-size: clamp(8px, 2.3vw, 15px); font-weight: 700; }
  .tile.new { background: var(--tile-new); box-shadow: 0 0 0 2px #fff inset; }
  .tile.blank { font-style: italic; opacity: .92; }
  .tile .v { position: absolute; right: 1px; bottom: 0; font-size: .5em;
             font-weight: 600; }
  .racks { margin-top: .9rem; display: flex; flex-direction: column; gap: .5rem; }
  .rack { background: #233; border-radius: 10px; padding: .4rem; }
  .rack .lbl { color: #9bb; font-size: .7rem; margin: 0 .2rem .25rem;
               text-transform: capitalize; }
  .rack.turn { box-shadow: 0 0 0 2px var(--tile-new); }
  .rtiles { display: grid; grid-template-columns: repeat(7, 1fr); gap: .35rem; }
  .rtile { background: var(--tile); color: #fff; border-radius: 6px; aspect-ratio: 1;
           display: flex; align-items: center; justify-content: center;
           font-weight: 700; position: relative; font-size: clamp(11px, 3.4vw, 20px); }
  .rtile.empty { background: #2c3d3d; }
  .rtile .v { position: absolute; right: 3px; bottom: 1px; font-size: .55em; }
</style>
</head>
<body>
<div class="wrap">
  {{ nav | safe }}
  <div class="scores">
    <div class="player" id="p0"><div class="name"></div><div class="pts"></div></div>
    <div class="vs">vs</div>
    <div class="player" id="p1"><div class="name"></div><div class="pts"></div></div>
  </div>
  <div class="status" id="status"></div>
  <div class="meta" id="meta"></div>
  <div class="board" id="board"></div>
  <div class="racks">
    <div class="rack" id="rack0"><div class="lbl"></div><div class="rtiles"></div></div>
    <div class="rack" id="rack1"><div class="lbl"></div><div class="rtiles"></div></div>
  </div>
</div>
<script>
const STATE_URL = {{ state_url | tojson }};
const PREMIUM = {{ premium | tojson }};
const VALUES = {{ values | tojson }};
const premClass = {"2L":"prem-2L","3L":"prem-3L","2W":"prem-2W","3W":"prem-3W"};

const boardEl = document.getElementById("board");
const cells = [];
for (let r = 0; r < 15; r++) for (let c = 0; c < 15; c++) {
  const d = document.createElement("div");
  d.className = "cell";
  boardEl.appendChild(d);
  cells.push(d);
}

function tileHtml(letter, value, cls) {
  const v = value === 0 ? "" : `<span class="v">${value}</span>`;
  return `<div class="tile ${cls}">${letter}${v}</div>`;
}

function render(s) {
  for (let i = 0; i < 2; i++) {
    const p = document.getElementById("p" + i);
    p.querySelector(".name").textContent = s.names[i];
    p.querySelector(".pts").textContent = s.scores[i];
    p.classList.toggle("turn", !s.over && s.turn === i);
  }
  document.getElementById("status").innerHTML = "<b>" + s.status + "</b>";
  document.getElementById("meta").textContent =
    `game ${s.game_no} · move ${s.move_no} · ${s.bag} tiles in bag`;

  const blanks = new Set((s.blanks || []).map(b => b[0] + "," + b[1]));
  const news = new Set((s.last_cells || []).map(b => b[0] + "," + b[1]));
  for (let r = 0; r < 15; r++) for (let c = 0; c < 15; c++) {
    const el = cells[r * 15 + c];
    const key = r + "," + c;
    const letter = s.board[r][c];
    if (letter) {
      const isBlank = blanks.has(key);
      const cls = (news.has(key) ? "new " : "") + (isBlank ? "blank" : "");
      el.innerHTML = tileHtml(letter, isBlank ? 0 : (VALUES[letter] || 0), cls);
    } else {
      const prem = PREMIUM[r][c];
      if (r === 7 && c === 7) el.innerHTML = '<span class="star">★</span>';
      else if (prem) el.innerHTML = `<span class="${premClass[prem]}">${prem}</span>`;
      else el.innerHTML = "";
    }
  }

  for (let i = 0; i < 2; i++) {
    const rk = document.getElementById("rack" + i);
    rk.querySelector(".lbl").textContent = s.names[i] + "  ·  " + s.scores[i];
    rk.classList.toggle("turn", !s.over && s.turn === i);
    const slots = rk.querySelector(".rtiles");
    let html = "";
    for (let j = 0; j < 7; j++) {
      const t = s.racks[i][j];
      if (t == null) { html += '<div class="rtile empty"></div>'; continue; }
      const blank = t === "?";
      const v = blank ? "" : `<span class="v">${VALUES[t] || 0}</span>`;
      html += `<div class="rtile">${blank ? "·" : t}${v}</div>`;
    }
    slots.innerHTML = html;
  }
}

async function poll() {
  try {
    const s = await (await fetch(STATE_URL)).json();
    if (s.ready) render(s);
  } catch (e) {}
}
poll();
setInterval(poll, 500);
</script>
</body>
</html>
"""
