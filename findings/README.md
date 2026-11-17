# Findings

Measurements and observations for the cs576 report. Each planned feature gets one file. Every result is recorded **before and after** the change, using N1's instrumentation as the measuring tool.

## Index

| File | Topic | Status |
|---|---|---|
| [00-baseline-e2e.md](00-baseline-e2e.md) | End-to-end test, VAD / turn-taking tuning, baseline latency | In progress |
| [N1-latency-instrumentation.md](N1-latency-instrumentation.md) | Per-stage timing, WS RTT, `metrics` message, CSV log | Not started |
| [N2-binary-frames-connection-reuse.md](N2-binary-frames-connection-reuse.md) | Binary WS audio frames, persistent ElevenLabs HTTP session | Not started |
| [N3-streaming-tts.md](N3-streaming-tts.md) | ElevenLabs streaming, progressive playback | Not started |
| [N4-browser-mic-streaming.md](N4-browser-mic-streaming.md) | Browser mic → server PCM streaming | Not started |
| [N5-network-conditions.md](N5-network-conditions.md) | Latency / loss / bandwidth experiments (clumsy, DevTools) | Not started |
| [N6-security-multi-user.md](N6-security-multi-user.md) | `wss://`, handshake auth, Origin check, per-user sessions | Not started |
| [N7-resilience.md](N7-resilience.md) | Heartbeats, session resume, jittered retry on 429 | Not started |
| [N8-protocol-comparison.md](N8-protocol-comparison.md) | WebSocket/TCP vs WebRTC/UDP (stretch) | Not started |
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
