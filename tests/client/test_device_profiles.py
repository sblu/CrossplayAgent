"""Unit tests for the device-profile library (list / activate / save round-trip).

The module uses fixed working-copy paths, so each test redirects them at a tmp
directory to stay isolated from the real data/ tree.
"""
import json

import pytest

from crossplay.client import device_profiles as dp


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    devices = tmp_path / "devices"
    active_cal = tmp_path / "calibration" / "calibration.json"
    active_tmpl = tmp_path / "templates"
    active_board = tmp_path / "board_templates"
    monkeypatch.setattr(dp, "DEVICES_DIR", devices)
    monkeypatch.setattr(dp, "ACTIVE_CAL", active_cal)
    monkeypatch.setattr(dp, "ACTIVE_TEMPLATES", active_tmpl)
    monkeypatch.setattr(dp, "ACTIVE_BOARD_TEMPLATES", active_board)
    return tmp_path


def _make_profile(devices, slug, *, platform, with_templates, name=None):
    d = devices / slug
    (d / "templates").mkdir(parents=True) if with_templates else d.mkdir(parents=True)
    (d / "calibration.json").write_text(json.dumps({
        "board_x": 1, "board_y": 2, "board_width": 30, "board_height": 30,
        "grid_size": 15, "pixel_scale": 2 if platform == "ios" else 1,
        "rack_cells": [[0, 0, 5, 5]], "buttons": {"submit": [1, 1]},
        "platform": platform,
    }))
    (d / "device.json").write_text(json.dumps({
        "name": name or slug, "platform": platform, "pixel_scale": 1, "notes": ""}))
    if with_templates:
        (d / "templates" / "A.png").write_bytes(b"\x89PNG\r\n")   # stand-in PNG
    return d


def test_list_profiles_sorted_and_described(sandbox):
    _make_profile(sandbox / "devices", "zeta", platform="android", with_templates=False, name="Zeta")
    _make_profile(sandbox / "devices", "alpha", platform="ios", with_templates=True, name="Alpha")
    profiles = dp.list_profiles()
    assert [p["slug"] for p in profiles] == ["alpha", "zeta"]      # sorted by name
    alpha = profiles[0]
    assert alpha["platform"] == "ios" and alpha["has_templates"] is True
    assert profiles[1]["has_templates"] is False


def test_activate_copies_calibration_and_records_active(sandbox):
    _make_profile(sandbox / "devices", "alpha", platform="ios", with_templates=True)
    summary = dp.activate_profile("alpha")
    assert summary["calibration"] and summary["templates"] == 1
    assert dp.ACTIVE_CAL.exists()
    cal = json.loads(dp.ACTIVE_CAL.read_text())
    assert cal["platform"] == "ios" and cal["device_profile"] == "alpha"
    assert (dp.ACTIVE_TEMPLATES / "A.png").exists()
    assert dp.active_slug() == "alpha"
    assert [p["active"] for p in dp.list_profiles()] == [True]


def test_activate_without_templates_leaves_active_untouched(sandbox):
    # An Android profile ships no templates; activating it must not wipe whatever
    # templates are currently active.
    dp.ACTIVE_TEMPLATES.mkdir(parents=True)
    (dp.ACTIVE_TEMPLATES / "keep.png").write_bytes(b"x")
    _make_profile(sandbox / "devices", "droid", platform="android", with_templates=False)
    summary = dp.activate_profile("droid")
    assert summary["templates"] == 0
    assert (dp.ACTIVE_TEMPLATES / "keep.png").exists()             # untouched


def test_activate_unknown_slug_raises(sandbox):
    (sandbox / "devices").mkdir()
    with pytest.raises(ValueError):
        dp.activate_profile("ghost")


def test_save_active_as_profile_round_trip(sandbox):
    _make_profile(sandbox / "devices", "alpha", platform="ios", with_templates=True)
    dp.activate_profile("alpha")
    out = dp.save_active_as_profile("alpha-copy", name="Copy", notes="cloned")
    assert out["templates"] == 1
    saved = sandbox / "devices" / "alpha-copy"
    assert (saved / "calibration.json").exists()
    meta = json.loads((saved / "device.json").read_text())
    assert meta["name"] == "Copy" and meta["platform"] == "ios"
    assert {p["slug"] for p in dp.list_profiles()} == {"alpha", "alpha-copy"}


def test_save_rejects_bad_slug(sandbox):
    dp.ACTIVE_CAL.parent.mkdir(parents=True)
    dp.ACTIVE_CAL.write_text("{}")
    with pytest.raises(ValueError):
        dp.save_active_as_profile("../escape")
