"""ElevenLabs REST text-to-speech for Frieren replies.
Env (server/.env):
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID
"""
from __future__ import annotations
import os
import re
import time

import httpx
from dotenv import load_dotenv

from http_pool import persistent_client
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
load_dotenv()  # also allow cwd override
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
# Turbo for lower latency on short chat replies.
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5").strip()

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

ELEVENLABS_STABILITY = _env_float("ELEVENLABS_STABILITY", 0.75)
ELEVENLABS_SIMILARITY_BOOST = _env_float("ELEVENLABS_SIMILARITY_BOOST", 0.85)
ELEVENLABS_STYLE = _env_float("ELEVENLABS_STYLE", 0.1)
ELEVENLABS_SPEED = _env_float("ELEVENLABS_SPEED", .9)
ELEVENLABS_SPEAKER_BOOST = _env_bool("ELEVENLABS_SPEAKER_BOOST", True)

API_BASE = "https://api.elevenlabs.io"
TTS_URL_TEMPLATE = API_BASE + "/v1/text-to-speech/{voice_id}"
TTS_TIMEOUT_SECONDS = 60.0

_http: httpx.Client | None = None
# TCP connect + TLS handshake time of the last synthesize() call; 0 when the
# pooled connection was reused.
last_handshake_ms = 0


def _client() -> httpx.Client:
    global _http
    if _http is None:
        _http = persistent_client(TTS_TIMEOUT_SECONDS)
    return _http


class _HandshakeTrace:
    """httpx trace hook: times connect_tcp through start_tls for a new connection."""

    def __init__(self) -> None:
        self.started: float | None = None
        self.finished: float | None = None

    def __call__(self, event_name: str, _info: dict) -> None:
        if event_name == "connection.connect_tcp.started":
            self.started = time.perf_counter()
        elif event_name in ("connection.start_tls.complete", "connection.connect_tcp.complete"):
            self.finished = time.perf_counter()

    def ms(self) -> int:
        if self.started is None or self.finished is None:
            return 0
        return round((self.finished - self.started) * 1000)


def warm_up() -> None:
    """Open the pooled HTTPS connection before the first turn. Raises RuntimeError on failure."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("Missing ELEVENLABS_API_KEY in server/.env")
    try:
        response = _client().get(API_BASE + "/v1/models", headers={"xi-api-key": ELEVENLABS_API_KEY})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs warm-up failed: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"ElevenLabs warm-up HTTP {response.status_code}: {response.text[:200]}")
_NARRATION_RE = re.compile(r"\*\*[^*]+\*\*")
_SPOKEN_RE = re.compile(r'"([^"]+)"')
# Phonetic alias for TTS only; UI still shows "Frieren".
_FRIEREN_RE = re.compile(r"\bFrieren\b", re.IGNORECASE)


def _for_tts(text: str) -> str:
    return _FRIEREN_RE.sub("FreeRen", text)


def extract_spoken_text(reply: str) -> str:
    """Return text for TTS. Strips leftover **narration**; uses quotes if present, else full reply."""
    if not reply:
        return ""
    text = _NARRATION_RE.sub(" ", reply)
    parts = [p.strip() for p in _SPOKEN_RE.findall(text) if p.strip()]
    if parts:
        spoken = " ".join(parts)
    else:
        spoken = " ".join(text.split()).strip()
    return _for_tts(spoken)
def synthesize(
    text: str,
    stability: float | None = None,
    similarity_boost: float | None = None,
    style: float | None = None,
    speed: float | None = None,
    speaker_boost: bool | None = None,
) -> bytes:
    """Return MP3 bytes for `text`. Raises RuntimeError on config/HTTP failure."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("Missing ELEVENLABS_API_KEY in server/.env")
    if not ELEVENLABS_VOICE_ID:
        raise RuntimeError("Missing ELEVENLABS_VOICE_ID in server/.env")
    if not text or not text.strip():
        raise RuntimeError("Cannot synthesize empty text")
    url = TTS_URL_TEMPLATE.format(voice_id=ELEVENLABS_VOICE_ID)
    voice_settings = {
        "stability": stability if stability is not None else ELEVENLABS_STABILITY,
        "similarity_boost": similarity_boost if similarity_boost is not None else ELEVENLABS_SIMILARITY_BOOST,
        "style": style if style is not None else ELEVENLABS_STYLE,
        "speed": speed if speed is not None else ELEVENLABS_SPEED,
        "use_speaker_boost": speaker_boost if speaker_boost is not None else ELEVENLABS_SPEAKER_BOOST,
    }
    global last_handshake_ms
    trace = _HandshakeTrace()
    try:
        response = _client().post(
            url,
            json={
                "text": text.strip(),
                "model_id": ELEVENLABS_MODEL_ID,
                "voice_settings": voice_settings,
            },
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Accept": "audio/mpeg",
            },
            extensions={"trace": trace},
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs request failed: {exc}") from exc
    last_handshake_ms = trace.ms()
    if response.status_code >= 400:
        raise RuntimeError(f"ElevenLabs HTTP {response.status_code}: {response.text}")
    audio = response.content
    if not audio:
        raise RuntimeError("ElevenLabs returned empty audio")
    return audio