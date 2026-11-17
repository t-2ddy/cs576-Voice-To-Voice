# Wireshark captures

Loopback capture on Windows via Npcap ("Adapter for loopback traffic capture"). Files go in `captures/`.

## Filters
- WS bridge: `tcp.port == 8766`
- Vite dev proxy: `tcp.port == 5173`
- Outbound APIs (TLS): `tls.handshake.type == 1` (ClientHello, shows SNI for OpenAI / ElevenLabs / Supabase)

## Capture log
| File | Date | What it shows | Related item |
|---|---|---|---|
| | | WS upgrade: HTTP GET → `101 Switching Protocols` | baseline |
| | | Text frame with base64 MP3 (before) | N2 |
| | | Binary frame with MP3 (after) | N2 |
| | | One TLS handshake per TTS call vs reused | N2 |
| | | Streamed audio chunks | N3 |
| | | Ping / pong keepalive | N7 |
| | | Rejected handshake (bad token / Origin) | N6 |

## Notes for the report
-
