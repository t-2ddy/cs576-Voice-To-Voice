"""Per-turn latency timing (N1) and CSV logging for the findings report.

Stage marks are wall-clock `time.time()` so they can be compared with the
browser's `Date.now()` (same machine only; a remote client needs a clock-offset
estimate). One CSV row per turn goes to
findings/data/N1-baseline-<YYYY-MM-DD>.csv unless METRICS_CSV overrides it.

Env (server/.env):
  METRICS_CSV  (optional output path, absolute or relative to server/)
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SERVER_DIR, "..", "findings", "data")

RUN_STARTED = datetime.now()
RUN_ID = RUN_STARTED.strftime("%Y-%m-%dT%H:%M:%S")

# (column, start mark, end mark)
STAGES = (
    ("vad_tail_ms", "speech_end", "vad_end"),
    ("stt_ms", "vad_end", "stt_done"),
    ("memory_ms", "stt_done", "memory_done"),
    ("llm_ms", "memory_done", "llm_done"),
    ("tts_ms", "llm_done", "tts_done"),
    ("ws_delivery_ms", "audio_sent", "recv"),
    ("playback_start_ms", "recv", "play"),
    ("total_ms", "speech_end", "play"),
)

COLUMNS = [
    "run",
    "turn",
    "memory_mode",
    "user_chars",
    "reply_chars",
    "mp3_bytes",
    *(name for name, _start, _end in STAGES),
    "ws_bytes",
    "tts_handshake_ms",
    "notes",
]


def csv_path() -> str:
    override = os.getenv("METRICS_CSV", "").strip()
    if override:
        return os.path.normpath(os.path.join(SERVER_DIR, override))
    name = f"N1-baseline-{RUN_STARTED:%Y-%m-%d}.csv"
    return os.path.normpath(os.path.join(DATA_DIR, name))


def _header(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f), [])


class TurnTimer:
    """Collects stage timestamps and metadata for one voice turn."""

    def __init__(self, turn: int) -> None:
        self.turn = turn
        self.marks: dict[str, float] = {}
        self.memory_mode = ""
        self.user_chars = 0
        self.reply_chars = 0
        self.mp3_bytes = 0
        self.ws_bytes: int | None = None
        self.tts_handshake_ms: int | None = None
        self.notes: list[str] = []

    def mark(self, name: str, at: float | None = None) -> None:
        self.marks[name] = time.time() if at is None else at

    def note(self, flag: str) -> None:
        if flag not in self.notes:
            self.notes.append(flag)

    def durations(self) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for name, start, end in STAGES:
            if start in self.marks and end in self.marks:
                result[name] = round((self.marks[end] - self.marks[start]) * 1000)
            else:
                result[name] = None
        return result

    def summary(self) -> str:
        d = self.durations()

        def fmt(key: str) -> str:
            value = d[key]
            return "-" if value is None else str(value)

        return (
            f"(latency: total {fmt('total_ms')} ms | vad {fmt('vad_tail_ms')} | "
            f"stt {fmt('stt_ms')} | mem {fmt('memory_ms')} | llm {fmt('llm_ms')} | "
            f"tts {fmt('tts_ms')} | ws {fmt('ws_delivery_ms')} | "
            f"play {fmt('playback_start_ms')} | tts handshake {self.tts_handshake_ms} | "
            f"ws bytes {self.ws_bytes})"
        )

    def write_row(self) -> str:
        """Append this turn to the CSV (header on first write); returns the path."""
        path = csv_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        if not new_file and _header(path) != COLUMNS:
            # Never mix column layouts in one file (e.g. an older N1 baseline CSV).
            root, ext = os.path.splitext(path)
            path = f"{root}-v{len(COLUMNS)}{ext}"
            new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        row = {
            "run": RUN_ID,
            "turn": self.turn,
            "memory_mode": self.memory_mode,
            "user_chars": self.user_chars,
            "reply_chars": self.reply_chars,
            "mp3_bytes": self.mp3_bytes,
            **{k: ("" if v is None else v) for k, v in self.durations().items()},
            "ws_bytes": "" if self.ws_bytes is None else self.ws_bytes,
            "tts_handshake_ms": "" if self.tts_handshake_ms is None else self.tts_handshake_ms,
            "notes": ";".join(self.notes),
        }
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        return path
