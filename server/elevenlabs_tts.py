"""ElevenLabs REST text-to-speech for Shiori replies.
Env (server/.env):
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request
from dotenv import load_dotenv
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

ELEVENLABS_STABILITY = _env_float("ELEVENLABS_STABILITY", 0.3)
ELEVENLABS_SIMILARITY_BOOST = _env_float("ELEVENLABS_SIMILARITY_BOOST", 0.4)
ELEVENLABS_STYLE = _env_float("ELEVENLABS_STYLE", 0.2)
ELEVENLABS_SPEED = _env_float("ELEVENLABS_SPEED", 1.0)
ELEVENLABS_SPEAKER_BOOST = _env_bool("ELEVENLABS_SPEAKER_BOOST", True)

TTS_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_NARRATION_RE = re.compile(r"\*\*[^*]+\*\*")
_SPOKEN_RE = re.compile(r'"([^"]+)"')


def extract_spoken_text(reply: str) -> str:
    """Return text for TTS. Strips leftover **narration**; uses quotes if present, else full reply."""
    if not reply:
        return ""
    text = _NARRATION_RE.sub(" ", reply)
    parts = [p.strip() for p in _SPOKEN_RE.findall(text) if p.strip()]
    if parts:
        return " ".join(parts)
    return " ".join(text.split()).strip()
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
    payload = json.dumps(
        {
            "text": text.strip(),
            "model_id": ELEVENLABS_MODEL_ID,
            "voice_settings": voice_settings,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ElevenLabs request failed: {exc}") from exc
    if not audio:
        raise RuntimeError("ElevenLabs returned empty audio")
    return audio