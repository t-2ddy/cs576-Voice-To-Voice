"""Microphone capture, RMS VAD, and OpenAI speech-to-text.

Env (server/.env):
  OPENAI_API_KEY
  STT_MODEL  (optional, default gpt-4o-mini-transcribe; whisper-1 also works)
  VAD_THRESHOLD_MULTIPLIER, VAD_MIN_THRESHOLD, VAD_START_FRAMES,
  VAD_SILENCE_END_MS, VAD_MIN_UTTERANCE_SECONDS, VAD_DEBUG  (optional tuning)
"""

import io
import os
import queue
import sys
import time
import unicodedata
import wave

import numpy as np
import sounddevice as sd

from metrics import TurnTimer
from openai_client import get_openai_client


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

CALIBRATION_SECONDS = 1.0
SPEECH_THRESHOLD_MULTIPLIER = _env_float("VAD_THRESHOLD_MULTIPLIER", 3.0)
# Floor so a dead-silent room doesn't trigger on tiny noise.
MIN_THRESHOLD = _env_float("VAD_MIN_THRESHOLD", 200.0)

SPEECH_START_FRAMES = int(_env_float("VAD_START_FRAMES", 3))  # consecutive loud frames to start
SILENCE_END_MS = int(_env_float("VAD_SILENCE_END_MS", 800))  # trailing silence to end
MAX_UTTERANCE_SECONDS = 30
PRE_BUFFER_MS = 300  # kept before speech onset so the start of words isn't clipped
# Discard shorter blips (coughs, clicks, etc.).
MIN_UTTERANCE_SECONDS = _env_float("VAD_MIN_UTTERANCE_SECONDS", 0.3)
VAD_DEBUG = os.getenv("VAD_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")

STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe").strip()
STT_FALLBACK_MODEL = "whisper-1"
STT_PROMPT = (
    "English conversation with Frieren, an elf mage. "
    "Names: Frieren, Fern, Stark, Himmel, Heiter, Eisen."
)


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


def record_utterance(
    frame_queue: queue.Queue, threshold: float
) -> tuple[np.ndarray, float] | None:
    """Blocks until a full utterance (speech surrounded by silence) is captured.

    Returns (audio, speech_end) where speech_end is the wall-clock time of the
    last loud frame, or None if the utterance was too short.
    """
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
    peak = max(rms(f) for f in recorded)
    end_reason = "silence"
    while True:
        frame = frame_queue.get()
        recorded.append(frame)

        level = rms(frame)
        peak = max(peak, level)
        silence_streak = 0 if level >= threshold else silence_streak + 1
        if silence_streak >= silence_end_frames:
            break
        if len(recorded) >= max_frames:
            print("(max utterance length reached, cutting off)")
            end_reason = "max length"
            break
    speech_end = time.time() - silence_streak * FRAME_MS / 1000

    audio = np.concatenate(recorded)
    duration = len(audio) / SAMPLE_RATE
    too_short = duration < MIN_UTTERANCE_SECONDS
    if VAD_DEBUG:
        reason = "too short, dropped" if too_short else end_reason
        print(
            f"(vad: {duration:.2f}s, peak RMS {peak:.0f}, threshold {threshold:.0f}, end: {reason})",
            file=sys.stderr,
        )
    if too_short:
        return None
    return audio, speech_end


def _to_wav_bytes(audio_int16: np.ndarray) -> bytes:
    """Wrap mono int16 PCM in an in-memory WAV container for upload."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio_int16.tobytes())
    return buffer.getvalue()


def _mostly_non_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
    return non_latin * 2 > len(letters)


def _transcribe_with(model: str, wav: bytes) -> str:
    result = get_openai_client().audio.transcriptions.create(
        model=model,
        file=("utterance.wav", wav, "audio/wav"),
        language="en",
        prompt=STT_PROMPT,
    )
    return result.text.strip()


def _normalize(text: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in text).split())


_PROMPT_NORM = _normalize(STT_PROMPT)


def _is_prompt_echo(text: str) -> bool:
    """On noise/silence the model can return the vocabulary prompt verbatim."""
    norm = _normalize(text)
    return bool(norm) and len(norm) > 12 and norm in _PROMPT_NORM


def transcribe(audio_int16: np.ndarray) -> str | None:
    """Transcribe English speech; returns None for prompt echoes or non-English script."""
    wav = _to_wav_bytes(audio_int16)
    text = _transcribe_with(STT_MODEL, wav)
    if _is_prompt_echo(text):
        print("(dropped STT prompt echo; likely noise)", file=sys.stderr)
        return None
    if not _mostly_non_latin(text):
        return text
    if STT_MODEL != STT_FALLBACK_MODEL:
        retry = _transcribe_with(STT_FALLBACK_MODEL, wav)
        if _is_prompt_echo(retry):
            print("(dropped STT prompt echo; likely noise)", file=sys.stderr)
            return None
        if not _mostly_non_latin(retry):
            return retry
        text = retry
    print(f"(dropped non-English transcript: {text})", file=sys.stderr)
    return None


class SpeechToText:
    """Owns the mic InputStream and frame queue/callback."""

    def __init__(self) -> None:
        self._frame_queue: queue.Queue = queue.Queue()
        get_openai_client()  # fail fast if OPENAI_API_KEY is missing
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            callback=self._audio_callback,
        )
        self._threshold = 0.0

    def _audio_callback(self, indata, _frames, _time_info, status) -> None:
        if status:
            print(f"(audio status: {status})", file=sys.stderr)
        self._frame_queue.put(indata[:, 0].copy())

    def __enter__(self) -> "SpeechToText":
        self._stream.start()
        self._threshold = calibrate_noise_floor(self._frame_queue)
        print("Listening... (Ctrl+C to quit)")
        return self

    def __exit__(self, *exc_info) -> None:
        self._stream.stop()
        self._stream.close()

    def flush(self) -> None:
        """Drop queued mic frames (e.g. the character's own voice picked up during playback)."""
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                return

    def listen_for_utterance(self, timer: TurnTimer | None = None) -> str | None:
        """Blocks until one utterance is captured, returns its transcript (or None if too short)."""
        captured = record_utterance(self._frame_queue, self._threshold)
        if captured is None:
            return None
        audio, speech_end = captured
        if timer is not None:
            timer.mark("speech_end", speech_end)
            timer.mark("vad_end")
        text = transcribe(audio)
        if timer is not None:
            timer.mark("stt_done")
        return text
