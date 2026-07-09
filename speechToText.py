"""Microphone capture, RMS VAD, and faster-whisper transcription for soul_shiori."""

import ctypes
import importlib.util
import os
import queue
import sys

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


class SpeechToText:
    """Owns the Whisper model, mic InputStream, and frame queue/callback."""

    def __init__(self) -> None:
        self._frame_queue: queue.Queue = queue.Queue()
        print("Loading faster-whisper model (this can take a moment on first run)...")
        self._model = WhisperModel(
            WHISPER_MODEL_NAME, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
        )
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
        return transcribe(self._model, audio)
