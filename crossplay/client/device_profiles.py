"""Named device profiles — a versioned library of per-device perception assets.

Each phone renders the Crossplay board differently (screen size, tile font, tap
targets), so calibration + letter templates are device-specific. Historically the
active `data/calibration/calibration.json` was git-ignored and easy to lose or to
run against the wrong device's templates. This module makes those assets a
*tracked library* under `data/devices/<slug>/` and lets you switch between them.

A profile directory holds:
    device.json        {"name", "platform", "pixel_scale", "notes"}
    calibration.json   board geometry + rack_cells + buttons + pixel_scale
    templates/         rack letter PNGs (optional — Android reads via OCR)
    board_templates/   board letter PNGs (optional)
    reference.png      one full screenshot (optional)

"Activating" a profile copies its files into the active working locations
(`data/calibration/`, `data/templates/`, `data/board_templates/`) and reloads the
in-process template caches. The library is the source of truth; the active copy is
yours to tweak, then `save_active_as_profile()` writes it back for committing.
"""
import json
import shutil
from pathlib import Path

from crossplay.client.device_config import DeviceConfig, update_calibration_file

DEVICES_DIR = Path("data/devices")
ACTIVE_CAL = Path("data/calibration/calibration.json")
ACTIVE_TEMPLATES = Path("data/templates")
ACTIVE_BOARD_TEMPLATES = Path("data/board_templates")

# Stored in the active calibration.json so the UI can show which profile is live.
_ACTIVE_KEY = "device_profile"


def _has_pngs(d: Path) -> bool:
    return d.is_dir() and any(d.glob("*.png"))


def _read_device_json(profile_dir: Path) -> dict:
    f = profile_dir / "device.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (ValueError, OSError):
            pass
    return {}


def active_slug() -> str:
    """The slug of the currently-active profile, or "" if none recorded."""
    if not ACTIVE_CAL.exists():
        return ""
    try:
        return str(json.loads(ACTIVE_CAL.read_text()).get(_ACTIVE_KEY, ""))
    except (ValueError, OSError):
        return ""


def list_profiles() -> list[dict]:
    """All profiles in the library (any subdir with a calibration.json), sorted by
    display name. Each entry describes what the profile ships and whether it's active.
    """
    if not DEVICES_DIR.is_dir():
        return []
    active = active_slug()
    out = []
    for d in sorted(DEVICES_DIR.iterdir()):
        if not d.is_dir() or not (d / "calibration.json").exists():
            continue
        meta = _read_device_json(d)
        ref = next((p.name for p in (d / "reference.png",) if p.exists()), None)
        out.append({
            "slug": d.name,
            "name": meta.get("name", d.name),
            "platform": meta.get("platform", ""),
            "pixel_scale": meta.get("pixel_scale"),
            "notes": meta.get("notes", ""),
            "has_templates": _has_pngs(d / "templates"),
            "has_board_templates": _has_pngs(d / "board_templates"),
            "reference": ref,
            "active": d.name == active,
        })
    out.sort(key=lambda p: p["name"].lower())
    return out


def _replace_dir(src: Path, dst: Path) -> int:
    """Clear dst and copy src into it. Returns number of PNGs copied."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return len(list(dst.glob("*.png")))


def activate_profile(slug: str) -> dict:
    """Copy a profile's assets into the active working locations and reload caches.

    Calibration is always copied. templates/ and board_templates/ are copied only
    if the profile ships them (an Android profile legitimately ships none, since
    Android reads letters via OCR). Returns a summary of what was copied.
    """
    profile = DEVICES_DIR / slug
    cal = profile / "calibration.json"
    if not cal.exists():
        raise ValueError(f"unknown device profile {slug!r}")

    ACTIVE_CAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cal, ACTIVE_CAL)

    summary = {"slug": slug, "calibration": True, "templates": 0, "board_templates": 0}
    if _has_pngs(profile / "templates"):
        summary["templates"] = _replace_dir(profile / "templates", ACTIVE_TEMPLATES)
    if _has_pngs(profile / "board_templates"):
        summary["board_templates"] = _replace_dir(profile / "board_templates", ACTIVE_BOARD_TEMPLATES)

    # Record the active profile and refresh the in-process template caches so a
    # running dashboard picks up the new glyphs without a restart.
    update_calibration_file(ACTIVE_CAL, **{_ACTIVE_KEY: slug})
    from crossplay.vision import tile_detector
    tile_detector.reload_templates()
    tile_detector.reload_board_templates()
    return summary


def save_active_as_profile(slug: str, name: str = "", notes: str = "",
                           reference: str | Path | None = None) -> dict:
    """Persist the current active config + templates into data/devices/<slug>/.

    Writes device.json (platform + pixel_scale read from the active DeviceConfig),
    calibration.json, and copies the active templates/board_templates and an
    optional reference screenshot. The caller then `git add`s the new directory.
    """
    if not slug or "/" in slug or slug.startswith("."):
        raise ValueError(f"invalid profile slug {slug!r}")
    if not ACTIVE_CAL.exists():
        raise ValueError("no active calibration to save")

    dest = DEVICES_DIR / slug
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ACTIVE_CAL, dest / "calibration.json")

    dev = DeviceConfig.load(ACTIVE_CAL)
    (dest / "device.json").write_text(json.dumps({
        "name": name or slug,
        "platform": dev.platform,
        "pixel_scale": dev.pixel_scale,
        "notes": notes,
    }, indent=2))

    summary = {"slug": slug, "templates": 0, "board_templates": 0, "reference": False}
    if _has_pngs(ACTIVE_TEMPLATES):
        summary["templates"] = _replace_dir(ACTIVE_TEMPLATES, dest / "templates")
    if _has_pngs(ACTIVE_BOARD_TEMPLATES):
        summary["board_templates"] = _replace_dir(ACTIVE_BOARD_TEMPLATES, dest / "board_templates")
    if reference and Path(reference).exists():
        shutil.copyfile(reference, dest / "reference.png")
        summary["reference"] = True
    return summary
