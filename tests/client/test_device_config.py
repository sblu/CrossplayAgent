import json

from crossplay.client.device_config import (
    DEFAULT_BUTTONS, DEFAULT_PIXEL_SCALE, DeviceConfig, update_calibration_file,
)
from crossplay.vision.calibration import Calibration


def test_defaults_match_historical_ios_values():
    cfg = DeviceConfig()
    assert cfg.pixel_scale == DEFAULT_PIXEL_SCALE == 3
    assert len(cfg.rack_cells) == 7
    assert cfg.submit == tuple(DEFAULT_BUTTONS["submit"])
    assert cfg.more == tuple(DEFAULT_BUTTONS["more"])


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = DeviceConfig.load(str(tmp_path / "nope.json"))
    assert cfg.pixel_scale == 3
    assert cfg.keepalive == tuple(DEFAULT_BUTTONS["keepalive"])


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "cal.json")
    cfg = DeviceConfig(pixel_scale=2, rack_cells=[[1, 2, 3, 4]],
                       buttons={"submit": [10, 20], "more": [5, 6], "keepalive": [7, 8]})
    cfg.save(path)

    loaded = DeviceConfig.load(path)
    assert loaded.pixel_scale == 2
    assert loaded.rack_cells == [[1, 2, 3, 4]]
    assert loaded.submit == (10, 20)


def test_platform_roundtrip_and_preserved_on_blank_save(tmp_path):
    # The platform ("android"/"ios") persists and round-trips.
    path = str(tmp_path / "cal.json")
    DeviceConfig(platform="android", pixel_scale=1).save(path)
    assert DeviceConfig.load(path).platform == "android"

    # A later save that omits platform (default "") must NOT wipe the stored value.
    DeviceConfig(pixel_scale=2).save(path)
    reloaded = DeviceConfig.load(path)
    assert reloaded.platform == "android" and reloaded.pixel_scale == 2


def test_algorithm_roundtrip_and_preserved_on_blank_save(tmp_path):
    path = str(tmp_path / "cal.json")
    DeviceConfig(algorithm="heuristic", pixel_scale=1).save(path)
    assert DeviceConfig.load(path).algorithm == "heuristic"
    # A later save that omits algorithm (default "") must not wipe it.
    DeviceConfig(pixel_scale=2).save(path)
    reloaded = DeviceConfig.load(path)
    assert reloaded.algorithm == "heuristic" and reloaded.pixel_scale == 2


def test_device_save_preserves_board_geometry(tmp_path):
    path = str(tmp_path / "cal.json")
    Calibration(board_x=27, board_y=800, board_width=1158, board_height=1150).save(path)

    DeviceConfig(pixel_scale=2).save(path)

    # Board geometry survives, and Calibration still loads despite the extra keys.
    data = json.loads(open(path).read())
    assert data["board_x"] == 27 and data["pixel_scale"] == 2
    cal = Calibration.load(path)
    assert cal.board_width == 1158


def test_board_save_merged_preserves_device_keys(tmp_path):
    path = str(tmp_path / "cal.json")
    DeviceConfig(pixel_scale=2).save(path)

    Calibration(board_x=1, board_y=2, board_width=3, board_height=4).save_merged(path)

    data = json.loads(open(path).read())
    assert data["pixel_scale"] == 2 and data["board_x"] == 1


def test_update_calibration_file_merges(tmp_path):
    path = str(tmp_path / "cal.json")
    update_calibration_file(path, board_x=5)
    update_calibration_file(path, pixel_scale=4)
    data = json.loads(open(path).read())
    assert data == {"board_x": 5, "pixel_scale": 4}
