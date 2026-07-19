import json
import logging
import subprocess
import sys
from pathlib import Path

import requests

from data import TileRange


BASE_URL = sys.argv[1]
DAY_TIMEOUT = 24 * 60 * 60
WORKER_PATH = Path(__file__).with_name('worker.py')

logging.basicConfig(level=logging.INFO)


def fetch_task(session: requests.Session) -> dict | None:
    response = session.get(f'{BASE_URL}/task', timeout=DAY_TIMEOUT)
    response.raise_for_status()
    return response.json()


def submit_ready(session: requests.Session, payload: dict) -> None:
    response = session.post(
        f'{BASE_URL}/task/ready', json=payload, timeout=DAY_TIMEOUT
    )
    response.raise_for_status()


def run_worker(task: dict) -> dict:
    try:
        process = subprocess.run(
            [sys.executable, str(WORKER_PATH)],
            input=json.dumps(task),
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            print(exc.stderr, file=sys.stderr, end='')
        raise
    return json.loads(process.stdout)


def build_payload(tile: TileRange, generations_out: dict) -> dict:
    return {
        'id': str(tile.id),
        'generation_start': tile.generation_start,
        'generation_end': tile.generation_end,
        'halo': tile.halo,
        'parent_id': (
            str(tile.parent_id) if tile.parent_id is not None else None
        ),
        'region_id': tile.region_id,
        'offset_row': tile.offset_row,
        'offset_col': tile.offset_col,
        'generations': {
            **{str(key): value for key, value in tile.generations.items()},
            **generations_out['generations'],
        },
    }


def run_once() -> bool:
    with requests.Session() as session:
        task = fetch_task(session)
        logging.info('request was sent')
        tile = TileRange(**task)
        logging.info(f'got id={tile.id}, parent_id={tile.parent_id}')
        result = run_worker(task)
        logging.info(f'calculated generations {len(result["generations"].keys())}')
        submit_ready(session, build_payload(tile, result))
        logging.info('answer submitted')
        return True


def main() -> None:
    while True:
        run_once()


if __name__ == '__main__':
    main()
