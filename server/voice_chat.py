"""Standalone mic -> STT -> local LLM test harness for soul_shiori.

Continuously listens to the microphone, auto-detects speech turns with a
simple RMS energy VAD, transcribes each utterance with faster-whisper, sends
the running conversation to the local Ollama model, and prints both the
transcript and the reply to the terminal.

Also broadcasts the same turns over WebSocket (chat_bridge on :8766) so the
React client can live-replace the VN textbox.

Compartmentalized into:
- speechToText.py — mic capture, VAD, faster-whisper
- local_model.py — Ollama server/model + chat requests
- chat_memory.py — Supabase four-tier memory (store / build_context_if_needed / prune)
- chat_bridge.py — WebSocket broadcast to the UI
- elevenlabs_tts.py — ElevenLabs REST TTS for Shiori replies
- voice_chat.py (this file) — wires the services and runs the loop

Not yet wired into orchestrator.py / the Warudo WebSocket bridge -- see
.cursor/rules/soul-shiori.mdc for the overall architecture.
"""

import sys

from chat_bridge import emit_audio, emit_chat, emit_status, start_chat_bridge
from chat_memory import build_context_if_needed, prune_recent_turns, store_turn
from elevenlabs_tts import extract_spoken_text, synthesize
from local_model import LocalModel
from speechToText import SpeechToText

# After this many assistant replies, archive overflow recent_turns into long-term memory.
PRUNE_EVERY_N_ASSISTANT_TURNS = 10
# Keep only the system message + this many latest user/assistant messages in the
# in-process history. Durable recent turns come from Supabase via build_context_if_needed.
LOCAL_HISTORY_MAX_MESSAGES = 10


def _build_ask_history(persona: str, context: str, user_text: str) -> list[dict]:
    """System (persona + memory context) + current user turn for one Ollama call.

    Recent turns live in `context` from Supabase, so we do not also replay a
    long local history (avoids double-sending the same turns).
    """
    system_parts = [p for p in (persona, context) if p]
    history: list[dict] = []
    if system_parts:
        history.append({"role": "system", "content": "\n\n".join(system_parts)})
    history.append({"role": "user", "content": user_text})
    return history


def _cap_local_history(history: list[dict], max_messages: int = LOCAL_HISTORY_MAX_MESSAGES) -> list[dict]:
    """Keep leading system message (if any) plus the last max_messages turns."""
    if not history:
        return history
    if history[0]["role"] == "system":
        system = history[:1]
        rest = history[1:]
        return system + rest[-max_messages:]
    return history[-max_messages:]


def main() -> None:
    start_chat_bridge()
    print("Chat UI bridge listening on ws://127.0.0.1:8766")

    local_model = LocalModel()
    try:
        local_model.start()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    persona = local_model.system_prompt
    # Session-local transcript for display/debug capping; Ollama asks use build_context_if_needed.
    history: list[dict] = local_model.build_initial_history()
    assistant_turns = 0

    with SpeechToText() as stt:
        try:
            while True:
                emit_status("listening")
                text = stt.listen_for_utterance()
                if not text:
                    continue

                print(f"You: {text}")
                emit_chat("you", text)
                history.append({"role": "user", "content": text})

                try:
                    emit_status("thinking")
                    context, memory_mode = build_context_if_needed(text)
                    print(f"(memory: {memory_mode})")
                    ask_history = _build_ask_history(persona, context, text)
                    reply = local_model.ask(ask_history)
                except Exception as exc:
                    print(f"(Ollama/memory request failed: {exc})", file=sys.stderr)
                    emit_status("error", str(exc))
                    history.pop()
                    continue

                print(f"Shiori: {reply}")
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
                    emit_chat("shiori", reply)
                    emit_audio(mp3)
                else:
                    emit_chat("shiori", reply)
                emit_status("ready")
                history.append({"role": "assistant", "content": reply})
                history = _cap_local_history(history)

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
