"""OpenAI (ChatGPT) as a reader when xAI is busy or has no key (JG, 10 Nov 2026).

"I've added in the open ai. i have credit on that and xai only ... we should switch to read this
as a fall back."

It slots in beside the Claude fallback, at the one text call every drawing read and targeted
question goes through (llm_full_extract._call_llm): when xAI stays busy after its retries, or no
XAI_API_KEY is set, the same question is asked of the first fallback that has a key, in
SDI_LLM_FALLBACK_ORDER (default claude,openai), and the read says who answered.

    OPENAI_API_KEY=...          in .env turns it on (never printed or written anywhere)
    SDI_OPENAI_MODEL=gpt-5      the model (this is the default; set it to any chat model the
                                account has)
    SDI_LLM_FALLBACK=off        turns every fallback off with the keys still set
"""
from __future__ import annotations

import os
from typing import Optional

MODEL_DEFAULT = "gpt-5"


def model() -> str:
    return (os.getenv("SDI_OPENAI_MODEL") or "").strip() or MODEL_DEFAULT


def available() -> bool:
    if (os.getenv("SDI_LLM_FALLBACK") or "").strip().lower() in {"0", "off", "no", "false"}:
        return False
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return False
    try:
        import openai  # noqa: F401,PLC0415
    except ImportError:
        return False
    return True


def ask(system: str, user_content: str, client: Optional[object] = None) -> str:
    """The model's text answer to the one question. No temperature or token cap is sent: the
    reasoning models refuse a temperature other than their own, and a cap cuts a long read short."""
    if client is None:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=600)
    resp = client.chat.completions.create(
        model=model(),
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_content}],
    )
    choice = resp.choices[0]
    if getattr(choice, "finish_reason", "") == "content_filter":
        raise RuntimeError("OpenAI declined the request (content filter)")
    return choice.message.content or ""
