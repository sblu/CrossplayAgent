"""
Minimal connection test: Mac -> Appium -> iPhone via WDA.
Run with: python verify_connection.py
Saves a screenshot to connection_test.png if successful.
"""
import os
from dotenv import load_dotenv
from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions

load_dotenv()

options = XCUITestOptions()
options.platform_name = "iOS"
options.device_name = "iphone"
options.udid = os.environ["DEVICE_UDID"]
options.bundle_id = os.environ["BUNDLE_ID"]
options.web_driver_agent_url = os.environ["WDA_URL"]
options.no_reset = True  # don't wipe app state between runs

appium_url = f"http://{os.environ['APPIUM_HOST']}:{os.environ['APPIUM_PORT']}"

print(f"Connecting to Appium at {appium_url} ...")
driver = webdriver.Remote(appium_url, options=options)
print("Connected!")

print("Capturing screenshot ...")
driver.save_screenshot("connection_test.png")
print("Screenshot saved to connection_test.png")

driver.quit()
print("Done. Hardware connection verified.")
