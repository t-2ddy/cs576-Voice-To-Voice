"""Supabase-backed chat memory for soul_shiori.

Four memory tiers (schema already live in Supabase):
  1. key_facts       — durable key/value facts (not used by prune)
  2. rolling_summary — compressed narrative of older conversation
  3. chat_memory     — embedded overflow turns (vector(768), HNSW)
  4. recent_turns    — short sliding window of latest turns

Retrieval RPC: match_memory(query_embedding, match_count).

Required .env keys:
  SUPABASE_URL              (project root, e.g. https://xxxx.supabase.co — no /rest/v1)
  SUPABASE_SERVICE_ROLE_KEY

Embeddings: local Ollama nomic-embed-text (768-d, must match vector(768)).
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client

from local_model import OLLAMA_CHAT_URL, OLLAMA_HOST, OLLAMA_MODEL

load_dotenv()

EMBED_MODEL = "nomic-embed-text"
OLLAMA_EMBED_URL = f"{OLLAMA_HOST}/api/embeddings"

_supabase: Client | None = None


def _normalize_supabase_url(url: str) -> str:
    """Strip accidental /rest/v1 suffix; create_client wants the project root."""
    cleaned = url.rstrip("/")
    if cleaned.endswith("/rest/v1"):
        cleaned = cleaned[: -len("/rest/v1")]
    return cleaned


def get_supabase() -> Client:
    """Lazy-init the Supabase client from SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY."""
    global _supabase
    if _supabase is not None:
        return _supabase

    url = _normalize_supabase_url(os.getenv("SUPABASE_URL", "").strip())
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env. "
            "Add both before using chat memory."
        )
    _supabase = create_client(url, key)
    return _supabase


def embed(text: str) -> list[float]:
    """Return a 768-d embedding from local Ollama nomic-embed-text."""
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    embedding = body.get("embedding")
    if not embedding:
        raise RuntimeError(f"Ollama embeddings response missing 'embedding': {body!r}")
    return embedding


def store_turn(speaker: str, content: str) -> None:
    """Append one turn to the recent_turns sliding window."""
    get_supabase().table("recent_turns").insert(
        {"speaker": speaker, "content": content}
    ).execute()


def get_recent_turns(limit: int = 10) -> list[dict]:
    """Return the latest turns in chronological order (oldest first)."""
    result = (
        get_supabase()
        .table("recent_turns")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(result.data or []))


def get_key_facts() -> dict[str, str]:
    """Return durable key_facts as {fact_key: fact_value}."""
    result = get_supabase().table("key_facts").select("*").execute()
    return {row["fact_key"]: row["fact_value"] for row in (result.data or [])}


def get_rolling_summary() -> str:
    """Return the latest rolling_summary text, or empty string if none."""
    result = (
        get_supabase()
        .table("rolling_summary")
        .select("*")
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return ""
    return result.data[0]["summary"] or ""


def retrieve_relevant(query: str, k: int = 5) -> list[dict]:
    """Semantic search over chat_memory via the match_memory RPC."""
    query_embedding = embed(query)
    result = (
        get_supabase()
        .rpc(
            "match_memory",
            {"query_embedding": query_embedding, "match_count": k},
        )
        .execute()
    )
    return result.data or []


def build_context(user_input: str) -> str:
    """Assemble all four memory tiers into one string for the system prompt."""
    facts = get_key_facts()
    summary = get_rolling_summary()
    relevant = retrieve_relevant(user_input)
    recent = get_recent_turns()

    parts: list[str] = []
    if facts:
        parts.append("Known facts: " + ", ".join(f"{k}: {v}" for k, v in facts.items()))
    if summary:
        parts.append("Summary of earlier conversation: " + summary)
    if relevant:
        parts.append(
            "Relevant past context: " + " | ".join(r["content"] for r in relevant)
        )
    if recent:
        parts.append(
            "Recent turns:\n"
            + "\n".join(f"{t['speaker']}: {t['content']}" for t in recent)
        )

    return "\n\n".join(parts)


def _format_overflow_for_prompt(overflow: list[dict]) -> str:
    lines = []
    for turn in overflow:
        speaker = turn.get("speaker", "unknown")
        content = turn.get("content", "")
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def update_rolling_summary(overflow: list[dict]) -> None:
    """Fold overflow turns into the latest rolling_summary row (insert if empty)."""
    if not overflow:
        return

    sb = get_supabase()
    existing = (
        sb.table("rolling_summary")
        .select("id, summary, turn_count")
        .order("id", desc=True)
        .limit(1)
        .execute()
        .data
    )
    current_summary = existing[0]["summary"] if existing else ""
    current_turn_count = int(existing[0]["turn_count"] or 0) if existing else 0

    turns_block = _format_overflow_for_prompt(overflow)
    messages = [
        {
            "role": "system",
            "content": (
                "You maintain a concise rolling summary of a conversation. "
                "Merge the new turns into the existing summary. Keep it short "
                "(a few sentences), preserve important facts and emotional tone, "
                "and do not invent details. Reply with only the updated summary text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Existing summary:\n{current_summary or '(empty)'}\n\n"
                f"New turns to fold in:\n{turns_block}"
            ),
        },
    ]
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    new_summary = body["message"]["content"].strip()
    new_turn_count = current_turn_count + len(overflow)
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        sb.table("rolling_summary").update(
            {
                "summary": new_summary,
                "turn_count": new_turn_count,
                "updated_at": now,
            }
        ).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("rolling_summary").insert(
            {
                "summary": new_summary,
                "turn_count": new_turn_count,
            }
        ).execute()


def prune_recent_turns(keep_last: int = 10) -> None:
    """Archive overflow recent_turns into chat_memory + rolling_summary, then delete them."""
    sb = get_supabase()
    turns = (
        sb.table("recent_turns")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    if not turns or len(turns) <= keep_last:
        return

    overflow = turns[keep_last:]
    overflow_ids = [t["id"] for t in overflow]

    for turn in overflow:
        embedding = embed(turn["content"])
        sb.table("chat_memory").insert(
            {
                "content": turn["content"],
                "embedding": embedding,
                "speaker": turn["speaker"],
            }
        ).execute()

    update_rolling_summary(overflow)

    sb.table("recent_turns").delete().in_("id", overflow_ids).execute()
