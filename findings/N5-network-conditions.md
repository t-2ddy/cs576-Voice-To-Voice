# N5 · Network-condition experiments

## Goal
Degrade the network on purpose and measure how each stage of a turn reacts. No new code: this reuses the N1 timing and CSV log, and changes only the network.

Questions it answers:
1. Which stages scale with round-trip time (RTT), and by how many round trips each?
2. How does packet loss affect the median vs the tail (p90)?
3. Does N2's connection reuse matter more on a slow network than on a fast one?

## Tool
**clumsy** (Windows, WinDivert-based): adds lag and drops packets for traffic matching a filter.

- **Filter:** `tcp.DstPort == 443 or tcp.SrcPort == 443` — every hosted API (OpenAI, Supabase, ElevenLabs) is HTTPS on 443. The local WebSocket (8766) and Vite proxy (5173) are untouched, so only the internet hop is degraded.
- **Lag:** tick **Outbound only**, so "+100 ms lag" adds 100 ms to each round trip (ticking both directions would add 200 ms).
- **Drop:** tick **Inbound and Outbound** at the stated percentage, so loss hits requests and responses.
- Close other apps that use HTTPS (browsers apart from the client tab, Steam, OneDrive sync) — the filter catches them too.

## Conditions
One run of the 10-line script per condition (n = 10), same settings as N3b (`TTS_STREAMING=1`, `LLM_STREAMING=1`, `MIC_SOURCE=local`, `VAD_SILENCE_END_MS=1200`).

| ID | clumsy setting | `HTTP_KEEPALIVE_SECONDS` | CSV (`METRICS_CSV=../findings/data/...`) | Shows |
|---|---|---|---|---|
| C0 | off | 300 | `N5-C0-<date>.csv` | Same-day baseline |
| C1 | lag 100 ms (outbound) | 300 | `N5-C1-lag100-<date>.csv` | RTT sensitivity |
| C2 | lag 300 ms (outbound) | 300 | `N5-C2-lag300-<date>.csv` | Same, larger signal |
| C3 | drop 2% (both) | 300 | `N5-C3-loss2-<date>.csv` | TCP retransmission, tail growth |
| C4 | drop 10% (both) | 300 | `N5-C4-loss10-<date>.csv` | Stalls, timeouts, worst case |
| C2-nr | lag 300 ms (outbound) | **5** (N2 reuse off) | `N5-C2-noreuse-<date>.csv` | Cost of new connections under latency |

**Rerun C0 the same day** instead of reusing the N3b CSV: API speed varies from day to day (a stray run on 2026-11-18 had STT near 1.9 s).

Optional: capture C3 and C4 in Wireshark (Wi-Fi adapter, filter `tcp.port == 443`) and count retransmissions with `tcp.analysis.retransmission`. Save as `captures/N5-C3-loss2.pcapng` etc.

## Procedure (per condition)
1. Set `METRICS_CSV` (and `HTTP_KEEPALIVE_SECONDS` for C2-nr) in `server/.env`.
2. Start clumsy with the condition's settings (C0: leave it stopped).
3. Start `python voice_chat.py` and `npm run dev`, click the page once (autoplay), and read the 10 lines.
4. Stop clumsy. Note anything odd in the run log below (errors, long hangs, wrong transcripts).
5. Summarize: `python metrics_summary.py ../findings/data/N5-<id>-<date>.csv`.

About 5 minutes per condition, under an hour in total.

## Hypothesis
Per turn, with connections reused, the hosted-API stages need roughly these round trips:

| Stage | Round trips (approx) | Why |
|---|---|---|
| STT | 2–4 | ~100 KB WAV upload (3 s × 32 KB/s) needs several TCP windows, then the response |
| Memory | 1 (light) – 3 (full) | Supabase reads; `full` adds an embedding call and the `match_memory` RPC |
| LLM (to first sentence) | 1 | Streamed response; first token after one round trip plus model time |
| TTS (to first byte) | 1 | Streamed response |

- **C1/C2:** total grows by about 5–9 × the added lag (+0.5–0.9 s at 100 ms, +1.5–2.7 s at 300 ms). STT should grow the most; the WS and playback stages should not move.
- **C2-nr:** each new connection adds TCP (1 RTT) + TLS 1.3 (1 RTT), × 3 services ≈ 6 extra round trips ≈ **+1.8 s** over C2. On a fast network N2 saved ~170 ms; here it should save about ten times as much.
- **C3/C4:** the median moves a little; p90 grows a lot. A lost packet costs a retransmission timeout (≥ 200 ms, often more) and holds up everything behind it on that TCP connection (head-of-line blocking). Expect audible gaps or underruns in streamed audio at 10%.

## Results
Fill in from `metrics_summary.py`. Medians in ms (p90 in brackets).

| ID | STT | Memory | LLM first sentence | TTS first byte | Total | Δ total vs C0 | Flagged turns |
|---|---|---|---|---|---|---|---|
| C0 | | | | | | — | |
| C1 | | | | | | | |
| C2 | | | | | | | |
| C3 | | | | | | | |
| C4 | | | | | | | |
| C2-nr | | | | | | | |

### Round trips per stage (from C0 → C2)
Δ stage median ÷ 300 ms ≈ round trips used by that stage.

| Stage | Δ C0 → C2 (ms) | ≈ Round trips | Matches hypothesis? |
|---|---|---|---|
| STT | | | |
| Memory | | | |
| LLM first sentence | | | |
| TTS first byte | | | |

### Connection reuse under latency
| Metric | C2 (reuse) | C2-nr (new connections) | Difference | Same comparison on a fast network (N2) |
|---|---|---|---|---|
| Total median (ms) | | | | −114 ms |
| New TLS connections per turn | 0 | 3 | | 3 → 0 |

## Run log
| ID | Date / time | Commit | Notes (errors, hangs, audio gaps, STT mistakes) |
|---|---|---|---|
| C0 | | | |
| C1 | | | |
| C2 | | | |
| C3 | | | |
| C4 | | | |
| C2-nr | | | |

## Analysis
_To write after the runs:_
- Which stages scaled with RTT and by how much; does the round-trip estimate match the table above?
- Loss: median vs p90, retransmission counts from Wireshark, any audible gaps.
- The N2 story: reuse is worth ~170 ms on a fast network and about ten times that at +300 ms.
- Link to N8: the local WebSocket hop stays at a few ms throughout; the transport protocol between browser and server isn't the bottleneck, the hosted-API round trips are.

## Issues / caveats
- **Retries can hide failures.** The OpenAI SDK retries failed requests (2 retries by default), so heavy loss may show up as long STT/LLM times rather than errors. Timeouts are 60 s (OpenAI, ElevenLabs) and 120 s (Supabase).
- clumsy lag is a fixed delay with no jitter, so it's a clean test of RTT, not of a realistic mobile network.
- n = 10 per condition is enough to see the trend; p90 from 10 turns is the second-slowest turn, so treat it as rough.
- The VAD tail (1200 ms) is local and unaffected; it stays in every total.
