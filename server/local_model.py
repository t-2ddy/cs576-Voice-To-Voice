"""Hosted OpenAI chat model, persona loading, and chat requests.

Env (server/.env):
  OPENAI_API_KEY
  LLM_MODEL  (OpenAI chat model id, e.g. gpt-5.6-luna)
  LLM_REASONING_EFFORT  (optional, default "none"; empty omits the parameter)
"""

import os
import random

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


def complete_chat(messages: list[dict], max_tokens: int | None = None) -> str:
    """Send `messages` to LLM_MODEL and return the reply text."""
    if not LLM_MODEL:
        raise RuntimeError("Missing LLM_MODEL in server/.env")
    kwargs = {"model": LLM_MODEL, "messages": messages}
    if LLM_REASONING_EFFORT:
        kwargs["reasoning_effort"] = LLM_REASONING_EFFORT
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    response = get_openai_client().chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


def ask_openai(history: list[dict]) -> str:
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
    return complete_chat(messages, max_tokens=preset["max_tokens"])


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
