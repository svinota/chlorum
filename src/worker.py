import json
import sys

import numpy as np

from data import Matrix


def neighbors(grid: np.ndarray) -> np.ndarray:
    return sum(
        np.roll(np.roll(grid, dx, axis=0), dy, axis=1)
        for dx, dy in (
            (-1, -1),
            (-1, 0),
            (-1, 1),
            (0, -1),
            (0, 1),
            (1, -1),
            (1, 0),
            (1, 1),
        )
    )


def next_generation(grid: np.ndarray) -> np.ndarray:
    counts = neighbors(grid)
    alive = grid == 1
    born = (~alive) & (counts == 3)
    survive = alive & ((counts == 2) | (counts == 3))
    return np.where(born | survive, 1, 0).astype(np.int8)


def build_generations(
    start_grid: Matrix, generation_start: int, generation_end: int
) -> dict[int, Matrix]:
    grid = np.array(start_grid, dtype=np.int8)
    generations: dict[int, list[list[int]]] = {generation_start: grid.tolist()}

    for generation in range(generation_start + 1, generation_end + 1):
        grid = next_generation(grid)
        generations[generation] = grid.tolist()

    return generations


def main() -> None:
    task = json.load(sys.stdin)
    start_grid = task["generations"][str(task["generation_start"])]
    generations = build_generations(
        start_grid,
        task["generation_start"],
        task["generation_end"],
    )
    json.dump(
        {
            "generations": {
                str(key): value for key, value in generations.items()
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
