# -*- coding: utf-8 -*-
"""
SDI Intelligence — LLM note-scan for bought-in items described in PDF prose.

WHY THIS EXISTS
---------------
Deterministic BOM-table extraction (estimator.extract_bought_in_from_pages) reliably
captures items that appear as structured BOM rows (ELECTRICS, FIXING5, FIXING 236, ...).
But some bought-in components are described ONLY in free-text drawing notes, never as a
BOM row — e.g. "ADHESIVE CABLE CLIPS TO BE USED TO SECURE ALL LOOSE CABLES", "EARTH STRAP
TO BE RIVETTED", "5m MAINS CABLE", "GU10 DOWNLIGHTS". A regex can't reliably turn varied
prose into a parts list; an LLM can. This module does exactly and only that.

DESIGN CONSTRAINTS (locked with the user)
-----------------------------------------
1. ADDITIVE ONLY. Runs AFTER deterministic extraction. Can only ADD new items; never
   changes, overrides or removes anything the deterministic pass found.
2. NO CONFLICTS. Every candidate is checked against the codes/descriptions already found
   (existing_pns + seen_codes + already-captured descriptions). Anything already present
   is dropped — no duplicates.
3. PDF PROSE ONLY. Operates on joined PDF note-text. DXF geometry is never sent to the LLM.
4. FLAGGED. Every added item is review_flag=True, low confidence, labelled
   "AI-identified from notes — verify". Quantity is left as a verify-flag, not invented.
5. NON-INTERFERENCE / REMOVABLE. Gated behind config.NOTE_SCAN_POLICY['enable']. If the
   flag is off (or this module is deleted), the engine returns EXACTLY its prior behaviour.
   Never raises into the caller — any failure returns an empty list.

The caller (estimator.extract_bought_in_from_pages) passes the already-joined note text and
the dedup sets; we return a list of new bought-in stubs to append. Pricing happens later in
the normal waterfall (UDEF -> web -> LLM, cached) — we do NOT price here.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set


# Items that are STRUCTURAL/fabricated or already handled elsewhere — never emit these as
# note-scan bought-in, even if the LLM mentions them. Guards against the model turning a
# fabricated part or a finish instruction into a phantom bought-in line.
_NEVER_EMIT_TOKENS = (
    "WELDMENT", "BRACKET", "PANEL", "PLATE", "LEG", "HEADER", "SUPPORT", "BAR",
    "POWDER", "PAINT", "VINYL", "MASK", "FOLD", "WELD", "LASER", "BEND",
)

# A conservative ceiling — note-described counts are usually absent; if the model invents a
# huge quantity, treat it as "unknown" rather than trusting it.
_MAX_TRUSTED_QTY = 50


def _strip_code_chars(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


_DEDUP_STOPWORDS = {
    "THE", "A", "AN", "OF", "TO", "FOR", "AND", "WITH", "BLACK", "WHITE",
    "MM", "CM", "M", "X", "OR", "BE", "IN", "ON", "PER",
}


def _sig_tokens(desc: str) -> Set[str]:
    """Significant word tokens of a description (alphanumeric, length>=2, not a stopword)."""
    words = re.split(r"[^A-Z0-9]+", (desc or "").upper())
    return {w for w in words if len(w) >= 2 and w not in _DEDUP_STOPWORDS}


def _looks_like_existing(desc: str, existing_descs: Set[str]) -> bool:
    """True if this description substantially overlaps something already captured.

    Uses TOKEN OVERLAP, not substring containment. Substring containment misses
    re-ordered descriptions — e.g. note-scan "50cm lighting loom" vs deterministic
    "50cm LOOM LIGHTING ELECTRICS": the words differ in order so neither contains the
    other, and the duplicate slips through (this happened on 1282). With token overlap,
    they share {50CM, LIGHTING, LOOM} and are correctly identified as the same item.
    """
    d = _sig_tokens(desc)
    if not d:
        return True
    for e in existing_descs:
        es = _sig_tokens(e)
        if not es:
            continue
        # Substring either way still catches exact-code cases (cheap pre-check).
        ds, ess = _strip_code_chars(desc), _strip_code_chars(e)
        if ds and ess and (ds in ess or ess in ds):
            return True
        # Token overlap: if (almost) all of the shorter item's significant tokens
        # appear in the other, treat as the same item.
        smaller, larger = (d, es) if len(d) <= len(es) else (es, d)
        shared = smaller & larger
        if smaller and len(shared) / len(smaller) >= 0.6 and len(shared) >= 2:
            return True
    return False


def _select_note_regions(note_text: str, budget: int = 9000) -> str:
    """The joined drawing text can be very large (100k+ chars) and the bought-in notes are
    often buried mid-document (e.g. on an assembly page 10 of 23). Blindly truncating misses
    them. We locate windows around note/bought-in CUE words and assemble them up to a budget.

    Critically, cues are RANKED by specificity: rare, telling words (JUNCTION, STRAP,
    DOWNLIGHT, RIVETT) must win budget over common words that also appear in title-block
    boilerplate. Without ranking, early boilerplate hits exhaust the budget before the real
    notes (which sit mid-document) are ever reached — which is exactly what happened on 1282
    (notes at char ~17,900 were starved by title-block matches in chars 0-9000)."""
    if not note_text:
        return ""
    up = note_text.upper()
    # STRONG cues: highly specific to bought-in note content, rarely in boilerplate.
    strong = (
        "JUNCTION", "STRAP", "DOWNLIGHT", "ADHESIVE", "RIVETT", "GU10", "LOOM",
        "CABLE CLIP", "CABLE TIE", "MAINS CABLE", "FOAM TAPE", "TRANSFORMER",
        "SECURE ALL", "EARTH",
    )
    # WEAK cues: useful but also appear in boilerplate; only used to fill leftover budget.
    weak = ("CABLE", "ELECTRIC", "LED", "DRIVER", "PLUG", "WIRE", "NOTE")

    def _collect(cues):
        hits = []
        for c in cues:
            start = 0
            while True:
                i = up.find(c, start)
                if i < 0:
                    break
                hits.append(i)
                start = i + 1
                if len(hits) > 400:
                    break
        return sorted(set(hits))

    win = 450
    spans: List[List[int]] = []
    total = 0

    def _add_hits(hits):
        nonlocal total
        for h in hits:
            if total >= budget:
                return
            s, e = max(0, h - win), min(len(note_text), h + win)
            merged = False
            for sp in spans:
                if s <= sp[1] and e >= sp[0]:  # overlap
                    grow = max(sp[1], e) - sp[1] + (sp[0] - min(sp[0], s))
                    sp[0], sp[1] = min(sp[0], s), max(sp[1], e)
                    total += max(0, grow)
                    merged = True
                    break
            if not merged:
                spans.append([s, e])
                total += (e - s)

    # Strong cues first — they claim budget before any boilerplate-prone weak cues.
    _add_hits(_collect(strong))
    if total < budget:
        _add_hits(_collect(weak))

    if not spans:
        return note_text[:budget]
    spans.sort()
    return " … ".join(note_text[s:e] for s, e in spans)


def _build_prompt(note_text: str) -> str:
    # Pull the note-bearing regions from anywhere in the (possibly huge) joined text,
    # rather than truncating to the front where the bought-in notes usually aren't.
    snippet = _select_note_regions(note_text)
    return (
        "You are reading the free-text NOTES from an engineering drawing for a retail "
        "display bay. Some bought-in components (electrical, fixings, cable management, "
        "lighting) are described in the notes rather than listed in the parts table.\n\n"
        "List ONLY discrete bought-in components that a buyer would purchase (e.g. cable "
        "clips, earth strap, mains cable, junction box, downlights, LED drivers, cable "
        "ties). Do NOT list fabricated metal parts, finishes, processes, or instructions.\n\n"
        "Return STRICT JSON only — no prose, no markdown — as a list of objects with keys:\n"
        '  "item"      : short component name (e.g. "Adhesive cable clip")\n'
        '  "quantity"  : integer if the notes clearly state one, else null\n'
        '  "evidence"  : the short phrase from the notes that mentions it\n\n'
        "If nothing qualifies, return [].\n\n"
        "NOTES:\n" + snippet
    )


def _call_llm(prompt: str) -> Optional[Any]:
    """Call the same xAI/Grok endpoint the price lookup uses, via its existing HTTP helper.
    _call_xai_llm already parses the model's JSON reply and returns a Python object
    (list/dict) or None. Isolated so a missing key / network error never propagates."""
    try:
        from web_ai_price_lookup import _call_xai_llm
    except Exception:
        return None
    try:
        return _call_xai_llm(prompt)
    except Exception:
        return None


def _coerce_items(parsed: Any) -> List[Dict[str, Any]]:
    """_call_xai_llm returns already-parsed JSON. Accept either a bare list of items, or a
    dict wrapping a list under a common key."""
    if parsed is None:
        return []
    data = parsed
    if isinstance(parsed, dict):
        for k in ("items", "components", "bought_in", "results", "data"):
            if isinstance(parsed.get(k), list):
                data = parsed[k]
                break
        else:
            # a single item dict
            if parsed.get("item"):
                data = [parsed]
            else:
                return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for d in data:
        if isinstance(d, dict) and d.get("item"):
            out.append(d)
    return out


def _price_via_waterfall(code: str, desc: str) -> Optional[Dict[str, Any]]:
    """Price a note-found bought-in item via web/LLM, reusing the SAME cache file the bay
    pricer uses (config.LLM_PRICE_CACHE) so a given description always resolves to the same
    price — determinism, exactly as for ELECTRICS. Note items are isolated from the bay
    catalogue pricer (we do NOT touch that hot path); we just call the shared lookup +
    shared cache here. Returns a price dict or None (never raises)."""
    try:
        import config as _cfg
        import json as _json, os as _os, hashlib as _hashlib
    except Exception:
        return None

    _cache_path = getattr(_cfg, "LLM_PRICE_CACHE",
                          _os.path.join(str(getattr(_cfg, "OUTPUT_DIR", ".")), "llm_price_cache.json"))
    _key = _hashlib.md5((str(code) + "|" + str(desc)).upper().strip().encode("utf-8")).hexdigest()

    # Read shared cache first (deterministic reuse across runs and across jobs).
    cache = {}
    try:
        if _os.path.exists(_cache_path):
            with open(_cache_path, encoding="utf-8") as cf:
                cache = _json.load(cf) or {}
    except Exception:
        cache = {}
    if _key in cache:
        c = cache[_key]
        return {
            "unit_cost_gbp": float(c["unit_cost_gbp"]),
            "source": c.get("source", "llm_market_estimate"),
            "confidence": float(c.get("confidence", 0.45)),
            "cached": True,
        }

    # Not cached — call the shared web/LLM lookup, then persist for next time.
    try:
        from web_ai_price_lookup import lookup_web_ai_price
        wr = lookup_web_ai_price(
            {"description": desc or code, "part_code": code},
            enable_web_search=True,
            enable_llm_estimate=True,
        )
    except Exception:
        return None
    if not (wr and wr.get("found") and wr.get("price_gbp")):
        return None
    try:
        uc = float(wr["price_gbp"])
    except Exception:
        return None
    reject_above = float(getattr(_cfg, "SYSTEM_COST_REJECT_ABOVE_GBP", 750.0) or 750.0)
    if not (0 < uc <= reject_above):
        return None
    cap = float((getattr(_cfg, "FALLBACK_PRICING_POLICY", {}) or {}).get("fallback_confidence_cap", 0.68))
    result = {
        "unit_cost_gbp": uc,
        "source": wr.get("source_type", "web_ai_fallback"),
        "confidence": min(float(wr.get("confidence") or 0.45), cap),
        "cached": False,
    }
    try:
        cache[_key] = {
            "unit_cost_gbp": uc,
            "source": result["source"],
            "confidence": result["confidence"],
            "review_reason": "Indicative AI price (note-scan) — verify before quoting.",
            "_desc": (str(code) + "|" + str(desc)).upper().strip(),
        }
        with open(_cache_path, "w", encoding="utf-8") as cf:
            _json.dump(cache, cf, indent=2)
    except Exception:
        pass
    return result


def scan_notes_for_bought_in(
    note_text: str,
    *,
    existing_pns: Set[str],
    seen_codes: Set[str],
    existing_descriptions: Optional[Set[str]] = None,
    stub_builder=None,
) -> List[Dict[str, Any]]:
    """
    Return a list of NEW bought-in stubs found only in prose notes.

    Additive + reconciled: drops anything already present in existing_pns / seen_codes /
    existing_descriptions. Never raises — returns [] on any failure or if disabled.

    stub_builder: estimator._bought_in_part_stub (passed in to avoid a circular import).
    """
    # ---- Gate: disabled => exact prior behaviour ----
    try:
        import config as _cfg
        _policy = getattr(_cfg, "NOTE_SCAN_POLICY", {}) or {}
        if not bool(_policy.get("enable", False)):
            return []
    except Exception:
        return []

    if not note_text or stub_builder is None:
        return []

    existing_descriptions = existing_descriptions or set()

    try:
        parsed = _call_llm(_build_prompt(note_text))
        items = _coerce_items(parsed)
    except Exception:
        return []

    new_stubs: List[Dict[str, Any]] = []
    emitted: Set[str] = set()

    for it in items:
        name = str(it.get("item") or "").strip()
        if not name:
            continue
        up = name.upper()

        # Guard: never emit structural/process tokens.
        if any(tok in up for tok in _NEVER_EMIT_TOKENS):
            continue

        # Reconcile against everything already found — no conflicts/dupes.
        code_guess = "NOTE-" + _strip_code_chars(name)[:18]
        if (
            code_guess in seen_codes
            or code_guess in existing_pns
            or up in emitted
            or _looks_like_existing(name, existing_descriptions)
        ):
            continue

        # Quantity: trust only a sane explicit integer; else leave unknown (verify).
        qty: Any = it.get("quantity")
        if not isinstance(qty, int) or qty <= 0 or qty > _MAX_TRUSTED_QTY:
            qty = 1  # placeholder count; flagged "verify qty" below

        stub = stub_builder(code_guess, name, qty)
        # Flag hard: this is an AI-identified, unverified, note-sourced line.
        stub["source"] = "llm_note_scan"
        stub["_note_scan"] = True
        stub["review_flag"] = True
        ev = str(it.get("evidence") or "").strip()[:120]
        _flags = [
            "AI-identified from drawing notes — verify item, qty & price"
            + (f" (note: \u201c{ev}\u201d)" if ev else "")
        ]
        # Price via the shared web/LLM waterfall (same cache as ELECTRICS) so the line carries
        # a real indicative price, not the generic handling default. Isolated from the bay
        # pricer; failure just leaves the stub's default price + a "no price found" flag.
        _price = _price_via_waterfall(code_guess, name)
        if _price is not None:
            stub["unit_cost_gbp"] = _price["unit_cost_gbp"]
            stub["unit_material_cost_gbp"] = _price["unit_cost_gbp"]
            stub["extended_total_cost_gbp"] = round(_price["unit_cost_gbp"] * qty, 2)
            stub["cost_source"] = _price["source"]
            stub["cost_confidence"] = _price["confidence"]
            stub["price_verified"] = False
            _src_label = "cached" if _price.get("cached") else "fresh"
            _flags.append(
                f"AI ESTIMATE ({_price['source']}, {_src_label}) \u00a3{_price['unit_cost_gbp']:.2f}/unit — indicative, verify"
            )
        else:
            stub["cost_source"] = "note_scan_no_price"
            _flags.append("No catalogue/web/AI price found — estimator to price")
        stub["review_flags"] = _flags
        # Make the unknown-quantity explicit for the estimator.
        stub["_qty_unverified"] = (not isinstance(it.get("quantity"), int))
        new_stubs.append(stub)
        emitted.add(up)
        seen_codes.add(code_guess)

    if new_stubs:
        print(f"[DEBUG] Note-scan (LLM) added {len(new_stubs)} note-described item(s): "
              f"{[s['part_number'] for s in new_stubs]}")
    else:
        print(f"[DEBUG] Note-scan (LLM) ran; added 0 new items "
              f"(LLM returned {len(items)} candidate(s), all duplicates/filtered or none found)")

    return new_stubs
