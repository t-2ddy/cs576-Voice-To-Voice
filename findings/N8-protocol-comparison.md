# N8 · Protocol comparison (stretch)

## Goal
Compare our WebSocket/TCP audio path with WebRTC (UDP + Opus), e.g. OpenAI Realtime over WebRTC as a baseline.

## Setup
- Our pipeline config:
- WebRTC baseline:
- Same prompt script and network conditions as N5

## Results
| Condition | WS/TCP total (ms) | WebRTC total (ms) | WS/TCP audio quality | WebRTC audio quality |
|---|---|---|---|---|
| C0 clean | | | | |
| C3 2% loss | | | | |
| C4 10% loss | | | | |

## Analysis
TCP retransmission vs UDP + Opus concealment under loss; latency floor of each design.

## Issues / caveats
- Not apples to apples: the Realtime API is a single speech-to-speech model, not our STT → LLM → TTS chain.
