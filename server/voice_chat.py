"""Mic -> STT -> LLM -> TTS voice loop for the cs576 voice companion.

Continuously listens to the microphone, auto-detects speech turns with a
simple RMS energy VAD, transcribes each utterance with OpenAI, sends the
conversation (plus Supabase memory context) to the OpenAI chat model, and
prints both the transcript and the reply to the terminal.

Also broadcasts the same turns over WebSocket (chat_bridge on :8766) so the
React client can live-replace the VN textbox.

Compartmentalized into:
- openai_client.py — shared OpenAI client (one OPENAI_API_KEY)
- speechToText.py — mic capture, VAD, OpenAI transcription
- local_model.py — OpenAI chat requests + persona
- chat_memory.py — Supabase four-tier memory (store / build_context_if_needed / prune)
- chat_bridge.py — WebSocket broadcast to the UI
- elevenlabs_tts.py — ElevenLabs REST TTS for character replies
- metrics.py — per-turn stage timing and the N1 latency CSV
- voice_chat.py (this file) — wires the services and runs the loop

See .cursor/rules/voice-to-voice.mdc for the overall architecture.
"""

import os
import queue
import sys
import threading
import time
from collections.abc import Iterator

from chat_bridge import (
    emit_audio,
    emit_audio_chunk,
    emit_audio_end,
    emit_audio_start,
    emit_chat,
    emit_status,
    get_playback_timing,
    start_chat_bridge,
    wait_for_client,
    wait_for_playback,
)
from chat_memory import build_context_if_needed, prune_recent_turns, store_turn
import elevenlabs_tts
from elevenlabs_tts import extract_spoken_text, synthesize, synthesize_stream
from local_model import LocalModel, ask_stream
from metrics import TurnTimer, csv_path
from sentence_stream import SentenceSplitter
from speechToText import SpeechToText

# After this many assistant replies, archive overflow recent_turns into long-term memory.
PRUNE_EVERY_N_ASSISTANT_TURNS = 10
# ElevenLabs' default output is 128 kbps MP3, used to estimate clip length when
# the UI never reports playback_done (tab closed, autoplay blocked, etc.).
MP3_BYTES_PER_SECOND = 16_000
PLAYBACK_GRACE_SECONDS = 3.0
# Speaker tail / room echo still reaches the mic briefly after playback_done.
ECHO_TAIL_SECONDS = float(os.getenv("ECHO_TAIL_SECONDS", "0.3") or 0)
# 0 = wait for the browser UI until it connects (Ctrl+C to quit); >0 = give up
# after that many seconds and run terminal-only.
UI_WAIT_SECONDS = float(os.getenv("UI_WAIT_SECONDS", "0") or 0)
UI_WAIT_REMINDER_SECONDS = 15.0


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# N3a: stream TTS audio chunks to the browser instead of sending one full clip.
TTS_STREAMING = _env_flag("TTS_STREAMING", True)
# N3b: stream the reply text and synthesize it sentence by sentence (needs TTS_STREAMING).
LLM_STREAMING = _env_flag("LLM_STREAMING", True) and TTS_STREAMING


def _wait_for_ui() -> None:
    print("Waiting for UI at http://localhost:5173 (open or focus the tab) ...")
    started = time.monotonic()
    next_reminder = started + UI_WAIT_REMINDER_SECONDS
    # Short slices keep Ctrl+C responsive on Windows.
    while UI_WAIT_SECONDS <= 0 or time.monotonic() - started < UI_WAIT_SECONDS:
        if wait_for_client(0.5):
            print("UI connected.")
            return
        if time.monotonic() >= next_reminder:
            print("(still waiting for UI; is http://localhost:5173 open?)", file=sys.stderr)
            next_reminder += UI_WAIT_REMINDER_SECONDS
    print(
        f"(no UI connected after {UI_WAIT_SECONDS:.0f}s; continuing in terminal-only mode)",
        file=sys.stderr,
    )


def _build_ask_history(persona: str, context: str, user_text: str) -> list[dict]:
    """System (persona + memory context) + current user turn for one chat call.

    Recent turns live in `context` from Supabase, so we do not also replay a
    long local history (avoids double-sending the same turns).
    """
    system_parts = [p for p in (persona, context) if p]
    history: list[dict] = []
    if system_parts:
        history.append({"role": "system", "content": "\n\n".join(system_parts)})
    history.append({"role": "user", "content": user_text})
    return history


class StreamedReply:
    """Runs ask_stream in a thread and hands out complete sentences as they form (N3b)."""

    _DONE = object()

    def __init__(self, history: list[dict], timer: TurnTimer) -> None:
        self._timer = timer
        self._queue: queue.Queue = queue.Queue()
        self.parts: list[str] = []
        self.error: Exception | None = None
        threading.Thread(target=self._produce, args=(history,), daemon=True).start()

    def _produce(self, history: list[dict]) -> None:
        splitter = SentenceSplitter()
        try:
            for delta in ask_stream(history):
                if not self.parts:
                    self._timer.mark("llm_first_token")
                self.parts.append(delta)
                for sentence in splitter.feed(delta):
                    self._queue.put(sentence)
            for sentence in splitter.flush():
                self._queue.put(sentence)
        except Exception as exc:  # surfaced to the main loop via self.error
            self.error = exc
        finally:
            self._timer.mark("llm_done")
            self._queue.put(self._DONE)

    def sentences(self) -> Iterator[str]:
        while True:
            item = self._queue.get()
            if item is self._DONE:
                return
            if "first_sentence" not in self._timer.marks:
                self._timer.mark("first_sentence")
            self._timer.sentences += 1
            yield item

    @property
    def text(self) -> str:
        return "".join(self.parts).strip()


def _stream_speech(sentences: Iterator[str], timer: TurnTimer, show_text: bool) -> int:
    """Synthesize each sentence with streaming TTS into one audio_start/audio_end stream.

    show_text=True live-updates the UI textbox with the reply so far (N3b).
    Returns total MP3 bytes sent (0 if nothing was spoken).
    """
    stream_id: int | None = None
    total = chunks = 0
    shown: list[str] = []
    spoken_so_far = ""
    for sentence in sentences:
        shown.append(sentence)
        if show_text:
            emit_chat("frieren", " ".join(shown))
        spoken = extract_spoken_text(sentence)
        if not spoken:
            continue
        try:
            for chunk in synthesize_stream(spoken, previous_text=spoken_so_far or None):
                if stream_id is None:
                    timer.mark("tts_first_byte")
                    timer.tts_handshake_ms = elevenlabs_tts.last_handshake_ms
                    emit_status("speaking")
                    stream_id = emit_audio_start()
                    timer.mark("audio_sent")
                    timer.first_chunk_bytes = len(chunk)
                emit_audio_chunk(chunk)
                total += len(chunk)
                chunks += 1
        except RuntimeError as exc:
            print(f"(ElevenLabs TTS failed: {exc})", file=sys.stderr)
            emit_status("error", f"TTS failed: {exc}")
            timer.note("tts_failed")
            break
        spoken_so_far = f"{spoken_so_far} {spoken}".strip()
    if stream_id is not None:
        timer.mark("tts_done")
        emit_audio_end(stream_id, total, chunks)
    timer.mp3_bytes = timer.ws_bytes = total
    timer.chunks = chunks
    return total


def main() -> None:
    try:
        start_chat_bridge()
    except RuntimeError as exc:
        print(f"Error: {exc} (is another voice_chat.py already running?)", file=sys.stderr)
        sys.exit(1)
    print("Chat UI bridge listening on ws://127.0.0.1:8766")
    try:
        _wait_for_ui()
    except KeyboardInterrupt:
        print("\nExiting.")
        return

    local_model = LocalModel()
    try:
        local_model.start()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Open the TTS connection now so the first turn doesn't pay the TLS handshake.
    try:
        elevenlabs_tts.warm_up()
    except RuntimeError as exc:
        print(f"(ElevenLabs warm-up failed: {exc})", file=sys.stderr)

    # Each session starts fresh; past turns stay recallable via chat_memory + summary.
    print("Archiving previous conversation...")
    try:
        prune_recent_turns(keep_last=0)
    except Exception as exc:
        print(f"(startup archive failed: {exc})", file=sys.stderr)

    print(f"Latency log: {csv_path()}")
    persona = local_model.system_prompt
    assistant_turns = 0
    turn_number = 0

    with SpeechToText() as stt:
        try:
            while True:
                emit_status("listening")
                timer = TurnTimer(turn_number + 1)
                try:
                    text = stt.listen_for_utterance(timer)
                except Exception as exc:
                    print(f"(speech-to-text request failed: {exc})", file=sys.stderr)
                    emit_status("error", f"STT failed: {exc}")
                    continue
                if not text:
                    continue
                turn_number += 1
                timer.user_chars = len(text)

                print(f"You: {text}")
                emit_chat("you", text)

                try:
                    emit_status("thinking")
                    context, memory_mode = build_context_if_needed(text)
                    timer.mark("memory_done")
                    timer.memory_mode = memory_mode
                    print(f"(memory: {memory_mode})")
                    ask_history = _build_ask_history(persona, context, text)
                    streamed = StreamedReply(ask_history, timer) if LLM_STREAMING else None
                    reply = "" if streamed else local_model.ask(ask_history)
                    if not streamed:
                        timer.mark("llm_done")
                except Exception as exc:
                    print(f"(chat/memory request failed: {exc})", file=sys.stderr)
                    emit_status("error", str(exc))
                    continue

                audio_bytes = 0
                spoken = ""
                chat_shown = False
                if streamed:
                    audio_bytes = _stream_speech(streamed.sentences(), timer, show_text=True)
                    reply = streamed.text
                    if streamed.error is not None:
                        print(f"(chat stream failed: {streamed.error})", file=sys.stderr)
                        emit_status("error", str(streamed.error))
                        if not reply:
                            continue
                    spoken = extract_spoken_text(reply)
                    emit_chat("frieren", reply)
                    chat_shown = True
                else:
                    spoken = extract_spoken_text(reply)
                    if not spoken:
                        print("(empty spoken text; skipping TTS)", file=sys.stderr)
                    elif TTS_STREAMING:
                        emit_chat("frieren", reply)
                        chat_shown = True
                        audio_bytes = _stream_speech(iter([reply]), timer, show_text=False)
                    else:
                        try:
                            mp3 = synthesize(spoken)
                            timer.mark("tts_done")
                            timer.tts_handshake_ms = elevenlabs_tts.last_handshake_ms
                            timer.mp3_bytes = audio_bytes = len(mp3)
                            emit_status("speaking")
                            emit_chat("frieren", reply)
                            chat_shown = True
                            timer.mark("audio_sent")
                            timer.ws_bytes = emit_audio(mp3)
                        except Exception as exc:
                            print(f"(ElevenLabs TTS failed: {exc})", file=sys.stderr)
                            emit_status("error", f"TTS failed: {exc}")
                timer.reply_chars = len(reply)
                print(f"Frieren: {reply}")

                if audio_bytes:
                    # Half-duplex: don't listen while the reply plays, or the mic
                    # hears Frieren through the speakers and she answers herself.
                    timeout = audio_bytes / MP3_BYTES_PER_SECOND + PLAYBACK_GRACE_SECONDS
                    played = wait_for_playback(timeout)
                    if played and ECHO_TAIL_SECONDS > 0:
                        time.sleep(ECHO_TAIL_SECONDS)
                    stt.flush()
                    playback = get_playback_timing()
                    if playback:
                        timer.mark("recv", playback["recv"])
                        timer.mark("play", playback["play"])
                        if playback["blocked"]:
                            timer.note("autoplay_blocked")
                    else:
                        timer.note("no_playback_report" if played else "no_ui_or_timeout")
                else:
                    timer.note("tts_failed" if spoken else "no_tts")
                    if not chat_shown:
                        emit_chat("frieren", reply)

                print(timer.summary())
                try:
                    timer.write_row()
                except OSError as exc:
                    print(f"(failed to write metrics CSV: {exc})", file=sys.stderr)

                try:
                    store_turn("user", text)
                    store_turn("assistant", reply)
                except Exception as exc:
                    print(f"(failed to store turns: {exc})", file=sys.stderr)
                    emit_status("error", f"failed to store turns: {exc}")
                    continue

                assistant_turns += 1
                if assistant_turns % PRUNE_EVERY_N_ASSISTANT_TURNS == 0:
                    try:
                        prune_recent_turns(keep_last=10)
                    except Exception as exc:
                        print(f"(prune_recent_turns failed: {exc})", file=sys.stderr)
                        emit_status("error", f"prune failed: {exc}")
        except KeyboardInterrupt:
            print("\nExiting.")


if __name__ == "__main__":
    main()
