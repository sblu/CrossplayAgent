import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Calibration:
    board_x: int
    board_y: int
    board_width: int
    board_height: int
    grid_size: int = 15

    def pixel_to_cell(self, x: int, y: int) -> tuple[int, int]:
        cell_w = self.board_width / self.grid_size
        cell_h = self.board_height / self.grid_size
        col = int((x - self.board_x) / cell_w)
        row = int((y - self.board_y) / cell_h)
        return (max(0, min(row, 14)), max(0, min(col, 14)))

    def cell_center_pixel(self, row: int, col: int) -> tuple[int, int]:
        cell_w = self.board_width / self.grid_size
        cell_h = self.board_height / self.grid_size
        x = int(self.board_x + (col + 0.5) * cell_w)
        y = int(self.board_y + (row + 0.5) * cell_h)
        return x, y

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        data = json.loads(Path(path).read_text())
        return cls(**data)
