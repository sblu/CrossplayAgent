# iOS backend — setup (macOS only)

The iOS backend drives the Crossplay app on a real iPhone through Appium's
**XCUITest** driver, which runs Apple's **WebDriverAgent (WDA)** on the device.
Unlike Android (Appium + adb, portable to Ubuntu), this toolchain is **macOS-only**
— it needs **Xcode** to build and launch WDA. Reference device here: an
**iPhone** over USB at **@3x** (the historical default; an iPhone 11 is @2x — see §6).

Where Android reads the board by **OCR**, iOS reads it straight from the
**accessibility tree** (`XCUIElementTypeStaticText` labels) — no Tesseract, no
templates. That makes iOS perception more robust but the toolchain heavier.

## 1. Install the toolchain

**Xcode** (from the App Store) plus its command-line tools:
```
xcode-select --install
```

**Node + Appium + the XCUITest driver:**
```
npm install -g appium
appium driver install xcuitest
```

Verify the driver and its native dependencies (Carthage, `xcodebuild`, etc.):
```
appium driver doctor xcuitest
```
The doctor calls out anything missing for building WebDriverAgent.

## 2. Prepare the iPhone

1. Settings → Privacy & Security → **Developer Mode** → on, then reboot and confirm.
2. Plug into USB. **Trust This Computer** when prompted on the phone.
3. Confirm the Mac sees it and grab its UDID:
   ```
   xcrun xctrace list devices        # → iPhone (<iOS ver>) (<UDID>)
   # or:  idevice_id -l              # (libimobiledevice, if installed)
   ```
   That UDID is your `DEVICE_UDID`.

> **Version note:** the device's iOS version must be supported by your installed
> Xcode (Xcode ships a fixed set of device-support bundles). A phone newer than
> Xcode can't run WDA until Xcode is updated. This is the most common iOS snag.

## 3. Build and run WebDriverAgent

WDA is the on-device agent Appium talks to. Build it once from Xcode:

1. Open the WebDriverAgent project (under the xcuitest driver, e.g.
   `~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj`).
2. Select the **WebDriverAgentRunner** scheme, pick your iPhone as the destination.
3. Signing & Capabilities → set a **Team** (a free Apple ID works) and a unique
   bundle id if Xcode reports a conflict.
4. **Product → Test** (⌘U) to build, install, and launch the runner on the phone.
5. The first run shows an **Untrusted Developer** prompt on the phone — approve it
   under Settings → General → VPN & Device Management.

When WDA is up it serves on a port (default `8100`) reachable via `iproxy`/USB.
Note that URL — it becomes `WDA_URL` (e.g. `http://localhost:8100`). Letting
Appium build WDA itself also works, but a pre-built runner is faster and far more
reliable across sessions.

## 4. Find the Crossplay bundle id

```
ideviceinstaller -l            # libimobiledevice: lists installed app bundle ids
```
Look for the NYT Crossplay entry and record it (→ `BUNDLE_ID`). If you don't have
`ideviceinstaller`, the bundle id is also visible in Xcode's **Devices and
Simulators** window under the installed apps for the phone.

## 5. Configure `.env`

```
APPIUM_HOST=127.0.0.1
APPIUM_PORT=4723
DEVICE_UDID=<UDID from step 2>
BUNDLE_ID=<Crossplay bundle id>
WDA_URL=http://localhost:8100          # optional: reuse a pre-built WDA
```

Confirm the whole chain before driving a game:
```
appium                         # terminal 1: start the server
python verify_connection.py    # terminal 2: connects via WDA, saves connection_test.png
```
A saved `connection_test.png` means Mac → Appium → WDA → iPhone is healthy.

## 6. Calibrate the device (one-time)

iOS taps use **logical (point) coordinates**, so the board/rack geometry (in real
pixels) is divided by the **pixel scale** before tapping. Set `pixel_scale` to your
phone's Retina factor:
- **@3x** — iPhone Pro / Plus / X-class (the bundled default).
- **@2x** — iPhone 11, XR, SE.

Take a screenshot on the phone mid-game, then in the dashboard's **Device Setup**
page upload it and mark the board box, the rack row (→ 7 cells), and the
**Play / More / keepalive** buttons. Saving writes
`data/calibration/calibration.json` — no code edits. (Owen's pre-existing
geometry-only iOS calibration migrates automatically: missing device fields fill
with the historical @3x defaults. See `tests/client/test_device_config.py`.)

## 7. Run

```
appium                                # terminal 1 (and WDA running on the phone)
CROSSPLAY_BACKEND=ios python main.py  # terminal 2 — ios is the default backend
```
`ios` is `main.py`'s default, so a bare `python main.py` also drives the iPhone.
To pick the algorithm explicitly: `CROSSPLAY_AGENT=heuristic python main.py`.

## 8. Tune perception (the only device-dependent code)

The geometry mapping and the runner loop are device-agnostic and unit-tested. What
may need confirming against your build of the app is *how the accessibility tree
exposes tiles and buttons*. Dump the live tree (during your turn) to inspect it:
```
python tools/check_accessibility.py   # writes tools/accessibility_dump.xml + summarises nodes
```
From the element labels, the iOS-specific knobs are:
- `crossplay/vision/accessibility_board.py` → `_RACK_HEIGHT_THRESHOLD` (rack vs.
  board tiles are separated by element height) and the blank-tile rule (a
  rack-height `StaticText` whose label isn't a single `A–Z` → `'?'`).
- `crossplay/client/ios_client.py` → the turn check (`Play` button enabled),
  game-over check (`Play` absent), `_DISMISS_BUTTONS` (modal dismiss labels),
  blank-letter selection, and the Pass flow (`More` → a `pass`/`skip` button).

Everything else — the `CrossplayClient` interface, the runner loop, agents,
`input.py` taps/drags (W3C, platform-neutral), and `DeviceConfig` — is shared with
Android and needs no changes.

## How iOS and Android differ

| | iOS | Android |
|---|---|---|
| Driver | XCUITest + WebDriverAgent | UiAutomator2 |
| Host OS | **macOS only** (needs Xcode) | macOS **or** Ubuntu |
| Board reading | accessibility tree (labels) | OCR (Tesseract + OpenCV) |
| Coordinates | logical points (`pixel_scale` 2 or 3) | real pixels (`pixel_scale = 1`) |
| `.env` keys | `DEVICE_UDID`, `BUNDLE_ID`, `WDA_URL` | `ANDROID_DEVICE_UDID`, `ANDROID_APP_PACKAGE` |

See **[Android setup](android-setup.md)** for the other backend and
**[device abstraction](device-abstraction.md)** for the shared design.
