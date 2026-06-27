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
import json
import os
import shutil
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template_string, request

from crossplay.client.device_config import DeviceConfig
from crossplay.engine.board import LETTER_VALUES
from crossplay.strategy.agent_config import AGENT_CONFIG_PATH, load_agent_configs
from crossplay.engine.dictionary import Dictionary
from crossplay.leaderboard import Leaderboard
from crossplay.leaderboard_report import render_html_report
from crossplay.vision.calibration import Calibration
from crossplay.web.spectator import AGENTS, attach_spectator, premium_grid

GAME_STATE_PATH = Path("data/game_state.json")
CAL_FILE = "data/calibration/calibration.json"
_BOT_LOG = Path("data/bot_run.log")

# Bot subprocess control — the live view can start/stop the Android game loop.
_bot = {"proc": None}


def _bot_running() -> bool:
    p = _bot["proc"]
    return p is not None and p.poll() is None


def _infer_platform() -> str:
    """Best-guess device platform from the environment when the config doesn't
    record one: an Android UDID means Android; iOS UDID/bundle means iOS."""
    if os.environ.get("ANDROID_DEVICE_UDID") or os.environ.get("ANDROID_APP_PACKAGE"):
        return "android"
    if os.environ.get("DEVICE_UDID") or os.environ.get("BUNDLE_ID"):
        return "ios"
    backend = os.environ.get("CROSSPLAY_BACKEND", "")
    return backend if backend in ("android", "ios") else ""


def _adb_path():
    adb = shutil.which("adb")
    if adb:
        return adb
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if home:
        cand = Path(home) / "platform-tools" / "adb"
        if cand.exists():
            return str(cand)
    return None


def _appium_reachable() -> bool:
    host = os.environ.get("APPIUM_HOST", "127.0.0.1")
    port = os.environ.get("APPIUM_PORT", "4723")
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _check_device_connection():
    """Preflight before starting the bot. Returns (ok, reason).

    Mirrors what AndroidDriver needs: an adb-visible device (matching the
    configured UDID, if any) and a reachable Appium server.
    """
    adb = _adb_path()
    if not adb:
        return False, "adb not found (install Android platform-tools / set ANDROID_HOME)."
    try:
        out = subprocess.run([adb, "devices"], capture_output=True, text=True,
                             timeout=8).stdout
    except Exception as e:
        return False, f"adb error: {e}"
    devices = [ln.split()[0] for ln in out.splitlines()[1:]
               if ln.strip().endswith("device")]
    if not devices:
        return False, "No Android device detected by adb."
    udid = os.environ.get("ANDROID_DEVICE_UDID")
    if udid and udid not in devices:
        return False, f"Configured device {udid} not connected (adb sees {devices})."
    if not _appium_reachable():
        host = os.environ.get("APPIUM_HOST", "127.0.0.1")
        port = os.environ.get("APPIUM_PORT", "4723")
        return False, f"Appium server not reachable at {host}:{port}. Start it with `appium`."
    return True, devices[0]


def _start_bot() -> None:
    if _bot_running():
        return
    _BOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(_BOT_LOG, "w")
    env = dict(os.environ, CROSSPLAY_BACKEND="android")
    _bot["proc"] = subprocess.Popen(
        [sys.executable, "main.py"], cwd=str(PROJECT_ROOT),
        env=env, stdout=log, stderr=subprocess.STDOUT)


def _stop_bot() -> None:
    p = _bot["proc"]
    if p is None or p.poll() is not None:
        return
    # SIGINT lets main.py's `with client:` run __exit__ → driver.quit() (clean
    # Appium teardown); fall back to kill if it doesn't exit promptly.
    try:
        p.send_signal(signal.SIGINT)
        p.wait(timeout=8)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    _bot["proc"] = None

# Shared top nav injected into the views we own.
NAV = """
<nav style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;
            font:600 13px/1 -apple-system,system-ui,sans-serif">
  <a href="/" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">⌂ Home</a>
  <a href="/sim" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Live Game</a>
  <a href="/arena" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Arena</a>
  <a href="/leaderboard" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Leaderboard</a>
  <a href="/device-live" style="text-decoration:none;color:#3f5bb0;border:1px solid #3f5bb0;
     border-radius:6px;padding:6px 12px">Live Phone</a>
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
      <a class="card" href="/arena"><h3>Arena →</h3>
        <p>Pick two algorithms, run the competition, track head-to-head W/L.</p></a>
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
      <a class="card" href="/device-live"><h3>Live Phone →</h3>
        <p>Mirror the real phone game move-by-move — board, scores &amp; play history.</p></a>
    </div>
    <p class="note">Device Setup works from an uploaded screenshot — no live device
      needed. The Inspector/Calibration tools need a connected device + Appium.</p>
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


_DEVICE_LIVE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crossplay — Live Phone</title>
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
  .player .name { font-size: .8rem; color: #888; }
  .player .pts { font-size: 1.6rem; font-weight: 700; }
  #pbot .name { color: var(--tile); font-weight: 600; }
  .vs { color: #bbb; font-weight: 600; padding: 0 .6rem; }
  .status { text-align: center; margin: .7rem 0 .2rem; font-size: 1.05rem;
            min-height: 1.3em; display: flex; align-items: center;
            justify-content: center; gap: .5rem; }
  .status b { color: #111; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--tile-new);
         flex: 0 0 auto; animation: pulse 1.1s ease-in-out infinite; }
  .dot.idle { background: #bbb; animation: none; }
  @keyframes pulse { 0%,100% { opacity: .25; transform: scale(.8); }
                     50% { opacity: 1; transform: scale(1.15); } }
  .substatus { text-align: center; color: #888; font-size: .8rem; min-height: 1em;
               margin-bottom: .1rem; }
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
  .tile .v { position: absolute; right: 1px; bottom: 0; font-size: .5em; font-weight: 600; }
  .rack { margin-top: .9rem; background: #233; border-radius: 10px; padding: .4rem; }
  .rack .lbl { color: #9bb; font-size: .7rem; margin: 0 .2rem .25rem; }
  .rtiles { display: grid; grid-template-columns: repeat(7, 1fr); gap: .35rem; }
  .rtile { background: var(--tile); color: #fff; border-radius: 6px; aspect-ratio: 1;
           display: flex; align-items: center; justify-content: center;
           font-weight: 700; position: relative; font-size: clamp(11px, 3.4vw, 20px); }
  .rtile.empty { background: #2c3d3d; }
  .rtile .v { position: absolute; right: 3px; bottom: 1px; font-size: .55em; }
  .history { margin-top: 1rem; background: #fff; border-radius: 12px;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow: hidden; }
  .history .hlbl { font-size: .75rem; color: #999; text-transform: uppercase;
                   letter-spacing: .04em; padding: .6rem .9rem .3rem; }
  .hlist { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; }
  .hrow { display: flex; align-items: center; gap: .6rem; padding: .45rem .9rem;
          border-top: 1px solid #f0f0ea; font-size: .9rem; }
  .hrow .who { font-size: .7rem; font-weight: 700; text-transform: uppercase;
               border-radius: 5px; padding: .1rem .4rem; min-width: 64px; text-align: center; }
  .hrow.bot .who { background: #e7ecf9; color: var(--tile); }
  .hrow.opp .who { background: #f1efe7; color: #9a7b1e; }
  .hrow .hw { flex: 1; font-weight: 600; letter-spacing: .02em; }
  .hrow .hs { font-weight: 700; color: #444; }
  .hempty { padding: .8rem .9rem; color: #aaa; font-size: .85rem; }
  .control { display: flex; align-items: center; gap: .7rem; margin: .2rem 0 .6rem;
             background: #fff; border-radius: 12px; padding: .6rem .8rem;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .toggle { border: 0; border-radius: 8px; padding: .55rem 1.1rem; font-weight: 700;
            font-size: .9rem; cursor: pointer; color: #fff; background: #2faa6a; }
  .toggle.on { background: #d2483f; }
  .toggle:disabled { opacity: .55; cursor: default; }
  .control .clbl { font-size: .85rem; color: #666; flex: 1; }
  .control .clbl b { color: #222; }
  .msg { border-radius: 10px; padding: .7rem .9rem; font-size: .85rem; margin-bottom: .6rem; }
  .msg.info { background: #eef3fb; color: #3a4b6b; }
  .msg.error { background: #fcecea; color: #9a2b22; }
  .msg ul { margin: .4rem 0 0; padding-left: 1.1rem; } .msg li { margin: .15rem 0; }
  .msg.hidden { display: none; }
  .cfg { margin-top: 1rem; background: #fff; border-radius: 12px;
         box-shadow: 0 1px 3px rgba(0,0,0,.08); overflow: hidden; }
  .cfg summary { cursor: pointer; padding: .7rem .9rem; font-size: .8rem;
                 color: #555; text-transform: uppercase; letter-spacing: .04em;
                 font-weight: 700; }
  .cfg .cfgbody { padding: 0 .9rem .8rem; font-size: .82rem; color: #444; }
  .cfg .file { font-family: ui-monospace, Menlo, monospace; color: #3f5bb0;
               background: #f4f4ef; border-radius: 5px; padding: .15rem .4rem; }
  .cfg table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
  .cfg td { padding: .35rem .3rem; border-top: 1px solid #f0f0ea; vertical-align: top; }
  .cfg td.k { color: #888; white-space: nowrap; width: 1%; padding-right: 1rem; }
  .cfg code { font-family: ui-monospace, Menlo, monospace; font-size: .8rem; }
  .cfg select { font: inherit; font-size: .82rem; padding: 4px 7px; border-radius: 6px;
                border: 1px solid #ccd; background: #fff; max-width: 100%; }
  .cfg .algo-desc { color: #666; font-size: .78rem; margin: .3rem 0 .15rem; }
  .cfg .algo-file { font-size: .78rem; color: #999; }
  .cfg .btns { display: flex; flex-wrap: wrap; gap: .25rem .5rem; }
  .cfg .btns .b { font-family: ui-monospace, Menlo, monospace; font-size: .78rem;
                  white-space: nowrap; color: #444; background: #f4f4ef;
                  border-radius: 5px; padding: .1rem .4rem; }
</style>
</head>
<body>
<div class="wrap">
  {{ nav | safe }}
  <div class="control">
    <button class="toggle" id="toggle" disabled>…</button>
    <div class="clbl" id="clbl">Checking bot status…</div>
  </div>
  <div class="msg hidden" id="msg"></div>
  <div class="scores">
    <div class="player" id="pbot"><div class="name">Bot</div><div class="pts">0</div></div>
    <div class="vs">vs</div>
    <div class="player" id="popp"><div class="name">Opponent</div><div class="pts">0</div></div>
  </div>
  <div class="status" id="status"><span class="dot idle"></span>Waiting for the phone…</div>
  <div class="substatus" id="substatus"></div>
  <div class="meta" id="meta"></div>
  <div class="board" id="board"></div>
  <div class="rack" id="rack"><div class="lbl">Bot rack</div><div class="rtiles"></div></div>
  <div class="history" id="history"><div class="hlbl">Plays</div><div class="hlist"></div></div>
  <details class="cfg" id="cfg">
    <summary>Device configuration</summary>
    <div class="cfgbody" id="cfgbody">Loading…</div>
  </details>
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

// Compute the cells touched by the last move so they can be highlighted.
function lastCells(m) {
  const out = [];
  if (!m || m.action === "pass" || !m.word) return out;
  const played = new Set(m.tiles_played || []);
  for (let i = 0; i < m.word.length; i++) {
    if (m.tiles_played && !played.has(i)) continue;
    const r = m.horizontal ? m.row : m.row + i;
    const c = m.horizontal ? m.col + i : m.col;
    out.push([r, c]);
  }
  return out;
}

let botRunning = false;

function render(s) {
  if (!s.ready) {
    const txt = botRunning
      ? '<span class="dot"></span><span>Bot starting — waiting for the game…</span>'
      : '<span class="dot idle"></span><span>No active game — connect the phone and press Start.</span>';
    document.getElementById("status").innerHTML = txt;
    document.getElementById("substatus").textContent = "";
    document.getElementById("meta").textContent = "";
    return;
  }
  const sc = s.scores || {};
  document.querySelector("#pbot .pts").textContent = sc.bot != null ? sc.bot : 0;
  document.querySelector("#popp .pts").textContent = sc.opponent != null ? sc.opponent : 0;

  const m = s.last_move;
  // The bot's current step (waiting / thinking / placing …) drives the headline.
  const phase = (s.phase || "").trim() || "Live phone game";
  const idle = /game over|waiting for the phone/i.test(phase);
  document.getElementById("status").innerHTML =
    `<span class="dot${idle ? " idle" : ""}"></span><span>${phase}</span>`;

  // The most recent completed play sits underneath as context.
  let sub = "";
  if (m && m.action === "pass") sub = "Last: passed";
  else if (m && m.word) sub = `Last play: ${m.word}` +
    (m.score != null ? ` · ${m.score} pts` : "");
  document.getElementById("substatus").textContent = sub;
  document.getElementById("meta").textContent = s.timestamp ? "updated " + s.timestamp : "";

  const hist = s.history || [];
  let hh = "";
  for (let i = hist.length - 1; i >= 0; i--) {          // newest at the top
    const e = hist[i];
    const cls = e.player === "Bot" ? "bot" : "opp";
    const score = e.score == null ? "" : e.score;
    hh += `<div class="hrow ${cls}"><span class="who">${e.player}</span>`
        + `<span class="hw">${e.word}</span><span class="hs">${score}</span></div>`;
  }
  document.querySelector("#history .hlist").innerHTML =
    hh || '<div class="hempty">No plays yet</div>';

  const news = new Set(lastCells(m).map(b => b[0] + "," + b[1]));
  for (let r = 0; r < 15; r++) for (let c = 0; c < 15; c++) {
    const el = cells[r * 15 + c];
    const letter = (s.board[r] && s.board[r][c]) || "";
    if (letter) {
      const cls = news.has(r + "," + c) ? "new" : "";
      el.innerHTML = tileHtml(letter, VALUES[letter] || 0, cls);
    } else {
      const prem = PREMIUM[r][c];
      if (r === 7 && c === 7) el.innerHTML = '<span class="star">★</span>';
      else if (prem) el.innerHTML = `<span class="${premClass[prem]}">${prem}</span>`;
      else el.innerHTML = "";
    }
  }

  const slots = document.querySelector("#rack .rtiles");
  let html = "";
  const rack = s.rack || [];
  for (let j = 0; j < 7; j++) {
    const t = rack[j];
    if (t == null || t === "") { html += '<div class="rtile empty"></div>'; continue; }
    const blank = t === "?";
    const v = blank ? "" : `<span class="v">${VALUES[t] || 0}</span>`;
    html += `<div class="rtile">${blank ? "·" : t}${v}</div>`;
  }
  slots.innerHTML = html;
}

function poll() {
  fetch(STATE_URL).then(r => r.json()).then(render).catch(()=>{});
}
poll();
setInterval(poll, 1500);

// ── Bot start/stop control ──────────────────────────────────────────────
const toggleBtn = document.getElementById("toggle");
const clbl = document.getElementById("clbl");
const msgEl = document.getElementById("msg");

function showMsg(kind, html) {
  msgEl.className = "msg " + kind;
  msgEl.innerHTML = html;
}
function hideMsg() { msgEl.className = "msg hidden"; }

function setRunning(running) {
  botRunning = running;
  toggleBtn.disabled = false;
  toggleBtn.textContent = running ? "Stop bot" : "Start bot";
  toggleBtn.classList.toggle("on", running);
  clbl.innerHTML = running
    ? "Bot is <b>running</b> — playing the game on the phone."
    : "Bot is <b>stopped</b>. Connect the phone, open the game, then Start.";
}

function refreshControl() {
  fetch("/device-control").then(r => r.json())
    .then(d => setRunning(!!d.running)).catch(() => {});
}

toggleBtn.addEventListener("click", () => {
  const action = botRunning ? "stop" : "start";
  toggleBtn.disabled = true;
  toggleBtn.textContent = action === "start" ? "Starting…" : "Stopping…";
  hideMsg();
  fetch("/device-control", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action})
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      setRunning(!!d.running);
      if (action === "start")
        showMsg("info", "Bot started. Make sure the Crossplay game is open on your turn.");
      else hideMsg();
    } else {
      setRunning(false);
      let html = "<b>Can't reach the phone.</b> " + (d.error || "");
      if (d.help && d.help.length)
        html += "<ul>" + d.help.map(h => "<li>" + h + "</li>").join("") + "</ul>";
      showMsg("error", html);
    }
  }).catch(() => { setRunning(false); showMsg("error", "Control request failed."); });
});

refreshControl();
setInterval(refreshControl, 3000);

// ── Device configuration panel ──────────────────────────────────────────
function renderConfig(c) {
  const body = document.getElementById("cfgbody");
  if (c.error && c.pixel_scale == null) {
    body.innerHTML = `Stored in <span class="file">${c.path}</span><br>` +
      `<span style="color:#9a2b22">${c.exists ? c.error : "Not calibrated yet — use Device Setup."}</span>`;
    return;
  }
  const b = c.board || {};
  const algos = c.algorithms || [];
  const btns = Object.entries(c.buttons || {})
    .map(([k, v]) => `<span class="b">${k} [${v}]</span>`).join("");
  const plat = c.platform
    ? c.platform.charAt(0).toUpperCase() + c.platform.slice(1)
    : "Unknown";
  const platNote = c.platform_source === "inferred" ? " (inferred from environment)"
                 : c.platform_source === "unknown" ? " — set it in Device Setup" : "";
  // Dropdown holds just the profile names; the selected profile's description sits
  // on its own line below so the row never has to word-wrap a long option.
  const opts = algos.map(a =>
    `<option value="${a.name}"${a.name === c.algorithm ? " selected" : ""}>` +
    `${a.name}</option>`).join("");
  const descOf = name => (algos.find(a => a.name === name) || {}).description || "";
  body.innerHTML =
    `Stored in <span class="file">${c.path}</span>` +
    `<table>` +
    `<tr><td class="k">platform</td><td><code>${plat}</code>` +
      `<span style="color:#999">${platNote}</span></td></tr>` +
    `<tr><td class="k">algorithm</td><td>` +
      `<select id="algoSel">${opts}</select> ` +
      `<span id="algoMsg" style="color:#2faa6a"></span>` +
      `<div class="algo-desc" id="algoDesc">${descOf(c.algorithm)}</div>` +
      `<div class="algo-file">defined in ` +
      `<span class="file">${c.agents_file || "data/agents.json"}</span></div></td></tr>` +
    `<tr><td class="k">pixel scale</td><td><code>${c.pixel_scale}</code></td></tr>` +
    `<tr><td class="k">board</td><td><code>x ${b.board_x}, y ${b.board_y}, ` +
      `${b.board_width}×${b.board_height}, grid ${b.grid_size}</code></td></tr>` +
    `<tr><td class="k">rack cells</td><td><code>${(c.rack_cells||[]).length} cells</code></td></tr>` +
    `<tr><td class="k">buttons</td><td class="btns">${btns}</td></tr>` +
    `</table>`;

  const sel = document.getElementById("algoSel");
  if (sel) sel.addEventListener("change", () => {
    const algoMsg = document.getElementById("algoMsg");
    document.getElementById("algoDesc").textContent = descOf(sel.value);
    algoMsg.textContent = "saving…";
    fetch("/device-algorithm", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({algorithm: sel.value})
    }).then(r => r.json()).then(d => {
      algoMsg.style.color = d.ok ? "#2faa6a" : "#9a2b22";
      algoMsg.textContent = d.ok ? "saved · applies on next Start" : (d.error || "failed");
    }).catch(() => { algoMsg.style.color = "#9a2b22"; algoMsg.textContent = "failed"; });
  });
}
fetch("/device-config").then(r => r.json()).then(renderConfig)
  .catch(() => { document.getElementById("cfgbody").textContent = "Failed to load config."; });
</script>
</body></html>"""


_ARENA_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crossplay — Arena</title>
<style>
  :root {
    --tile: #3f5bb0; --tile-new: #6b86d6; --tile-text: #fff;
    --cell: #fbfbf7; --line: #e6e6dd; --bg: #f4f4ef;
    --c2l: #4a90d9; --c3l: #2faa6a; --c2w: #e0a426; --c3w: #c63f93;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg);
         margin: 0; padding: 1rem; color: #222; }
  .wrap { max-width: 980px; margin: 0 auto; }
  h1 { margin: .2rem 0; } .hint { color: #777; font-size: .85rem; margin: .2rem 0 1rem; }
  .layout { display: flex; gap: 1.2rem; flex-wrap: wrap; align-items: flex-start; }
  .left { flex: 1 1 360px; min-width: 320px; } .right { flex: 1 1 380px; min-width: 320px; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          padding: 1rem; margin-bottom: 1rem; }
  .card h2 { font-size: .8rem; color: #999; text-transform: uppercase;
             letter-spacing: .04em; margin: 0 0 .7rem; }
  .pickers { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
  select { font: 600 14px/1 inherit; padding: 7px 8px; border-radius: 7px;
           border: 1px solid #ccd; background: #fff; color: #233; max-width: 200px; }
  .vs { color: #bbb; font-weight: 700; }
  .toggle { border: 0; border-radius: 8px; padding: .6rem 1.2rem; font-weight: 700;
            font-size: .9rem; cursor: pointer; color: #fff; background: #2faa6a;
            margin-top: .8rem; }
  .toggle.on { background: #d2483f; }
  .toggle:disabled { opacity: .55; cursor: default; }
  .runline { font-size: .85rem; color: #666; margin-top: .55rem; }
  .runline b { color: #222; }
  .msg { border-radius: 9px; padding: .55rem .8rem; font-size: .82rem; margin-top: .7rem; }
  .msg.error { background: #fcecea; color: #9a2b22; } .msg.hidden { display: none; }
  .file { font-family: ui-monospace, Menlo, monospace; color: #3f5bb0;
          background: #f4f4ef; border-radius: 5px; padding: .12rem .4rem; }
  .h2h { display: flex; justify-content: space-around; text-align: center; margin: .3rem 0; }
  .h2h .n { font-size: 2rem; font-weight: 800; }
  .h2h .l { font-size: .7rem; color: #999; text-transform: uppercase; letter-spacing: .03em; }
  .h2h .win .n { color: #2faa6a; } .h2h .loss .n { color: #d2483f; }
  .h2h .tie .n { color: #999; }
  .h2hsub { text-align: center; color: #888; font-size: .82rem; margin-top: .2rem; }
  table.stand { width: 100%; border-collapse: collapse; font-size: .85rem; }
  table.stand th, table.stand td { padding: .35rem .5rem; text-align: right;
                                   border-bottom: 1px solid #f0f0ea; }
  table.stand th:nth-child(2), table.stand td:nth-child(2) { text-align: left; }
  table.stand th { color: #999; font-weight: 600; font-size: .72rem;
                   text-transform: uppercase; }
  table.stand tr.cur td { background: #f3f6fd; font-weight: 700; }
  .scores { display: flex; justify-content: space-between; align-items: center;
            background: #fff; border-radius: 14px; padding: .6rem 1rem; margin-bottom: .5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .player { text-align: center; flex: 1; }
  .player .name { font-size: .78rem; color: #888; text-transform: capitalize; }
  .player .pts { font-size: 1.5rem; font-weight: 700; }
  .player.turn { color: var(--tile); } .player.turn .name { color: var(--tile); }
  .status { text-align: center; margin: .4rem 0; font-size: .9rem; min-height: 1.2em; }
  .status b { color: #111; }
  .meta { text-align: center; color: #999; font-size: .72rem; margin-bottom: .5rem; }
  .board { display: grid; grid-template-columns: repeat(15, 1fr); gap: 2px;
           background: var(--line); border: 2px solid var(--line); border-radius: 8px;
           aspect-ratio: 1; }
  .cell { background: var(--cell); position: relative; display: flex;
          align-items: center; justify-content: center; border-radius: 2px;
          font-size: clamp(5px, 1.4vw, 9px); font-weight: 700; }
  .prem-2L { color: var(--c2l); } .prem-3L { color: var(--c3l); }
  .prem-2W { color: var(--c2w); } .prem-3W { color: var(--c3w); }
  .star { color: #c9a227; font-size: 1.3em; }
  .tile { position: absolute; inset: 0; background: var(--tile); color: var(--tile-text);
          border-radius: 3px; display: flex; align-items: center; justify-content: center;
          font-size: clamp(8px, 2.3vw, 15px); font-weight: 700; }
  .tile.new { background: var(--tile-new); box-shadow: 0 0 0 2px #fff inset; }
  .tile .v { position: absolute; right: 1px; bottom: 0; font-size: .5em; font-weight: 600; }
</style>
</head>
<body><div class="wrap">
{{ nav | safe }}
<h1>Arena</h1>
<p class="hint">Pick two algorithms and run the head-to-head competition that drives the
  <a href="/leaderboard">leaderboard</a>. Edit the profiles in
  <span class="file">{{ agents_file_hint }}</span>.</p>

<div class="layout">
  <div class="left">
    <div class="card">
      <h2>Matchup</h2>
      <div class="pickers">
        <select id="selA"></select>
        <span class="vs">vs</span>
        <select id="selB"></select>
      </div>
      <button class="toggle" id="toggle" disabled>…</button>
      <div class="runline" id="runline">Loading…</div>
      <div class="msg hidden" id="msg"></div>
    </div>

    <div class="card">
      <h2>Head-to-head</h2>
      <div class="h2h">
        <div class="win"><div class="n" id="h2hW">0</div><div class="l" id="h2hWl">A wins</div></div>
        <div class="tie"><div class="n" id="h2hT">0</div><div class="l">ties</div></div>
        <div class="loss"><div class="n" id="h2hL">0</div><div class="l" id="h2hLl">B wins</div></div>
      </div>
      <div class="h2hsub" id="h2hsub">No games yet between this pair.</div>
    </div>

    <div class="card">
      <h2>Standings</h2>
      <table class="stand"><thead><tr><th>#</th><th>Agent</th><th>Rating</th>
        <th>Games</th><th>W-L-T</th><th>Win%</th></tr></thead>
        <tbody id="standBody"></tbody></table>
    </div>
  </div>

  <div class="right">
    <div class="scores">
      <div class="player" id="p0"><div class="name"></div><div class="pts"></div></div>
      <div class="vs">vs</div>
      <div class="player" id="p1"><div class="name"></div><div class="pts"></div></div>
    </div>
    <div class="status" id="status"></div>
    <div class="meta" id="meta"></div>
    <div class="board" id="board"></div>
  </div>
</div>
</div>
<script>
const STATE_URL = {{ state_url | tojson }};
const PREMIUM = {{ premium | tojson }};
const VALUES = {{ values | tojson }};
const premClass = {"2L":"prem-2L","3L":"prem-3L","2W":"prem-2W","3W":"prem-3W"};

// ── Board (mirrors the live spectator) ──────────────────────────────────
const boardEl = document.getElementById("board"), cells = [];
for (let r = 0; r < 15; r++) for (let c = 0; c < 15; c++) {
  const d = document.createElement("div"); d.className = "cell";
  boardEl.appendChild(d); cells.push(d);
}
function tileHtml(letter, value, cls) {
  const v = value === 0 ? "" : `<span class="v">${value}</span>`;
  return `<div class="tile ${cls}">${letter}${v}</div>`;
}
function renderBoard(s) {
  if (!s.ready) {
    document.getElementById("status").innerHTML =
      s.running === false ? "<b>Stopped.</b> Pick a matchup and press Start."
                          : "<b>Starting…</b>";
    return;
  }
  for (let i = 0; i < 2; i++) {
    const p = document.getElementById("p" + i);
    p.querySelector(".name").textContent = s.names[i];
    p.querySelector(".pts").textContent = s.scores[i];
    p.classList.toggle("turn", !s.over && s.turn === i);
  }
  document.getElementById("status").innerHTML = "<b>" + s.status + "</b>";
  document.getElementById("meta").textContent =
    `game ${s.game_no} · move ${s.move_no} · ${s.bag} tiles in bag`;
  const news = new Set((s.last_cells || []).map(b => b[0] + "," + b[1]));
  for (let r = 0; r < 15; r++) for (let c = 0; c < 15; c++) {
    const el = cells[r * 15 + c], letter = s.board[r][c];
    if (letter) {
      el.innerHTML = tileHtml(letter, VALUES[letter] || 0,
                              news.has(r + "," + c) ? "new" : "");
    } else {
      const prem = PREMIUM[r][c];
      if (r === 7 && c === 7) el.innerHTML = '<span class="star">★</span>';
      else if (prem) el.innerHTML = `<span class="${premClass[prem]}">${prem}</span>`;
      else el.innerHTML = "";
    }
  }
}
function pollBoard() {
  fetch(STATE_URL).then(r => r.json()).then(renderBoard).catch(()=>{});
}
pollBoard(); setInterval(pollBoard, 700);

// ── Controls + stats ────────────────────────────────────────────────────
const selA = document.getElementById("selA"), selB = document.getElementById("selB");
const toggle = document.getElementById("toggle"), runline = document.getElementById("runline");
const msgEl = document.getElementById("msg");
let running = false, optionsLoaded = false;

function showMsg(t) { msgEl.className = "msg error"; msgEl.textContent = t; }
function hideMsg() { msgEl.className = "msg hidden"; }

function fillOptions(sel, algos, chosen) {
  sel.innerHTML = algos.map(a =>
    `<option value="${a.name}"${a.name === chosen ? " selected" : ""}>${a.name}</option>`
  ).join("");
}
function renderStandings(rows, curA, curB) {
  const cur = new Set([curA, curB]);
  document.getElementById("standBody").innerHTML = rows.length ? rows.map((r, i) =>
    `<tr class="${cur.has(r.name) ? "cur" : ""}"><td>${i+1}</td><td>${r.name}</td>` +
    `<td>${r.rating}</td><td>${r.games}</td><td>${r.record}</td><td>${r.winrate}</td></tr>`
  ).join("") : '<tr><td colspan="6" style="text-align:center;color:#aaa">No games yet</td></tr>';
}
function renderH2H(m, a, b) {
  document.getElementById("h2hW").textContent = m.wins;
  document.getElementById("h2hT").textContent = m.ties;
  document.getElementById("h2hL").textContent = m.losses;
  document.getElementById("h2hWl").textContent = a + " wins";
  document.getElementById("h2hLl").textContent = b + " wins";
  document.getElementById("h2hsub").textContent = m.games
    ? `${m.games} game${m.games === 1 ? "" : "s"} played · ${a} vs ${b}`
    : "No games yet between this pair.";
}
function setRunning(r) {
  running = r;
  toggle.disabled = false;
  toggle.textContent = r ? "Stop competition" : "Start competition";
  toggle.classList.toggle("on", r);
  runline.innerHTML = r
    ? `Running — <b>${selA.value}</b> vs <b>${selB.value}</b>.`
    : "Stopped. Choose a matchup, then Start.";
}

function refresh() {
  const q = optionsLoaded ? `?a=${encodeURIComponent(selA.value)}&b=${encodeURIComponent(selB.value)}` : "";
  fetch("/arena-config" + q).then(r => r.json()).then(d => {
    if (!optionsLoaded) {
      fillOptions(selA, d.algorithms, d.selected.a);
      fillOptions(selB, d.algorithms, d.selected.b);
      optionsLoaded = true;
    }
    setRunning(d.running);
    renderH2H(d.matchup, d.selected.a, d.selected.b);
    renderStandings(d.standings, d.current.a, d.current.b);
  }).catch(()=>{});
}
// When the user changes a dropdown, refresh head-to-head for the new pair.
selA.addEventListener("change", refresh);
selB.addEventListener("change", refresh);

toggle.addEventListener("click", () => {
  const action = running ? "stop" : "start";
  toggle.disabled = true; hideMsg();
  fetch("/arena-control", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action, a: selA.value, b: selB.value})
  }).then(r => r.json()).then(d => {
    if (d.ok) { setRunning(!!d.running); refresh(); }
    else { toggle.disabled = false; showMsg(d.error || "Failed."); }
  }).catch(() => { toggle.disabled = false; showMsg("Control request failed."); });
});

refresh(); setInterval(refresh, 2500);
</script>
</body></html>"""


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
    try:                       # load .env so the device preflight sees APPIUM_*/UDID
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

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
        cal_path = CAL_FILE
        out = {"path": cal_path, "exists": Path(cal_path).exists()}
        try:
            dev = DeviceConfig.load(cal_path)
            platform = dev.platform or _infer_platform()
            configs = load_agent_configs()
            algorithm = dev.algorithm or "greedy"
            out.update(platform=platform,
                       platform_source=("config" if dev.platform else
                                        "inferred" if platform else "unknown"),
                       algorithm=algorithm,
                       algorithm_source="config" if dev.algorithm else "default",
                       agents_file=AGENT_CONFIG_PATH,
                       algorithms=[{"name": n, "type": c.get("type", n),
                                    "description": c.get("description", "")}
                                   for n, c in configs.items()],
                       pixel_scale=dev.pixel_scale, rack_cells=dev.rack_cells,
                       buttons=dev.buttons)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
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
        cal_path = CAL_FILE
        try:
            d = request.json
            b = d["board"]
            Calibration(board_x=int(b["board_x"]), board_y=int(b["board_y"]),
                        board_width=int(b["board_width"]), board_height=int(b["board_height"]),
                        grid_size=int(b.get("grid_size", 15))).save_merged(cal_path)
            DeviceConfig(
                platform=str(d.get("platform", "")),
                pixel_scale=int(d["pixel_scale"]),
                rack_cells=[[int(v) for v in cell] for cell in d["rack_cells"]],
                buttons={k: [int(v) for v in xy] for k, xy in d["buttons"].items()},
            ).save(cal_path)
            return jsonify({"success": True, "path": cal_path})
        except Exception as e:
            return jsonify({"success": False, "error": f"{type(e).__name__}: {e}"})

    live_values = {k: v for k, v in LETTER_VALUES.items() if k != ' '}

    @app.route("/device-algorithm", methods=["POST"])
    def set_device_algorithm():
        name = (request.json or {}).get("algorithm", "")
        configs = load_agent_configs()
        if name not in configs:
            return jsonify({"ok": False, "error": f"unknown algorithm {name!r}"}), 400
        dev = DeviceConfig.load(CAL_FILE)
        dev.algorithm = name
        dev.save(CAL_FILE)
        return jsonify({"ok": True, "algorithm": name,
                        "note": "Applies on the next Start."})

    @app.route("/device-control", methods=["GET"])
    def device_control_status():
        return jsonify({"running": _bot_running()})

    @app.route("/device-control", methods=["POST"])
    def device_control():
        action = (request.json or {}).get("action")
        if action == "stop":
            _stop_bot()
            return jsonify({"ok": True, "running": False})
        if action == "start":
            if _bot_running():
                return jsonify({"ok": True, "running": True})
            ok, reason = _check_device_connection()
            if not ok:
                return jsonify({"ok": False, "running": False, "error": reason,
                                "help": [
                                    "Connect the phone over USB.",
                                    "Enable Developer Options and turn on USB debugging.",
                                    "Accept the 'Allow USB debugging' prompt on the phone.",
                                    "Confirm with `adb devices`.",
                                    "Start Appium with `appium`.",
                                    "Open the Crossplay game on the phone, on your turn.",
                                ]})
            _start_bot()
            return jsonify({"ok": True, "running": True})
        return jsonify({"ok": False, "error": "unknown action"}), 400

    @app.route("/device-live")
    def device_live():
        return render_template_string(
            _DEVICE_LIVE_HTML, nav=NAV, premium=premium_grid(),
            values=live_values, state_url="/device-live-state",
        )

    @app.route("/device-live-state")
    def device_live_state():
        if not GAME_STATE_PATH.exists():
            resp = jsonify({"ready": False})
        else:
            try:
                data = json.loads(GAME_STATE_PATH.read_text())
                resp = jsonify({
                    "ready": True,
                    "board": data.get("board", [["" for _ in range(15)] for _ in range(15)]),
                    "rack": data.get("rack", []),
                    "last_move": data.get("last_move"),
                    "scores": data.get("scores", {}),
                    "history": data.get("history", []),
                    "phase": data.get("phase", ""),
                    "timestamp": data.get("timestamp"),
                })
            except (ValueError, OSError):
                resp = jsonify({"ready": False})
        resp.headers["Cache-Control"] = "no-store"   # always fetch the latest move
        return resp

    spec = attach_spectator(
        app, page_route="/sim", state_route="/sim-state",
        agent_specs=(args.a, args.b), dictionary=dictionary,
        delay=args.delay, seed=args.seed, leaderboard_path=args.leaderboard,
        nav_html=NAV,
    )

    @app.route("/arena")
    def arena():
        return render_template_string(
            _ARENA_HTML, nav=NAV, premium=premium_grid(),
            values=live_values, state_url="/sim-state",
            agents_file_hint=AGENT_CONFIG_PATH)

    @app.route("/arena-config")
    def arena_config():
        configs = load_agent_configs()
        algorithms = [{"name": n, "type": c.get("type", n),
                       "description": c.get("description", "")}
                      for n, c in configs.items()]
        status = spec.status()
        sel_a = request.args.get("a") or status["names"][0]
        sel_b = request.args.get("b") or status["names"][1]
        board = Leaderboard.load(args.leaderboard)
        return jsonify({
            "algorithms": algorithms,
            "agents_file": AGENT_CONFIG_PATH,
            "running": status["running"],
            "current": {"a": status["names"][0], "b": status["names"][1]},
            "selected": {"a": sel_a, "b": sel_b},
            "matchup": board.matchup(sel_a, sel_b),
            "standings": [{"name": n, "rating": round(r.rating, 1), "games": r.games,
                           "record": f"{r.wins}-{r.losses}-{r.ties}",
                           "winrate": round(r.winrate * 100, 1)}
                          for n, r in board.standings()],
        })

    @app.route("/arena-control", methods=["POST"])
    def arena_control():
        d = request.json or {}
        action = d.get("action")
        if action == "stop":
            spec.set_running(False)
            return jsonify({"ok": True, "running": False})
        if action == "start":
            a, b = d.get("a"), d.get("b")
            configs = load_agent_configs()
            if a not in configs or b not in configs:
                return jsonify({"ok": False,
                                "error": "Pick two configured algorithms."}), 400
            spec.configure(a, b, start=True)
            return jsonify({"ok": True, "running": True, "current": {"a": a, "b": b}})
        return jsonify({"ok": False, "error": "unknown action"}), 400

    mount_device_tools(app)

    print(f"Dashboard at http://localhost:{args.port}   ({args.a} vs {args.b})")
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
