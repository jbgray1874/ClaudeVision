"""Claude as the reader when xAI is busy or has no key (JG, 10 Nov 2026).

"Let's set up a Claude key as the fallback. can we add in claude or xai api key without making
lots of code changes? can it slot in?"

It slots in at one place: llm_full_extract._call_llm, the text call every drawing read and every
targeted question goes through. When xAI stays busy after its retries (xai_models.call_with_retry:
a capacity 429, a rate limit, a timeout or a server error), or when no XAI_API_KEY is set, the same
question, system prompt and all, is asked of Claude instead, and the console and the read say so.

    ANTHROPIC_API_KEY=...            in .env turns it on (never printed or written anywhere)
    SDI_CLAUDE_MODEL=claude-opus-5-5 the model (this is the default)
    SDI_CLAUDE_EFFORT=medium         low | medium | high | xhigh | max (medium is the default)
    SDI_LLM_FALLBACK=off             turns the fallback off with the key still set

A refusal is not an answer: a request Claude declines on safety grounds is re-run on the model the
API chooses for it (server-side fallback); if that declines too it is raised like any failure, and
the run's other readers' findings stand.
"""
from __future__ import annotations

import os
from typing import Optional

MODEL_DEFAULT = "claude-opus-5-5"
EFFORT_DEFAULT = "medium"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def model() -> str:
    return (os.getenv("SDI_CLAUDE_MODEL") or "").strip() or MODEL_DEFAULT


def effort() -> str:
    v = (os.getenv("SDI_CLAUDE_EFFORT") or "").strip().lower()
    return v if v in {"low", "medium", "high", "xhigh", "max"} else EFFORT_DEFAULT


def available() -> bool:
    """A key is set, the fallback is not switched off, and the SDK is installed."""
    if (os.getenv("SDI_LLM_FALLBACK") or "").strip().lower() in {"0", "off", "no", "false"}:
        return False
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        return False
    try:
        import anthropic  # noqa: F401,PLC0415
    except ImportError:
        return False
    return True


def ask(system: str, user_content: str, max_tokens: int = 64000,
        client: Optional[object] = None) -> str:
    """Claude's text answer to the one question. Streamed, so a long transcription is not cut
    off by an HTTP timeout; the SDK retries rate limits and server errors itself."""
    import anthropic  # noqa: PLC0415
    client = client or anthropic.Anthropic()
    with client.beta.messages.stream(
        model=model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"effort": effort()},
        betas=[_FALLBACK_BETA],
        fallbacks="default",
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the request ({getattr(message, 'stop_details', None)})")
    return "".join(block.text for block in message.content if block.type == "text")
