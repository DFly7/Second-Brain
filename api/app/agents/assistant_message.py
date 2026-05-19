"""OpenAI-style assistant payloads for LiteLLM multi-turn tool loops."""

from __future__ import annotations

import json
from typing import Any


def assistant_message_for_litellm(msg: Any) -> dict:
    """
    Build the assistant dict to append after each completion.

    LiteLLM's Gemini adapter fails when re-sending tool_calls whose
    ``function.arguments`` is the string ``'{}'`` (no keys): it cannot build a
    Gemini ``function_call`` (see BerriAI/litellm#6833). Use a minimal non-empty
    JSON object so the next ``acompletion`` call succeeds. Dispatch ignores extra
    keys for tools like ``list_pages``.

    Thought-signature propagation for Gemini thinking models is handled
    internally by LiteLLM >=1.83 (it encodes the signature into the tool call
    ID on the way out and re-attaches it on the way in).
    """
    out: dict[str, Any] = {"role": "assistant"}
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip() or None
    if content:
        out["content"] = content
    tool_calls = getattr(msg, "tool_calls", None) or []
    if not tool_calls:
        return out

    serialized: list[dict[str, Any]] = []
    for tc in tool_calls:
        fn = tc.function
        raw = fn.arguments if isinstance(fn.arguments, str) else json.dumps(fn.arguments)
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = None
        if not parsed:
            raw = '{"_":""}'
        serialized.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": fn.name, "arguments": raw},
            }
        )
    out["tool_calls"] = serialized
    return out
