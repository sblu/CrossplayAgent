# Android backend — setup (macOS & Ubuntu)

The Android backend drives the Crossplay app through Appium's **UiAutomator2** driver
over **adb**. Unlike iOS (Xcode + WebDriverAgent, macOS-only), this toolchain is
identical on macOS and Ubuntu, so the same code and `.env` move straight to a Linux
desktop. Target device here: a **Pixel 10 Pro** over USB.

## 1. Install the toolchain

**Shared (both OSes):** Node + Appium + the driver (already installed on the Mac):
```
npm install -g appium
appium driver install uiautomator2
```

**Android platform-tools (adb):**
- macOS:  `brew install --cask android-platform-tools`  (or Android Studio)
- Ubuntu: `sudo apt install android-tools-adb`  (or Android Studio / the SDK)

Verify: `adb version` and `appium driver doctor uiautomator2` (the doctor reports
any missing `ANDROID_HOME`/SDK bits).

## 2. Prepare the Pixel 10 Pro

1. Settings → About phone → tap **Build number** 7× to unlock Developer options.
2. Settings → System → Developer options → enable **USB debugging**.
3. Plug into USB. On the phone, **Allow USB debugging** when prompted (trust this computer).
4. Confirm the host sees it:
   ```
   adb devices        # → <serial>   device
   ```
   That `<serial>` is your `ANDROID_DEVICE_UDID`.

## 3. Find the Crossplay app package

With the app installed and open on the phone:
```
adb shell dumpsys window | grep -i mCurrentFocus     # shows package/activity in focus
# or list packages:
adb shell pm list packages | grep -i -E 'nyt|cross|times'
```
Record the package id (→ `ANDROID_APP_PACKAGE`) and, if you want Appium to launch it,
the activity (→ `ANDROID_APP_ACTIVITY`). Leaving the activity unset attaches to the
app as already launched by hand.

## 4. Configure `.env`

```
APPIUM_HOST=127.0.0.1
APPIUM_PORT=4723
ANDROID_DEVICE_UDID=<serial from adb devices>
ANDROID_APP_PACKAGE=<package id>
# ANDROID_APP_ACTIVITY=<launch activity>   # optional
```

## 5. Run

```
appium                                   # terminal 1: start the server
CROSSPLAY_BACKEND=android python main.py # terminal 2: drive a game
```

## 6. Calibrate the device (one-time)

Android taps use **real device pixels**, so set **`pixel_scale = 1`** in Device Setup
(board/rack geometry and taps then share one coordinate space). Take a screenshot on
the Pixel mid-game, then in the dashboard's **Device Setup** page upload it and mark
the board box, the rack row, and the Play/More/keepalive buttons. Saves to
`data/calibration/calibration.json` — no code edits.

## 7. Tune perception (the only device-dependent code)

The geometry mapping is device-agnostic and unit-tested; what must be confirmed
against the real app is *how letters and buttons are exposed*:
```
python tools/android_dump.py     # writes tools/android_dump.xml + lists labelled nodes
```
From that output, adjust:
- `crossplay/vision/android_board.py` → `_label_of` (does the app put the letter in
  `text` or `content-desc`?) and blank-tile representation.
- `crossplay/client/android_client.py` → the `_TURN_/_PASS_/_MORE_/_OVER_KEYWORDS`
  (turn / pass / menu / game-over indicators) and blank-letter selection.

Everything else — the `CrossplayClient` interface, the runner loop, agents,
`input.py` taps/drags (W3C, platform-neutral), and `DeviceConfig` — is shared with
iOS and needs no changes.

## Portability note (Ubuntu)

On your Ubuntu desktop the steps are the same minus Homebrew: install `appium`
(via npm), `appium driver install uiautomator2`, and `android-tools-adb`. No Xcode,
no WebDriverAgent, no macOS-specific anything. Copy the repo + `.env`, point
`ANDROID_DEVICE_UDID` at the Pixel on that machine, and `CROSSPLAY_BACKEND=android
python main.py` works identically.
```
