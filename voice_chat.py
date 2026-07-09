"""Standalone mic -> STT -> local LLM test harness for soul_shiori.

Continuously listens to the microphone, auto-detects speech turns with a
simple RMS energy VAD, transcribes each utterance with faster-whisper, sends
the running conversation to the local Ollama model, and prints both the
transcript and the reply to the terminal.

Compartmentalized into:
- speechToText.py — mic capture, VAD, faster-whisper
- local_model.py — Ollama server/model + chat requests
- chat_memory.py — Supabase four-tier memory (store / build_context / prune)
- voice_chat.py (this file) — wires the services and runs the loop

Not yet wired into orchestrator.py / the WebSocket bridge -- see
.cursor/rules/soul-shiori.mdc for the overall architecture.
"""

import sys

from chat_memory import build_context, prune_recent_turns, store_turn
from local_model import LocalModel
from speechToText import SpeechToText

# After this many assistant replies, archive overflow recent_turns into long-term memory.
PRUNE_EVERY_N_ASSISTANT_TURNS = 10
# Keep only the system message + this many latest user/assistant messages in the
# in-process history. Durable recent turns come from Supabase via build_context.
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
    local_model = LocalModel()
    try:
        local_model.start()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    persona = local_model.system_prompt
    # Session-local transcript for display/debug capping; Ollama asks use build_context.
    history: list[dict] = local_model.build_initial_history()
    assistant_turns = 0

    with SpeechToText() as stt:
        try:
            while True:
                text = stt.listen_for_utterance()
                if not text:
                    continue

                print(f"You: {text}")
                history.append({"role": "user", "content": text})

                try:
                    context = build_context(text)
                    ask_history = _build_ask_history(persona, context, text)
                    reply = local_model.ask(ask_history)
                except Exception as exc:
                    print(f"(Ollama/memory request failed: {exc})", file=sys.stderr)
                    history.pop()
                    continue

                print(f"Shiori: {reply}")
                history.append({"role": "assistant", "content": reply})
                history = _cap_local_history(history)

                try:
                    store_turn("user", text)
                    store_turn("assistant", reply)
                except Exception as exc:
                    print(f"(failed to store turns: {exc})", file=sys.stderr)
                    continue

                assistant_turns += 1
                if assistant_turns % PRUNE_EVERY_N_ASSISTANT_TURNS == 0:
                    try:
                        prune_recent_turns(keep_last=10)
                    except Exception as exc:
                        print(f"(prune_recent_turns failed: {exc})", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nExiting.")


if __name__ == "__main__":
    main()
