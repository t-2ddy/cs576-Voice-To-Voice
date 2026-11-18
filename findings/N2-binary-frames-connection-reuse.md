# N2 · Binary WS frames + connection reuse

## Goal
1. Send MP3 as binary WebSocket frames instead of base64 inside JSON.
2. Reuse one HTTP/TLS connection to ElevenLabs instead of a fresh `urllib` handshake per call.

## Hypothesis
- ~~Audio bytes on the wire drop by about 25% (base64 inflates by a third).~~ **Falsified by the before capture:** the WebSocket already negotiates `permessage-deflate`, which squeezes the base64 back to about the raw MP3 size. Binary frames will cut CPU work (base64 encode + deflate on the server, inflate + `atob` on the client) and the pre-compression size, but not bytes on the wire.
- TTS time drops by roughly one TCP + TLS handshake per turn after the first. **Broadened:** the capture shows OpenAI and Supabase also open a new connection every turn, so the expected saving is about 170 ms per turn across all three services.

## Setup
- Date: 2026-11-17 · Commit before: `a90e3be` · Commit after: (uncommitted at time of the after-runs; fill in when committed)
- Prompt script: same as `00-baseline-e2e.md`
- Before capture: `captures/N2-before.pcapng` (Wi-Fi + Npcap loopback, 3 turns, 93 s). Latency rows for those 3 turns: `data/N2-before-capture-2026-11-17.csv` (kept out of the N1 baseline).

## What changed
- **Connection reuse:** `server/http_pool.py` sets `keepalive_expiry` to `HTTP_KEEPALIVE_SECONDS` (default 300 s) for the OpenAI client (`DefaultHttpxClient`), the Supabase client (`SyncClientOptions(httpx_client=...)`), and a new pooled `httpx.Client` replacing `urllib` in `elevenlabs_tts.py`. `warm_up()` opens the ElevenLabs connection at startup; OpenAI and Supabase are already opened by the startup model check and archive.
- **Binary frames:** `emit_audio` sends `{"type": "audio", "format": "mp3", "encoding": "binary", "bytes": N}` then one binary frame (opcode 2) with the raw MP3. WebSocket compression is off (`WS_COMPRESSION=0`), because MP3 doesn't compress and deflate only made sense for base64.
- **New CSV columns:** `ws_bytes` (audio payload sent per client, before compression) and `tts_handshake_ms` (ElevenLabs TCP + TLS time from an httpx trace hook; 0 = reused connection).
- **Reproducing the before behavior** for comparison runs: `WS_AUDIO_BINARY=0`, `WS_COMPRESSION=1`, `HTTP_KEEPALIVE_SECONDS=5`.

## Results: bytes on the wire (before)
Per `audio` message, from the 3 captured turns. The WebSocket frame has RSV1 set (compressed); the handshake response carried `Sec-WebSocket-Extensions: permessage-deflate; server_max_window_bits=12`.

| Turn | MP3 bytes | Base64 JSON (uncompressed, bytes) | WS payload on the wire (bytes) | Wire / MP3 |
|---|---|---|---|---|
| 1 | 24,702 | ~32,980 | 24,308 | 98% |
| 2 | 113,310 | ~151,120 | 113,717 | 100.4% |
| 3 | 94,083 | ~125,480 | 94,370 | 100.3% |

After (`captures/N2-after.pcapng`, 3 turns, decoded with `-d tcp.port==8766,websocket` because the capture started after the upgrade): each reply is a 72–73-byte JSON text frame followed by one binary frame (opcode 2, RSV1 clear = uncompressed) of exactly the MP3 size: 100,771, 130,446, and 53,959 bytes.

| Metric | Before (base64 JSON + deflate) | After (binary, no deflate) | Change |
|---|---|---|---|
| Audio payload per turn, pre-compression (bytes) | ~4/3 × MP3 + ~40 (~102,600 at the 77 KB median) | MP3 + ~72 (median `ws_bytes` 80,781 = 100.1% of MP3) | −25% of the data the server has to produce and the client has to parse |
| WS payload on the wire (bytes) | ≈ MP3 size (98–100%) | MP3 size + 72-byte header | ≈ 0 |
| Server work per reply | base64 encode + JSON + deflate | none (raw bytes) | |
| Client work per reply | inflate + JSON parse + `atob` loop | wrap `ArrayBuffer` in a `Blob` | |

## Results: connection setup (before)
Each turn opened one new TLS connection to each service; nothing was reused between turns. Times are from the capture: TCP = SYN → SYN/ACK, setup = SYN → first encrypted request byte. TLS 1.3 offered on all.

| Service | New connections | TCP connect (ms) | Full setup, TCP + TLS (ms) | Per-turn cost |
|---|---|---|---|---|
| OpenAI (`api.openai.com`) | 1 at startup + 1 per turn | 15–20 | 47–54 (median ~50) | ~50 ms on STT (chat and embeddings reuse it within the turn) |
| Supabase | 1 at startup + 1 per turn | 13–15 | 41–56 (median ~49) | ~49 ms on memory |
| ElevenLabs (`urllib`) | 1 per turn | 20–24 | 60–74 (median ~74) | ~74 ms on TTS |
| **Total** | | | | **~170 ms per turn** (about 4–5% of the 3675 ms baseline) |

Root cause for OpenAI and Supabase: both use `httpx`, whose default `keepalive_expiry` is 5 s (`openai._constants.DEFAULT_CONNECTION_LIMITS`). Turns are 15–20 s apart, so the pooled connection has expired before the next turn. ElevenLabs uses `urllib`, which never reuses connections. DNS lookups weren't captured (port 53 was filtered out) and would add to these numbers on a cold cache.

## Results: latency after (3 runs, n = 31 turns)
Before = `data/N1-baseline-2026-11-17.csv` (n = 29), after = `data/N2-after-2026-11-17.csv` (n = 31, none flagged). Same machine, models, voice, 10-line script, and `VAD_SILENCE_END_MS=1200`. Median MP3 was 77 KB before and 81 KB after, so reply lengths are comparable.

| Metric | Before | After | Change |
|---|---|---|---|
| New TLS connections per turn | 3 | 0 (`tts_handshake_ms` = 0 on 31/31 turns; no ClientHellos in the after capture) | −3 |
| TTS median / p90 (ms) | 403 / 539 | 312 / 443 | **−91 / −96 (−23%)** |
| STT median / p90 (ms) | 758 / 1069 | 664 / 1037 | **−94 / −32 (−12%)** |
| Memory median / p90 (ms) | 158 / 461 | 121 / 389 | −37 / −72 |
| Memory, `full` / `light` medians (ms) | 423 / 132 | 364 / 92 | −59 / −40 |
| LLM median / p90 (ms) | 1062 / 1226 | 1051 / 1396 | −11 / +170 (control: already reused within a turn) |
| WS delivery median / p90 (ms) | 3 / 5 | 2 / 3 | −1 / −2 |
| Playback start median / p90 (ms) | 2 / 3 | 2 / 3 | 0 |
| **Total median / p90 (ms)** | **3675 / 4107** | **3561 / 4103** | **−114 / −4 (−3%)** |

TTS time vs clip size (linear fit, ms = fixed + per-KB): before 283 ms + 1.61 ms/KB, after 173 ms + 1.53 ms/KB. The fixed cost fell by ~110 ms while the per-KB cost stayed the same, which is what removing a per-request handshake should do: it doesn't make the audio download faster, it removes setup in front of it.

Evidence: `captures/N2-before.pcapng`, display filter `tls.handshake.type == 1` (one ClientHello per service per turn). `captures/N2-after.pcapng`: no ClientHellos to OpenAI, Supabase, or ElevenLabs; one TCP connection each (ElevenLabs 192.168.0.111:57573 → 34.8.184.191:443, Supabase :57574, OpenAI over IPv6 :57571) carries all three turns.

## Other observations from the before capture
- WebSocket upgrade: `GET /ws` → `101 Switching Protocols` in 0.4 ms on loopback (Vite proxy on :5173 forwards to :8766).
- Keepalive: `websockets` ping/pong every 20 s; the pong came back in 0.26–0.30 ms on loopback (useful for N1 phase B and N7).

## Analysis
- **Connection reuse worked and is where N2's time saving comes from.** Removing three handshakes per turn cut TTS by ~91 ms and STT by ~94 ms at the median, and memory by ~37 ms. That matches the ~170 ms of setup measured in the before capture. The stages that didn't involve a new connection (LLM, which already rode on the STT connection within the turn, and the local WebSocket hop) didn't move, which makes them a useful control.
- **The end-to-end gain is smaller than the sum of the stage gains** (−114 ms median, ~3%), because the LLM stage got noisier in the after-runs (p90 +170 ms). LLM variance is OpenAI-side and unrelated to this change; it is the largest source of run-to-run spread.
- **Binary frames changed what the endpoints do, not what crosses the wire.** `permessage-deflate` was already removing base64's overhead, so on-the-wire bytes stayed ≈ MP3 size. What binary frames remove is the encode/compress/decompress/decode work (the data the server builds per reply is 25% smaller and needs no compression). On loopback that's a ~1 ms improvement in delivery. The design is also simpler and is the format N3 streaming chunks will use.
- **Hypothesis scorecard:** "bytes on the wire −25%" was wrong (compression was already on, which we only found by looking at the capture). "TTS drops by one handshake" was right, and the same root cause (5 s idle timeout) also affected OpenAI and Supabase.
- **Next:** the remaining time is dominated by the 1.2 s silence wait (34%), the LLM (30%), and STT (19%). Networking-wise, N3 should overlap stages (stream TTS, ideally fed by streamed LLM text) rather than shave transport.

## Issues / caveats
- **The after capture started after the server and the WebSocket connected**, so it has no WebSocket upgrade and no startup handshakes. The absence of per-turn ClientHellos plus single long-lived API connections still shows reuse; the WebSocket frames were decoded by forcing port 8766 as WebSocket. Start the capture before the server next time to also show the one startup handshake per service.
- **Idle limits on the server side are unknown.** All three providers kept the connection open across turns ~15–20 s apart. Longer pauses (minutes) may still hit a provider idle timeout, and the next turn would then reconnect (visible as `tts_handshake_ms` > 0).
- **Run-to-run noise:** per-turn values vary by hundreds of ms (STT 489–1677 ms after). The improvements show in medians over ~30 turns, not in individual turns.
- **Run 1 of the after-runs has 11 turns** (line 4 was said again after line 9). It's a valid turn for latency, so it was kept.
- **STT outlier:** run 1 turn 1 STT took 1419 ms after (vs 846/850 in runs 2–3); one memory outlier of 1157 ms on run 1 turn 4. Both are inside the medians' tolerance and not connection-related (`tts_handshake_ms` = 0, no new connections in the capture).
