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
- voice_chat.py (this file) — wires the services and runs the loop

See .cursor/rules/voice-to-voice.mdc for the overall architecture.
"""

import os
import sys
import time

from chat_bridge import (
    emit_audio,
    emit_chat,
    emit_status,
    start_chat_bridge,
    wait_for_client,
    wait_for_playback,
)
from chat_memory import build_context_if_needed, prune_recent_turns, store_turn
from elevenlabs_tts import extract_spoken_text, synthesize
from local_model import LocalModel
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

    # Each session starts fresh; past turns stay recallable via chat_memory + summary.
    print("Archiving previous conversation...")
    try:
        prune_recent_turns(keep_last=0)
    except Exception as exc:
        print(f"(startup archive failed: {exc})", file=sys.stderr)

    persona = local_model.system_prompt
    assistant_turns = 0

    with SpeechToText() as stt:
        try:
            while True:
                emit_status("listening")
                try:
                    text = stt.listen_for_utterance()
                except Exception as exc:
                    print(f"(speech-to-text request failed: {exc})", file=sys.stderr)
                    emit_status("error", f"STT failed: {exc}")
                    continue
                if not text:
                    continue

                print(f"You: {text}")
                emit_chat("you", text)

                try:
                    emit_status("thinking")
                    context, memory_mode = build_context_if_needed(text)
                    print(f"(memory: {memory_mode})")
                    ask_history = _build_ask_history(persona, context, text)
                    reply = local_model.ask(ask_history)
                except Exception as exc:
                    print(f"(chat/memory request failed: {exc})", file=sys.stderr)
                    emit_status("error", str(exc))
                    continue

                print(f"Frieren: {reply}")
                spoken = extract_spoken_text(reply)
                mp3: bytes | None = None
                if spoken:
                    try:
                        mp3 = synthesize(spoken)
                    except Exception as exc:
                        print(f"(ElevenLabs TTS failed: {exc})", file=sys.stderr)
                        emit_status("error", f"TTS failed: {exc}")
                else:
                    print("(empty spoken text; skipping TTS)", file=sys.stderr)

                if mp3:
                    emit_status("speaking")
                    emit_chat("frieren", reply)
                    emit_audio(mp3)
                    # Half-duplex: don't listen while the reply plays, or the mic
                    # hears Frieren through the speakers and she answers herself.
                    timeout = len(mp3) / MP3_BYTES_PER_SECOND + PLAYBACK_GRACE_SECONDS
                    if wait_for_playback(timeout) and ECHO_TAIL_SECONDS > 0:
                        time.sleep(ECHO_TAIL_SECONDS)
                    stt.flush()
                else:
                    emit_chat("frieren", reply)

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
