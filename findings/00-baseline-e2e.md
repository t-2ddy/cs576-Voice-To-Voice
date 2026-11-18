# 00 · Baseline end-to-end test

## Goal
Confirm the full pipeline works (mic → VAD → STT → chat + memory → TTS → WS → client playback) and tune turn-taking before any networking change.

## Setup
Update the date and commit on every run.

- Date: 2026-11-17
- Commit: `09fffe0` (runs 1–2), `deaae25` (runs 3–5, N1 baseline)
- Server: `python voice_chat.py` in `server/`
- Client: `npm run dev` in `client/`
- Models: `STT_MODEL=gpt-4o-mini-transcribe` · `LLM_MODEL=gpt-5.6-luna` (`LLM_REASONING_EFFORT=none`) · `ELEVENLABS_MODEL_ID=eleven_turbo_v2_5` (default, not set in `.env`)
- Audio: earbuds for output, separate mic for input (mic: ______)
- Reply length is picked at random each turn (`LENGTH_WEIGHTS = [0.66, 0.30, 0.04]` in `server/local_model.py`: one sentence / 1–2 sentences / 3–4 sentences), so the run log records each reply's character count.

## VAD / turn-taking tuning
Defaults come from `server/.env.example`.

| Setting | Default | Chosen | Why |
|---|---|---|---|
| `VAD_SILENCE_END_MS` | 800 | **1200** (900 for runs 1–2) | Run 1 split a turn at a pause with 900; no splits in runs 3–5 with 1200 |
| `VAD_THRESHOLD_MULTIPLIER` | 3.0 | 3.0 (unchanged) | |
| `VAD_MIN_THRESHOLD` | 200 | 200 (unchanged) | |
| `VAD_START_FRAMES` | 3 | 3 (unchanged) | |
| `VAD_MIN_UTTERANCE_SECONDS` | 0.3 | 0.3 (unchanged) | |
| `ECHO_TAIL_SECONDS` | 0.3 | 0.3 (unchanged) | |

## Test script (reuse in every later run)
Read each line word for word, in order. Wait for Frieren to finish and the status to return to listening before the next line. One run = 10 turns.

The expected memory mode comes from `should_retrieve_memory` in `server/chat_memory.py`: phrases such as "favorite", "what's my", or "remember" trigger `full`, and everything else is `light`. The name and the food are planted inside each run, so the recall lines work whatever earlier runs left in memory.

| # | Say | Expected memory | Tests |
|---|---|---|---|
| 1 | "Hey Frieren, call me proxie. I'm studying computer networks." | light | Plants the name without saying "my name", so it stays light |
| 2 | "What spell are you studying these days?" | light | Normal chat |
| 3 | "Okay." | light | Filler; a short utterance must not be dropped by `VAD_MIN_UTTERANCE_SECONDS` |
| 4 | "My favorite food is strawberry cake." | full | Plants a second fact |
| 5 | "I was thinking… *(pause about half a second)* …we should travel north next." | light | A pause shorter than `VAD_SILENCE_END_MS` (1200 ms) must not split the turn |
| 6 | "Tell me about a place you visited with Himmel, and why it stayed with you." | light | Invites a longer reply |
| 7 | "Today I spent the whole afternoon debugging a WebSocket connection that kept dropping, and I still don't know if it was the proxy or the server." | light | Long utterance (about 8 s), so a larger STT upload |
| 8 | "What's my name?" | full | She should answer proxie |
| 9 | "Do you remember my favorite food?" | full | She should answer strawberry cake |
| 10 | "Thanks, goodnight." | light | Closing line |

## Run log
Copy this table once per run. Latency is measured by stopwatch from the end of your speech to the first audio, until N1 replaces it.

### Template
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | | | light | | | | |
| 2 | | | light | | | | |
| 3 | | | light | | | | |
| 4 | | | full | | | | |
| 5 | | | light | | | | |
| 6 | | | light | | | | |
| 7 | | | light | | | | |
| 8 | | | full | | | | |
| 9 | | | full | | | | |
| 10 | | | light | | | | |

### Run 1: 2026-11-17, commit `09fffe0` (recent-turns window 10 rows)
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | y ("Firnen", "Proxy") | light | light | 149 | | | |
| 2 | y | light | light | 121 | | | UI refreshed after this reply (reconnect test) |
| 3 | y | light | light | 87 | | | Not dropped |
| 4 | y | full | full | 146 | | | |
| 5 | split: "I was thinking..." / "We should travel north." ("next" missing) | light, light | light | 30, 98 | cut-off | | Pause ended the turn |
| 6 | y | light | light | 196 | | | |
| 7 | y | light | light | 190 | | | |
| 8 | y | full | full | 19 | | | Recalled "Proxy" |
| 9 | y | full | full | 40 | | | **Recall failed** (window bug, since fixed) |
| 10 | y ("good night") | light | light | 59 | | | |

### Run 2: 2026-11-17, commit `09fffe0` + uncommitted `RECENT_TURNS_LIMIT = 30`
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | y ("Proxy") | light | light | 63 | | | |
| 2 | y | light | light | 91 | | | |
| 3 | y | light | light | 43 | | | Not dropped |
| 4 | y | full | full | 62 | | | "I remember": cross-run memory (rolling summary), expected |
| 5 | y (no "...", one turn) | light | light | 74 | | | Not split; pause may have been shorter than run 1 |
| 6 | y | light | light | 195 | | | |
| 7 | y | light | light | 145 | | | |
| 8 | y | full | full | 19 | | | Recalled "Proxy" |
| 9 | y | full | full | 35 | | | Recalled strawberry cake |
| 10 | y ("good night") | light | light | 62 | | | |

Runs 3–5 are the N1 baseline. Latency is `total_ms` from `data/N1-baseline-2026-11-17.csv` (end of speech to playback start); see `N1-latency-instrumentation.md` for the per-stage breakdown.

### Run 3: 2026-11-17 16:28, commit `deaae25`, `VAD_SILENCE_END_MS=1200`
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | y ("Proxy") | light | light | 84 | | 8800 | Autoplay blocked until click; excluded from stats |
| 2 | y | light | light | 78 | | 3856 | |
| 3 | y | light | light | 73 | | 3392 | Not dropped |
| 4 | y | full | full | 62 | | 3856 | "I remember": cross-run memory, expected |
| 5 | y (comma, one turn) | light | light | 88 | | 3703 | Not split |
| 6 | y | light | light | 138 | | 3600 | |
| 7 | y | light | light | 134 | | 4062 | |
| 8 | y | full | full | 19 | | 3604 | Recalled "Proxy" |
| 9 | y | full | full | 50 | | 3675 | Recalled strawberry cake |
| 10 | y ("good night") | light | light | 57 | | 3259 | |

### Run 4: 2026-11-17 16:30, commit `deaae25`, `VAD_SILENCE_END_MS=1200`
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | y ("Proxy") | light | light | 109 | | 3780 | |
| 2 | y | light | light | 88 | | 3565 | |
| 3 | y | light | light | 77 | | 3368 | Not dropped |
| 4 | y | full | full | 66 | | 3551 | |
| 5 | y (comma, one turn) | light | light | 89 | | 4545 | Not split; slowest STT of the baseline (1430 ms) |
| 6 | y | light | light | 121 | | 4010 | |
| 7 | y | light | light | 192 | | 4384 | |
| 8 | y | full | full | 19 | | 3393 | Recalled "Proxy" |
| 9 | y | full | full | 36 | | 3651 | Recalled strawberry cake |
| 10 | y ("good night") | light | light | 61 | | 3264 | |

### Run 5: 2026-11-17 16:33, commit `deaae25`, `VAD_SILENCE_END_MS=1200`
| # | Transcript correct (y/n + diff) | Memory logged | Expected | Reply chars | Cut-off / hang | Latency (ms) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | y ("Proxy") | light | light | 156 | | 4191 | |
| 2 | y | light | light | 155 | | 3926 | |
| 3 | y | light | light | 107 | | 3471 | Not dropped |
| 4 | y | full | full | 66 | | 3520 | |
| 5 | y (comma, one turn) | light | light | 106 | | 3789 | Not split |
| 6 | n: "why **I** stayed with you" | light | light | 142 | | 4007 | STT error; reply went along with it |
| 7 | y | light | light | 128 | | 3835 | |
| 8 | y | full | full | 19 | | 3388 | Recalled "Proxy" |
| 9 | y | full | full | 35 | | 4086 | Recalled strawberry cake |
| 10 | y ("Thanks. Good night.") | light | light | 61 | | 3580 | |

## Checks
- [x] Utterances end at the right time (no early cut-off, no long hang); line 3 is not dropped; line 5 is not split (runs 3–5 with 1200 ms; run 1 split at 900 ms)
- [x] Transcripts match the script: 1 error in 30 baseline turns (run 5 line 6, "it" → "I"); "proxie" is always "Proxy"
- [x] Memory mode logged per turn matches the Expected column; lines 8 and 9 recall correctly (all of runs 2–5)
- [ ] UI status goes listening → thinking → speaking → ready on each turn (not checked)
- [x] `playback_done` arrives and listening resumes without waiting for the timeout (every baseline turn got a `playback_started` report; no `no_ui_or_timeout` flags)
- [x] Reconnect works after closing and reopening the client (run 1: page refreshed after line 2, line 3 continued normally)
- [ ] An error stays visible in the status bar until the next user turn (not tested)
- [ ] *Deferred, low priority:* speaker echo test (laptop speakers + built-in mic) to confirm Frieren's voice is not transcribed as the user. Not exercised in the current setup, since earbuds plus a separate mic avoid echo.

## Baseline observations
Measured with N1 instead of a stopwatch (runs 3–5), from end of speech to playback start:

- **Median: 3675 ms · p90: 4107 ms** (n = 29 turns; 1 autoplay-blocked turn excluded)
- About a third is the 1200 ms VAD silence wait, about 60% is hosted API calls (STT 758, LLM 1062, TTS 403 ms medians), and the local WebSocket hop is ~5 ms. Full breakdown in `N1-latency-instrumentation.md`.

## Issues found
- Run 1, line 9: "I don't remember your favorite food yet." The fact (line 4) had left the 10-row recent-turns window but no prune had run yet, so semantic search couldn't find it either. Fixed by raising the window to 30 rows (see `decisions-log.md`); later runs should recall it.
- Run 1, line 5: the pause split the turn in two ("I was thinking..." / "We should travel north."). Raised `VAD_SILENCE_END_MS` to 1200; no splits in runs 3–5.
- STT hears "proxie" as "Proxy" and "Frieren" as "Firnen". Counted as correct.
- Not a bug, by design: long-term memory carries across runs. Startup folds the previous run into the rolling summary (included in every turn) and `chat_memory`, so in run 2, line 4 got "I remember, Proxy." Recall on lines 8–9 is still a valid in-run test because the facts are inside the 30-row window. Expect replies to reference earlier runs.
