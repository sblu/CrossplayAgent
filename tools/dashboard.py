#!/usr/bin/env python3
"""Unified Crossplay dashboard — one server, links to every view.

Hosts, on a single port:
  * Live self-play spectator   (/sim)        — watch simulated games move-by-move
  * Leaderboard + charts       (/leaderboard) — self-play standings and progress
  * Device debug tools         (/inspector, /templates, /calibrate, /live)
    — mounted from tools/debug_server.py (these need a connected iPhone)

    python tools/dashboard.py --a greedy --b weak --delay 1.0
    open http://localhost:8765
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template_string, request

from crossplay.client.device_config import DeviceConfig
from crossplay.engine.dictionary import Dictionary
from crossplay.leaderboard import Leaderboard
from crossplay.leaderboard_report import render_html_report
from crossplay.vision.calibration import Calibration
from crossplay.web.spectator import AGENTS, attach_spectator

# Shared top nav injected into the views we own.
NAV = """
<nav style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;
            font:600 13px/1 -apple-system,system-ui,sans-serif">
  <a href="/" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">⌂ Home</a>
  <a href="/sim" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Live Game</a>
  <a href="/leaderboard" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Leaderboard</a>
  <a href="/device-setup" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Device Setup</a>
</nav>"""

_LANDING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crossplay Dashboard</title>
<style>
  body { font-family:-apple-system,system-ui,sans-serif; background:#f4f4ef; color:#222;
         margin:0; padding:2rem; }
  .wrap { max-width:680px; margin:0 auto; }
  h1 { margin:0 0 .25rem; } .sub { color:#888; margin:0 0 1.5rem; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1rem; }
  a.card { display:block; text-decoration:none; color:inherit; background:#fff;
           border-radius:12px; padding:1.1rem 1.2rem; box-shadow:0 1px 3px rgba(0,0,0,.08);
           border:1px solid #eee; transition:transform .08s; }
  a.card:hover { transform:translateY(-2px); border-color:#3f5bb0; }
  .card h3 { margin:0 0 .3rem; color:#3f5bb0; } .card p { margin:0; color:#666; font-size:.85rem; }
  .group { margin-top:1.8rem; } .group h2 { font-size:.9rem; color:#999;
           text-transform:uppercase; letter-spacing:.04em; margin:0 0 .7rem; }
  .note { color:#aaa; font-size:.75rem; margin-top:.4rem; }
</style></head>
<body><div class="wrap">
  <h1>Crossplay Dashboard</h1>
  <p class="sub">{{ a }} vs {{ b }} · {{ delay }}s per move</p>

  <div class="group"><h2>Simulator</h2>
    <div class="cards">
      <a class="card" href="/sim"><h3>Live Game →</h3>
        <p>Watch simulated games play out move-by-move, app-styled board.</p></a>
      <a class="card" href="/leaderboard"><h3>Leaderboard →</h3>
        <p>Self-play standings, Elo, and progress charts.</p></a>
    </div>
  </div>

  <div class="group"><h2>Device tools</h2>
    <div class="cards">
      <a class="card" href="/inspector"><h3>Inspector →</h3>
        <p>Inspect board/rack parsing from a device screenshot.</p></a>
      <a class="card" href="/templates"><h3>Template Capture →</h3>
        <p>Capture per-letter OCR templates.</p></a>
      <a class="card" href="/device-setup"><h3>Device Setup →</h3>
        <p>Calibrate board, rack &amp; buttons from a screenshot (iOS or Android).</p></a>
      <a class="card" href="/live"><h3>Live Device Board →</h3>
        <p>Mirror a real game via data/game_state.json.</p></a>
    </div>
    <p class="note">Device Setup works from an uploaded screenshot — no live device
      needed. The Inspector/Calibration/Live tools need a connected iPhone + Appium.</p>
  </div>
</div></body></html>"""


_DEVICE_SETUP_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Device Setup</title>
<style>
  body { font-family:-apple-system,system-ui,sans-serif; background:#f4f4ef; color:#222;
         margin:0; padding:1.2rem; }
  .wrap { max-width:1000px; margin:0 auto; }
  h1 { margin:.2rem 0; } .hint { color:#777; font-size:.85rem; margin:.2rem 0 1rem; }
  .controls { display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin-bottom:.8rem; }
  button, .mode { font:600 13px/1 inherit; border:1px solid #3f5bb0; color:#3f5bb0;
                  background:#fff; border-radius:6px; padding:7px 12px; cursor:pointer; }
  .mode.active { background:#3f5bb0; color:#fff; }
  #save { background:#2faa6a; border-color:#2faa6a; color:#fff; }
  .layout { display:flex; gap:1rem; flex-wrap:wrap; }
  .stage { position:relative; flex:1 1 420px; min-width:320px; }
  #shot { max-width:100%; display:block; border:1px solid #ccc; border-radius:6px; }
  #overlay { position:absolute; left:0; top:0; cursor:crosshair; }
  .panel { flex:0 0 260px; background:#fff; border-radius:10px; padding:1rem;
           box-shadow:0 1px 3px rgba(0,0,0,.08); font-size:.82rem; }
  .panel h3 { margin:.2rem 0 .5rem; font-size:.9rem; } .row { margin:.25rem 0; color:#555; }
  .row b { color:#222; } label { font-size:.82rem; color:#555; }
  input[type=number] { width:64px; padding:3px; }
  #status { margin-top:.6rem; font-size:.82rem; min-height:1.2em; }
</style></head>
<body><div class="wrap">
{{ nav | safe }}
<h1>Device Setup</h1>
<p class="hint">Upload a screenshot taken on the phone (iOS or Android), then mark the
board, rack and buttons. Saves to <code>data/calibration/calibration.json</code> —
no live device needed.</p>

<div class="controls">
  <input type="file" id="file" accept="image/*">
  <span class="mode" data-mode="board">1 · Board box</span>
  <span class="mode" data-mode="rack">2 · Rack row →7</span>
  <span class="mode" data-mode="submit">Submit</span>
  <span class="mode" data-mode="more">More</span>
  <span class="mode" data-mode="keepalive">Keepalive</span>
  <label>pixel scale <input type="number" id="scale" min="1" max="4" step="1" value="3"></label>
  <button id="save">Save</button>
</div>

<div class="layout">
  <div class="stage"><img id="shot" alt=""><canvas id="overlay"></canvas></div>
  <div class="panel">
    <h3>Current values</h3>
    <div class="row">Board: <b id="v-board">—</b></div>
    <div class="row">Rack cells: <b id="v-rack">0</b>/7</div>
    <div class="row">Submit: <b id="v-submit">—</b></div>
    <div class="row">More: <b id="v-more">—</b></div>
    <div class="row">Keepalive: <b id="v-keep">—</b></div>
    <div class="row" style="margin-top:.6rem;color:#999">Drag = box · click = point.
      Buttons stored as logical points (÷ pixel scale).</div>
    <div id="status"></div>
  </div>
</div>

<script>
const img = document.getElementById("shot"), cv = document.getElementById("overlay");
const ctx = cv.getContext("2d");
let mode = "board";
const st = { board:null, rackRow:null, rackCells:[], buttons:{} };
let ratio = 1, drag = null;

document.querySelectorAll(".mode").forEach(el => el.onclick = () => {
  mode = el.dataset.mode;
  document.querySelectorAll(".mode").forEach(m => m.classList.toggle("active", m === el));
});
document.querySelector('.mode[data-mode="board"]').classList.add("active");

document.getElementById("file").onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  img.onload = sized; img.src = URL.createObjectURL(f);
};
function sized() {
  cv.width = img.clientWidth; cv.height = img.clientHeight;
  cv.style.width = img.clientWidth + "px"; cv.style.height = img.clientHeight + "px";
  ratio = img.naturalWidth / img.clientWidth;   // natural px per display px
  redraw();
}
window.addEventListener("resize", () => { if (img.naturalWidth) sized(); });

const toNat = d => d * ratio, toDisp = n => n / ratio;
function pos(e) { const r = cv.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top }; }

cv.onmousedown = e => { const p = pos(e); drag = { x0:p.x, y0:p.y, x1:p.x, y1:p.y }; };
cv.onmousemove = e => { if (!drag) return; const p = pos(e); drag.x1 = p.x; drag.y1 = p.y; redraw(); };
cv.onmouseup = e => {
  const p = pos(e);
  if (mode === "submit" || mode === "more" || mode === "keepalive") {
    st.buttons[mode] = { x: Math.round(toNat(p.x)), y: Math.round(toNat(p.y)) };
  } else if (drag) {
    const x = Math.round(toNat(Math.min(drag.x0, p.x))), y = Math.round(toNat(Math.min(drag.y0, p.y)));
    const w = Math.round(toNat(Math.abs(p.x - drag.x0))), h = Math.round(toNat(Math.abs(p.y - drag.y0)));
    if (w > 4 && h > 4) {
      if (mode === "board") st.board = { x, y, w, h };
      else if (mode === "rack") { st.rackRow = { x, y, w, h };
        const cw = w / 7; st.rackCells = [];
        for (let i = 0; i < 7; i++) st.rackCells.push([Math.round(x + i*cw), y, Math.round(cw), h]); }
    }
  }
  drag = null; redraw(); updatePanel();
};

function rect(b, color) { ctx.strokeStyle = color; ctx.lineWidth = 2;
  ctx.strokeRect(toDisp(b.x), toDisp(b.y), toDisp(b.w), toDisp(b.h)); }
function dot(p, color, label) { ctx.fillStyle = color;
  ctx.beginPath(); ctx.arc(toDisp(p.x), toDisp(p.y), 5, 0, 7); ctx.fill();
  ctx.fillText(label, toDisp(p.x) + 7, toDisp(p.y) - 6); }
function redraw() {
  ctx.clearRect(0, 0, cv.width, cv.height); ctx.font = "11px sans-serif";
  if (st.board) rect(st.board, "#3f5bb0");
  st.rackCells.forEach(c => rect({x:c[0],y:c[1],w:c[2],h:c[3]}, "#2faa6a"));
  if (st.buttons.submit) dot(st.buttons.submit, "#e0a426", "Submit");
  if (st.buttons.more) dot(st.buttons.more, "#c63f93", "More");
  if (st.buttons.keepalive) dot(st.buttons.keepalive, "#4a90d9", "Keep");
  if (drag) { ctx.strokeStyle = "#999"; ctx.setLineDash([4,3]);
    ctx.strokeRect(drag.x0, drag.y0, drag.x1-drag.x0, drag.y1-drag.y0); ctx.setLineDash([]); }
}
function fmt(b){ return b ? `${b.x},${b.y} ${b.w}×${b.h}` : "—"; }
function fmtp(p){ return p ? `${p.x},${p.y}` : "—"; }
function updatePanel() {
  document.getElementById("v-board").textContent = fmt(st.board);
  document.getElementById("v-rack").textContent = st.rackCells.length;
  document.getElementById("v-submit").textContent = fmtp(st.buttons.submit);
  document.getElementById("v-more").textContent = fmtp(st.buttons.more);
  document.getElementById("v-keep").textContent = fmtp(st.buttons.keepalive);
}

document.getElementById("save").onclick = async () => {
  const scale = parseInt(document.getElementById("scale").value) || 1;
  if (!st.board || st.rackCells.length !== 7) {
    setStatus("Need a board box and a rack row (7 cells) before saving.", true); return; }
  const buttons = {};
  for (const k of ["submit","more","keepalive"]) {
    const p = st.buttons[k] || { x:0, y:0 };
    buttons[k] = [Math.round(p.x/scale), Math.round(p.y/scale)];   // → logical points
  }
  const payload = {
    pixel_scale: scale,
    board: { board_x:st.board.x, board_y:st.board.y,
             board_width:st.board.w, board_height:st.board.h, grid_size:15 },
    rack_cells: st.rackCells, buttons,
  };
  const r = await fetch("/device-config", { method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
  const res = await r.json();
  setStatus(res.success ? "Saved to " + res.path : "Error: " + res.error, !res.success);
};
function setStatus(msg, err){ const s = document.getElementById("status");
  s.textContent = msg; s.style.color = err ? "#c0392b" : "#2faa6a"; }

// Prefill numeric scale from any existing config.
fetch("/device-config").then(r => r.json()).then(d => {
  if (d.pixel_scale) document.getElementById("scale").value = d.pixel_scale;
}).catch(()=>{});
</script>
</div></body></html>"""


def mount_device_tools(app) -> bool:
    """Re-register tools/debug_server.py's routes onto `app`. Returns success."""
    try:
        import debug_server as ds
    except Exception as e:  # pragma: no cover - depends on optional device libs
        print(f"[!] device tools unavailable ({e}); dashboard runs without them")
        return False
    for rule in ds.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        view = ds.app.view_functions[rule.endpoint]
        path = "/inspector" if rule.rule == "/" else rule.rule
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        app.add_url_rule(path, f"ds_{rule.endpoint}", view, methods=methods)
    return True


def main():
    p = argparse.ArgumentParser(description="Unified Crossplay dashboard")
    p.add_argument("--a", default="greedy", choices=list(AGENTS))
    p.add_argument("--b", default="weak", choices=list(AGENTS))
    p.add_argument("--dict", default="data/dictionary/nwl23.txt")
    p.add_argument("--delay", type=float, default=1.2, help="seconds between moves")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--leaderboard", default="data/leaderboard.json")
    args = p.parse_args()

    try:
        dictionary = Dictionary.load(args.dict)
    except FileNotFoundError:
        print(f"[!] {args.dict} not found — falling back to data/sample_words.txt")
        dictionary = Dictionary.load("data/sample_words.txt")

    app = Flask(__name__)

    @app.route("/")
    def home():
        return render_template_string(_LANDING, a=args.a, b=args.b, delay=args.delay)

    @app.route("/leaderboard")
    def leaderboard():
        board = Leaderboard.load(args.leaderboard)
        return NAV + render_html_report(board)

    @app.route("/device-setup")
    def device_setup():
        return render_template_string(_DEVICE_SETUP_HTML, nav=NAV)

    @app.route("/device-config", methods=["GET"])
    def get_device_config():
        cal_path = "data/calibration/calibration.json"
        dev = DeviceConfig.load(cal_path)
        out = {"pixel_scale": dev.pixel_scale, "rack_cells": dev.rack_cells,
               "buttons": dev.buttons}
        try:
            cal = Calibration.load(cal_path)
            out["board"] = {"board_x": cal.board_x, "board_y": cal.board_y,
                            "board_width": cal.board_width, "board_height": cal.board_height,
                            "grid_size": cal.grid_size}
        except Exception:
            out["board"] = None
        return jsonify(out)

    @app.route("/device-config", methods=["POST"])
    def save_device_config():
        cal_path = "data/calibration/calibration.json"
        try:
            d = request.json
            b = d["board"]
            Calibration(board_x=int(b["board_x"]), board_y=int(b["board_y"]),
                        board_width=int(b["board_width"]), board_height=int(b["board_height"]),
                        grid_size=int(b.get("grid_size", 15))).save_merged(cal_path)
            DeviceConfig(
                pixel_scale=int(d["pixel_scale"]),
                rack_cells=[[int(v) for v in cell] for cell in d["rack_cells"]],
                buttons={k: [int(v) for v in xy] for k, xy in d["buttons"].items()},
            ).save(cal_path)
            return jsonify({"success": True, "path": cal_path})
        except Exception as e:
            return jsonify({"success": False, "error": f"{type(e).__name__}: {e}"})

    attach_spectator(
        app, page_route="/sim", state_route="/sim-state",
        agent_specs=(args.a, args.b), dictionary=dictionary,
        delay=args.delay, seed=args.seed, leaderboard_path=args.leaderboard,
        nav_html=NAV,
    )

    mount_device_tools(app)

    print(f"Dashboard at http://localhost:{args.port}   ({args.a} vs {args.b})")
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
