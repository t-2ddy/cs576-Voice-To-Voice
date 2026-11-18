# N3 · Streaming audio pipeline

## Goal
Start playing Frieren's reply before the whole reply exists. Two stages, measured separately:
- **N3a, streaming TTS**: stream ElevenLabs audio in chunks, forward each chunk over the WS, start playback on the first chunk.
- **N3b, streaming model text**: stream the chat reply token by token, cut it into sentences, and start TTS on the first sentence while the model is still writing the rest.

## Approach
- **TTS transport**: ElevenLabs `POST /v1/text-to-speech/{voice}/stream?output_format=mp3_44100_128` (chunked HTTP over the same pooled, kept-alive `httpx` connection as N2), read with `iter_bytes()`. Same MP3 format as the N2 full clips, so byte counts are comparable. Chosen over the ElevenLabs WebSocket input-streaming API: one request per sentence keeps the N2 connection reuse and handshake trace, and needs no second persistent connection.
- **WS protocol**: `{"type":"audio_start","format":"mp3","stream":id}`, then one binary frame per MP3 chunk as it arrives, then `{"type":"audio_end","stream":id,"bytes":N,"chunks":k}`. Every chunk is forwarded immediately (no re-buffering on the server).
- **Client playback**: `MediaSource` with a `SourceBuffer('audio/mpeg')` in `sequence` mode. Chunks are appended in order (queued while the buffer is updating), `play()` is called after the first append, and `endOfStream()` after `audio_end` once the queue drains. MP3 frames split across chunks are fine: the MSE MPEG-audio parser buffers partial frames. Fallback when `MediaSource.isTypeSupported('audio/mpeg')` is false (some Firefox builds): collect the chunks and play one Blob at `audio_end` (same latency as N2). Both paths were tested in the Cursor browser (Chromium 150) on 2026-11-17.
- **`playback_done` with chunks**: the client sends `playback_done` on the media element's `ended`, which only fires after `endOfStream()`; a buffer underrun mid-reply pauses (`waiting`) instead of ending. Reports carry the stream id, and while a stream is current the server ignores untagged reports. This was needed because a second, stale tab sent `playback_done` early and unmuted the mic mid-reply. Fallback timeout = total bytes / 16 kB/s + 3 s, counted from `audio_end`.
- **N3b sentence pipeline**: a producer thread runs `ask_stream()` (OpenAI `stream=True`, SSE) and feeds `sentence_stream.SentenceSplitter`. It splits on `. ! ? …` followed by whitespace, skips abbreviations and initials, and merges fragments under 12 characters (like "I see.") into the next sentence. Sentences go on a queue; the main loop synthesizes each one with `synthesize_stream(sentence, previous_text=<already spoken>)` so intonation carries across requests, and all of them share one `audio_start`/`audio_end` stream. The textbox updates sentence by sentence. Unit tests: `python -m unittest test_sentence_stream`.
- **Toggles** (`server/.env`): `TTS_STREAMING=0` restores the N2 full-clip path; `LLM_STREAMING=0` gives N3a only (full reply text, then streamed TTS).

### What the timing columns mean with streaming
`total_ms` keeps its N1 meaning (end of user speech to audio starting in the browser), so all N1–N3 totals compare directly.

| Column | Start | End |
|---|---|---|
| `llm_ms` | memory done | last model token |
| `tts_ms` | text ready (first sentence in N3b, full reply otherwise) | last TTS byte |
| `ws_delivery_ms` / `playback_start_ms` | first chunk sent / received | first chunk received / audio playing |
| `tts_ttfb_ms` | text ready | first TTS byte |
| `llm_ttft_ms` (N3b) | memory done | first model token |
| `first_sentence_ms` (N3b) | memory done | first complete sentence |

Plus `chunks`, `first_chunk_bytes`, and `sentences` per reply. In N3b the stages overlap, so the per-stage shares no longer add up to 100%.

## Hypothesis
- **N3a**: small gain. ElevenLabs' fixed cost per request dominates for short replies: in a pre-run check, a 1.3 s clip had its first byte at 216 ms and its last at 230 ms. Expect total to drop by roughly the TTS generation time beyond the first byte (tens of ms for short replies, more for long ones).
- **N3b**: larger gain. The model takes ~1.05 s median for the full reply (N2-after); audio can start once the first sentence plus one TTS first byte are ready. Expect a few hundred ms off the median, more on long replies.

## Setup
- Date: 2026-11-17
- Commit before: `475e1c5` (N2-after state); before data: `findings/data/N2-after-2026-11-17.csv`
- Commit after (N3a / N3b): uncommitted on `main` (N3 code + this write-up); N3b has no separate Wireshark capture
- N3a runs: `LLM_STREAMING=0`, CSV `findings/data/N3a-after-2026-11-17.csv` (n=33, 4 runs, 0 skipped), capture `findings/captures/N3a-after.pcapng`
- N3b runs: `LLM_STREAMING=1`, CSV `findings/data/N3b-after-2026-11-17.csv` (n=30, 3 runs, 0 skipped)

## Results
### N3a: streaming TTS
| Metric | Before (N2 full clip) | After (N3a) | Change |
|---|---|---|---|
| TTS first byte after text ready (ms, median) | 312 (whole clip) | 206 | −106 |
| TTS last byte after text ready (ms, median) | 312 | 276 | −36 |
| LLM → audio playing (ms, approx: TTS path + WS + play) | 316 | 269 | −47 |
| Total voice-to-voice median (ms) | 3561 | 3444 | −117 |
| Total voice-to-voice p90 (ms) | 4103 | 3827 | −276 |
| Playback start (recv → play, ms median) | 2 | 61 | +59 |
| Chunks per reply | 1 | 72 (p90 114) | |
| First chunk size (bytes) | 80709 (whole clip) | 1384 | |

Capture check: `N3a-after.pcapng` shows `audio_start` → many opcode-2 binary frames (~126 B payload each in the decode) → then chat/`audio_end` for the stream. No new TLS handshakes (same N2 keep-alive pool).

### N3b: streaming model text
| Metric | N3a | N3b | Change |
|---|---|---|---|
| LLM first token (ms, median) | n/a | 633 | |
| LLM first sentence (ms, median) | = full LLM (1072) | 808 | −264 vs waiting for full reply |
| Full LLM (ms, median) | 1072 | 868 | −204 (shorter replies this set) |
| TTS first byte after text ready (ms) | 206 | 190 | −16 |
| Total voice-to-voice median (ms) | 3444 | 3309 | **−135** |
| Total voice-to-voice p90 (ms) | 3827 | 3685 | −142 |
| Sentences per reply (median / p90) | 1 / 1 | 1 / 2 | 9 of 30 turns had ≥2 |

Multi-sentence subset (n=9): first sentence ready at 716 ms vs full LLM 971 ms (−255), but `playback_start_ms` jumped to 365 ms median (single-sentence turns stayed at 44). Net multi-sentence total median 3372 ms — still close to the overall 3309.

### N1 → N3 cumulative
| Milestone | CSV | Total median (ms) | Δ vs prior | Δ vs N1 |
|---|---|---|---|---|
| N1 baseline | `N1-baseline-2026-11-17.csv` | 3675 | | |
| N2 keep-alive + binary | `N2-after-2026-11-17.csv` | 3561 | −114 | −114 |
| N3a stream TTS | `N3a-after-2026-11-17.csv` | 3444 | −117 | −231 |
| N3b stream LLM text | `N3b-after-2026-11-17.csv` | 3309 | −135 | **−366 (−10%)** |

## Analysis
N3a matches the “small gain” hypothesis. ElevenLabs still spends most of its time before the first byte (median TTFB 206 of 276 ms TTS), so streaming only saves ~70 ms of generation that used to sit in front of playback. About half of that comes back as MediaSource startup: `playback_start_ms` rose from 2 → 61 ms (Blob had the whole clip ready; MSE waits for the first `appendBuffer` + `play()`). Net LLM→sound is still ~47 ms faster, and total median 3561 → 3444 ms (−3%).

N3b’s gain is real but smaller than the “few hundred ms” hope, because the length presets keep most replies to **one sentence** (median 1, only 9/30 multi). When there is only one sentence, first-sentence time = full LLM time, so streaming text does not start TTS earlier — you still pay for the whole reply before audio. The measured −135 ms vs N3a is a mix of: slightly earlier TTS start when there *is* a second sentence, a bit faster TTS TTFB, and run noise (STT was slower in this set: 742 vs 635 ms; LLM full-completion times were also shorter, which may mean shorter replies). On the multi-sentence turns, text was ready ~255 ms earlier, but MediaSource took much longer to fire `playing` (365 vs 44 ms) — likely a short first sentence / thin first buffer — so a lot of that overlap was spent waiting in the browser.

Across N1→N3 the pipeline is ~10% faster at the median (3675 → 3309 ms). The remaining total is still dominated by the fixed 1200 ms VAD tail plus STT + LLM (~2 s). Further wins need overlapping those stages (N4 browser mic won’t cut hosted APIs; a realtime speech-to-speech model would).

No notes in either N3 CSV. No Firefox / N3b capture this round.

## Issues / caveats
- MediaSource adds ~60 ms of browser startup vs a ready Blob on typical turns; on short first sentences in N3b it was hundreds of ms before `playing`.
- Gaps between sentences: sentence N+1's TTS request starts after sentence N has fully downloaded. TTS runs faster than real time, so playback normally stays ahead, but a very short first sentence followed by a slow request could underrun (heard as a brief pause).
- Per-sentence TTS sends `previous_text` for continuity, but each sentence is still a separate generation, so prosody can differ slightly at sentence boundaries.
- Multi-tab: every connected tab plays the audio; only reports tagged with the current stream id count for turn-taking.
- One-sentence replies blunt N3b; raising the “go longer” length weight would show the overlap more clearly but would change the N1–N3 comparison.
