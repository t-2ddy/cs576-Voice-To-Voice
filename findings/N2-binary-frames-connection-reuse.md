# N2 · Binary WS frames + connection reuse

## Goal
1. Send MP3 as binary WebSocket frames instead of base64 inside JSON.
2. Reuse one HTTP/TLS connection to ElevenLabs instead of a fresh `urllib` handshake per call.

## Hypothesis
- Audio bytes on the wire drop by about 25% (base64 inflates by a third).
- TTS time drops by roughly one TCP + TLS handshake per turn after the first.

## Setup
- Date: · Commit before: · Commit after:
- Prompt script: same as `00-baseline-e2e.md`

## Results: bytes on the wire
| Metric | Before (base64 JSON) | After (binary) | Change |
|---|---|---|---|
| Audio payload per turn (bytes) | | | |
| WS frame size (bytes) | | | |

## Results: ElevenLabs connection
| Metric | Before (`urllib`) | After (persistent session) | Change |
|---|---|---|---|
| TCP connect (ms) | | | |
| TLS handshake (ms) | | | |
| TTS RTT median (ms) | | | |
| TTS RTT p90 (ms) | | | |

Evidence: Wireshark capture in `captures/` showing one handshake vs one per turn.

## Analysis

## Issues / caveats
-
