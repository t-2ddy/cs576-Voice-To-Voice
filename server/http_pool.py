"""Shared httpx settings so hosted-API connections survive the gap between turns.

httpx drops idle pooled connections after 5 s by default, but turns are
15-20 s apart, so every turn paid a fresh TCP + TLS handshake per service.

Env (server/.env):
  HTTP_KEEPALIVE_SECONDS  (optional, default 300)
"""

from __future__ import annotations

import os

import httpx

DEFAULT_KEEPALIVE_SECONDS = 300.0


def keepalive_seconds() -> float:
    raw = os.getenv("HTTP_KEEPALIVE_SECONDS", "").strip()
    try:
        return float(raw) if raw else DEFAULT_KEEPALIVE_SECONDS
    except ValueError:
        return DEFAULT_KEEPALIVE_SECONDS


def keepalive_limits() -> httpx.Limits:
    return httpx.Limits(
        max_connections=20,
        max_keepalive_connections=10,
        keepalive_expiry=keepalive_seconds(),
    )


def persistent_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, limits=keepalive_limits())
