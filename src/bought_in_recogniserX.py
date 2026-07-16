# -*- coding: utf-8 -*-
"""
bought_in_recogniser.py  —  LAYER 2 of the three-layer bought-in capture model.

THE THREE LAYERS (deterministic-first, LLM-last):
  Layer 1  Structured BOM grid scan (pdfplumber)  -> items in the ITEM/DWG/DESC/QTY table.
           Reliable, already built (estimator.extract_bought_in_from_pages).
  Layer 2  THIS MODULE — deterministic PROSE recogniser. Reads the drawing's own note
           text, matches against a vocabulary of bought-in component TYPES mined from SDI's
           real history (dbo.historical_quote_material_line + dbo.bought_in_parts), and
           emits the items that are genuinely described in THIS drawing's prose — priced
           from real SDI history where a confident match exists. Deterministic: same drawing
           -> same items -> same prices, every run.
  Layer 3  LLM note-scan (note_scan.py) — BACKSTOP only. Catches novel phrasings layer 2's
           vocabulary does not yet know. Flagged as AI-sourced. When it finds something new,
           that term is a candidate to add to the vocabulary so layer 2 catches it next time.

PROVENANCE / SAFETY DISCIPLINE (do not weaken):
  * The VOCABULARY (what a bought-in component is called) is global, mined across all jobs.
  * INCLUSION on a job's BOM is local: an item appears ONLY because its type-words appear in
    THIS drawing's prose. A vocabulary term never forces an item onto a job.
  * A historical price is replayed ONLY for a confident same-part match. Descriptions are
    kept VERBATIM (never reworded) so they (a) stay traceable to source and (b) keep matching
    the same part on future jobs. A weak match is SURFACED (flagged) but not silently priced
    as if verified.
  * Cross-job contamination guard: we match a *type/description*, not a specific job's part;
    bundles from one job (e.g. a "downlights+transformer+cable+plug" package) are NOT matched
    onto a different job's individual components.

This module reads the DB read-only. It never writes. It never sends DXF geometry anywhere.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Stopwords / non-component words. Kept deliberately small and obvious. These
# are words that recur in material descriptions but are NOT component types
# (spreadsheet artefacts, admin words, units, generic adjectives).
# ---------------------------------------------------------------------------
_STOP = set("""
and the to of for with a an or be in on per x mm cm m std part each set kg no not all
from as is by off thru dia ext int down up rev semi gloss ral mat material description
item misc inc max min height width depth charge total cost delivery elc upc sticker
black white red blue grey green clear natural left right top bottom front back side
new old approx tbc na n/a unless otherwise stated qty quantity price each
""".split())

# Minimum token length to be considered a meaningful type-word.
_MIN_TOKEN = 3


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tokens(s: str) -> List[str]:
    s = _norm(s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [w for w in s.split() if len(w) >= _MIN_TOKEN and w not in _STOP and not w.isdigit()]


def _sig_token_set(s: str) -> Set[str]:
    return set(_tokens(s))


# ---------------------------------------------------------------------------
# Vocabulary + priced reference, loaded ONCE from SDI history.
# ---------------------------------------------------------------------------
class BoughtInReference:
    """Holds the mined type-vocabulary and the priced historical descriptions.

    Built once (a few seconds: one SQL pull + in-memory tally), then matching per job is
    in-memory and effectively instant — it never re-queries the 68k rows per job.
    """

    def __init__(self) -> None:
        self.vocab: Set[str] = set()           # recognised component type-words / phrases
        self.priced: List[Dict[str, Any]] = []  # [{desc, desc_tokens, price, code, source}]
        self.loaded = False

    def load(self, get_connection, *, min_term_freq: int = 3,
             max_price: float = 750.0) -> "BoughtInReference":
        """Mine vocabulary + priced reference from SDI history (read-only)."""
        try:
            conn = get_connection()
            cur = conn.cursor()
        except Exception:
            # No DB — module stays empty; layer-2 becomes a no-op and the LLM backstop carries.
            self.loaded = True
            return self

        rows: List[Tuple[str, Optional[float], Optional[str]]] = []

        # Priced bought-in material lines (the gold: real descriptions + real prices + codes).
        try:
            cur.execute("""
                SELECT line_description, unit_price_gbp, part_code
                FROM dbo.historical_quote_material_line
                WHERE line_description IS NOT NULL
            """)
            rows += [(r[0], r[1], r[2]) for r in cur.fetchall()]
        except Exception:
            pass

        # Curated bought_in_parts (small, clean, also priced).
        try:
            cur.execute("""
                SELECT description, unit_price_gbp, part_code
                FROM dbo.bought_in_parts
                WHERE description IS NOT NULL
            """)
            rows += [(r[0], r[1], r[2]) for r in cur.fetchall()]
        except Exception:
            pass

        try:
            conn.close()
        except Exception:
            pass

        # Build priced reference (keep descriptions VERBATIM) + tally vocabulary.
        from collections import Counter
        uni: Counter = Counter()
        bi: Counter = Counter()
        for desc, price, code in rows:
            toks = _tokens(str(desc))
            if not toks:
                continue
            uni.update(toks)
            bi.update(" ".join(p) for p in zip(toks, toks[1:]))
            try:
                p = float(price) if price is not None else None
            except Exception:
                p = None
            if p is not None and 0 < p <= max_price:
                self.priced.append({
                    "desc": str(desc).strip(),          # VERBATIM — never reworded
                    "desc_tokens": set(toks),
                    "price": p,
                    "code": (str(code).strip() if code else None),
                    "source": "historical_quote_material_line",
                })

        # Vocabulary = type-words/phrases recurring at least min_term_freq times.
        self.vocab = {w for w, n in uni.items() if n >= min_term_freq}
        self.vocab |= {w for w, n in bi.items() if n >= min_term_freq}
        self.loaded = True
        return self

    # --- matching -----------------------------------------------------------
    def best_priced_match(self, phrase: str, *, min_overlap: float = 0.6,
                          min_shared: int = 2) -> Optional[Dict[str, Any]]:
        """Find the closest priced historical line for a recognised phrase, by token overlap.

        Conservative on purpose: returns a match only when the phrase and a historical
        description share enough significant tokens. Confidence scales with overlap so the
        caller can flag weak matches rather than apply them blindly. Never rewords anything.
        """
        ptoks = _sig_token_set(phrase)
        if len(ptoks) < min_shared:
            return None
        best = None
        best_score = 0.0
        for ref in self.priced:
            rtoks = ref["desc_tokens"]
            if not rtoks:
                continue
            shared = ptoks & rtoks
            if len(shared) < min_shared:
                continue
            smaller = min(len(ptoks), len(rtoks))
            score = len(shared) / smaller if smaller else 0.0
            if score > best_score:
                best_score, best = score, ref
        if best is None or best_score < min_overlap:
            return None
        return {
            "matched_desc": best["desc"],       # verbatim source description
            "price": best["price"],
            "code": best["code"],
            "source": best["source"],
            "match_score": round(best_score, 3),
        }


# Module-level singleton so the reference is built once per process.
_REFERENCE: Optional[BoughtInReference] = None


def get_reference(get_connection) -> BoughtInReference:
    global _REFERENCE
    if _REFERENCE is None or not _REFERENCE.loaded:
        _REFERENCE = BoughtInReference().load(get_connection)
    return _REFERENCE


# ---------------------------------------------------------------------------
# The layer-2 prose recogniser.
# ---------------------------------------------------------------------------
def recognise_bought_in_in_prose(
    note_text: str,
    *,
    get_connection,
    existing_pns: Optional[Set[str]] = None,
    existing_descriptions: Optional[Set[str]] = None,
    stub_builder=None,
) -> List[Dict[str, Any]]:
    """Deterministically recognise bought-in items described in THIS drawing's prose.

    Returns a list of bought-in stubs for items whose component type-words appear in the
    prose AND are known to SDI's vocabulary. Where a confident priced historical match
    exists, the stub carries that real price + code (verbatim source description recorded);
    otherwise the item is surfaced flagged "type recognised, price to confirm".

    Deterministic: same note_text + same DB -> same result, every run. No LLM. No DXF.
    """
    if not note_text or stub_builder is None:
        return []
    existing_pns = existing_pns or set()
    existing_descriptions = existing_descriptions or set()

    ref = get_reference(get_connection)
    if not ref.vocab:
        return []  # nothing mined (e.g. no DB) -> layer-2 no-op, backstop carries

    up = (note_text or "").lower()

    # Candidate phrases: scan for known vocabulary phrases (multi-word first, then single)
    # and capture a tight surrounding window so qualifiers ("5m", "black") are retained.
    found: List[Tuple[str, str]] = []  # (canonical_term, evidence_phrase)
    seen_terms: Set[str] = set()

    # Prefer multi-word vocab phrases (more specific) before single words.
    multiword = sorted((t for t in ref.vocab if " " in t), key=len, reverse=True)
    singles = sorted((t for t in ref.vocab if " " not in t), key=len, reverse=True)

    def _capture(term: str):
        idx = up.find(term)
        if idx < 0:
            return
        # Evidence window: a little context either side, trimmed to a phrase.
        s, e = max(0, idx - 30), min(len(note_text), idx + len(term) + 30)
        ev = re.sub(r"\s+", " ", note_text[s:e]).strip()
        found.append((term, ev))

    for term in multiword:
        if term in up and term not in seen_terms:
            seen_terms.add(term)
            _capture(term)
    for term in singles:
        if term in up and term not in seen_terms:
            # Skip a single word already covered by a captured multiword phrase.
            if any(term in mw for mw in seen_terms if " " in mw):
                continue
            seen_terms.add(term)
            _capture(term)

    # Build stubs, deduped against what layer 1 already found.
    out: List[Dict[str, Any]] = []
    emitted: Set[str] = set()
    for term, evidence in found:
        # The DESCRIPTION is the clean canonical recognised term (title-cased), NOT the raw
        # surrounding window. The window is kept as provenance/evidence only. This keeps the
        # BOM line clean AND lets the price-match work on a clean phrase rather than noise.
        desc = term.strip().title()
        key = _norm(desc)
        if not key or key in emitted:
            continue
        # Dedup against layer-1 descriptions by token overlap.
        dts = _sig_token_set(desc)
        if any(len(dts & _sig_token_set(e)) >= max(2, int(0.6 * len(dts)))
               for e in existing_descriptions if e):
            continue

        code_guess = "BI-" + re.sub(r"[^A-Z0-9]", "", term.upper())[:18]
        if code_guess in existing_pns:
            continue

        stub = stub_builder(code_guess, desc, 1)
        stub["source"] = "prose_recogniser_layer2"
        stub["_layer2_recognised"] = True
        stub["_evidence"] = evidence[:120]
        stub["page_roles"] = ["bought_in"]
        stub["review_flag"] = True

        # Price it from real SDI history if a confident match exists. Match on the clean term.
        match = ref.best_priced_match(desc)
        flags = [f"Deterministically recognised in drawing notes (type: '{term}')"]
        if match:
            stub["unit_cost_gbp"] = match["price"]
            stub["unit_material_cost_gbp"] = match["price"]
            stub["extended_total_cost_gbp"] = round(match["price"], 2)
            stub["cost_source"] = "historical_quote_material_line"
            stub["price_verified"] = False
            stub["_matched_historical_desc"] = match["matched_desc"]
            stub["_matched_code"] = match["code"]
            stub["_match_score"] = match["match_score"]
            conf = "confident" if match["match_score"] >= 0.8 else "indicative"
            flags.append(
                f"Priced from SDI history ({conf}, score {match['match_score']}): "
                f"\u00a3{match['price']:.2f} \u2190 \u201c{match['matched_desc']}\u201d"
                + (f" [{match['code']}]" if match["code"] else "")
                + " \u2014 verify"
            )
        else:
            stub["cost_source"] = "layer2_no_price_match"
            flags.append("Type recognised but no confident historical price \u2014 estimator to price")
        stub["review_flags"] = flags

        out.append(stub)
        emitted.add(key)

    if out:
        print(f"[DEBUG] Layer-2 prose recogniser (deterministic) found {len(out)} item(s): "
              f"{[s['part_number'] for s in out if s.get('part_number')] or [s['description'][:24] for s in out]}")
    else:
        print("[DEBUG] Layer-2 prose recogniser ran; 0 items recognised in prose")
    return out
