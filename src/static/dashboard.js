const SIZE = 100;
const GENERATIONS_WINDOW = 10;
const FRAME_DELAY = 500;

const board = document.getElementById("board");
const submitBtn = document.getElementById("submit-btn");
const clearBtn = document.getElementById("clear-btn");
const stopBtn = document.getElementById("stop-btn");
const status = document.getElementById("status");

const matrix = Array.from({ length: SIZE }, () => Array(SIZE).fill(0));
let playbackTimer = null;
let isPlaybackRunning = false;
let frameQueue = [];
let runActive = false;
let runId = 0;
let taskInFlight = false;
let nextGenerationStart = 0;
let requestController = null;
let displayedGeneration = 0;

function lockRun() {
  submitBtn.disabled = true;
}

function unlockRun() {
  submitBtn.disabled = false;
}

function setStatus(text) {
  status.textContent = text;
}

function stopRun() {
  runActive = false;
  runId += 1;
  requestController?.abort();
  requestController = null;

  if (playbackTimer !== null) {
    clearTimeout(playbackTimer);
    playbackTimer = null;
  }

  isPlaybackRunning = false;
  taskInFlight = false;
  frameQueue = [];
  board.classList.remove("playback-disabled");
  stopBtn.disabled = true;
  unlockRun();
}

function buildPayload(seedFrame, generationStart) {
  return {
    id: crypto.randomUUID(),
    generation_start: generationStart,
    generation_end: generationStart + GENERATIONS_WINDOW,
    halo: GENERATIONS_WINDOW,
    generations: { [generationStart]: seedFrame },
  };
}

function postTask(payload, signal) {
  return fetch("/task/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

function renderMatrix(nextMatrix) {
  board.replaceChildren();

  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      const cell = document.createElement("div");
      cell.className = "cell";
      if (row === 50) cell.classList.add("region-border-top");
      if (col === 50) cell.classList.add("region-border-left");
      if (nextMatrix[row][col] === 1) {
        cell.classList.add("alive");
      }
      cell.dataset.row = String(row);
      cell.dataset.col = String(col);
      board.appendChild(cell);
    }
  }

  appendRegionOverlay();
}

function applyMatrix(nextMatrix) {
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      matrix[row][col] = nextMatrix[row][col];
    }
  }
  renderMatrix(nextMatrix);
}

function orderedGenerations(generations) {
  return Object.keys(generations)
    .map((key) => Number(key))
    .sort((a, b) => a - b)
    .map((generation) => generations[String(generation)] ?? generations[generation]);
}

async function submitTask(seedFrame, generationStart, currentRunId) {
  const payload = buildPayload(seedFrame, generationStart);
  const controller = requestController;
  taskInFlight = true;

  try {
    const submitResponse = await postTask(payload, controller.signal);
    if (!submitResponse.ok) throw new Error("Failed to submit task");

    const answerResponse = await fetch(`/answer/${payload.id}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!answerResponse.ok) throw new Error("Failed to fetch task answer");

    const answer = await answerResponse.json();
    if (!runActive || currentRunId !== runId) return;

    const frames = orderedGenerations(answer.generations);
    frameQueue.push(...frames.slice(1));
    nextGenerationStart = payload.generation_end;
  } catch (error) {
    if (error.name === "AbortError" || currentRunId !== runId) return;
    stopRun();
    setStatus(error.message);
    return;
  } finally {
    if (currentRunId === runId) {
      taskInFlight = false;
    }
  }

  maybeSubmitNextTask();
}

function maybeSubmitNextTask(fallbackFrame = null) {
  if (!runActive || taskInFlight || frameQueue.length >= GENERATIONS_WINDOW) {
    return;
  }

  const seedFrame = frameQueue.at(-1) ?? fallbackFrame;
  if (!seedFrame) return;

  submitTask(seedFrame, nextGenerationStart, runId);
}

function playbackTick() {
  if (!runActive || !isPlaybackRunning) return;

  if (frameQueue.length === 0) {
    playbackTimer = setTimeout(playbackTick, 100);
    return;
  }

  const nextFrame = frameQueue.shift();
  applyMatrix(nextFrame);
  displayedGeneration += 1;
  setStatus(`Playing ${displayedGeneration}`);
  maybeSubmitNextTask(nextFrame);
  playbackTimer = setTimeout(playbackTick, FRAME_DELAY);
}

function appendRegionOverlay() {
  if (board.querySelector(".region-divider")) return;

  const vertical = document.createElement("div");
  vertical.className = "region-divider region-divider-vertical";

  const horizontal = document.createElement("div");
  horizontal.className = "region-divider region-divider-horizontal";

  board.appendChild(vertical);
  board.appendChild(horizontal);
}

function paint(target, value) {
  if (isPlaybackRunning) return;
  const row = Number(target.dataset.row);
  const col = Number(target.dataset.col);
  matrix[row][col] = value;
  target.classList.toggle("alive", value === 1);
}

let drawing = false;
let drawValue = 1;

board.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(".cell");
  if (!target) return;
  drawing = true;
  drawValue = target.classList.contains("alive") ? 0 : 1;
  paint(target, drawValue);
  board.setPointerCapture(event.pointerId);
});

board.addEventListener("pointerover", (event) => {
  if (!drawing) return;
  const target = event.target.closest(".cell");
  if (!target) return;
  paint(target, drawValue);
});

board.addEventListener("pointerup", () => {
  drawing = false;
});

clearBtn.addEventListener("click", () => {
  if (isPlaybackRunning) return;
  for (let row = 0; row < SIZE; row += 1) {
    matrix[row].fill(0);
  }
  renderMatrix(matrix);
  setStatus("Cleared");
});

submitBtn.addEventListener("click", () => {
  runId += 1;
  runActive = true;
  taskInFlight = false;
  nextGenerationStart = 0;
  frameQueue = [];
  displayedGeneration = 0;
  requestController = new AbortController();
  isPlaybackRunning = true;

  lockRun();
  board.classList.add("playback-disabled");
  stopBtn.disabled = false;
  setStatus("Waiting for frames");

  playbackTick();
  submitTask(matrix.map((row) => [...row]), 0, runId);
});

stopBtn.addEventListener("click", () => {
  stopRun();
  renderMatrix(matrix);
  setStatus("Stopped");
});

renderMatrix(matrix);
setStatus("Ready");
unlockRun();
