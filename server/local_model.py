"""Hosted OpenAI chat model, persona loading, and chat requests.

Env (server/.env):
  OPENAI_API_KEY
  LLM_MODEL  (OpenAI chat model id, e.g. gpt-5.6-luna)
  LLM_REASONING_EFFORT  (optional, default "none"; empty omits the parameter)
"""

import os
import random
from collections.abc import Iterator

from openai import OpenAIError

from openai_client import get_openai_client

LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
# Reasoning tokens count against max_completion_tokens, so the small length
# presets below would yield empty replies with reasoning on.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "none").strip()

# Most turns stay short/chatty; rare longer replies for variety.
LENGTH_PRESETS = [
    {"max_tokens": 80, "hint": "Reply in one short sentence, like a quick text back."},
    {"max_tokens": 120, "hint": "Reply in 1-2 short sentences -- natural conversational length."},
    {"max_tokens": 180, "hint": "You may go a little longer this turn, up to 3-4 sentences, still conversational."},
]
LENGTH_WEIGHTS = [0.66, 0.30, 0.04]

SOUL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soul")


def load_system_prompt() -> str:
    """Read the character's persona/system prompt from the `soul` file, if present."""
    try:
        with open(SOUL_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _chat_kwargs(messages: list[dict], max_tokens: int | None) -> dict:
    if not LLM_MODEL:
        raise RuntimeError("Missing LLM_MODEL in server/.env")
    kwargs = {"model": LLM_MODEL, "messages": messages}
    if LLM_REASONING_EFFORT:
        kwargs["reasoning_effort"] = LLM_REASONING_EFFORT
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    return kwargs


def complete_chat(messages: list[dict], max_tokens: int | None = None) -> str:
    """Send `messages` to LLM_MODEL and return the reply text."""
    response = get_openai_client().chat.completions.create(**_chat_kwargs(messages, max_tokens))
    return (response.choices[0].message.content or "").strip()


def _with_length_hint(history: list[dict]) -> tuple[list[dict], int]:
    preset = random.choices(LENGTH_PRESETS, weights=LENGTH_WEIGHTS)[0]
    # The per-turn length hint is folded into the leading system message for
    # this call only -- it is never persisted into `history`.
    messages = list(history)
    if messages and messages[0]["role"] == "system":
        messages[0] = {
            "role": "system",
            "content": messages[0]["content"] + "\n\n" + preset["hint"],
        }
    else:
        messages = [{"role": "system", "content": preset["hint"]}] + messages
    return messages, preset["max_tokens"]


def ask_openai(history: list[dict]) -> str:
    messages, max_tokens = _with_length_hint(history)
    return complete_chat(messages, max_tokens=max_tokens)


def ask_stream(history: list[dict]) -> Iterator[str]:
    """Like ask_openai, but yields reply text deltas as the model produces them (SSE)."""
    messages, max_tokens = _with_length_hint(history)
    stream = get_openai_client().chat.completions.create(
        **_chat_kwargs(messages, max_tokens), stream=True
    )
    try:
        for event in stream:
            if event.choices and event.choices[0].delta.content:
                yield event.choices[0].delta.content
    finally:
        stream.close()


class LocalModel:
    """Wraps OpenAI config checks, persona seeding, and chat requests."""

    def __init__(self) -> None:
        self.system_prompt = load_system_prompt()

    def start(self) -> None:
        """Raises RuntimeError if the key or LLM_MODEL is missing or rejected."""
        if not LLM_MODEL:
            raise RuntimeError("Missing LLM_MODEL in server/.env")
        try:
            get_openai_client().models.retrieve(LLM_MODEL)
        except OpenAIError as exc:
            raise RuntimeError(f"OpenAI rejected the key or model '{LLM_MODEL}': {exc}") from exc
        print(f"OpenAI chat model ready: {LLM_MODEL} (reasoning: {LLM_REASONING_EFFORT or 'default'})")

    def ask(self, history: list[dict]) -> str:
        return ask_openai(history)
