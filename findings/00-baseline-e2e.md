# 00 · Baseline end-to-end test

## Goal
Confirm the full pipeline works (mic → VAD → STT → chat + memory → TTS → WS → client playback) and tune turn-taking before any networking change.

## Setup
- Date:
- Commit:
- Server: `python voice_chat.py` in `server/`
- Client: `npm run dev` in `client/`
- Models: `STT_MODEL=` · `LLM_MODEL=` · `ELEVENLABS_MODEL_ID=`
- Audio: speakers / headphones, mic:

## VAD / turn-taking tuning
| Setting | Default | Chosen | Why |
|---|---|---|---|
| `VAD_SILENCE_END_MS` | 800 | **900** | Fewer cut-offs mid-sentence |
| Energy threshold | | | |
| `VAD_MIN_UTTERANCE_SECONDS` | | | |

## Test script (reuse in every later run)
1.
2.
3.
4.
5.

## Checks
- [ ] Utterances end at the right time (no early cut-off, no long hang)
- [ ] Half-duplex: Frieren's voice from the speakers is not transcribed as the user
- [ ] `playback_done` arrives and listening resumes
- [ ] Reconnect works after closing and reopening the client
- [ ] Memory mode logged per turn (`light` / `full`)

## Baseline observations
Rough voice-to-voice latency by feel / stopwatch, before N1 exists:

## Issues found
-
