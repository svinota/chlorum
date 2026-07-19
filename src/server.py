from collections import deque
import asyncio
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from data import Matrix, TileRange


@dataclass(slots=True)
class QueueState:
    tasks: deque[TileRange] = field(default_factory=deque)
    task_ready: asyncio.Condition = field(default_factory=asyncio.Condition)
    ready_answers: dict[str, TileRange] = field(default_factory=dict)
    pending_answers: dict[str, dict[int, TileRange]] = field(
        default_factory=dict
    )
    answer_ready: asyncio.Condition = field(default_factory=asyncio.Condition)


state = QueueState()
app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/task")
async def get_task() -> dict:
    async with state.task_ready:
        while not state.tasks:
            await state.task_ready.wait()

        task = state.tasks.popleft()
        return jsonable_encoder(asdict(task))


@app.post("/task/new")
async def post_task_new(task: TileRange) -> dict:
    full_matrix = _get_generation_matrix(task, task.generation_start)
    if full_matrix is None:
        raise HTTPException(
            status_code=400, detail="task must contain start generation"
        )

    regions = split_task_into_regions(task, full_matrix)
    state.tasks.extend(regions)
    async with state.task_ready:
        state.task_ready.notify_all()
    return {
        "status": "queued",
        "tasks_size": len(state.tasks),
        "regions_size": len(regions),
    }


@app.post("/task/ready")
async def post_task_ready(answer: TileRange) -> dict:
    if answer.parent_id is None:
        async with state.answer_ready:
            state.ready_answers[answer.id] = answer
            state.answer_ready.notify_all()
        return {"status": "queued", "answers_size": len(state.ready_answers)}

    bucket = state.pending_answers.setdefault(answer.parent_id, {})
    bucket[answer.region_id] = answer

    if len(bucket) < 4:
        return {
            "status": "pending",
            "received_regions": len(bucket),
            "answers_size": len(state.ready_answers),
        }

    merged = merge_region_answers(answer.parent_id, bucket)
    async with state.answer_ready:
        state.ready_answers[merged.parent_id or merged.id] = merged
        state.answer_ready.notify_all()
    del state.pending_answers[answer.parent_id]
    return {"status": "merged", "answers_size": len(state.ready_answers)}


@app.get("/dashboard")
def dashboard() -> HTMLResponse:
    html = (BASE_DIR / "templates" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    return HTMLResponse(content=html)


@app.get("/dashboard/stats")
def dashboard_stats() -> dict:
    return jsonable_encoder(serialize_queue())


@app.get("/stats")
def stats() -> dict:
    return jsonable_encoder(serialize_queue())


@app.get("/answer/{parent_id}")
async def get_answer_for_parent(parent_id: str) -> dict:
    async with state.answer_ready:
        while parent_id not in state.ready_answers and not any(
            answer.parent_id == parent_id
            for answer in state.ready_answers.values()
        ):
            await state.answer_ready.wait()

        for key, answer in list(state.ready_answers.items()):
            if answer.parent_id == parent_id or answer.id == parent_id:
                del state.ready_answers[key]
                return jsonable_encoder(asdict(answer))

    raise HTTPException(status_code=404, detail="answer for parent not found")


def enqueue_task(
    generation_start: int,
    generation_end: int,
    halo: int,
    generations: dict[int, Matrix],
    ) -> TileRange:
    task = TileRange(
        id=str(uuid4()),
        generation_start=generation_start,
        generation_end=generation_end,
        halo=halo,
        generations=generations,
    )
    state.tasks.append(task)
    return task


def _get_generation_matrix(task: TileRange, generation: int) -> Matrix | None:
    return task.generations.get(generation) or task.generations.get(
        str(generation)
    )


def _slice_with_halo(
    matrix: Matrix,
    row_start: int,
    row_end: int,
    col_start: int,
    col_end: int,
    halo: int,
) -> Matrix:
    row_from = row_start - halo
    row_to = row_end + halo
    col_from = col_start - halo
    col_to = col_end + halo
    result: Matrix = []

    for row in range(row_from, row_to):
        result_row: list[int] = []
        for col in range(col_from, col_to):
            if 0 <= row < len(matrix) and 0 <= col < len(matrix[0]):
                result_row.append(matrix[row][col])
            else:
                result_row.append(0)
        result.append(result_row)

    return result


def split_task_into_regions(
    task: TileRange, matrix: Matrix
) -> list[TileRange]:
    height = len(matrix)
    width = len(matrix[0]) if matrix else 0
    row_mid = height // 2
    col_mid = width // 2
    regions: list[TileRange] = []

    specs = (
        (0, 0, row_mid, 0, col_mid),
        (1, 0, row_mid, col_mid, width),
        (2, row_mid, height, 0, col_mid),
        (3, row_mid, height, col_mid, width),
    )

    for region_id, row_start, row_end, col_start, col_end in specs:
        region_matrix = _slice_with_halo(
            matrix,
            row_start,
            row_end,
            col_start,
            col_end,
            task.halo,
        )
        regions.append(
            TileRange(
                id=uuid4(),
                parent_id=task.id,
                region_id=region_id,
                offset_row=row_start,
                offset_col=col_start,
                generation_start=task.generation_start,
                generation_end=task.generation_end,
                halo=task.halo,
                generations={task.generation_start: region_matrix},
            )
        )

    return regions


def merge_region_answers(
    parent_id: str, regions: dict[int, TileRange]
) -> TileRange:
    ordered_regions = [regions[index] for index in range(4)]
    template = ordered_regions[0]
    generations: dict[int, Matrix] = {}

    for generation in range(
        template.generation_start, template.generation_end + 1
    ):
        full_height = max(
            region.offset_row
            + len(_trim_halo_for_generation(region, generation))
            for region in ordered_regions
        )
        full_width = max(
            region.offset_col
            + len(_trim_halo_for_generation(region, generation)[0])
            for region in ordered_regions
        )
        merged_generation: Matrix = [
            [0 for _ in range(full_width)] for _ in range(full_height)
        ]

        for region in ordered_regions:
            trimmed = _trim_halo_for_generation(region, generation)
            for row_index, row in enumerate(trimmed):
                for col_index, value in enumerate(row):
                    merged_generation[region.offset_row + row_index][
                        region.offset_col + col_index
                    ] = value

        generations[generation] = merged_generation

    return TileRange(
        id=parent_id,
        parent_id=parent_id,
        generation_start=template.generation_start,
        generation_end=template.generation_end,
        halo=template.halo,
        generations=generations,
    )


def _trim_halo_for_generation(region: TileRange, generation: int) -> Matrix:
    matrix = _get_generation_matrix(region, generation)
    if matrix is None:
        return []

    top = region.halo
    left = region.halo
    bottom = len(matrix) - region.halo
    right = len(matrix[0]) - region.halo if matrix else 0
    return [row[left:right] for row in matrix[top:bottom]]


def serialize_queue() -> dict:
    return {
        "tasks_size": len(state.tasks),
        "answers_size": len(state.ready_answers),
        "tasks": [asdict(task) for task in state.tasks],
        "answers": [asdict(answer) for answer in state.ready_answers.values()],
    }
