# Wireshark captures

Loopback capture on Windows via Npcap ("Adapter for loopback traffic capture"). Files go in `captures/`.

## Filters
- WS bridge: `tcp.port == 8766`
- Vite dev proxy: `tcp.port == 5173`
- Outbound APIs (TLS): `tls.handshake.type == 1` (ClientHello, shows SNI for OpenAI / ElevenLabs / Supabase)

## Capture log
| File | Date | What it shows | Related item |
|---|---|---|---|
| `N2-before.pcapng` | 2026-11-17 | WS upgrade: HTTP GET → `101 Switching Protocols` (with `permessage-deflate`) | baseline |
| `N2-before.pcapng` | 2026-11-17 | Compressed text frames (RSV1) with base64 MP3, ≈ MP3 size on the wire | N2 |
| `N2-after.pcapng` | 2026-11-17 | 73-byte JSON header + binary frame (opcode 2, uncompressed) exactly the MP3 size; decode with `-d tcp.port==8766,websocket` (capture started after the upgrade) | N2 |
| `N2-before.pcapng` | 2026-11-17 | One new TLS connection per turn to OpenAI, Supabase, and ElevenLabs | N2 |
| `N2-after.pcapng` | 2026-11-17 | No new ClientHellos; one long-lived connection each to OpenAI, Supabase, ElevenLabs across 3 turns | N2 |
| `N3a-after.pcapng` | 2026-11-17 | `audio_start` JSON, many binary opcode-2 MP3 chunks, then `audio_end` (decode with `-d tcp.port==8766,websocket`); ~70 s / 3 sample turns | N3a |
| `N2-before.pcapng` | 2026-11-17 | Ping / pong keepalive every 20 s, 0.26–0.30 ms RTT on loopback | N7 |
| | | Rejected handshake (bad token / Origin) | N6 |

## Notes for the report
-
