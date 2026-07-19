from dataclasses import dataclass, field


Matrix = list[list[int]]


@dataclass(slots=True)
class TileRange:
    id: str
    generation_start: int
    generation_end: int = 10
    halo: int = 10
    parent_id: str | None = None
    region_id: int = 0
    offset_row: int = 0
    offset_col: int = 0
    generations: dict[int, Matrix] = field(default_factory=dict)
