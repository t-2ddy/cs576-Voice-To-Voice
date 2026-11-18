"""Summarize N1 latency CSVs as a markdown table (median, p90, share of total).

Usage (from server/):
  python metrics_summary.py                 # newest findings/data/N1-*.csv
  python metrics_summary.py a.csv b.csv     # combine specific files

Rows with any note (autoplay blocked, no UI, TTS failed, ...) or no total are skipped.
"""

import csv
import glob
import os
import statistics
import sys

from metrics import DATA_DIR, STAGES

LABELS = {
    "vad_tail_ms": "VAD tail",
    "stt_ms": "STT",
    "memory_ms": "Memory",
    "llm_ms": "LLM",
    "tts_ms": "TTS",
    "ws_delivery_ms": "WS delivery",
    "playback_start_ms": "Playback start",
    "total_ms": "**Total**",
}


def load_rows(paths: list[str]) -> tuple[list[dict], int]:
    rows, skipped = [], 0
    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("notes") or not row.get("total_ms"):
                    skipped += 1
                else:
                    rows.append(row)
    return rows, skipped


def p90(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return statistics.quantiles(values, n=10, method="inclusive")[8]


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        candidates = sorted(glob.glob(os.path.join(DATA_DIR, "N1-*.csv")), key=os.path.getmtime)
        if not candidates:
            sys.exit(f"No N1-*.csv in {os.path.normpath(DATA_DIR)}")
        paths = [candidates[-1]]

    rows, skipped = load_rows(paths)
    if not rows:
        sys.exit(f"No usable rows ({skipped} skipped)")

    runs = {r["run"] for r in rows}
    print(f"n = {len(rows)} turns across {len(runs)} run(s), {skipped} skipped")
    print("files: " + ", ".join(os.path.basename(p) for p in paths))
    print()
    print("| Stage | Median (ms) | p90 (ms) | Share of total |")
    print("|---|---|---|---|")
    total_median = statistics.median(float(r["total_ms"]) for r in rows)
    for column, _start, _end in STAGES:
        values = [float(r[column]) for r in rows if r.get(column)]
        if not values:
            print(f"| {LABELS[column]} | | | |")
            continue
        median = statistics.median(values)
        share = "100%" if column == "total_ms" else f"{median / total_median:.0%}"
        print(f"| {LABELS[column]} | {median:.0f} | {p90(values):.0f} | {share} |")


if __name__ == "__main__":
    main()
