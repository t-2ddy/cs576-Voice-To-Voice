# cs576 group 10: Voice-to-Voice Companion

A real-time AI voice companion: you talk into the mic, **Frieren** (an elf mage assistant) answers out loud. Every AI step runs on a hosted API, so the project is a pipeline of network services stitched together over HTTPS and a WebSocket.

**Project theme:** real-time voice over the network: protocol design and measurement.

## TL;DR: networking features

**Have now**
- ✅ HTTPS/TLS REST calls to OpenAI, Supabase, and ElevenLabs every turn
- ✅ WebSocket server (:8766) with HTTP 101 upgrade handshake
- ✅ Bidirectional JSON message protocol (`chat` / `audio` / `status` ↔ `playback_done`)
- ✅ Half-duplex playback handshake with timeout fallback (app-level flow control)
- ✅ Vite reverse proxy (`/ws` → `127.0.0.1:8766`), server bound to loopback
- ✅ Client reconnect with exponential backoff (×1.5, max 10 s)
- ✅ WebSocket keepalive pings (library default, every 20 s)

**Planned** (N = networking feature, numbered by priority)
- ⬜ N1 Latency instrumentation per pipeline stage + RTT, network panel in UI
- ⬜ N2 Binary WS frames (drop base64 overhead) + HTTP connection reuse
- ⬜ N3 Streaming TTS, audio chunks forwarded over the WS
- ⬜ N4 Browser mic → server real-time audio streaming (true client-server, LAN devices)
- ⬜ N5 Experiments under simulated latency / loss / bandwidth caps
- ⬜ N6 `wss://`, auth on handshake, Origin check, per-user sessions
- ⬜ N7 Resilience: heartbeats, session resume, jittered retry on API errors
- ⬜ N8 (stretch) WebSocket/TCP vs WebRTC/UDP comparison

## Architecture

```
Mic → RMS voice detection → OpenAI speech-to-text ──HTTPS──┐
                                                           ▼
         Supabase memory (facts, summary, vector search) ◄─HTTPS─► OpenAI chat
                                                           │
                                         ElevenLabs TTS ◄──HTTPS
                                                           │ MP3
                                                           ▼
              Python server ──WebSocket :8766──► Vite proxy (/ws) ──► React client
                            ◄── playback_done ──                      (text + audio)
```

| Part | Where | Role |
|---|---|---|
| Voice loop | `server/voice_chat.py` | Mic → STT → chat → TTS → WebSocket, one turn at a time |
| Speech-to-text | `server/speechToText.py` | Mic capture, RMS voice detection, OpenAI transcription |
| Chat model | `server/local_model.py`, `server/soul` | OpenAI chat + Frieren persona |
| Memory | `server/chat_memory.py`, `supabase/schema.sql` | Supabase: key facts, rolling summary, vector search, recent turns |
| Voice | `server/elevenlabs_tts.py` | ElevenLabs text-to-speech (MP3) |
| WebSocket hub | `server/chat_bridge.py` | Broadcasts events to the UI, receives `playback_done` |
| UI | `client/` (React + Vite) | Visual-novel style textbox, status bar, audio playback |

### WebSocket message protocol (JSON)

Server → client:
```json
{"type": "chat", "who": "you" | "frieren", "text": "..."}
{"type": "audio", "format": "mp3", "data": "<base64>"}
{"type": "status", "value": "listening" | "thinking" | "speaking" | "ready" | "error", "detail": "..."}
```
Client → server:
```json
{"type": "playback_done"}
```
After sending `audio`, the server waits for `playback_done` (or a timeout of clip length + 3 s) before listening again, so the mic doesn't pick up Frieren's own voice from the speakers.

## Networking focus

### Already in the project
- **Multi-service pipeline over HTTPS**: each turn makes TLS REST calls to OpenAI (STT multipart upload, chat, sometimes embeddings), Supabase (PostgREST over HTTPS, `match_memory` RPC), and ElevenLabs, then pushes results over a WebSocket.
- **WebSocket upgrade + bidirectional protocol**: HTTP `101 Switching Protocols` handshake, JSON message types in both directions. `websockets` sends keepalive pings every 20 s by default.
- **Reverse proxy**: Vite proxies `/ws` → `ws://127.0.0.1:8766` (same-origin for the browser; server bound to loopback only).
- **Reconnect with exponential backoff**: client retries ×1.5 per attempt, capped at 10 s.
- **Application-level flow control**: the half-duplex `playback_done` handshake with timeout fallback.
- **Known inefficiencies to measure and fix**: MP3 is base64 inside JSON (~33% overhead); `elevenlabs_tts.py` uses `urllib`, so every call pays a fresh TCP + TLS handshake (the `openai` SDK reuses connections).

### Planned additions (priority order)
Each item should produce a before/after number; N1 is the measuring tool for the rest.

| # | Item | Effort | What to measure / show |
|---|---|---|---|
| N1 | **Latency instrumentation**: timestamp each stage (end of speech → STT RTT → LLM → TTS → WS delivery → playback start); WS ping/RTT; a `metrics` message type and a small network panel in the UI; CSV log per turn | Low | Per-stage latency breakdown; total voice-to-voice latency |
| N2 | **Binary WS frames + connection reuse**: send MP3 as binary frames instead of base64 JSON; persistent HTTP session for ElevenLabs | Low | Bytes on the wire (−33%); handshake time saved per turn |
| N3 | **Streaming TTS**: ElevenLabs streaming (chunked HTTP or its WS endpoint), forward chunks over the WS, client plays progressively | Medium | Time-to-first-audio before vs after |
| N4 | **Browser mic → server audio streaming**: capture in the browser, stream 16 kHz/16-bit PCM (256 kbps) as binary WS frames; server VAD/STT on the stream. Makes it true client-server; a phone or another LAN device can be the client | High | Bandwidth, chunk size vs latency, jitter, backpressure |
| N5 | **Network-condition experiments**: clumsy (Windows) or Chrome DevTools throttling to add latency, loss, bandwidth caps | Low (after N1) | How each stage degrades; TCP head-of-line blocking under loss |
| N6 | **Security + multi-user**: `wss://` via reverse proxy, auth token checked on the WS handshake, `Origin` check against cross-site WebSocket hijacking, per-user sessions | Medium | Threat model; handshake trace |
| N7 | **Resilience**: tuned heartbeats, session resume with message sequence numbers, retry with jittered backoff on API errors / HTTP 429 | Low | Recovery time after a dropped connection |
| N8 | **Protocol comparison (stretch)**: WebSocket/TCP audio vs WebRTC (UDP + Opus), e.g. OpenAI Realtime over WebRTC as a baseline | High | Latency and loss tolerance, TCP vs UDP |

**Recommended scope:** core = N1 + N2 + N3; then N4 with N5 as the experiments section if time allows. Capture the WebSocket handshake and frames in **Wireshark** for the report (loopback capture via Npcap).

## Setup

**Requirements:** Python 3.14, Node.js, a microphone, and accounts for OpenAI (API credits), ElevenLabs, and Supabase.

1. **Python deps:** `pip install -r requirements.txt`
2. **Client deps:** `cd client && npm install`
3. **Supabase:** create a project, then run `supabase/schema.sql` in the SQL Editor. Optionally run `supabase/seed_key_facts.sql` for Frieren lore facts.
4. **Keys:** copy `server/.env.example` to `server/.env` and fill it in (never commit `server/.env`):
   - `OPENAI_API_KEY`, `LLM_MODEL` (e.g. `gpt-5.6-luna`), optional `LLM_REASONING_EFFORT` (default `none`), optional `STT_MODEL`
   - `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
   - `SUPABASE_URL` (`https://<project-ref>.supabase.co`), `SUPABASE_SERVICE_ROLE_KEY` (secret key)

## Run

```bash
# terminal 1
cd server
python voice_chat.py

# terminal 2
cd client
npm run dev
```
Open the URL Vite prints, stay quiet for the 1 s mic calibration, then talk.

## Other to-dos
- Run an end-to-end test; tune voice detection (threshold, `SILENCE_END_MS`) and check that the mic stays muted while Frieren speaks.
- Decide whether each run starts a fresh chat (archive `recent_turns` at startup).
- Spells as agentic tools (after the networking core); spells that call web APIs fit the theme.
- Auto-extract `key_facts` from conversation.
