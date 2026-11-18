"""Summarize latency CSVs as a markdown table (median, p90, share of total).

Usage (from server/):
  python metrics_summary.py                 # newest findings/data/*.csv
  python metrics_summary.py a.csv b.csv     # combine specific files

Rows with any note (autoplay blocked, no UI, TTS failed, ...) or no total are skipped.
Streaming (N3) detail columns get a second table when present.
"""

import csv
import glob
import os
import statistics
import sys

from metrics import DATA_DIR, DETAIL_STAGES, STAGES

LABELS = {
    "vad_tail_ms": "VAD tail",
    "stt_ms": "STT",
    "memory_ms": "Memory",
    "llm_ms": "LLM",
    "tts_ms": "TTS",
    "ws_delivery_ms": "WS delivery",
    "playback_start_ms": "Playback start",
    "total_ms": "**Total**",
    "tts_ttfb_ms": "TTS first byte (after text ready)",
    "llm_ttft_ms": "LLM first token",
    "first_sentence_ms": "LLM first sentence",
}


def load_rows(paths: list[str]) -> tuple[list[dict], int]:
    rows, skipped = [], 0
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
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
        candidates = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")), key=os.path.getmtime)
        if not candidates:
            sys.exit(f"No CSV in {os.path.normpath(DATA_DIR)}")
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

    detail = [(c, [float(r[c]) for r in rows if r.get(c)]) for c, _s, _e in DETAIL_STAGES]
    detail = [(c, v) for c, v in detail if v]
    if detail:
        print()
        print("| Streaming detail | Median (ms) | p90 (ms) |")
        print("|---|---|---|")
        for column, values in detail:
            print(f"| {LABELS[column]} | {statistics.median(values):.0f} | {p90(values):.0f} |")
    for column, label in (("chunks", "chunks per reply"), ("first_chunk_bytes", "first chunk bytes"),
                          ("sentences", "sentences per reply")):
        values = [float(r[column]) for r in rows if r.get(column)]
        if values:
            print(f"{label}: median {statistics.median(values):.0f}, p90 {p90(values):.0f}")

    ws_bytes = [float(r["ws_bytes"]) for r in rows if r.get("ws_bytes")]
    mp3_bytes = [float(r["mp3_bytes"]) for r in rows if r.get("mp3_bytes")]
    handshakes = [float(r["tts_handshake_ms"]) for r in rows if r.get("tts_handshake_ms")]
    if ws_bytes or handshakes:
        print()
    if ws_bytes:
        ratio = statistics.median(ws_bytes) / statistics.median(mp3_bytes)
        print(
            f"WS audio payload: median {statistics.median(ws_bytes):.0f} bytes "
            f"({ratio:.0%} of median MP3 {statistics.median(mp3_bytes):.0f} bytes)"
        )
    if handshakes:
        new = [h for h in handshakes if h > 0]
        detail = f", median {statistics.median(new):.0f} ms when new" if new else ""
        print(f"TTS new connections: {len(new)} of {len(handshakes)} turns{detail}")


if __name__ == "__main__":
    main()
