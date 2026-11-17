# Decisions log

Dated tuning and design decisions that affect measurements. Newest first.

| Date | Decision | Reason | Affects |
|---|---|---|---|
| 2026-11-17 | `VAD_SILENCE_END_MS` = 900 (default 800) | Fewer mid-sentence cut-offs in the end-to-end test | VAD tail in every latency number |
