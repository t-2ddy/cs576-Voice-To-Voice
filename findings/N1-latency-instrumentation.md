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
n = 29 turns (3 runs of the 10-line script, 1 turn excluded) · date: 2026-11-17 · commit: `deaae25` · CSV: `data/N1-baseline-2026-11-17.csv` · `VAD_SILENCE_END_MS=1200`, client and server on one machine (loopback)

| Stage | Median (ms) | p90 (ms) | Share of total |
|---|---|---|---|
| VAD tail | 1200 | 1200 | 33% |
| STT | 758 | 1069 | 21% |
| Memory | 158 | 461 | 4% |
| LLM | 1062 | 1226 | 29% |
| TTS | 403 | 539 | 11% |
| WS delivery | 3 | 5 | 0% |
| Playback start | 2 | 3 | 0% |
| **Total** | 3675 | 4107 | 100% |

Shares are each stage's median divided by the total's median, so they don't sum to exactly 100%.

Supporting numbers from the same CSV:
- Memory: median 423 ms on `full` turns (embedding + `match_memory` RPC) vs 132 ms on `light` turns. The first turn of each run is also slower (299–413 ms) because the session cache for facts + summary starts cold.
- Hosted API calls (STT + memory + LLM + TTS) together: median 2470 ms, about two thirds of the total.
- MP3 size: median 77 KB (max 193 KB) for a median 78-character reply. Base64 inflates that to about 103 KB per `audio` message.
- TTS time tracks clip size closely (correlation 0.86 with MP3 bytes); STT time only loosely tracks utterance length (0.51 with user characters).

WS RTT median: not measured yet (phase B).

## Analysis
- **Waiting on hosted APIs dominates.** STT, the reply model, and TTS are three sequential HTTPS round trips and make up about 60% of the total. The reply model is the single largest API stage (~1.1 s).
- **The VAD tail is a third of the total, and it's pure configuration.** It's exactly `VAD_SILENCE_END_MS`, because the detector always ends after that many quiet frames. Every 100 ms cut there is 100 ms off every turn, traded against splitting turns at natural pauses.
- **The local WebSocket hop is negligible on loopback** (3 ms delivery, 2 ms to start playback), even with ~100 KB of base64 JSON per reply.
- **Implications for N2:** binary frames will cut bytes on the wire by about 25% (base64 removed), but won't move latency on loopback. Report it as a bandwidth result, and measure time under N5 throttling, where 100 KB starts to matter. Reusing the ElevenLabs connection should shave the TCP + TLS handshake (typically 50–150 ms) off the 403 ms TTS stage.
- **Implications for N3:** streaming TTS can save at most part of the 403 ms TTS stage, since short clips already return quickly. A bigger win would be overlapping stages, e.g. streaming the reply model's text into streaming TTS so audio starts before the full reply exists.

## Issues / caveats
- **VAD tail is configured, not observed.** It's computed as the trailing silence count × 30 ms frames, so it's constant per setting. It doesn't capture mic-buffer delay before frames reach the detector.
- **Clock alignment** relies on one machine. WS delivery and playback start would be wrong with a remote client until clock-offset estimation exists (N4).
- **Excluded turn:** run 1, turn 1 had autoplay blocked until a click (playback start 4904 ms, total 8800 ms). It was flagged `autoplay_blocked` and skipped. Click the page once before each run to avoid it.
- **Reply length varies by design** (random length preset), which spreads the TTS and LLM numbers. That's why the CSV records `reply_chars` and `mp3_bytes`.
