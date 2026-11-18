# N6 · Security + multi-user

> **Status: TBD.** Not in the presentation scope. See the priority table in `README.md`.

## Goal
`wss://` through a reverse proxy, an auth token checked during the WS handshake, an `Origin` check against cross-site WebSocket hijacking, and per-user sessions (which also fixes the shared global memory).

## Threat model
| Threat | Current exposure | Mitigation | Verified how |
|---|---|---|---|
| Eavesdropping on LAN | | TLS (`wss://`) | |
| Unauthorized client connects | | Handshake token | |
| Cross-site WebSocket hijacking | | `Origin` check | |
| One user reads another's memory | | Per-user session / memory scoping | |
| API key exposure | | Keys stay server-side | |

## Handshake trace
Screenshot or capture in `captures/`: `101 Switching Protocols`, with and without a valid token / Origin.

## Results
| Test | Expected | Observed |
|---|---|---|
| No token | rejected | |
| Bad Origin | rejected | |
| Valid token + Origin | accepted | |
| TLS overhead on handshake (ms) | | |

## Issues / caveats
-
