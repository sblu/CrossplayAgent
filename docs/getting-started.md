# Getting Started

A guide for someone who just cloned this repo and wants to (1) run the dashboard,
(2) build and test a Crossplay-playing algorithm in the simulator, and eventually
(3) let it play a real game on a phone.

> **The short version of the project:** the valuable part is the *algorithm* that
> chooses moves. Everything else — the simulator, the arena, the leaderboard, the
> phone automation — exists so you can build that algorithm, prove it's good, and
> then point it at a real game. You can do almost all of the work with **no phone
> at all**.

---

## 1. Prerequisites

| Need | Why | Notes |
|------|-----|-------|
| **Python 3.11+** | everything | `python3 --version` |
| **pip + venv** | install deps | standard library |
| **Tesseract OCR engine** | reading an **Android** board from screenshots | macOS: `brew install tesseract` · Ubuntu: `sudo apt install tesseract-ocr`. *Not* needed for sim/arena/leaderboard. |
| A **word list** (NWL2023) | legal-move generation | **You must obtain this yourself — see §3.** |

Device automation has its own extra prerequisites — covered in §7. You do **not**
need any of that to develop and test algorithms.

## 2. Install

```bash
git clone <this-repo> CrossPlay && cd CrossPlay
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Sanity check (runs the full test suite, no device needed):

```bash
python -m pytest -q
```

## 3. The dictionary — you must supply NWL2023 yourself

The bot generates moves against the **NASPA Word List 2023 (NWL2023)**. That list
is **copyrighted and is not distributed in this repo** — obtaining a legitimate
copy is **your responsibility**. Once you have it as plain text (one word per
line), save it to:

```
data/dictionary/nwl23.txt
```

Every entry point looks there by default and **falls back to `data/sample_words.txt`**
(a tiny bundled list) if it's missing — so the dashboard and tests still run
without it, you just get a thin vocabulary. A real algorithm evaluation needs the
full list.

## 4. Start the dashboard from scratch

```bash
source .venv/bin/activate
python tools/dashboard.py                       # defaults: greedy vs weak, port 8765
# options: --a greedy --b heuristic --delay 1.0 --port 8765 --dict data/dictionary/nwl23.txt
```

Open **http://localhost:8765**. The pages:

| Page | What it's for |
|------|---------------|
| **/sim** — Live Game | Watch one simulated game render move-by-move. |
| **/arena** — Arena | Pick two algorithms, run the head-to-head competition, watch the W/L tally. |
| **/leaderboard** | Elo standings + progress charts across all recorded games. |
| **/device-live** — Live Phone | Mirror a real phone game; start/stop the bot; pick its algorithm. |
| **/device-setup** | Calibrate a device from a screenshot (no live device needed). |
| **/docs** | These guides, rendered in the browser. |

The dashboard runs a normal Flask dev server in the foreground; `Ctrl-C` stops it.
It serves over `127.0.0.1` only.

## 5. How the Arena and Leaderboard work together

These two are the core of algorithm evaluation:

- The **Arena** (`/arena`) runs a continuous **head-to-head** competition between
  two chosen algorithms. Start/stop it from the page; switch the matchup from the
  two dropdowns (the choices come from `data/agents.json`, see §6). Each finished
  game is recorded.
- The **Leaderboard** (`/leaderboard`) is the persistent record of those games
  (`data/leaderboard.json`). It tracks, per algorithm: an **Elo rating**, W-L-T,
  average score and margin — plus **per-pair head-to-head** records surfaced back
  on the arena page.

So the loop is: *the arena generates games → the leaderboard scores them → the
arena shows you who's ahead in that specific matchup.* Leave the arena running and
the sample size (and confidence) grows.

For scripted batches instead of the live arena, use the CLI harness:

```bash
python selfplay.py --agent-a heuristic --agent-b greedy --games 200 \
    --leaderboard data/leaderboard.json
# add --out runs/ab.jsonl to log every decision for later analysis
```

## 6. Algorithms are configured in `data/agents.json`

The dashboard's dropdowns and the device bot all pick algorithms by **profile
name** from `data/agents.json`. A profile selects an implementation *type* plus
optional constructor params:

```json
{
  "heuristic": { "type": "heuristic", "params": { "leave_weight": 1.0 },
                 "description": "Balances immediate score against rack-leave quality." }
}
```

The file is created with sensible defaults on first run. **The implementation
logic lives in code** (`crossplay/strategy/`), not here — this file only chooses
and tunes. To create or modify an algorithm, see **[Adding an Algorithm](adding-an-algorithm.md)**.

## 7. Playing on a real device

Only needed for the final step — proving the bot in a live game. Pick one
platform:

### Android (recommended — same toolchain on macOS & Ubuntu)
Full instructions: **[Android setup](architecture/android-setup.md)**. In short
you need:
- **Appium** + the **UiAutomator2** driver (`npm i -g appium`, `appium driver install uiautomator2`)
- **adb** (Android platform-tools) and a phone with **USB debugging** enabled
- **Tesseract** (the board is read by OCR)
- a `.env` with `ANDROID_DEVICE_UDID`, `ANDROID_APP_PACKAGE`, `APPIUM_HOST`, `APPIUM_PORT`

### iOS (macOS only)
- **Xcode** running **WebDriverAgent** on the device
- a `.env` with `DEVICE_UDID`, `BUNDLE_ID`, `WDA_URL`, `APPIUM_HOST`, `APPIUM_PORT`
- verify with `python verify_connection.py`

### Calibrate the device (one-time, per device)

The bot needs to know where the board, rack and buttons are on *your* screen.
Open **/device-setup**, upload a screenshot taken on the phone, and mark:
1. the **board** box, 2. the **rack** row (→ 7 cells), 3. the **Submit / More /
Keepalive** buttons, and set the **pixel scale**.

Saving writes **`data/calibration/calibration.json`** (board geometry + tap
targets + `platform` + selected `algorithm`). No live device is required to
calibrate — just a screenshot.

### Run it live

Start the dashboard, open **/device-live**, pick the bot's algorithm from the
config panel, make sure the game is open on your turn, and press **Start bot**.
The page mirrors the board, shows each play, and the bot's current step. (Under
the hood this runs `main.py` with `CROSSPLAY_BACKEND=android`.)

## 8. The development loop

The intended end-to-end flow for building a winning bot:

1. **Propose** an algorithm — add a class + profile (see the next guide).
2. **Test it in the arena** against the current leaderboard leader (usually
   **greedy**). Let enough games accumulate to trust the head-to-head record.
3. **Tweak** — adjust params in `data/agents.json` (no code) or the logic in
   `crossplay/strategy/`, and re-run. Iterate until it consistently beats greedy.
4. **Prove it live** — set it as the device algorithm on **/device-live** and let
   it play a real game.

## 9. Where things live

```
main.py                     # bot entry point (CROSSPLAY_BACKEND=ios|android|sim)
selfplay.py                 # batch A/B self-play harness → leaderboard / JSONL
tools/dashboard.py          # the unified web dashboard
data/dictionary/nwl23.txt   # YOUR word list (not in repo)
data/agents.json            # algorithm profiles (type + params)
data/calibration/…json      # per-device geometry + tap targets
data/leaderboard.json       # standings + head-to-head record
crossplay/strategy/         # the algorithms (the part you'll work on)
crossplay/engine/           # board, scoring, dictionary, move generation
crossplay/client/           # device backends (android/ios/sim)
crossplay/web/spectator.py  # the arena game loop
docs/architecture/          # design docs (device abstraction, android setup)
```

## Next

→ **[Adding an Algorithm](adding-an-algorithm.md)** — the Agent contract, the
config→registry→class chain, and a worked example.
