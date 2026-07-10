"""Local Ollama model startup, persona loading, and chat requests for soul_shiori."""

import json
import os
import random
import subprocess
import sys
import time
import urllib.request

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_MODEL = "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q6_K"
OLLAMA_KEEP_ALIVE = "30m"  # keep the model resident between turns instead of the 5m default
OLLAMA_STARTUP_TIMEOUT = 30.0

# Most turns stay short/chatty; rare longer replies for variety.
LENGTH_PRESETS = [
    {"num_predict": 80, "hint": "Reply in one short sentence, like a quick text back."},
    {"num_predict": 120, "hint": "Reply in 1-2 short sentences -- natural conversational length."},
    {"num_predict": 180, "hint": "You may go a little longer this turn, up to 3-4 sentences, still conversational."},
]
LENGTH_WEIGHTS = [0.66, 0.30, 0.04]

SOUL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soul")


def load_system_prompt() -> str:
    """Read Shiori's persona/system prompt from the `soul` file, if present."""
    try:
        with open(SOUL_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _ollama_is_reachable() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=1.5):
            return True
    except Exception:
        return False


def ensure_ollama_server() -> None:
    """Start `ollama serve` if it isn't already running, and wait until it responds."""
    if _ollama_is_reachable():
        print("Ollama server already running.")
        return

    print("Ollama server not detected, starting 'ollama serve'...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Could not find the 'ollama' executable on PATH. Install Ollama (or start it manually), then re-run."
        ) from exc

    deadline = time.monotonic() + OLLAMA_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if _ollama_is_reachable():
            print("Ollama server is up.")
            return
        time.sleep(0.5)
    raise RuntimeError(f"Ollama server did not respond within {OLLAMA_STARTUP_TIMEOUT:.0f}s.")


def preload_model() -> None:
    """Load OLLAMA_MODEL into memory up front, so the first reply isn't slow."""
    print(f"Loading '{OLLAMA_MODEL}' into Ollama (first run may take a while to download/load)...")
    payload = json.dumps({"model": OLLAMA_MODEL, "keep_alive": OLLAMA_KEEP_ALIVE}).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            response.read()
        print("Model loaded.")
    except Exception as exc:
        print(f"(warning: could not preload model, it will load on the first message instead: {exc})", file=sys.stderr)


def ask_ollama(history: list[dict]) -> str:
    preset = random.choices(LENGTH_PRESETS, weights=LENGTH_WEIGHTS)[0]
    # Qwen's chat template requires the system message to be the first message
    # in the list (a trailing system message raises a template error), so the
    # per-turn length hint is folded into the existing leading system message
    # for this call only -- it is never persisted into `history`.
    messages = list(history)
    if messages and messages[0]["role"] == "system":
        messages[0] = {
            "role": "system",
            "content": messages[0]["content"] + "\n\n" + preset["hint"],
        }
    else:
        messages = [{"role": "system", "content": preset["hint"]}] + messages
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "think": False,
            "options": {"num_predict": preset["num_predict"]},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["message"]["content"].strip()


class LocalModel:
    """Wraps Ollama startup, persona seeding, and chat requests."""

    def __init__(self) -> None:
        self.system_prompt = load_system_prompt()

    def start(self) -> None:
        """Raises RuntimeError if the Ollama server can't be reached/started."""
        ensure_ollama_server()
        preload_model()

    def build_initial_history(self) -> list[dict]:
        return [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []

    def ask(self, history: list[dict]) -> str:
        return ask_ollama(history)
