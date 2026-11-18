"""Supabase-backed chat memory for the voice companion.

Four memory tiers (schema already live in Supabase):
  1. key_facts       — durable key/value facts (not used by prune)
  2. rolling_summary — compressed narrative of older conversation
  3. chat_memory     — embedded overflow turns (vector(768), HNSW)
  4. recent_turns    — short sliding window of latest turns

Retrieval RPC: match_memory(query_embedding, match_count).

Selective context:
  should_retrieve_memory / build_context_if_needed — heuristic gate so
  semantic search (tier 3) only runs when the turn likely needs recall.
  Light context = tiers 1, 2, 4 (facts/summary cached per session).

Required .env keys:
  SUPABASE_URL              (project root, e.g. https://xxxx.supabase.co — no /rest/v1)
  SUPABASE_SERVICE_ROLE_KEY

Embeddings: OpenAI text-embedding-3-small at 768 dimensions (must match vector(768)).
Rows embedded by the old nomic model are not comparable and must be cleared.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from http_pool import persistent_client
from local_model import complete_chat
from openai_client import get_openai_client

load_dotenv()

SUPABASE_TIMEOUT_SECONDS = 120.0

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 768

_supabase: Client | None = None

# Session cache for light tiers (facts + summary). Invalidated on prune.
_cached_key_facts: dict[str, str] | None = None
_cached_rolling_summary: str | None = None
_light_cache_valid = False

_SKIP_FILLERS = frozenset(
    {
        "hey",
        "hi",
        "hello",
        "yo",
        "sup",
        "lol",
        "lmao",
        "haha",
        "hehe",
        "ok",
        "okay",
        "k",
        "kk",
        "yeah",
        "yep",
        "yup",
        "nah",
        "nope",
        "hmm",
        "hm",
        "uh",
        "um",
        "ah",
        "oh",
        "wow",
        "nice",
        "cool",
        "thanks",
        "thank you",
        "ty",
        "bye",
        "goodbye",
        "gn",
        "goodnight",
        "good night",
    }
)

# Phrases that suggest the user needs long-term / semantic recall.
_MEMORY_NEED_PATTERNS = (
    re.compile(
        r"\b("
        r"remember|you said|last time|earlier|previously|we talked|"
        r"do you know my|what'?s my|what is my|my name|favorite|prefer|"
        r"what did we|have we|did i tell you|before that|a while ago|"
        r"you told me|i told you|remind me|do you recall"
        r")\b",
        re.IGNORECASE,
    ),
)


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
    _supabase = create_client(
        url,
        key,
        options=SyncClientOptions(httpx_client=persistent_client(SUPABASE_TIMEOUT_SECONDS)),
    )
    return _supabase


def embed(text: str) -> list[float]:
    """Return a 768-d embedding from OpenAI text-embedding-3-small."""
    response = get_openai_client().embeddings.create(
        model=EMBED_MODEL,
        input=text,
        dimensions=EMBED_DIMENSIONS,
    )
    return response.data[0].embedding


def store_turn(speaker: str, content: str) -> None:
    """Append one turn to the recent_turns sliding window."""
    get_supabase().table("recent_turns").insert(
        {"speaker": speaker, "content": content}
    ).execute()


# Must cover every row recent_turns can hold between prunes (keep_last=10 plus
# 2 rows x PRUNE_EVERY_N_ASSISTANT_TURNS=10 in voice_chat.py), or turns drop out
# of context before they are archived into chat_memory.
RECENT_TURNS_LIMIT = 30


def get_recent_turns(limit: int = RECENT_TURNS_LIMIT) -> list[dict]:
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


def invalidate_light_cache() -> None:
    """Drop cached key_facts / rolling_summary (call after prune or fact updates)."""
    global _cached_key_facts, _cached_rolling_summary, _light_cache_valid
    _cached_key_facts = None
    _cached_rolling_summary = None
    _light_cache_valid = False


def _get_cached_key_facts() -> dict[str, str]:
    global _cached_key_facts, _cached_rolling_summary, _light_cache_valid
    if not _light_cache_valid:
        _cached_key_facts = get_key_facts()
        _cached_rolling_summary = get_rolling_summary()
        _light_cache_valid = True
    return _cached_key_facts or {}


def _get_cached_rolling_summary() -> str:
    global _cached_key_facts, _cached_rolling_summary, _light_cache_valid
    if not _light_cache_valid:
        _cached_key_facts = get_key_facts()
        _cached_rolling_summary = get_rolling_summary()
        _light_cache_valid = True
    return _cached_rolling_summary or ""


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


def should_retrieve_memory(user_text: str) -> bool:
    """Cheap heuristic: True only when the turn likely needs semantic recall.

    Defaults to False when unsure so chatty turns stay fast; recent turns and
    light context still cover short-term continuity.
    """
    text = user_text.strip().lower()
    if len(text) < 3:
        return False
    # Strip trailing punctuation for filler matching ("ok.", "lol!")
    normalized = re.sub(r"[^\w\s']+", "", text).strip()
    if normalized in _SKIP_FILLERS:
        return False
    for pattern in _MEMORY_NEED_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _format_light_parts(facts: dict[str, str], summary: str, recent: list[dict]) -> list[str]:
    parts: list[str] = []
    if facts:
        parts.append("Known facts: " + ", ".join(f"{k}: {v}" for k, v in facts.items()))
    if summary:
        parts.append("Summary of earlier conversation: " + summary)
    if recent:
        parts.append(
            "Recent turns:\n"
            + "\n".join(f"{t['speaker']}: {t['content']}" for t in recent)
        )
    return parts


def build_light_context() -> str:
    """Facts + summary (cached) + recent turns. No embedding / semantic search."""
    facts = _get_cached_key_facts()
    summary = _get_cached_rolling_summary()
    recent = get_recent_turns()
    return "\n\n".join(_format_light_parts(facts, summary, recent))


def build_full_context(user_input: str) -> str:
    """Light tiers plus semantic retrieve_relevant for the user utterance."""
    facts = _get_cached_key_facts()
    summary = _get_cached_rolling_summary()
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


def build_context_if_needed(user_input: str) -> tuple[str, str]:
    """Return (context_string, mode) where mode is 'light' or 'full'."""
    if should_retrieve_memory(user_input):
        return build_full_context(user_input), "full"
    return build_light_context(), "light"


def build_context(user_input: str) -> str:
    """Selective entry point: light or full context based on should_retrieve_memory."""
    context, _mode = build_context_if_needed(user_input)
    return context


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
    new_summary = complete_chat(messages)
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

    # Fetched newest-first; summarize oldest-first so the summary reads chronologically.
    overflow = list(reversed(turns[keep_last:]))
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
    invalidate_light_cache()
