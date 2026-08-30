r"""
llm_scan_price.py — what one drawing costs, read straight off the PDF by the model.

WHY A SECOND METHOD EXISTS AT ALL, AND WHY IT IS NOT A BETTER FIRST ONE.

11650-00 took about forty minutes on the runner. SOLIDWORKS and Excel are driven on one
desktop, so estimates run one after another, and a hundred-drawing M&S enquiry at that rate
is sixty hours. The full engine cannot be the method for an enquiry of that size — not
because it is wrong but because the answer arrives next week.

So this reads the drawing and returns a price. Seconds, not forty minutes. It is a
DIFFERENT KIND OF NUMBER and the whole module is arranged so nobody can lose track of which
kind they are holding:

  * it is not firm — nobody has agreed to it
  * it is not reproducible — ask twice and the answers may differ, which is why the answer
    is cached against the drawing rather than re-asked
  * it carries no BOM, so there is nothing to check it against line by line

The one thing it IS, that the engine is not, is INDEPENDENT. It shares none of the engine's
rate tables, nesting rules or catalogue lookups, so where the two disagree the disagreement
carries information. That is the reason to run both rather than to pick one.

STAMPED SO IT CANNOT BE MISTAKEN FOR A QUOTE. The source name carries "llm" and "grok",
both of which price_provenance._NON_REPRODUCIBLE_TOKENS already catches, so
check_prices_are_firm reports any job carrying one of these as not firm without needing a
new rule. That was deliberate: a new pricing route that needs the checks updated to notice
it is a route that will one day be added without them.

WHAT IT REFUSES TO DO. It does not return a price it did not get. A model that answers in
prose, or with a number it will not stand behind, produces found=False and a reason —
never 0.00, which reads downstream as "free" rather than "unknown". It does not raise,
because one unreadable drawing must not take a hundred others down with it. And it records
what it ASSUMED, because a price with no stated assumptions cannot be argued with, and an
estimator who cannot argue with a number can only accept or discard it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# The name every price from this module carries. "llm" and "grok" are both in
# price_provenance._NON_REPRODUCIBLE_TOKENS, so this is recognised as un-reproducible by
# every check that already exists, on the day it is written rather than the day somebody
# remembers to add it to a list.
SOURCE_NAME = "llm_scan_estimate_grok"

# Bumped whenever the prompt changes. A cached answer produced by a different question is
# not an answer to this one, and a cache that cannot tell the difference silently serves
# yesterday's prompt for ever.
PROMPT_VERSION = "2026-08-13.1"

SYSTEM = (
    "You are a sheet metal and shopfitting estimator at a UK fabricator. You are shown the "
    "text of one engineering drawing. Give your best estimate of the MANUFACTURING COST per "
    "unit in GBP at the stated order quantity: material, cutting, forming, finishing and "
    "assembly labour. Exclude margin, delivery and tooling.\n"
    "You will often be working from incomplete information. Say what you assumed. If the "
    "drawing does not tell you enough to give a figure you would defend, say so instead of "
    "producing one — a wrong number that looks confident is worse to us than no number.\n"
    "Reply with JSON only, no prose around it:\n"
    '{"price_gbp": <number or null>, "confidence": <0.0-1.0>, '
    '"basis": "<one sentence on how you got there>", '
    '"assumptions": ["<what you had to assume>", ...], '
    '"why_not": "<only if price_gbp is null>"}'
)


def _cache_path(key: str) -> Optional[Path]:
    try:
        import config
        base = Path(getattr(config, "BASE_DIR", None) or Path(__file__).resolve().parents[1])
    except Exception:                                        # noqa: BLE001
        return None
    return base / "cache" / "llm_scan_prices" / f"{key}.json"


def _key(pdf_path: Path, units: int, model: str) -> str:
    """Identity of the QUESTION, not of the file path.

    Hashed over the drawing's CONTENT, the quantity, the model and the prompt version, so
    the same drawing under a different name is one lookup, and a changed prompt or a changed
    quantity is a different one. A cache keyed on the path alone would serve the answer for
    45 off when asked about 500.
    """
    h = hashlib.sha256()
    try:
        h.update(pdf_path.read_bytes())
    except OSError:
        h.update(str(pdf_path).encode("utf-8", "replace"))
    h.update(f"|{int(units)}|{model}|{PROMPT_VERSION}".encode())
    return h.hexdigest()[:32]


def _number(value: Any) -> Optional[float]:
    """A price, or nothing. NEVER 0.0 for something unparseable — downstream, zero is a
    claim that the part is free to make, and this module's whole job is to not make claims
    it cannot support."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if not m:
            return None
        out = float(m.group(0))
    return out if out > 0 else None


def _parse(raw: Any) -> Dict[str, Any]:
    """The model's reply, read strictly.

    Models fence JSON in ```json blocks and occasionally add a sentence in front of it.
    Tolerating that is not the same as tolerating an answer with no number in it — the
    first is a formatting habit, the second is the model declining, and only one of them
    should produce a price.
    """
    text = str(raw or "").strip()
    if not text:
        return {"found": False, "why": "the model returned nothing"}
    block = re.search(r"\{.*\}", text, re.S)
    if not block:
        return {"found": False, "why": f"no JSON in the reply: {text[:120]}"}
    try:
        data = json.loads(block.group(0))
    except json.JSONDecodeError as exc:
        return {"found": False, "why": f"the reply was not valid JSON ({exc})"}
    if not isinstance(data, dict):
        return {"found": False, "why": "the reply was not an object"}

    price = _number(data.get("price_gbp"))
    if price is None:
        return {"found": False,
                "why": str(data.get("why_not") or "the model gave no figure it would stand "
                                                  "behind").strip()}
    conf = _number(data.get("confidence"))
    assumptions = data.get("assumptions")
    if isinstance(assumptions, str):
        assumptions = [assumptions]
    return {
        "found": True,
        "price_gbp": round(price, 2),
        "confidence": min(1.0, conf) if conf is not None else None,
        "basis": str(data.get("basis") or "").strip(),
        "assumptions": [str(a).strip() for a in (assumptions or []) if str(a).strip()],
    }


def _stamp(result: Dict[str, Any], model: str, units: int) -> Dict[str, Any]:
    """Everything needed to say where this number came from, beside the number.

    A figure whose model and prompt cannot be named is a figure nobody can reproduce OR
    audit, which is a different and worse thing from one that is merely not reproducible.
    """
    result.update({
        "source": SOURCE_NAME,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "units": int(units),
        "firm": False,
        "reproducible": False,
        "price_source": {
            "source": SOURCE_NAME,
            "source_type": "ai_estimate",
            "applied": bool(result.get("found")),
            "applied_basis": "llm_whole_drawing_scan",
            "note": ("An LLM read of the drawing. NOT a supplier quote, NOT derived from our "
                     "rate tables, and not reproducible — asking again may give a different "
                     "figure. It is here to be compared with the engine's estimate, not to "
                     "be sent to a customer."),
        },
    })
    return result


def scan_price(pdf_path: Any, units: int, model: Optional[str] = None,
               use_cache: bool = True) -> Dict[str, Any]:
    """One drawing, one price. Never raises.

    A hundred-drawing enquiry runs this a hundred times. An exception on drawing seven
    must not cost the other ninety-three, so every failure returns a result that SAYS what
    went wrong instead of propagating.
    """
    model = model or os.environ.get("XAI_VISION_MODEL") or "grok-4.3"
    path = Path(pdf_path)
    if not path.is_file():
        return _stamp({"found": False, "why": f"the drawing is not readable: {path}"},
                      model, units)
    try:
        units = int(units)
        if units < 1:
            raise ValueError
    except (TypeError, ValueError):
        return _stamp({"found": False, "why": "a quantity of 1 or more is required — a "
                                              "price per unit means nothing without one"},
                      model, units if isinstance(units, int) else 0)

    key = _key(path, units, model)
    cache = _cache_path(key) if use_cache else None
    if cache is not None and cache.is_file():
        try:
            hit = json.loads(cache.read_text(encoding="utf-8"))
            hit["cached"] = True
            return hit
        except Exception:                                    # noqa: BLE001
            pass                       # an unreadable cache entry is not a reason to fail

    try:
        from llm_full_extract import build_document_context, _call_llm
        context = build_document_context(path)
    except Exception as exc:                                 # noqa: BLE001
        return _stamp({"found": False,
                       "why": f"the drawing could not be read ({type(exc).__name__}: {exc})"},
                      model, units)
    if not str(context or "").strip():
        return _stamp({"found": False,
                       "why": "no text could be read from this drawing — it may be a scan, "
                              "in which case this method cannot price it"}, model, units)

    prompt = (f"ORDER QUANTITY: {units} off\n\n"
              f"DRAWING:\n{context}")
    try:
        reply = _call_llm(prompt, model, system=SYSTEM)
    except Exception as exc:                                 # noqa: BLE001
        return _stamp({"found": False,
                       "why": f"the model could not be reached ({type(exc).__name__}: "
                              f"{str(exc)[:160]})"}, model, units)

    out = _stamp(_parse(reply), model, units)
    # ONLY A HIT IS CACHED. Writing a miss would make one unreachable moment permanent, and
    # the next run would report a drawing as unpriceable without ever asking again.
    if out.get("found") and cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
        except OSError:
            pass
    return out
