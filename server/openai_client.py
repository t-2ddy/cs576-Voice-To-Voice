"""Shared OpenAI client for speech-to-text, chat, and embeddings.

One key covers every OpenAI call in the server.
Env (server/.env):
  OPENAI_API_KEY
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import DefaultHttpxClient, OpenAI

from http_pool import keepalive_limits

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
load_dotenv()  # also allow cwd override

OPENAI_TIMEOUT_SECONDS = 60.0

_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Lazy-init the OpenAI client from OPENAI_API_KEY."""
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in server/.env")
    _client = OpenAI(
        api_key=api_key,
        timeout=OPENAI_TIMEOUT_SECONDS,
        http_client=DefaultHttpxClient(limits=keepalive_limits()),
    )
    return _client
