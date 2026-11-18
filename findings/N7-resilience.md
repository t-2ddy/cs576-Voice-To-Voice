# N7 · Resilience

> **Status: TBD.** Not in the presentation scope. See the priority table in `README.md`.

## Goal
Tuned heartbeats, session resume with message sequence numbers, and jittered-backoff retries on API errors / HTTP 429.

## Current behaviour (baseline)
- `websockets` keepalive ping every 20 s (default)
- Client reconnect: exponential backoff ×1.5, capped at 10 s
- API errors:

## Experiments
| Scenario | How induced | Recovery time before (ms) | Recovery time after (ms) | Messages lost before | Messages lost after |
|---|---|---|---|---|---|
| Client tab reload | | | | | |
| Server restart | | | | | |
| Network drop 5 s | clumsy | | | | |
| API 429 / 5xx | forced / mocked | | | | |

## Heartbeat tuning
| Ping interval (s) | Ping timeout (s) | Dead-connection detection time (s) | Overhead (bytes/min) |
|---|---|---|---|
| 20 (default) | | | |
| | | | |

## Analysis

## Issues / caveats
-
