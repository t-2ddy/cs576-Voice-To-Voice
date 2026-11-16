"""Microphone capture, RMS VAD, and OpenAI speech-to-text.

Env (server/.env):
  OPENAI_API_KEY
  STT_MODEL  (optional, default gpt-4o-mini-transcribe; whisper-1 also works)
"""

import io
import os
import queue
import sys
import wave

import numpy as np
import sounddevice as sd

from openai_client import get_openai_client

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

STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe").strip()


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


def _to_wav_bytes(audio_int16: np.ndarray) -> bytes:
    """Wrap mono int16 PCM in an in-memory WAV container for upload."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio_int16.tobytes())
    return buffer.getvalue()


def transcribe(audio_int16: np.ndarray) -> str:
    result = get_openai_client().audio.transcriptions.create(
        model=STT_MODEL,
        file=("utterance.wav", _to_wav_bytes(audio_int16), "audio/wav"),
        language="en",
    )
    return result.text.strip()


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

    def listen_for_utterance(self) -> str | None:
        """Blocks until one utterance is captured, returns its transcript (or None if too short)."""
        audio = record_utterance(self._frame_queue, self._threshold)
        if audio is None:
            return None
        return transcribe(audio)
