"""Appium UiAutomator2 connection to an Android device.

OS-agnostic: identical on macOS and Ubuntu — UiAutomator2 + adb need no Xcode/WDA
equivalent, so the same code and .env move straight to a Linux desktop.

.env keys (all optional except UDID/package):
    APPIUM_HOST, APPIUM_PORT          shared with iOS (default 127.0.0.1:4723)
    ANDROID_DEVICE_UDID               adb device serial (`adb devices`)
    ANDROID_APP_PACKAGE               e.g. the Crossplay/NYT Games package id
    ANDROID_APP_ACTIVITY              launch activity (optional; omit to attach)
"""
import os

from dotenv import load_dotenv
from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options


class AndroidDriver:
    def __init__(self, host: str, port: str, udid: str,
                 app_package: str | None = None, app_activity: str | None = None):
        self._url = f"http://{host}:{port}"
        self._udid = udid
        self._app_package = app_package
        self._app_activity = app_activity
        self._driver = None

    @classmethod
    def from_env(cls) -> "AndroidDriver":
        load_dotenv()
        return cls(
            host=os.environ.get("APPIUM_HOST", "127.0.0.1"),
            port=os.environ.get("APPIUM_PORT", "4723"),
            udid=os.environ["ANDROID_DEVICE_UDID"],
            app_package=os.environ.get("ANDROID_APP_PACKAGE"),
            app_activity=os.environ.get("ANDROID_APP_ACTIVITY"),
        )

    def start(self) -> "AndroidDriver":
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.udid = self._udid
        options.no_reset = True               # don't wipe app state
        options.new_command_timeout = 600     # allow long gaps during move generation
        if self._app_package:
            options.app_package = self._app_package
        if self._app_activity:
            options.app_activity = self._app_activity
        else:
            # Attach to whatever is already foregrounded (app launched by hand).
            options.set_capability("appium:autoLaunch", False)
        self._driver = webdriver.Remote(self._url, options=options)
        return self

    def stop(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    @property
    def session(self):
        return self._driver

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
