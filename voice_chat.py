"""Standalone mic -> STT -> local LLM test harness for soul_shiori.

Continuously listens to the microphone, auto-detects speech turns with a
simple RMS energy VAD, transcribes each utterance with faster-whisper, sends
the running conversation to the local Ollama model, and prints both the
transcript and the reply to the terminal.

Not yet wired into orchestrator.py / the WebSocket bridge -- see
.cursor/rules/soul-shiori.mdc for the overall architecture.
"""

import ctypes
import importlib.util
import json
import os
import queue
import random
import subprocess
import sys
import time
import urllib.request

import numpy as np
import sounddevice as sd


def _add_nvidia_dll_dirs() -> None:
    """Register pip-installed NVIDIA CUDA/cuDNN DLL folders (nvidia-cublas-cu12,
    nvidia-cudnn-cu12) so CTranslate2 can find cublas64_12.dll / cudnn64_9.dll
    on Windows without requiring them to be on the system PATH."""
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(package)
        if not spec or not spec.submodule_search_locations:
            continue
        bin_dir = os.path.join(next(iter(spec.submodule_search_locations)), "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)


def _preload_cuda_dlls() -> None:
    """Explicitly load cuBLAS/cuDNN via ctypes so they're already resident in
    the process. CTranslate2 loads these internally via a plain LoadLibrary()
    call that does NOT consult os.add_dll_directory()-registered folders, but
    Windows resolves LoadLibrary for an already-loaded DLL instantly from the
    process's module cache regardless of search flags, so preloading here is
    what actually makes CTranslate2's later internal load succeed."""
    if sys.platform != "win32":
        return
    for dll_name in ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(dll_name)
        except OSError:
            pass


_add_nvidia_dll_dirs()
_preload_cuda_dlls()

from faster_whisper import WhisperModel  # noqa: E402 (must follow DLL directory setup)

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

CALIBRATION_SECONDS = 1.0
SPEECH_THRESHOLD_MULTIPLIER = 3.0
MIN_THRESHOLD = 200.0  # floor so a dead-silent room doesn't trigger on tiny noise

SPEECH_START_FRAMES = 3  # consecutive loud frames needed to start recording
SILENCE_END_MS = 800  # trailing silence needed to end an utterance
MAX_UTTERANCE_SECONDS = 30
PRE_BUFFER_MS = 300  # kept before speech onset so the start of words isn't clipped
MIN_UTTERANCE_SECONDS = 0.3  # discard shorter blips (coughs, clicks, etc.)

WHISPER_MODEL_NAME = "large-v3-turbo"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_MODEL = "hf.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q6_K"
OLLAMA_KEEP_ALIVE = "30m"  # keep the model resident between turns instead of the 5m default
OLLAMA_STARTUP_TIMEOUT = 30.0

# Reply length is randomized per turn (both a hard token cap and a soft phrasing
# hint) so responses don't all come out the same length. Weighted towards
# short/medium so it still reads as "about half" the old unconstrained length
# on average, with occasional longer rambles for variety.
LENGTH_PRESETS = [
    {"num_predict": 40, "hint": "Reply in one short sentence -- quick and punchy."},
    {"num_predict": 90, "hint": "Reply in 2-3 sentences -- your usual conversational length."},
    {"num_predict": 160, "hint": "Feel free to ramble a bit more than usual, 4-5 sentences."},
]
LENGTH_WEIGHTS = [0.35, 0.45, 0.20]

SOUL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soul")


def load_system_prompt() -> str:
    """Read Shiori's persona/system prompt from the `soul` file, if present."""
    try:
        with open(SOUL_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def calibrate_noise_floor(frame_queue: queue.Queue) -> float:
    print(f"Calibrating mic noise floor ({CALIBRATION_SECONDS:.0f}s, stay quiet)...")
    samples_needed = int(SAMPLE_RATE * CALIBRATION_SECONDS)
    collected = []
    total = 0
    while total < samples_needed:
        frame = frame_queue.get()
        collected.append(frame)
        total += len(frame)
    floor = rms(np.concatenate(collected))
    threshold = max(floor * SPEECH_THRESHOLD_MULTIPLIER, MIN_THRESHOLD)
    print(f"Noise floor RMS: {floor:.1f} -> speech threshold: {threshold:.1f}")
    return threshold


def record_utterance(frame_queue: queue.Queue, threshold: float) -> np.ndarray | None:
    """Blocks until a full utterance (speech surrounded by silence) is captured."""
    pre_buffer_frames = max(1, PRE_BUFFER_MS // FRAME_MS)
    silence_end_frames = max(1, SILENCE_END_MS // FRAME_MS)
    max_frames = (MAX_UTTERANCE_SECONDS * 1000) // FRAME_MS

    pre_buffer: list[np.ndarray] = []
    loud_streak = 0

    while True:
        frame = frame_queue.get()
        pre_buffer.append(frame)
        if len(pre_buffer) > pre_buffer_frames:
            pre_buffer.pop(0)

        loud_streak = loud_streak + 1 if rms(frame) >= threshold else 0
        if loud_streak >= SPEECH_START_FRAMES:
            break

    recorded = list(pre_buffer)
    silence_streak = 0
    while True:
        frame = frame_queue.get()
        recorded.append(frame)

        silence_streak = 0 if rms(frame) >= threshold else silence_streak + 1
        if silence_streak >= silence_end_frames:
            break
        if len(recorded) >= max_frames:
            print("(max utterance length reached, cutting off)")
            break

    audio = np.concatenate(recorded)
    if len(audio) / SAMPLE_RATE < MIN_UTTERANCE_SECONDS:
        return None
    return audio


def transcribe(model: WhisperModel, audio_int16: np.ndarray) -> str:
    audio_f32 = audio_int16.astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio_f32, vad_filter=True)
    return "".join(segment.text for segment in segments).strip()


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


def main() -> None:
    try:
        ensure_ollama_server()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    preload_model()

    print("Loading faster-whisper model (this can take a moment on first run)...")
    model = WhisperModel(WHISPER_MODEL_NAME, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)

    frame_queue: queue.Queue = queue.Queue()

    def audio_callback(indata, _frames, _time_info, status):
        if status:
            print(f"(audio status: {status})", file=sys.stderr)
        frame_queue.put(indata[:, 0].copy())

    persona = load_system_prompt()
    history: list[dict] = [{"role": "system", "content": persona}] if persona else []

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME_SAMPLES,
        callback=audio_callback,
    ):
        threshold = calibrate_noise_floor(frame_queue)
        print("Listening... (Ctrl+C to quit)")

        try:
            while True:
                audio = record_utterance(frame_queue, threshold)
                if audio is None:
                    continue

                text = transcribe(model, audio)
                if not text:
                    continue

                print(f"You: {text}")
                history.append({"role": "user", "content": text})

                try:
                    reply = ask_ollama(history)
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
