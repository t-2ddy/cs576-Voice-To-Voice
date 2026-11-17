# Decisions log

Dated tuning and design decisions that affect measurements. Newest first.

| Date | Decision | Reason | Affects |
|---|---|---|---|
| 2026-11-17 | Recent-turns context window 10 → 30 rows (`RECENT_TURNS_LIMIT` in `chat_memory.py`) | Run 1 line 9 recall failed: turns fell out of the 10-row window before the next prune archived them into `chat_memory`. 30 covers every row the table can hold between prunes | Prompt size (up to ~28 short turns); no extra network calls |
| 2026-11-17 | `VAD_SILENCE_END_MS` = 900 (default 800) | Fewer mid-sentence cut-offs in the end-to-end test | VAD tail in every latency number |
