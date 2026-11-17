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
- `metrics` message type:
- Clock alignment between Python and browser:
- CSV columns:
- UI network panel:

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
