# N4 · Browser mic → server audio streaming

## Goal
Capture the mic in the browser and stream 16 kHz / 16-bit PCM as binary WS frames, so any device on the LAN (e.g. a phone) can be the client.

## Design
- Chunk size (ms / bytes):
- Server VAD on the stream:
- Backpressure handling:

## Expected bandwidth
16,000 samples/s × 16 bit = 256 kbps upstream while the mic is open.

## Results: chunk size vs latency
| Chunk (ms) | Frames/s | Measured upstream (kbps) | VAD tail added (ms) | Total voice-to-voice (ms) |
|---|---|---|---|---|
| 20 | | | | |
| 40 | | | | |
| 100 | | | | |

## Results: jitter
| Client | Network | Inter-arrival jitter (ms) | Notes |
|---|---|---|---|
| Same PC | loopback | | |
| Phone | Wi-Fi LAN | | |

## Analysis

## Issues / caveats
- Browsers only allow mic capture on secure origins (https or localhost), which ties into N6.
