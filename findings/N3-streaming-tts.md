# N3 · Streaming TTS

## Goal
Stream ElevenLabs audio in chunks, forward each chunk over the WS, and start playback on the first chunk.

## Approach
- Chunked HTTP or ElevenLabs WS endpoint:
- Client playback method (MediaSource / Web Audio):
- How `playback_done` still works with chunks:

## Hypothesis
Time-to-first-audio drops sharply; total generation time stays about the same.

## Setup
- Date: · Commit before: · Commit after:

## Results
| Metric | Before (full clip) | After (streaming) | Change |
|---|---|---|---|
| Time to first audio byte at server (ms) | | | |
| Time to first audio played (ms) | | | |
| Total voice-to-voice median (ms) | | | |
| Total voice-to-voice p90 (ms) | | | |
| Chunks per reply | n/a | | |
| Chunk size (bytes) | n/a | | |

## Analysis
Does reply length still matter? Any audible gaps between chunks?

## Issues / caveats
-
