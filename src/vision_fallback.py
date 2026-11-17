"""The image reads fall back to OpenAI whenever xAI does not answer (17 Nov 2026).

JG: "yes, 100 percent fall back". The drawing read already asked the OpenAI or Claude fallback
when xAI gave no answer (llm_full_extract._call_llm). The two IMAGE reads, the parts-list page
read (_bom_vision_reader) and the concept read (concept_scan), had no fallback: a hung xAI request
cost the job its whole xAI limit and the read was left NOT done.

Now any failure of an image read on xAI (no answer, busy, an error, the job's xAI limit spent, or
no XAI_API_KEY) asks OpenAI the same question with the same page images, at once, and says so:

    [llm-fallback] xAI gave no answer on a parts-list image read: asking openai (gpt-5) ...
    [llm-fallback] openai answered (1234 characters)

Turned on by OPENAI_API_KEY; off with SDI_LLM_FALLBACK=off, as for the drawing read. If OpenAI
fails too, the xAI error is raised as before and the read is marked NOT done on the book.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

# Who answered the last image read: "" (xAI) or "openai:<model>".
LAST_ANSWERED_BY = ""


def _openai() -> Any:
    try:
        import openai_fallback                                       # noqa: PLC0415
    except Exception:                                                # noqa: BLE001
        return None
    try:
        return openai_fallback if openai_fallback.available() else None
    except Exception:                                                # noqa: BLE001
        return None


def ready() -> bool:
    return _openai() is not None


def ask(prompt: str, png_pages: List[bytes], what: str, why: str,
        say: Optional[Callable[[str], None]] = None) -> str:
    """Ask OpenAI the image question. Raises when no fallback is ready or it fails."""
    global LAST_ANSWERED_BY
    say = (lambda m: print(m, flush=True)) if say is None else say
    mod = _openai()
    if mod is None:
        raise RuntimeError("no image fallback reader is ready (OPENAI_API_KEY not set)")
    say(f"   [llm-fallback] {why} on {what}: asking openai ({mod.model()}) the same question "
        f"with the same {len(png_pages)} page image(s) instead")
    try:
        text = mod.ask_image(prompt, list(png_pages))
    except Exception as exc:                                         # noqa: BLE001
        say(f"   [llm-fallback] openai did not answer {what} ({type(exc).__name__}: "
            f"{str(exc)[:160]}). This read is NOT done and is said so on the book.")
        raise
    LAST_ANSWERED_BY = f"openai:{mod.model()}"
    say(f"   [llm-fallback] openai answered {what} ({len(text or '')} characters)")
    return text


def why_of(exc: BaseException) -> str:
    """A plain reason for the log line."""
    try:
        import xai_models                                            # noqa: PLC0415
        kind = xai_models.busy_kind(exc)
    except Exception:                                                # noqa: BLE001
        kind = ""
    if type(exc).__name__ == "XaiJobBudgetSpent":
        return "this job's xAI time limit is spent"
    if isinstance(exc, TimeoutError) or kind == "timeout":
        return "xAI gave no answer"
    if kind:
        return f"xAI stayed busy ({kind})"
    return f"xAI failed ({type(exc).__name__})"
