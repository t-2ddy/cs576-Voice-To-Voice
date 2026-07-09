"""Standalone mic -> STT -> local LLM test harness for soul_shiori.

Continuously listens to the microphone, auto-detects speech turns with a
simple RMS energy VAD, transcribes each utterance with faster-whisper, sends
the running conversation to the local Ollama model, and prints both the
transcript and the reply to the terminal.

Compartmentalized into:
- speechToText.py — mic capture, VAD, faster-whisper
- local_model.py — Ollama server/model + chat requests
- voice_chat.py (this file) — wires the two and runs the loop

Not yet wired into orchestrator.py / the WebSocket bridge -- see
.cursor/rules/soul-shiori.mdc for the overall architecture.
"""

import sys

from local_model import LocalModel
from speechToText import SpeechToText


def main() -> None:
    local_model = LocalModel()
    try:
        local_model.start()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    history = local_model.build_initial_history()

    with SpeechToText() as stt:
        try:
            while True:
                text = stt.listen_for_utterance()
                if not text:
                    continue

                print(f"You: {text}")
                history.append({"role": "user", "content": text})

                try:
                    reply = local_model.ask(history)
                except Exception as exc:
                    print(f"(Ollama request failed: {exc})", file=sys.stderr)
                    history.pop()
                    continue

                print(f"Shiori: {reply}")
                history.append({"role": "assistant", "content": reply})
        except KeyboardInterrupt:
            print("\nExiting.")


if __name__ == "__main__":
    main()
