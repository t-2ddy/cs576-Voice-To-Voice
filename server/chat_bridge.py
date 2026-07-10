"""Local WebSocket hub that broadcasts voice_chat events to the React UI.

Listens on ws://127.0.0.1:8766 (any path, including /ws from the Vite proxy).
Clients receive JSON events:
  {"type": "chat", "who": "you"|"shiori", "text": "..."}
  {"type": "audio", "format": "mp3", "data": "<base64>"}
  {"type": "status", "value": "listening"|"thinking"|"speaking"|"ready"|"error", "detail"?: "..."}
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

CHAT_WS_HOST = "127.0.0.1"
CHAT_WS_PORT = 8766

_clients: set[ServerConnection] = set()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


async def _handler(websocket: ServerConnection) -> None:
    _clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        _clients.discard(websocket)


async def _broadcast_async(event: dict[str, Any]) -> None:
    if not _clients:
        return
    payload = json.dumps(event)
    dead: list[ServerConnection] = []
    for client in list(_clients):
        try:
            await client.send(payload)
        except Exception:
            dead.append(client)
    for client in dead:
        _clients.discard(client)


def broadcast(event: dict[str, Any]) -> None:
    """Thread-safe: queue a JSON event to all connected UI clients."""
    loop = _loop
    if loop is None or not loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(_broadcast_async(event), loop)


def emit_chat(who: str, text: str) -> None:
    broadcast({"type": "chat", "who": who, "text": text})


def emit_audio(mp3_bytes: bytes) -> None:
    """Broadcast MP3 audio as base64 for the React client to play."""
    broadcast(
        {
            "type": "audio",
            "format": "mp3",
            "data": base64.b64encode(mp3_bytes).decode("ascii"),
        }
    )


def emit_status(value: str, detail: str | None = None) -> None:
    event: dict[str, Any] = {"type": "status", "value": value}
    if detail:
        event["detail"] = detail
    broadcast(event)


async def _run_server() -> None:
    async with serve(_handler, CHAT_WS_HOST, CHAT_WS_PORT):
        await asyncio.Future()  # run forever


def _thread_main() -> None:
    global _loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    try:
        loop.run_until_complete(_run_server())
    finally:
        _loop = None
        loop.close()


def start_chat_bridge() -> None:
    """Start the WebSocket hub once in a daemon background thread."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_thread_main,
            name="chat-bridge-ws",
            daemon=True,
        )
        _thread.start()
    for _ in range(50):
        if _loop is not None and _loop.is_running():
            break
        time.sleep(0.02)
