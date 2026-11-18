# N1 · Latency instrumentation

## Goal
Timestamp every stage of a turn so later features have before/after numbers. This is the measuring tool for N2–N8.

## Stages to time
| Stage | Start | End |
|---|---|---|
| VAD tail | last voiced frame | utterance end detected |
| STT RTT | WAV upload starts | transcript received |
| Memory context | context build starts | context ready (`light` / `full`) |
| LLM | request sent | reply received |
| TTS | request sent | MP3 received |
| WS delivery | `audio` sent | client receives it |
| Playback start | client receives audio | audio starts playing |
| **Total voice-to-voice** | end of user speech | playback start |

Plus WS ping RTT (client ↔ server).

## Implementation notes
Phase A (measurement for the baseline) is in; phase B (live panel, round-trip time) comes after the baseline is recorded.

- **Server marks** (`server/metrics.py`, `TurnTimer`): `speech_end` (last loud mic frame, computed in `record_utterance` as now − trailing silence), `vad_end`, `stt_done` (`speechToText.py`), then `memory_done`, `llm_done`, `tts_done`, `audio_sent` (`voice_chat.py`). Each turn prints a `(latency: ...)` line.
- **`playback_started` message** (client → server): `{"type": "playback_started", "recv_ts": <ms>, "play_ts": <ms>, "blocked"?: true}`. `recv_ts` is taken when the `audio` WS message arrives, `play_ts` on the audio element's `playing` event. `blocked` marks clips held by autoplay until a click; those rows are flagged.
- **Clock alignment**: browser `Date.now()` and Python `time.time()` read the same Windows clock, so they are compared directly. Valid only with client and server on one machine. For N4 (phone client) estimate the clock offset from ping round trips (NTP-style: offset ≈ ((t1 − t0) + (t2 − t3)) / 2).
- **CSV**: one row per turn, appended to `findings/data/N1-baseline-<YYYY-MM-DD>.csv` (override with `METRICS_CSV` in `server/.env`, e.g. for `N2-after-...` runs). Columns: `run, turn, memory_mode, user_chars, reply_chars, mp3_bytes, vad_tail_ms, stt_ms, memory_ms, llm_ms, tts_ms, ws_delivery_ms, playback_start_ms, total_ms, notes`. `run` is the server start time. `notes` flags `autoplay_blocked`, `no_ui_or_timeout`, `no_playback_report`, `tts_failed`, `no_tts`.
- **Stage boundaries**: memory = transcript back → context ready (includes the status/chat emits, which are sub-ms); WS delivery = just before `emit_audio` → browser receives it (includes base64 encoding and JSON); playback start = receive → `playing` (includes base64 decode and MP3 decode).
- **Summary**: `python metrics_summary.py [csv ...]` in `server/` prints n, median, p90, and share of total as a markdown table; flagged rows are skipped.
- **`metrics` message type / UI network panel / WS RTT**: phase B. RTT can come from `websockets` keepalive pings (`connection.latency`).

## Results: baseline (current code)
n = · date: · commit: · CSV: `data/`

| Stage | Median (ms) | p90 (ms) | Share of total |
|---|---|---|---|
| VAD tail | | | |
| STT | | | |
| Memory | | | |
| LLM | | | |
| TTS | | | |
| WS delivery | | | |
| Playback start | | | |
| **Total** | | | 100% |

WS RTT median:

## Analysis
Which stage dominates? What does that imply for N2/N3 priorities?

## Issues / caveats
-
