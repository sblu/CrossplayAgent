"""Per-device tap configuration — what used to be hardcoded in ios_client.py.

Stored in the same file as the board geometry (data/calibration/calibration.json)
so one device profile lives in one place, and configurable from the dashboard's
device-setup UI rather than by editing code. Loading fills any missing field with
the historical iOS @3x defaults, so existing setups keep working unchanged.

Coordinate conventions (kept identical to the original ios_client):
  * board_* geometry and rack_cells are in PHYSICAL pixels.
  * pixel_scale converts physical px → logical points (screenshots are @Nx).
  * button coordinates (submit/more/keepalive) are in LOGICAL points.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = "data/calibration/calibration.json"

# Historical iOS @3x defaults (the values previously hardcoded in ios_client.py).
DEFAULT_PIXEL_SCALE = 3
DEFAULT_RACK_CELLS = [
    [12, 2133, 156, 157], [183, 2133, 156, 157], [353, 2133, 157, 157],
    [524, 2133, 157, 157], [695, 2133, 157, 157], [866, 2133, 156, 157],
    [1037, 2133, 156, 157],
]
DEFAULT_BUTTONS = {"submit": [311, 810], "more": [38, 810], "keepalive": [300, 130]}

# Keys this model owns within the shared calibration file.
_DEVICE_KEYS = ("platform", "pixel_scale", "rack_cells", "buttons")


def update_calibration_file(path: str | Path, **fields) -> None:
    """Merge `fields` into the JSON calibration file, preserving other keys."""
    p = Path(path)
    data = json.loads(p.read_text()) if p.exists() else {}
    data.update(fields)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


@dataclass
class DeviceConfig:
    platform: str = ""          # "android" | "ios" — which device this profile targets
    pixel_scale: int = DEFAULT_PIXEL_SCALE
    rack_cells: list[list[int]] = field(default_factory=lambda: [c[:] for c in DEFAULT_RACK_CELLS])
    buttons: dict[str, list[int]] = field(default_factory=lambda: {k: v[:] for k, v in DEFAULT_BUTTONS.items()})

    # Convenience accessors for the three known buttons (logical points).
    @property
    def submit(self) -> tuple[int, int]:
        return tuple(self.buttons.get("submit", DEFAULT_BUTTONS["submit"]))

    @property
    def more(self) -> tuple[int, int]:
        return tuple(self.buttons.get("more", DEFAULT_BUTTONS["more"]))

    @property
    def keepalive(self) -> tuple[int, int]:
        return tuple(self.buttons.get("keepalive", DEFAULT_BUTTONS["keepalive"]))

    @property
    def recall(self) -> tuple[int, int] | None:
        """Recall-tiles button (Android). None if not calibrated for this device."""
        v = self.buttons.get("recall")
        return tuple(v) if v else None

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "DeviceConfig":
        p = Path(path)
        data = json.loads(p.read_text()) if p.exists() else {}
        cfg = cls()
        if "platform" in data:
            cfg.platform = str(data["platform"])
        if "pixel_scale" in data:
            cfg.pixel_scale = int(data["pixel_scale"])
        if "rack_cells" in data:
            cfg.rack_cells = [list(map(int, c)) for c in data["rack_cells"]]
        if "buttons" in data:
            cfg.buttons = {k: list(map(int, v)) for k, v in data["buttons"].items()}
        return cfg

    def save(self, path: str | Path = DEFAULT_PATH) -> None:
        fields = dict(
            pixel_scale=self.pixel_scale,
            rack_cells=self.rack_cells,
            buttons=self.buttons,
        )
        if self.platform:          # only write when set, so a save without it
            fields["platform"] = self.platform   # doesn't wipe an existing value
        update_calibration_file(path, **fields)
