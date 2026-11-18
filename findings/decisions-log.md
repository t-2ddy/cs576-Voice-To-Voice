# Decisions log

Dated tuning and design decisions that affect measurements. Newest first.

| Date | Decision | Reason | Affects |
|---|---|---|---|
| 2026-11-17 | N3: `TTS_STREAMING=1` (chunked ElevenLabs → MediaSource) + `LLM_STREAMING=1` (SSE reply, per-sentence TTS with `previous_text`) | N3a −117 ms vs N2; N3b −135 vs N3a; cumulative N1→N3b −366 ms (−10%). One-sentence replies limit N3b overlap | Default path; `TTS_STREAMING=0` / `LLM_STREAMING=0` restore N2 / N3a |
| 2026-11-17 | N2: binary WS audio frames, WS compression off, `HTTP_KEEPALIVE_SECONDS=300` for OpenAI / Supabase / ElevenLabs | Before capture: deflate already removed base64 overhead; 3 new TLS connections per turn (~170 ms). After: 0 new connections, total median −114 ms | Every later measurement; reproduce the old behavior with `WS_AUDIO_BINARY=0 WS_COMPRESSION=1 HTTP_KEEPALIVE_SECONDS=5` |
| 2026-11-17 | `VAD_SILENCE_END_MS` = 1200 (was 900) | Run 1 split line 5 at a pause; no splits in the three N1 baseline runs | Adds 300 ms to every turn; VAD tail is 33% of the N1 baseline total |
| 2026-11-17 | Recent-turns context window 10 → 30 rows (`RECENT_TURNS_LIMIT` in `chat_memory.py`) | Run 1 line 9 recall failed: turns fell out of the 10-row window before the next prune archived them into `chat_memory`. 30 covers every row the table can hold between prunes | Prompt size (up to ~28 short turns); no extra network calls |
| 2026-11-17 | `VAD_SILENCE_END_MS` = 900 (default 800) | Fewer mid-sentence cut-offs in the end-to-end test | VAD tail in every latency number |
