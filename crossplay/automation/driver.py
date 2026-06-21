import os
from dotenv import load_dotenv
from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions


class CrossplayDriver:
    def __init__(self, host: str, udid: str, bundle_id: str, wda_url: str | None = None):
        self._host = host
        self._udid = udid
        self._bundle_id = bundle_id
        self._wda_url = wda_url
        self._driver = None

    @classmethod
    def from_env(cls) -> "CrossplayDriver":
        load_dotenv()
        return cls(
            host=os.environ["APPIUM_HOST"],
            udid=os.environ["DEVICE_UDID"],
            bundle_id=os.environ["BUNDLE_ID"],
            wda_url=os.environ.get("WDA_URL"),
        )

    def start(self) -> "CrossplayDriver":
        options = XCUITestOptions()
        options.udid = self._udid
        options.bundle_id = self._bundle_id
        options.platform_name = "iOS"
        options.automation_name = "XCUITest"
        options.no_reset = True
        # Allow long gaps between Appium commands (e.g. during Monte Carlo computation).
        # Default is 60s which is too short for multi-second move generation.
        options.new_command_timeout = 600
        if self._wda_url:
            options.web_driver_agent_url = self._wda_url
        self._driver = webdriver.Remote(self._host, options=options)
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
