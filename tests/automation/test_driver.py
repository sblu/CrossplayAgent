from unittest.mock import patch, MagicMock
import pytest
from crossplay.automation.driver import CrossplayDriver


def test_driver_creates_appium_session():
    mock_session = MagicMock()
    with patch("crossplay.automation.driver.webdriver.Remote", return_value=mock_session) as mock_remote:
        driver = CrossplayDriver(host="http://localhost:4723", udid="fake-udid", bundle_id="com.test.app")
        driver.start()
        assert mock_remote.called
        caps = mock_remote.call_args[1]["options"].to_capabilities()
        assert caps["appium:udid"] == "fake-udid"
        assert caps["appium:bundleId"] == "com.test.app"


def test_driver_quit_closes_session():
    mock_session = MagicMock()
    with patch("crossplay.automation.driver.webdriver.Remote", return_value=mock_session):
        driver = CrossplayDriver(host="http://localhost:4723", udid="fake-udid", bundle_id="com.test.app")
        driver.start()
        driver.stop()
        mock_session.quit.assert_called_once()


def test_from_env_reads_environment(monkeypatch):
    monkeypatch.setenv("APPIUM_HOST", "http://192.168.1.1:4723")
    monkeypatch.setenv("DEVICE_UDID", "test-device-udid")
    monkeypatch.setenv("BUNDLE_ID", "com.test.app")
    driver = CrossplayDriver.from_env()
    assert driver._host == "http://192.168.1.1:4723"
    assert driver._udid == "test-device-udid"
    assert driver._bundle_id == "com.test.app"
