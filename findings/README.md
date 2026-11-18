# Findings

Measurements and observations for the cs576 report. Each planned feature gets one file. Every result is recorded **before and after** the change, using N1's instrumentation as the measuring tool.

## Index

| File | Topic | Status |
|---|---|---|
| [00-baseline-e2e.md](00-baseline-e2e.md) | End-to-end test, VAD / turn-taking tuning, baseline latency | In progress |
| [N1-latency-instrumentation.md](N1-latency-instrumentation.md) | Per-stage timing, WS RTT, `metrics` message, CSV log | In progress (phase A done) |
| [N2-binary-frames-connection-reuse.md](N2-binary-frames-connection-reuse.md) | Binary WS audio frames, persistent ElevenLabs HTTP session | Done (total median −114 ms) |
| [N3-streaming-tts.md](N3-streaming-tts.md) | Streaming TTS (N3a) + LLM text streaming (N3b), progressive playback | Done (N1→N3b total −366 ms / −10%) |
| [N4-browser-mic-streaming.md](N4-browser-mic-streaming.md) | Browser mic → server PCM streaming | TBD (code built, uncommitted; not measured) |
| [N5-network-conditions.md](N5-network-conditions.md) | Lag / loss experiments with clumsy | Planned (test plan written, runs pending) |
| [N6-security-multi-user.md](N6-security-multi-user.md) | `wss://`, handshake auth, Origin check, per-user sessions | TBD |
| [N7-resilience.md](N7-resilience.md) | Heartbeats, session resume, jittered retry on 429 | TBD |
| [N8-protocol-comparison.md](N8-protocol-comparison.md) | WebSocket/TCP vs WebRTC/UDP (stretch) | TBD |

**Presentation scope:** N1, N2, N3, N5. N4, N6, N7, N8 are TBD.

## Remaining TBD items: priority by time and effort
Cheapest first. "Write-up only" means no new code, using existing captures, CSVs, or written analysis.

| Priority | Item | Write-up only (no code) | Full version (with code) | Notes |
|---|---|---|---|---|
| 1 | **N8** protocol comparison | ~1–2 h: TCP vs UDP / WebRTC theory, argued with N1 data (WS hop is 2–3 ms) and N5 loss results | Days: WebRTC or Realtime-API baseline | Best value per hour; the write-up alone is a strong slide |
| 2 | **N6** security | ~2 h: threat model + one-line console demo of a cross-origin WebSocket connecting (own server only) | ~1 day: Origin check + token are small; `wss://` and per-user memory are larger | Origin check is ~10 lines if a code fix is wanted |
| 3 | **N7** resilience | ~1–2 h: kill/restart server and time reconnect vs the ×1.5 / 10 s backoff schedule; explain 20 s ping + 20 s timeout | ~1 day: session resume with sequence numbers, jittered retry on 429 | Tests need a stopwatch or the console, no code |
| 4 | **N4** browser mic | ~2 h: design + bandwidth and chunk-overhead math (256 kbps up, header overhead by chunk size) | ~1–2 days: fix multi-tab ingest, add uplink timestamps, chunk-size runs, phone needs `wss://` (pulls in N6) | Most code already exists but is the hardest to measure properly |
| [wireshark-captures.md](wireshark-captures.md) | WS handshake and frame captures (Npcap loopback) | Not started |
| [decisions-log.md](decisions-log.md) | Dated tuning and design decisions | Ongoing |

## Folders

- `data/`: per-turn CSV logs from N1 (`<topic>-<before|after>-<YYYY-MM-DD>.csv`).
- `captures/`: Wireshark `.pcapng` files and screenshots (`<topic>-<desc>.pcapng`).

## Recording conventions

- **Sample size:** at least 10 turns per condition. Report the median and p90, not a single run.
- **Fixed conditions:** same machine, network, models, voice and reply-length preset across a before/after pair. Note the git commit for each run.
- **Prompt set:** use the same short script of utterances for every run (see `00-baseline-e2e.md`) so reply lengths are comparable.
- **Units:** milliseconds for time, bytes for size, kbps for bandwidth.
- Write down surprises and failures too; they make good report material.
