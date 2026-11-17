# N5 · Network-condition experiments

## Goal
Degrade the network on purpose and measure how each stage reacts. Requires N1.

## Tools
- clumsy (Windows): added latency, loss, throttling
- Chrome DevTools network throttling (client side only)

## Conditions
| ID | Added latency (ms) | Loss (%) | Bandwidth cap | Applied to |
|---|---|---|---|---|
| C0 | 0 | 0 | none | baseline |
| C1 | 100 | 0 | none | |
| C2 | 300 | 0 | none | |
| C3 | 0 | 2 | none | |
| C4 | 0 | 10 | none | |
| C5 | 0 | 0 | 256 kbps | |

## Results (median ms, n ≥ 10 per condition)
| ID | STT | LLM | TTS | WS delivery | Total | Failures / timeouts |
|---|---|---|---|---|---|---|
| C0 | | | | | | |
| C1 | | | | | | |
| C2 | | | | | | |
| C3 | | | | | | |
| C4 | | | | | | |
| C5 | | | | | | |

## Analysis
- Which stages scale with RTT (many round trips) vs barely move?
- TCP head-of-line blocking under loss: visible as stalls in streamed audio (N3) or PCM upload (N4)?

## Issues / caveats
-
