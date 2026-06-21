#!/usr/bin/env python3
"""
Debug web server — board/rack inspector + board template capture tool.
Run from project root:  python3 tools/debug_server.py
Inspector:              http://localhost:8765
Template capture:       http://localhost:8765/templates
"""
import base64
import io
import json
import os
import sys
import threading
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from flask import Flask, jsonify, render_template_string, request
from PIL import Image

from crossplay.vision.calibration import Calibration
from crossplay.vision.board_parser import parse_board, _has_tile
from crossplay.vision.rack_parser import parse_rack
from crossplay.vision.tile_detector import _to_canonical_board, reload_board_templates
from crossplay.vision.accessibility_board import parse_board_and_rack_accessibility

app = Flask(__name__)

CAL_PATH = "data/calibration/calibration.json"
BOARD_TEMPLATE_DIR = Path("data/board_templates")

RACK_CELLS = [
    (12,   2133, 156, 157),
    (183,  2133, 156, 157),
    (353,  2133, 157, 157),
    (524,  2133, 157, 157),
    (695,  2133, 157, 157),
    (866,  2133, 156, 157),
    (1037, 2133, 156, 157),
]

# ── Global image state (for template capture) ─────────────────────────────────
_current_image: np.ndarray | None = None
_image_lock = threading.Lock()

# ── Shared helpers ─────────────────────────────────────────────────────────────

def _load_image_from_request() -> np.ndarray:
    """Load from uploaded file (multipart) or capture live from phone."""
    file = request.files.get("image")
    if file:
        pil = Image.open(io.BytesIO(file.read())).convert("RGB")
        return np.array(pil)
    from crossplay.automation.driver import CrossplayDriver
    from crossplay.automation.screenshot import capture_screenshot
    with CrossplayDriver.from_env() as driver:
        return capture_screenshot(driver.session)


def _load_image_and_driver_from_request():
    """Like _load_image_from_request but also returns the driver for accessibility reads.

    Returns (img, driver_or_none). driver is None for file uploads.
    Caller is responsible for closing the driver context if non-None.
    """
    file = request.files.get("image")
    if file:
        pil = Image.open(io.BytesIO(file.read())).convert("RGB")
        return np.array(pil), None
    from crossplay.automation.driver import CrossplayDriver
    from crossplay.automation.screenshot import capture_screenshot
    driver = CrossplayDriver.from_env().start()
    img = capture_screenshot(driver.session)
    return img, driver


def _img_to_b64(img: np.ndarray, fmt: str = "jpg", quality: int = 88) -> str:
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if fmt == "jpg" else []
    _, buf = cv2.imencode(f".{fmt}", bgr, params)
    return base64.b64encode(buf).decode()


def _gray_to_b64(gray: np.ndarray) -> str:
    _, buf = cv2.imencode(".png", gray)
    return base64.b64encode(buf).decode()


def _get_existing_templates() -> list[str]:
    if not BOARD_TEMPLATE_DIR.exists():
        return []
    return sorted(p.stem for p in BOARD_TEMPLATE_DIR.glob("*.png")
                  if len(p.stem) == 1 and p.stem.isupper())


# ── Inspector helpers ──────────────────────────────────────────────────────────

def _blend_rect(img, x0, y0, x1, y1, color, alpha):
    roi = img[y0:y1, x0:x1]
    overlay = roi.copy()
    cv2.rectangle(overlay, (0, 0), (x1 - x0, y1 - y0), color, -1)
    cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)
    img[y0:y1, x0:x1] = roi


def _annotate(img, board_grid, rack_letters, cal):
    out = img.copy()
    cw = cal.board_width // cal.grid_size
    ch = cal.board_height // cal.grid_size
    for row in range(cal.grid_size):
        for col in range(cal.grid_size):
            x0 = cal.board_x + col * cw
            y0 = cal.board_y + row * ch
            x1, y1 = x0 + cw, y0 + ch
            letter = board_grid[row][col]
            if letter:
                _blend_rect(out, x0, y0, x1, y1, (0, 200, 60), 0.40)
                fs = cw / 62.0
                (tw, th), _ = cv2.getTextSize(letter, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
                cv2.putText(out, letter,
                            (x0 + (cw - tw) // 2, y0 + (ch + th) // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 245, 0), 2, cv2.LINE_AA)
            cv2.rectangle(out, (x0, y0), (x1, y1),
                          (0, 220, 100) if letter else (70, 70, 70), 1)
    for i, (rx, ry, rw, rh) in enumerate(RACK_CELLS):
        letter = rack_letters[i] if i < len(rack_letters) else None
        if letter:
            _blend_rect(out, rx, ry, rx + rw, ry + rh, (0, 180, 60), 0.40)
        cv2.rectangle(out, (rx, ry), (rx + rw, ry + rh),
                      (0, 220, 100) if letter else (70, 70, 70), 2)
        if letter:
            fs = rw / 85.0
            (tw, th), _ = cv2.getTextSize(letter, cv2.FONT_HERSHEY_SIMPLEX, fs, 3)
            cv2.putText(out, letter,
                        (rx + (rw - tw) // 2, ry + (rh + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 245, 0), 3, cv2.LINE_AA)
    return out


def _run_detection(img):
    cal = Calibration.load(CAL_PATH)
    board_grid = parse_board(img, cal)
    rack_letters = parse_rack(img, RACK_CELLS)
    return board_grid, rack_letters, _annotate(img, board_grid, rack_letters, cal)


# ── Inspector routes ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(INSPECTOR_HTML)


@app.route("/capture", methods=["POST"])
def capture():
    """Capture from phone: uses accessibility tree for board/rack, screenshot for display."""
    global _current_image
    driver = None
    try:
        img, driver = _load_image_and_driver_from_request()
        with _image_lock:
            _current_image = img.copy()
        if driver is not None:
            # Live phone capture — read letters from accessibility tree (exact, no vision)
            cal = Calibration.load(CAL_PATH)
            board_grid, rack_letters, *_ = parse_board_and_rack_accessibility(
                driver.session, cal, RACK_CELLS, scale=3,
            )
            ann = _annotate(img, board_grid, rack_letters, cal)
        else:
            board_grid, rack_letters, ann = _run_detection(img)
        return jsonify({"success": True, "image": _img_to_b64(ann),
                        "board": board_grid, "rack": rack_letters})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()})
    finally:
        if driver is not None:
            driver.stop()


@app.route("/analyze", methods=["POST"])
def analyze():
    """Analyze an uploaded image using vision (no phone connection needed)."""
    global _current_image
    try:
        img = _load_image_from_request()
        with _image_lock:
            _current_image = img.copy()
        board_grid, rack_letters, ann = _run_detection(img)
        return jsonify({"success": True, "image": _img_to_b64(ann),
                        "board": board_grid, "rack": rack_letters})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()})


@app.route("/cell-crop")
def cell_crop():
    """Return a single board cell's raw crop for the inspector preview."""
    try:
        row = int(request.args["row"])
        col = int(request.args["col"])
        with _image_lock:
            if _current_image is None:
                return jsonify({"success": False, "error": "No image loaded"})
            img = _current_image.copy()
        cal = Calibration.load(CAL_PATH)
        cw_f = cal.board_width / cal.grid_size
        ch_f = cal.board_height / cal.grid_size
        x0 = round(cal.board_x + col * cw_f)
        y0 = round(cal.board_y + row * ch_f)
        x1 = round(cal.board_x + (col + 1) * cw_f)
        y1 = round(cal.board_y + (row + 1) * ch_f)
        cell = img[y0:y1, x0:x1]
        return jsonify({"success": True, "image": _img_to_b64(cell, fmt="jpg", quality=92)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ── Calibration routes ────────────────────────────────────────────────────────

@app.route("/calibrate")
def calibrate_page():
    cal = Calibration.load(CAL_PATH)
    return render_template_string(CALIBRATE_HTML,
                                  board_x=cal.board_x, board_y=cal.board_y,
                                  board_width=cal.board_width, board_height=cal.board_height,
                                  grid_size=cal.grid_size)


@app.route("/cal-image", methods=["POST"])
def cal_image():
    """Return screenshot as base64 for the calibration canvas."""
    try:
        img = _load_image_from_request()
        h, w = img.shape[:2]
        return jsonify({"success": True, "image": _img_to_b64(img, fmt="jpg", quality=80),
                        "width": w, "height": h})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()})


@app.route("/save-calibration", methods=["POST"])
def save_calibration():
    try:
        data = request.json
        cal = Calibration(
            board_x=int(data["board_x"]),
            board_y=int(data["board_y"]),
            board_width=int(data["board_width"]),
            board_height=int(data["board_height"]),
            grid_size=int(data.get("grid_size", 15)),
        )
        cal.save(CAL_PATH)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}"})


# ── Template capture routes ────────────────────────────────────────────────────

def _extract_cells(img, cal, show_all=False):
    """Return a list of cell dicts for the template capture UI."""
    cw_f = cal.board_width / cal.grid_size
    ch_f = cal.board_height / cal.grid_size
    cells = []
    for row in range(cal.grid_size):
        for col in range(cal.grid_size):
            x0 = round(cal.board_x + col * cw_f)
            y0 = round(cal.board_y + row * ch_f)
            x1 = round(cal.board_x + (col + 1) * cw_f)
            y1 = round(cal.board_y + (row + 1) * ch_f)
            cell_rgb = img[y0:y1, x0:x1]
            has_tile = _has_tile(cell_rgb)
            if not has_tile and not show_all:
                continue
            gray = cv2.cvtColor(cell_rgb, cv2.COLOR_RGB2GRAY)
            canonical = _to_canonical_board(gray)
            cells.append({
                "row": row, "col": col, "has_tile": has_tile,
                # raw: JPEG for compact transfer; canonical: PNG (binary, lossless)
                # canonical inverted for display: dark letter on white background
                "raw": _img_to_b64(cell_rgb, fmt="jpg", quality=92),
                "canonical": _gray_to_b64(255 - canonical),
            })
    return cells


@app.route("/templates")
def templates_page():
    return render_template_string(TEMPLATES_HTML, existing=_get_existing_templates())


@app.route("/get-cells", methods=["POST"])
def get_cells():
    global _current_image
    try:
        show_all = request.form.get("show_all", "false") == "true"
        img = _load_image_from_request()
        with _image_lock:
            _current_image = img.copy()
        cal = Calibration.load(CAL_PATH)
        cells = _extract_cells(img, cal, show_all=show_all)
        return jsonify({"success": True, "cells": cells,
                        "existing": _get_existing_templates()})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()})


@app.route("/save-templates", methods=["POST"])
def save_templates():
    global _current_image
    try:
        with _image_lock:
            if _current_image is None:
                return jsonify({"success": False,
                                "error": "No image loaded. Capture or upload first."})
            img = _current_image.copy()

        data = request.json
        labels = data.get("labels", [])  # [{row, col, letter}, ...]
        cal = Calibration.load(CAL_PATH)
        cw_f = cal.board_width / cal.grid_size
        ch_f = cal.board_height / cal.grid_size
        BOARD_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for item in labels:
            letter = str(item.get("letter", "")).upper().strip()
            if not letter or len(letter) != 1 or not letter.isalpha():
                continue
            row, col = int(item["row"]), int(item["col"])
            x0 = round(cal.board_x + col * cw_f)
            y0 = round(cal.board_y + row * ch_f)
            x1 = round(cal.board_x + (col + 1) * cw_f)
            y1 = round(cal.board_y + (row + 1) * ch_f)
            cell_rgb = img[y0:y1, x0:x1]
            gray = cv2.cvtColor(cell_rgb, cv2.COLOR_RGB2GRAY)
            canonical = _to_canonical_board(gray)
            cv2.imwrite(str(BOARD_TEMPLATE_DIR / f"{letter}.png"), canonical)
            saved.append(letter)

        reload_board_templates()  # flush the in-process cache
        return jsonify({"success": True, "saved": saved,
                        "existing": _get_existing_templates()})
    except Exception as e:
        return jsonify({"success": False, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()})


# ── Live board routes ─────────────────────────────────────────────────────────

GAME_STATE_PATH = PROJECT_ROOT / "data" / "game_state.json"


@app.route("/live")
def live_page():
    return render_template_string(LIVE_HTML)


@app.route("/live-state")
def live_state():
    try:
        if not GAME_STATE_PATH.exists():
            return jsonify({"ready": False})
        data = json.loads(GAME_STATE_PATH.read_text())
        data["ready"] = True
        return jsonify(data)
    except Exception as e:
        return jsonify({"ready": False, "error": str(e)})


# ── HTML templates ─────────────────────────────────────────────────────────────

_NAV = """
<nav style="margin-bottom:24px;display:flex;gap:12px">
  <a href="/" style="color:#4ecca3;text-decoration:none;padding:6px 14px;
     border:1px solid #4ecca3;border-radius:4px;font-size:13px;{active_inspector}">Inspector</a>
  <a href="/templates" style="color:#4ecca3;text-decoration:none;padding:6px 14px;
     border:1px solid #4ecca3;border-radius:4px;font-size:13px;{active_templates}">Template Capture</a>
</nav>"""

INSPECTOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Crossplay Inspector</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #12121e; color: #dde; min-height: 100vh; padding: 24px; }
  h1 { color: #4ecca3; font-size: 22px; margin-bottom: 20px; letter-spacing: 1px; }
  .controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 20px; }
  button { padding: 11px 22px; font-size: 14px; font-weight: bold; cursor: pointer; border: none; border-radius: 5px; }
  #capture-btn { background: #4ecca3; color: #12121e; }
  #capture-btn:hover { background: #38b48d; }
  #capture-btn:disabled { background: #336655; color: #789; cursor: not-allowed; }
  #upload-btn { background: #e05570; color: #fff; }
  #upload-btn:hover { background: #c04060; }
  #file-input { display: none; }
  #status { font-size: 13px; color: #7ec; }
  #error-box { display: none; background: #2a1220; border: 1px solid #e05570; border-radius: 5px; padding: 12px; margin-bottom: 16px; font-size: 12px; color: #f88; white-space: pre-wrap; }

  .results { display: flex; gap: 24px; flex-wrap: wrap; }
  .col-image { flex: 0 0 auto; }
  .col-image img { max-width: 360px; height: auto; border: 2px solid #2a3a3a; border-radius: 6px; display: block; }
  .col-data { flex: 1; min-width: 340px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #4ecca3; margin-bottom: 10px; }
  .section { margin-bottom: 24px; }

  /* Rack */
  .rack { display: flex; gap: 6px; }
  .tile { width: 38px; height: 38px; border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: bold; border: 2px solid #4ecca3; background: #1e3a5a; color: #fff; }
  .tile.empty { border-color: #334; background: #1a1a26; color: #445; }

  /* Board grid */
  .board-wrap { overflow-x: auto; }
  .board-grid { display: inline-block; }
  .board-row { display: flex; }
  .hdr-cell { width: 24px; height: 20px; font-size: 9px; color: #446; display: flex; align-items: center; justify-content: center; }
  .row-label { width: 20px; font-size: 9px; color: #446; display: flex; align-items: center; justify-content: flex-end; padding-right: 3px; }

  .board-cell { width: 24px; height: 24px; border: 1px solid #1e2a2a; position: relative; }
  .board-cell.has-tile { background: #0e2018; border-color: #1e4030; }
  .board-cell.empty-cell { background: #131320; }
  .board-cell.selected { border-color: #4a7fd4 !important; z-index: 1; }

  .cell-input {
    width: 100%; height: 100%; border: none; background: transparent;
    font-family: 'Courier New', monospace; font-size: 11px; font-weight: bold;
    text-align: center; outline: none; cursor: pointer; padding: 0;
    color: #4ecca3;  /* detected — green */
  }
  .cell-input.corrected { color: #f0a030; }  /* user changed — orange */
  .cell-input.added    { color: #e05570; }   /* was empty, user added — red */
  .cell-input.empty-input { color: #2a3a3a; }

  /* Preview panel */
  #preview-panel { display: none; background: #1a1a2e; border: 1px solid #2a3a5a;
    border-radius: 6px; padding: 14px; margin-bottom: 16px; }
  #preview-panel h2 { margin-bottom: 10px; }
  .preview-inner { display: flex; gap: 14px; align-items: flex-start; }
  #preview-img { width: 96px; height: 96px; object-fit: contain; border: 1px solid #2a3a5a;
    border-radius: 4px; image-rendering: pixelated; background: #0e0e1a; }
  .preview-meta { font-size: 12px; color: #aac; line-height: 2; }
  .preview-meta strong { color: #dde; }
  .preview-edit { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
  #preview-input { width: 44px; height: 44px; font-size: 22px; font-weight: bold;
    text-align: center; background: #1e2a3e; border: 2px solid #2a3a5a; border-radius: 4px;
    color: #fff; outline: none; font-family: 'Courier New', monospace; }
  #preview-input:focus { border-color: #4a7fd4; }
  #preview-clear { padding: 6px 12px; font-size: 12px; background: #2a1220;
    border: 1px solid #e05570; border-radius: 4px; color: #e05570; cursor: pointer; }

  /* Save bar */
  #save-bar { display: none; background: #0e0e1a; border: 1px solid #2a4a2a;
    border-radius: 6px; padding: 12px 16px; margin-bottom: 16px;
    display: none; align-items: center; gap: 14px; flex-wrap: wrap; }
  #save-tmpl-btn { padding: 9px 18px; font-size: 13px; font-weight: bold;
    background: #4a7fd4; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
  #save-tmpl-btn:disabled { background: #2a3a5a; color: #556; cursor: not-allowed; }
  #save-bar-msg { font-size: 12px; color: #aac; }

  .summary { font-size: 13px; color: #aac; }
  .count-hi { color: #4ecca3; font-weight: bold; }
</style>
</head>
<body>
<nav style="margin-bottom:24px;display:flex;gap:12px">
  <a href="/" style="color:#12121e;background:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px;font-weight:bold">Inspector</a>
  <a href="/templates" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Template Capture</a>
  <a href="/calibrate" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Calibrate</a>
  <a href="/live" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Live Board</a>
</nav>
<h1>Crossplay Inspector</h1>
<div class="controls">
  <button id="capture-btn" onclick="captureFromPhone()">Capture from Phone</button>
  <button id="upload-btn" onclick="document.getElementById('file-input').click()">Upload Screenshot</button>
  <input type="file" id="file-input" accept="image/*" onchange="analyzeFile(this)">
  <span id="status"></span>
</div>
<div id="error-box"></div>

<div id="results" class="results" style="display:none">
  <div class="col-image">
    <div class="section">
      <h2>Annotated Screenshot</h2>
      <img id="screenshot" src="" alt="screenshot">
    </div>
  </div>
  <div class="col-data">
    <div class="section">
      <h2>Rack — <span id="rack-count">0</span> tiles</h2>
      <div class="rack" id="rack-display"></div>
    </div>

    <div class="section">
      <h2>Board — <span id="board-count">0</span> tiles &nbsp;<span id="changed-badge" style="display:none;color:#f0a030;font-size:10px"></span></h2>
      <div class="board-wrap">
        <div class="board-grid" id="board-grid"></div>
      </div>
      <div style="font-size:11px;color:#446;margin-top:6px">Click any cell to inspect · Type to correct · Green=detected · Orange=corrected · Red=added</div>
    </div>

    <div id="preview-panel">
      <h2>Cell Preview — <span id="preview-title">none selected</span></h2>
      <div class="preview-inner">
        <img id="preview-img" src="" alt="cell">
        <div>
          <div class="preview-meta">
            <div>Position: <strong id="preview-pos">—</strong></div>
            <div>Detected: <strong id="preview-detected">—</strong></div>
          </div>
          <div class="preview-edit">
            <input id="preview-input" type="text" maxlength="1" placeholder="?">
            <button id="preview-clear" onclick="clearSelected()">Clear</button>
          </div>
          <div style="font-size:11px;color:#446;margin-top:6px">Type letter or clear to mark empty</div>
        </div>
      </div>
    </div>

    <div id="save-bar">
      <button id="save-tmpl-btn" onclick="saveAsTemplates()">Save Corrections as Templates</button>
      <span id="save-bar-msg"></span>
    </div>

    <div class="section">
      <div class="summary" id="summary"></div>
    </div>
  </div>
</div>

<script>
let boardDetected = [];   // original detection: 15x15 of letter|null
let selectedRow = -1, selectedCol = -1;

function setStatus(msg) { document.getElementById('status').textContent = msg; }
function showError(msg, detail) {
  const b = document.getElementById('error-box');
  b.textContent = 'Error: ' + msg + (detail ? '\\n\\n' + detail : '');
  b.style.display = 'block';
}
function clearError() { document.getElementById('error-box').style.display = 'none'; }

function cellKey(r, c) { return r * 15 + c; }
function getInput(r, c) { return document.querySelector(`.cell-input[data-r="${r}"][data-c="${c}"]`); }

function updateChangedBadge() {
  const inputs = document.querySelectorAll('.cell-input');
  let n = 0;
  inputs.forEach(inp => {
    const orig = inp.dataset.orig;
    const cur = inp.value.toUpperCase();
    if (cur !== (orig || '')) n++;
  });
  const badge = document.getElementById('changed-badge');
  const bar   = document.getElementById('save-bar');
  if (n > 0) {
    badge.textContent = n + ' change' + (n > 1 ? 's' : '');
    badge.style.display = 'inline';
    bar.style.display = 'flex';
  } else {
    badge.style.display = 'none';
    bar.style.display = 'none';
  }
}

function applyInputStyle(inp) {
  const orig = inp.dataset.orig || '';
  const cur  = inp.value.toUpperCase();
  inp.classList.remove('corrected', 'added', 'empty-input');
  if (cur === orig) {
    inp.classList.toggle('empty-input', !cur);
  } else if (!orig && cur) {
    inp.classList.add('added');
  } else {
    inp.classList.add('corrected');
  }
}

async function selectCell(r, c) {
  // deselect previous
  if (selectedRow >= 0) {
    const prev = document.querySelector(`.board-cell[data-r="${selectedRow}"][data-c="${selectedCol}"]`);
    if (prev) prev.classList.remove('selected');
  }
  selectedRow = r; selectedCol = c;

  const cell = document.querySelector(`.board-cell[data-r="${r}"][data-c="${c}"]`);
  if (cell) cell.classList.add('selected');

  const inp = getInput(r, c);
  const detected = inp ? (inp.dataset.orig || '') : '';

  document.getElementById('preview-panel').style.display = 'block';
  document.getElementById('preview-title').textContent = 'row ' + r + ', col ' + c;
  document.getElementById('preview-pos').textContent = 'row ' + r + ', col ' + c;
  document.getElementById('preview-detected').textContent = detected || '(none)';
  document.getElementById('preview-img').src = '';

  const pi = document.getElementById('preview-input');
  pi.value = inp ? inp.value : '';
  pi.focus();

  try {
    const resp = await fetch('/cell-crop?row=' + r + '&col=' + c);
    const data = await resp.json();
    if (data.success) document.getElementById('preview-img').src = 'data:image/jpeg;base64,' + data.image;
  } catch (_) {}
}

function clearSelected() {
  if (selectedRow < 0) return;
  const inp = getInput(selectedRow, selectedCol);
  if (inp) { inp.value = ''; applyInputStyle(inp); }
  document.getElementById('preview-input').value = '';
  updateChangedBadge();
}

// Sync preview input → grid input
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('preview-input').addEventListener('input', e => {
    if (selectedRow < 0) return;
    const inp = getInput(selectedRow, selectedCol);
    if (!inp) return;
    const val = e.target.value.replace(/[^a-zA-Z]/g,'').toUpperCase().slice(-1);
    e.target.value = val;
    inp.value = val;
    applyInputStyle(inp);
    updateChangedBadge();
    // auto-advance to next cell after typing
    if (val) {
      const nextCol = selectedCol + 1 < 15 ? selectedCol + 1 : selectedCol;
      const nextRow = selectedCol + 1 < 15 ? selectedRow : (selectedRow + 1 < 15 ? selectedRow + 1 : selectedRow);
      selectCell(nextRow, nextCol);
    }
  });
});

function renderResults(data) {
  clearError();
  boardDetected = data.board;
  document.getElementById('results').style.display = 'flex';
  document.getElementById('screenshot').src = 'data:image/jpeg;base64,' + data.image;
  document.getElementById('preview-panel').style.display = 'none';
  document.getElementById('save-bar').style.display = 'none';
  document.getElementById('changed-badge').style.display = 'none';
  selectedRow = -1; selectedCol = -1;

  const rack = data.rack;
  document.getElementById('rack-count').textContent = rack.filter(l => l).length;
  document.getElementById('rack-display').innerHTML = rack.map(l =>
    '<div class="tile ' + (l ? '' : 'empty') + '">' + (l || '·') + '</div>'
  ).join('');

  const board = data.board;
  let tileCount = 0;
  let html = '<div class="board-row"><div class="row-label"></div>';
  for (let c = 0; c < 15; c++) html += '<div class="hdr-cell">' + c + '</div>';
  html += '</div>';
  for (let r = 0; r < 15; r++) {
    html += '<div class="board-row"><div class="row-label">' + r + '</div>';
    for (let c = 0; c < 15; c++) {
      const l = board[r][c] || '';
      if (l) tileCount++;
      const cellCls = l ? 'has-tile' : 'empty-cell';
      const inpCls  = l ? '' : 'empty-input';
      html += '<div class="board-cell ' + cellCls + '" data-r="' + r + '" data-c="' + c + '" onclick="selectCell(' + r + ',' + c + ')">'
            + '<input class="cell-input ' + inpCls + '" type="text" maxlength="1"'
            + ' value="' + l + '" data-orig="' + l + '" data-r="' + r + '" data-c="' + c + '"'
            + ' readonly tabindex="-1">'
            + '</div>';
    }
    html += '</div>';
  }
  document.getElementById('board-grid').innerHTML = html;
  document.getElementById('board-count').textContent = tileCount;
  document.getElementById('summary').innerHTML =
    'Board: <span class="count-hi">' + tileCount + '</span> tiles &nbsp;|&nbsp; '
    + 'Rack: <span class="count-hi">' + rack.filter(l=>l).length + '</span> tiles';
  setStatus('Done. Click any cell to review.');
}

async function saveAsTemplates() {
  const inputs = document.querySelectorAll('.cell-input');
  const labels = [];
  inputs.forEach(inp => {
    const letter = inp.value.toUpperCase();
    if (letter && /^[A-Z]$/.test(letter)) {
      labels.push({ row: parseInt(inp.dataset.r), col: parseInt(inp.dataset.c), letter });
    }
  });
  if (!labels.length) return;
  document.getElementById('save-tmpl-btn').disabled = true;
  document.getElementById('save-bar-msg').textContent = 'Saving ' + labels.length + ' templates…';
  try {
    const resp = await fetch('/save-templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ labels }),
    });
    const data = await resp.json();
    if (data.success) {
      document.getElementById('save-bar-msg').textContent =
        'Saved: ' + data.saved.join(', ') + ' (' + data.existing.length + '/26 total)';
    } else {
      document.getElementById('save-bar-msg').textContent = 'Error: ' + data.error;
    }
  } catch (e) {
    document.getElementById('save-bar-msg').textContent = 'Error: ' + e.message;
  } finally {
    document.getElementById('save-tmpl-btn').disabled = false;
  }
}

async function captureFromPhone() {
  clearError(); setStatus('Connecting to phone…');
  document.getElementById('capture-btn').disabled = true;
  try {
    const resp = await fetch('/capture', { method: 'POST' });
    const data = await resp.json();
    data.success ? renderResults(data) : (showError(data.error, data.detail), setStatus(''));
  } catch (e) { showError(e.message); setStatus(''); }
  finally { document.getElementById('capture-btn').disabled = false; }
}
async function analyzeFile(input) {
  if (!input.files.length) return;
  clearError(); setStatus('Analyzing…');
  const form = new FormData();
  form.append('image', input.files[0]);
  try {
    const resp = await fetch('/analyze', { method: 'POST', body: form });
    const data = await resp.json();
    data.success ? renderResults(data) : (showError(data.error, data.detail), setStatus(''));
  } catch (e) { showError(e.message); setStatus(''); }
  finally { input.value = ''; }
}
</script>
</body>
</html>"""


TEMPLATES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Crossplay — Template Capture</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #12121e; color: #dde; padding: 24px; }
  h1 { color: #4ecca3; font-size: 20px; margin-bottom: 20px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #4ecca3; margin-bottom: 10px; }
  .section { margin-bottom: 24px; }
  .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 16px; background: #1a1a2e; border-radius: 6px; margin-bottom: 24px; }
  button { padding: 10px 20px; font-size: 13px; font-weight: bold; cursor: pointer; border: none; border-radius: 4px; }
  .btn-phone { background: #4ecca3; color: #12121e; }
  .btn-upload { background: #e05570; color: #fff; }
  .btn-save { background: #4a7fd4; color: #fff; font-size: 14px; padding: 12px 28px; }
  .btn-save:disabled { background: #2a3a5a; color: #556; cursor: not-allowed; }
  #file-input { display: none; }
  .toggle-label { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #aac; cursor: pointer; }
  #status { font-size: 13px; color: #7ec; }
  #error-box { display: none; background: #2a1220; border: 1px solid #e05570; border-radius: 5px;
    padding: 12px; margin-bottom: 16px; font-size: 12px; color: #f88; white-space: pre-wrap; }

  /* Coverage */
  .coverage-row { display: flex; flex-wrap: wrap; gap: 5px; }
  .badge { width: 30px; height: 30px; border-radius: 4px; font-size: 13px; font-weight: bold;
    display: flex; align-items: center; justify-content: center;
    background: #1e2030; color: #3a4460; border: 1px solid #2a3050; }
  .badge.done { background: #1a3a22; color: #4ecca3; border-color: #2a6040; }

  /* Cell grid */
  #cell-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 80px; }
  .cell-card { border: 2px solid #2a3a4a; border-radius: 6px; padding: 8px; width: 198px;
    background: #161626; display: flex; flex-direction: column; gap: 6px; }
  .cell-card.has-tile { border-color: #2a5040; }
  .cell-card.no-tile { border-color: #4a3020; opacity: 0.6; }
  .cell-card.labeled { border-color: #4ecca3 !important; opacity: 1 !important; }
  .pos-label { font-size: 10px; color: #4a5a6a; }
  .cell-imgs { display: flex; gap: 6px; }
  .cell-imgs figure { display: flex; flex-direction: column; gap: 2px; }
  .cell-imgs img { width: 88px; height: 88px; object-fit: contain;
    border: 1px solid #2a3a4a; border-radius: 3px; image-rendering: pixelated; }
  .cell-imgs figcaption { font-size: 9px; color: #3a5060; text-align: center; }
  .letter-input { width: 100%; padding: 7px; font-size: 20px; font-weight: bold; text-align: center;
    background: #1e2a3e; border: 2px solid #2a3a5a; border-radius: 4px; color: #ccd;
    outline: none; letter-spacing: 2px; }
  .letter-input:focus { border-color: #4a7fd4; background: #1a2030; }
  .letter-input.filled { border-color: #4ecca3; color: #4ecca3; background: #102018; }

  /* Sticky save bar */
  .save-bar { position: fixed; bottom: 0; left: 0; right: 0; background: #0e0e1a;
    border-top: 1px solid #2a3a4a; padding: 14px 24px;
    display: flex; align-items: center; gap: 16px; z-index: 10; }
  #save-msg { font-size: 13px; color: #aac; }
</style>
</head>
<body>
<nav style="margin-bottom:24px;display:flex;gap:12px">
  <a href="/" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Inspector</a>
  <a href="/templates" style="color:#12121e;background:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px;font-weight:bold">Template Capture</a>
  <a href="/calibrate" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Calibrate</a>
  <a href="/live" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Live Board</a>
</nav>

<h1>Board Template Capture</h1>

<div class="section">
  <h2>Coverage — <span id="cov-count">{{ existing|length }}</span> / 26 letters</h2>
  <div class="coverage-row" id="coverage-row">
    {% for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' %}
    <div class="badge{% if ch in existing %} done{% endif %}" id="badge-{{ ch }}">{{ ch }}</div>
    {% endfor %}
  </div>
</div>

<div class="controls">
  <button class="btn-phone" onclick="loadFromPhone()">Capture from Phone</button>
  <button class="btn-upload" onclick="document.getElementById('file-input').click()">Upload Screenshot</button>
  <input type="file" id="file-input" accept="image/*" onchange="loadFile(this)">
  <label class="toggle-label">
    <input type="checkbox" id="show-all-cb">
    Show all 225 cells (incl. undetected)
  </label>
  <span id="status"></span>
</div>
<div id="error-box"></div>

<div id="cells-section" style="display:none">
  <div class="section">
    <h2 id="cells-hdr"></h2>
    <div id="cell-grid"></div>
  </div>
</div>

<div class="save-bar">
  <button class="btn-save" id="save-btn" onclick="saveTemplates()" disabled>Save Templates</button>
  <span id="save-msg">Load a screenshot above, then label each tile with its letter.</span>
</div>

<script>
const ALL_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
let cellData = [];

function setStatus(msg) { document.getElementById('status').textContent = msg; }
function showError(msg, detail) {
  const b = document.getElementById('error-box');
  b.textContent = 'Error: ' + msg + (detail ? '\\n\\n' + detail : '');
  b.style.display = 'block';
}
function clearError() { document.getElementById('error-box').style.display = 'none'; }

function updateCoverage(existing) {
  const s = new Set(existing);
  document.getElementById('cov-count').textContent = existing.length;
  for (const ch of ALL_LETTERS) {
    const el = document.getElementById('badge-' + ch);
    el.className = 'badge' + (s.has(ch) ? ' done' : '');
  }
}

function renderCells(cells, existing) {
  cellData = cells;
  const detected = cells.filter(c => c.has_tile).length;
  document.getElementById('cells-hdr').textContent =
    detected + ' cells detected as having a tile' +
    (cells.length > detected ? ' + ' + (cells.length - detected) + ' undetected shown' : '');
  document.getElementById('cells-section').style.display = 'block';

  const grid = document.getElementById('cell-grid');
  grid.innerHTML = '';
  cells.forEach((cell, idx) => {
    const card = document.createElement('div');
    card.className = 'cell-card ' + (cell.has_tile ? 'has-tile' : 'no-tile');
    card.innerHTML =
      '<div class="pos-label">row ' + cell.row + ', col ' + cell.col +
        (cell.has_tile ? '' : ' — undetected') + '</div>' +
      '<div class="cell-imgs">' +
        '<figure><img src="data:image/jpeg;base64,' + cell.raw + '" alt="raw">' +
        '<figcaption>raw</figcaption></figure>' +
        '<figure><img src="data:image/png;base64,' + cell.canonical + '" alt="canonical">' +
        '<figcaption>canonical</figcaption></figure>' +
      '</div>' +
      '<input type="text" class="letter-input" maxlength="2" placeholder="A–Z"' +
        ' data-idx="' + idx + '" autocomplete="off" autocorrect="off" spellcheck="false">';
    grid.appendChild(card);
  });

  const inputs = Array.from(grid.querySelectorAll('.letter-input'));
  inputs.forEach((inp, i) => {
    inp.addEventListener('input', () => {
      const val = inp.value.replace(/[^a-zA-Z]/g, '').toUpperCase().slice(-1);
      inp.value = val;
      const card = inp.closest('.cell-card');
      if (val) {
        inp.classList.add('filled');
        card.classList.add('labeled');
        if (i + 1 < inputs.length) inputs[i + 1].focus();
      } else {
        inp.classList.remove('filled');
        card.classList.remove('labeled');
      }
      document.getElementById('save-btn').disabled =
        !inputs.some(el => el.classList.contains('filled'));
    });
    inp.addEventListener('keydown', e => {
      if (e.key === 'Backspace' && !inp.value && i > 0) {
        e.preventDefault();
        const prev = inputs[i - 1];
        prev.value = '';
        prev.classList.remove('filled');
        prev.closest('.cell-card').classList.remove('labeled');
        prev.focus();
      }
    });
  });

  updateCoverage(existing);
  setStatus(cells.length + ' cells loaded. Label each tile, then click Save.');
  if (inputs.length) inputs[0].focus();
  document.getElementById('save-btn').disabled = true;
  document.getElementById('save-msg').textContent = 'Label tiles above, then save.';
}

async function loadCells(formData) {
  clearError();
  setStatus('Loading cells…');
  try {
    const resp = await fetch('/get-cells', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.success) renderCells(data.cells, data.existing);
    else { showError(data.error, data.detail); setStatus(''); }
  } catch (e) { showError(e.message); setStatus(''); }
}

async function loadFromPhone() {
  const fd = new FormData();
  if (document.getElementById('show-all-cb').checked) fd.append('show_all', 'true');
  await loadCells(fd);
}

async function loadFile(input) {
  if (!input.files.length) return;
  const fd = new FormData();
  fd.append('image', input.files[0]);
  if (document.getElementById('show-all-cb').checked) fd.append('show_all', 'true');
  input.value = '';
  await loadCells(fd);
}

async function saveTemplates() {
  const inputs = Array.from(document.querySelectorAll('.letter-input'));
  const labels = [];
  inputs.forEach((inp, i) => {
    if (inp.value) labels.push({ row: cellData[i].row, col: cellData[i].col, letter: inp.value });
  });
  if (!labels.length) return;

  document.getElementById('save-btn').disabled = true;
  document.getElementById('save-msg').textContent = 'Saving…';
  try {
    const resp = await fetch('/save-templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ labels }),
    });
    const data = await resp.json();
    if (data.success) {
      updateCoverage(data.existing);
      const missing = ALL_LETTERS.split('').filter(c => !data.existing.includes(c));
      document.getElementById('save-msg').textContent =
        'Saved: ' + data.saved.join(', ') +
        '  |  Coverage: ' + data.existing.length + '/26' +
        (missing.length ? '  |  Still need: ' + missing.join(' ') : '  ✔ All 26 letters covered!');
    } else {
      showError(data.error, data.detail);
      document.getElementById('save-msg').textContent = 'Save failed.';
    }
  } catch (e) {
    showError(e.message);
  } finally {
    document.getElementById('save-btn').disabled = false;
  }
}
</script>
</body>
</html>"""


CALIBRATE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Crossplay — Calibration</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #12121e; color: #dde; padding: 24px; }
  h1 { color: #4ecca3; font-size: 20px; margin-bottom: 20px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #4ecca3; margin-bottom: 10px; }
  .section { margin-bottom: 24px; }
  .controls-top { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 16px; background: #1a1a2e; border-radius: 6px; margin-bottom: 24px; }
  button { padding: 10px 20px; font-size: 13px; font-weight: bold; cursor: pointer; border: none; border-radius: 4px; }
  .btn-phone { background: #4ecca3; color: #12121e; }
  .btn-upload { background: #e05570; color: #fff; }
  .btn-save { background: #4a7fd4; color: #fff; font-size: 14px; padding: 12px 28px; }
  .btn-save:disabled { background: #2a3a5a; color: #556; cursor: not-allowed; }
  #file-input { display: none; }
  #status { font-size: 13px; color: #7ec; }
  #error-box { display: none; background: #2a1220; border: 1px solid #e05570; border-radius: 5px;
    padding: 12px; margin-bottom: 16px; font-size: 12px; color: #f88; white-space: pre-wrap; }
  .layout { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 80px; }
  #canvas-wrap { flex: 0 0 auto; }
  canvas { border: 2px solid #2a3a4a; border-radius: 4px; display: block; }
  .params { flex: 1; min-width: 280px; }
  .param-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
    background: #1a1a2e; padding: 10px 12px; border-radius: 6px; }
  .param-name { font-size: 13px; color: #7ec; width: 110px; }
  .param-val { font-size: 18px; font-weight: bold; color: #fff; width: 60px; text-align: right; }
  .nudge-group { display: flex; gap: 4px; }
  .nudge { padding: 5px 9px; font-size: 11px; font-weight: bold; cursor: pointer;
    border: 1px solid #2a4a6a; border-radius: 3px; background: #1e2a3e; color: #7ac; }
  .nudge:hover { background: #2a3a5e; color: #9ce; }
  .tips { font-size: 12px; color: #779; line-height: 1.7; }
  .save-bar { position: fixed; bottom: 0; left: 0; right: 0; background: #0e0e1a;
    border-top: 1px solid #2a3a4a; padding: 14px 24px;
    display: flex; align-items: center; gap: 16px; z-index: 10; }
  #save-msg { font-size: 13px; color: #aac; }
</style>
</head>
<body>
<nav style="margin-bottom:24px;display:flex;gap:12px">
  <a href="/" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Inspector</a>
  <a href="/templates" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Template Capture</a>
  <a href="/calibrate" style="color:#12121e;background:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px;font-weight:bold">Calibrate</a>
  <a href="/live" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Live Board</a>
</nav>

<h1>Board Calibration</h1>

<div class="controls-top">
  <button class="btn-phone" onclick="loadFromPhone()">Capture from Phone</button>
  <button class="btn-upload" onclick="document.getElementById('file-input').click()">Upload Screenshot</button>
  <input type="file" id="file-input" accept="image/*" onchange="loadFile(this)">
  <span id="status">Load a screenshot to see the grid overlay.</span>
</div>
<div id="error-box"></div>

<div class="layout">
  <div id="canvas-wrap">
    <canvas id="cal-canvas" width="400" height="700"></canvas>
  </div>
  <div class="params">
    <div class="section">
      <h2>Grid Parameters</h2>
      <div class="param-row">
        <div class="param-name">board_x</div>
        <div class="param-val" id="val-board_x">{{ board_x }}</div>
        <div class="nudge-group">
          <button class="nudge" onclick="nudge('board_x',-10)">−10</button>
          <button class="nudge" onclick="nudge('board_x',-1)">−1</button>
          <button class="nudge" onclick="nudge('board_x',+1)">+1</button>
          <button class="nudge" onclick="nudge('board_x',+10)">+10</button>
        </div>
      </div>
      <div class="param-row">
        <div class="param-name">board_y</div>
        <div class="param-val" id="val-board_y">{{ board_y }}</div>
        <div class="nudge-group">
          <button class="nudge" onclick="nudge('board_y',-10)">−10</button>
          <button class="nudge" onclick="nudge('board_y',-1)">−1</button>
          <button class="nudge" onclick="nudge('board_y',+1)">+1</button>
          <button class="nudge" onclick="nudge('board_y',+10)">+10</button>
        </div>
      </div>
      <div class="param-row">
        <div class="param-name">board_width</div>
        <div class="param-val" id="val-board_width">{{ board_width }}</div>
        <div class="nudge-group">
          <button class="nudge" onclick="nudge('board_width',-10)">−10</button>
          <button class="nudge" onclick="nudge('board_width',-1)">−1</button>
          <button class="nudge" onclick="nudge('board_width',+1)">+1</button>
          <button class="nudge" onclick="nudge('board_width',+10)">+10</button>
        </div>
      </div>
      <div class="param-row">
        <div class="param-name">board_height</div>
        <div class="param-val" id="val-board_height">{{ board_height }}</div>
        <div class="nudge-group">
          <button class="nudge" onclick="nudge('board_height',-10)">−10</button>
          <button class="nudge" onclick="nudge('board_height',-1)">−1</button>
          <button class="nudge" onclick="nudge('board_height',+1)">+1</button>
          <button class="nudge" onclick="nudge('board_height',+10)">+10</button>
        </div>
      </div>
    </div>
    <div class="section tips">
      <h2>Tips</h2>
      board_x / board_y shift the grid left/right or up/down.<br>
      board_width / board_height expand or shrink it.<br>
      The outer border should land exactly on the board edge.<br>
      The 15×15 inner lines should split each tile in half.
    </div>
  </div>
</div>

<div class="save-bar">
  <button class="btn-save" id="save-btn" onclick="saveCalibration()">Save Calibration</button>
  <span id="save-msg">Adjust parameters until the grid aligns, then save.</span>
</div>

<script>
const params = {
  board_x: {{ board_x }},
  board_y: {{ board_y }},
  board_width: {{ board_width }},
  board_height: {{ board_height }},
  grid_size: {{ grid_size }},
};

let nativeW = 1, nativeH = 1, scale = 1;
let bgImage = null;
const canvas = document.getElementById('cal-canvas');
const ctx = canvas.getContext('2d');

function setStatus(msg) { document.getElementById('status').textContent = msg; }
function showError(msg, detail) {
  const b = document.getElementById('error-box');
  b.textContent = 'Error: ' + msg + (detail ? '\\n\\n' + detail : '');
  b.style.display = 'block';
}
function clearError() { document.getElementById('error-box').style.display = 'none'; }

function drawGrid() {
  if (!bgImage) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bgImage, 0, 0, canvas.width, canvas.height);

  const x0 = params.board_x * scale;
  const y0 = params.board_y * scale;
  const w  = params.board_width * scale;
  const h  = params.board_height * scale;
  const gs = params.grid_size;

  ctx.strokeStyle = 'rgba(78, 204, 163, 0.7)';
  ctx.lineWidth = 0.5;
  for (let i = 1; i < gs; i++) {
    const x = x0 + (w / gs) * i;
    ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y0 + h); ctx.stroke();
  }
  for (let i = 1; i < gs; i++) {
    const y = y0 + (h / gs) * i;
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 + w, y); ctx.stroke();
  }
  ctx.strokeStyle = 'rgba(78, 204, 163, 1)';
  ctx.lineWidth = 2;
  ctx.strokeRect(x0, y0, w, h);
}

function nudge(param, delta) {
  params[param] += delta;
  document.getElementById('val-' + param).textContent = params[param];
  drawGrid();
}

function setImage(b64, w, h) {
  nativeW = w; nativeH = h;
  const maxW = Math.min(window.innerWidth - 380, 440);
  scale = maxW / w;
  canvas.width  = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  bgImage = new Image();
  bgImage.onload = drawGrid;
  bgImage.src = 'data:image/jpeg;base64,' + b64;
  setStatus('Screenshot loaded — adjust nudge buttons until grid aligns with board edges.');
}

async function loadFromPhone() {
  clearError(); setStatus('Connecting to phone…');
  try {
    const resp = await fetch('/cal-image', { method: 'POST' });
    const data = await resp.json();
    if (data.success) setImage(data.image, data.width, data.height);
    else showError(data.error, data.detail);
  } catch (e) { showError(e.message); setStatus(''); }
}

async function loadFile(input) {
  if (!input.files.length) return;
  clearError(); setStatus('Loading…');
  const fd = new FormData();
  fd.append('image', input.files[0]);
  input.value = '';
  try {
    const resp = await fetch('/cal-image', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.success) setImage(data.image, data.width, data.height);
    else showError(data.error, data.detail);
  } catch (e) { showError(e.message); setStatus(''); }
}

async function saveCalibration() {
  document.getElementById('save-btn').disabled = true;
  document.getElementById('save-msg').textContent = 'Saving…';
  try {
    const resp = await fetch('/save-calibration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    const data = await resp.json();
    document.getElementById('save-msg').textContent = data.success
      ? 'Saved — board_x=' + params.board_x + ', board_y=' + params.board_y
        + ', board_width=' + params.board_width + ', board_height=' + params.board_height
      : 'Error: ' + data.error;
  } catch (e) {
    document.getElementById('save-msg').textContent = 'Error: ' + e.message;
  } finally {
    document.getElementById('save-btn').disabled = false;
  }
}
</script>
</body>
</html>"""


LIVE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Crossplay — Live Board</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #12121e; color: #dde; padding: 24px; }
  h1 { color: #4ecca3; font-size: 20px; margin-bottom: 4px; letter-spacing: 1px; }
  #subtitle { font-size: 12px; color: #446; margin-bottom: 20px; }
  #status-bar { font-size: 13px; color: #7ec; margin-bottom: 16px; min-height: 20px; }
  .layout { display: flex; gap: 32px; flex-wrap: wrap; align-items: flex-start; }

  /* Board */
  .board-wrap { flex: 0 0 auto; }
  .board-grid { display: inline-block; border: 2px solid #2a6040; border-radius: 4px; }
  .board-row { display: flex; }
  .sq {
    width: 36px; height: 36px;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: bold;
    border: 1px solid #1a2a22;
    position: relative;
    transition: background 0.15s;
  }
  .sq-label {
    font-size: 7px; font-weight: normal; position: absolute;
    top: 2px; left: 0; right: 0; text-align: center;
    letter-spacing: 0;
  }
  /* Premium square types */
  .sq.TW  { background: #5a1a1a; color: #ff8080; }
  .sq.DW  { background: #3a1520; color: #ff80b0; }
  .sq.TL  { background: #0e2a4a; color: #80b0ff; }
  .sq.DL  { background: #0e1e3a; color: #80c8ff; }
  .sq.NM  { background: #141a18; }
  /* Tile placed */
  .sq.tile { background: #2a4030 !important; color: #f0e060 !important; font-size: 16px; border-color: #3a6050; }
  .sq.tile.last-move { background: #1a5030 !important; border-color: #4ecca3; box-shadow: inset 0 0 0 2px #4ecca3; }

  /* Rack */
  .sidebar { flex: 1; min-width: 220px; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #4ecca3; margin-bottom: 10px; }
  .section { margin-bottom: 24px; }
  .rack { display: flex; gap: 7px; flex-wrap: wrap; }
  .rack-tile { width: 42px; height: 42px; border-radius: 5px; display: flex; align-items: center;
    justify-content: center; font-size: 20px; font-weight: bold;
    border: 2px solid #4ecca3; background: #1e3a5a; color: #fff; }
  .rack-tile.empty { border-color: #223; background: #1a1a26; color: #334; }

  /* Move info */
  #move-box { background: #1a1a2e; border: 1px solid #2a3a5a; border-radius: 6px;
    padding: 14px; font-size: 13px; line-height: 2; }
  #move-box .word { font-size: 22px; font-weight: bold; color: #4ecca3; letter-spacing: 2px; }
  #move-box .info { color: #aac; }
  #move-box .pass { color: #e05570; font-style: italic; }
  #waiting { color: #446; font-style: italic; }

  /* Legend */
  .legend { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .leg { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #668; }
  .leg-sq { width: 16px; height: 16px; border-radius: 2px; flex-shrink: 0; }
</style>
</head>
<body>
<nav style="margin-bottom:24px;display:flex;gap:12px">
  <a href="/" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Inspector</a>
  <a href="/templates" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Template Capture</a>
  <a href="/calibrate" style="color:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px">Calibrate</a>
  <a href="/live" style="color:#12121e;background:#4ecca3;text-decoration:none;padding:6px 14px;border:1px solid #4ecca3;border-radius:4px;font-size:13px;font-weight:bold">Live Board</a>
</nav>
<h1>Live Board</h1>
<div id="subtitle">Auto-refreshes every 2 seconds while the bot is running.</div>
<div id="status-bar">Waiting for bot to start...</div>

<div class="layout">
  <div class="board-wrap">
    <div class="board-grid" id="board-grid"></div>
    <div class="legend">
      <div class="leg"><div class="leg-sq" style="background:#5a1a1a"></div>Triple Word</div>
      <div class="leg"><div class="leg-sq" style="background:#3a1520"></div>Double Word</div>
      <div class="leg"><div class="leg-sq" style="background:#0e2a4a"></div>Triple Letter</div>
      <div class="leg"><div class="leg-sq" style="background:#0e1e3a"></div>Double Letter</div>
    </div>
  </div>
  <div class="sidebar">
    <div class="section">
      <h2>Rack</h2>
      <div class="rack" id="rack-display"></div>
    </div>
    <div class="section">
      <h2>Last Move</h2>
      <div id="move-box"><span id="waiting">Waiting for first move...</span></div>
    </div>
    <div class="section">
      <h2>Updated</h2>
      <div id="ts" style="font-size:13px;color:#668">—</div>
    </div>
  </div>
</div>

<script>
// Premium square map: key = "row,col" → type string
const SQUARE_TYPES = {};
const TW = [[0,3],[0,11],[3,0],[3,14],[11,0],[11,14],[14,3],[14,11]];
const DW = [[1,1],[1,13],[3,7],[11,7],[7,3],[7,11],[13,1],[13,13]];
const TL = [[0,0],[0,14],[1,6],[1,8],[4,5],[4,9],[5,4],[5,10],[6,1],[6,13],
            [8,1],[8,13],[9,4],[9,10],[10,5],[10,9],[13,6],[13,8],[14,0],[14,14]];
const DL = [[0,7],[14,7],[2,4],[2,10],[3,3],[3,11],[4,2],[4,12],[5,7],[9,7],
            [7,0],[7,14],[7,5],[7,9],[10,2],[10,12],[11,3],[11,11],[12,4],[12,10]];

for (const [r,c] of TW) SQUARE_TYPES[r+','+c] = 'TW';
for (const [r,c] of DW) SQUARE_TYPES[r+','+c] = 'DW';
for (const [r,c] of TL) SQUARE_TYPES[r+','+c] = 'TL';
for (const [r,c] of DL) SQUARE_TYPES[r+','+c] = 'DL';

const SQ_LABELS = { TW: '3W', DW: '2W', TL: '3L', DL: '2L' };

let lastTimestamp = null;

function buildEmptyBoard() {
  const grid = document.getElementById('board-grid');
  grid.innerHTML = '';
  for (let r = 0; r < 15; r++) {
    const row = document.createElement('div');
    row.className = 'board-row';
    for (let c = 0; c < 15; c++) {
      const key = r + ',' + c;
      const typ = SQUARE_TYPES[key] || 'NM';
      const sq = document.createElement('div');
      sq.className = 'sq ' + typ;
      sq.id = 'sq-' + r + '-' + c;
      if (typ !== 'NM') {
        const lbl = document.createElement('div');
        lbl.className = 'sq-label';
        lbl.textContent = SQ_LABELS[typ];
        sq.appendChild(lbl);
      }
      row.appendChild(sq);
    }
    grid.appendChild(row);
  }
}

function renderBoard(board, lastMove) {
  // Collect last-move tile positions
  const lastCells = new Set();
  if (lastMove && lastMove.word) {
    const { word, row, col, horizontal, tiles_played } = lastMove;
    if (tiles_played) {
      for (const idx of tiles_played) {
        const r = horizontal ? row : row + idx;
        const c = horizontal ? col + idx : col;
        lastCells.add(r + ',' + c);
      }
    }
  }

  for (let r = 0; r < 15; r++) {
    for (let c = 0; c < 15; c++) {
      const sq = document.getElementById('sq-' + r + '-' + c);
      if (!sq) continue;
      const key = r + ',' + c;
      const typ = SQUARE_TYPES[key] || 'NM';
      const letter = board[r][c];
      // Reset
      sq.className = 'sq ' + typ;
      // Remove old label if re-adding
      while (sq.firstChild) sq.removeChild(sq.firstChild);
      if (letter) {
        sq.classList.add('tile');
        if (lastCells.has(key)) sq.classList.add('last-move');
        sq.textContent = letter;
      } else if (typ !== 'NM') {
        sq.classList.remove('tile');
        const lbl = document.createElement('div');
        lbl.className = 'sq-label';
        lbl.textContent = SQ_LABELS[typ];
        sq.appendChild(lbl);
      }
    }
  }
}

function renderRack(rack) {
  const el = document.getElementById('rack-display');
  el.innerHTML = (rack || []).map(l =>
    '<div class="rack-tile ' + (l ? '' : 'empty') + '">' + (l || '') + '</div>'
  ).join('');
}

function renderMove(lastMove) {
  const box = document.getElementById('move-box');
  if (!lastMove) { box.innerHTML = '<span id="waiting">Waiting for first move...</span>'; return; }
  if (lastMove.action === 'pass') {
    box.innerHTML = '<div class="pass">Passed this turn</div>';
    return;
  }
  const dir = lastMove.horizontal ? 'horizontal' : 'vertical';
  box.innerHTML =
    '<div class="word">' + (lastMove.word || '?') + '</div>' +
    '<div class="info">Row ' + lastMove.row + ', Col ' + lastMove.col + ' · ' + dir + '</div>' +
    '<div class="info">Score: <strong style="color:#4ecca3">' + (lastMove.score || 0) + '</strong></div>';
}

async function poll() {
  try {
    const resp = await fetch('/live-state');
    const data = await resp.json();
    if (!data.ready) {
      document.getElementById('status-bar').textContent = 'Waiting for bot to write state...';
      return;
    }
    document.getElementById('status-bar').textContent =
      'Live · last update ' + (data.timestamp || '?');
    document.getElementById('ts').textContent = data.timestamp || '—';
    if (data.timestamp !== lastTimestamp) {
      lastTimestamp = data.timestamp;
      renderBoard(data.board, data.last_move);
      renderRack(data.rack);
      renderMove(data.last_move);
    }
  } catch (e) {
    document.getElementById('status-bar').textContent = 'Poll error: ' + e.message;
  }
}

buildEmptyBoard();
poll();
setInterval(poll, 2000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Crossplay debug server running:")
    print("  Inspector:         http://localhost:8765")
    print("  Template Capture:  http://localhost:8765/templates")
    print("  Calibration:       http://localhost:8765/calibrate")
    print("  Live Board:        http://localhost:8765/live")
    print("Press Ctrl+C to stop.")
    app.run(debug=False, port=8765, threaded=True)
