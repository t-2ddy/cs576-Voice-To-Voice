"""Local WebSocket hub that broadcasts voice_chat events to the React UI.

Listens on ws://127.0.0.1:8766 (any path, including /ws from the Vite proxy).
Clients receive JSON events:
  {"type": "chat", "who": "you"|"frieren", "text": "..."}
  {"type": "audio", "format": "mp3", "data": "<base64>"}
  {"type": "status", "value": "listening"|"thinking"|"speaking"|"ready"|"error", "detail"?: "..."}
Clients may send:
  {"type": "playback_done"}  -- the last `audio` clip finished (or failed) playing
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
import time
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

CHAT_WS_HOST = "127.0.0.1"
CHAT_WS_PORT = 8766

_clients: set[ServerConnection] = set()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_server_ready = threading.Event()
_start_error: BaseException | None = None
_lock = threading.Lock()
_playback_done = threading.Event()
_client_connected = threading.Event()
_last_status: dict[str, Any] | None = None
_last_chat: dict[str, dict[str, Any]] = {}
_warned_no_client: set[str] = set()


def _handle_client_message(raw: str | bytes) -> None:
    try:
        event = json.loads(raw)
    except (TypeError, ValueError):
        return
    if isinstance(event, dict) and event.get("type") == "playback_done":
        _playback_done.set()


def _remember_event(event: dict[str, Any]) -> None:
    """Cache the latest status / chat so late joiners can catch up (no audio)."""
    global _last_status
    event_type = event.get("type")
    if event_type == "status":
        _last_status = event
    elif event_type == "chat":
        who = event.get("who")
        if isinstance(who, str) and who:
            _last_chat[who] = event


async def _replay_state(websocket: ServerConnection) -> None:
    events: list[dict[str, Any]] = []
    if _last_status is not None:
        events.append(_last_status)
    # Send both speakers when present; frieren last so the VN textbox shows
    # her reply after a reconnect mid-session.
    for who in ("you", "frieren"):
        if who in _last_chat:
            events.append(_last_chat[who])
    for event in events:
        try:
            await websocket.send(json.dumps(event))
        except Exception:
            return


async def _handler(websocket: ServerConnection) -> None:
    _clients.add(websocket)
    _client_connected.set()
    print(f"(UI connected, {len(_clients)} client{'s' if len(_clients) != 1 else ''})", flush=True)
    await _replay_state(websocket)
    try:
        async for raw in websocket:
            _handle_client_message(raw)
    except ConnectionClosed:
        pass
    finally:
        _clients.discard(websocket)
        if not _clients:
            _client_connected.clear()
        print(
            f"(UI disconnected, {len(_clients)} client{'s' if len(_clients) != 1 else ''} left)",
            flush=True,
        )


async def _broadcast_async(event: dict[str, Any]) -> None:
    if not _clients:
        event_type = str(event.get("type") or "event")
        if event_type not in _warned_no_client:
            _warned_no_client.add(event_type)
            print(f"(no UI connected; {event_type} not delivered)", file=sys.stderr, flush=True)
        return
    _warned_no_client.clear()
    payload = json.dumps(event)
    dead: list[ServerConnection] = []
    for client in list(_clients):
        try:
            await client.send(payload)
        except Exception:
            dead.append(client)
    for client in dead:
        _clients.discard(client)
    if not _clients:
        _client_connected.clear()


def broadcast(event: dict[str, Any]) -> None:
    """Thread-safe: queue a JSON event to all connected UI clients."""
    _remember_event(event)
    loop = _loop
    if loop is None or not loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(_broadcast_async(event), loop)


def emit_chat(who: str, text: str) -> None:
    broadcast({"type": "chat", "who": who, "text": text})


def emit_audio(mp3_bytes: bytes) -> None:
    """Broadcast MP3 audio as base64 for the React client to play."""
    _playback_done.clear()
    broadcast(
        {
            "type": "audio",
            "format": "mp3",
            "data": base64.b64encode(mp3_bytes).decode("ascii"),
        }
    )


def wait_for_playback(timeout: float) -> bool:
    """Block until a client reports playback_done for the last emit_audio, or timeout.

    Returns False immediately when no UI is connected (nothing is playing).
    """
    if not _clients:
        return False
    return _playback_done.wait(timeout)


def wait_for_client(timeout: float) -> bool:
    """Block until at least one UI client is connected, or timeout."""
    return _client_connected.wait(timeout)


def emit_status(value: str, detail: str | None = None) -> None:
    event: dict[str, Any] = {"type": "status", "value": value}
    if detail:
        event["detail"] = detail
    broadcast(event)


def _process_request(connection: ServerConnection, request: Request) -> Response | None:
    """Plain-HTTP health check so the UI can probe without opening a WebSocket."""
    if request.path.split("?", 1)[0] == "/health":
        return connection.respond(HTTPStatus.OK, "ok\n")
    return None


async def _run_server() -> None:
    async with serve(
        _handler,
        CHAT_WS_HOST,
        CHAT_WS_PORT,
        process_request=_process_request,
    ):
        _server_ready.set()
        await asyncio.Future()  # run forever


def _thread_main() -> None:
    global _loop, _start_error
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    try:
        loop.run_until_complete(_run_server())
    except BaseException as exc:
        _start_error = exc
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
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if _server_ready.wait(0.05):
            return
        if not _thread.is_alive():
            break
    detail = f": {_start_error}" if _start_error else ""
    raise RuntimeError(f"chat bridge failed to bind {CHAT_WS_HOST}:{CHAT_WS_PORT}{detail}")
