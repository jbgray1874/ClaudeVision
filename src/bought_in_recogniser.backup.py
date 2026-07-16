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
# HEAD-WORDS: the generic nouns that name a physical PURCHASED component. A prose
# phrase only counts as a bought-in item if it is multi-word AND anchored on one of
# these. This is what kills the boilerplate noise (CLIENT, BARN, SURFACE, TABLE...):
# none of those contain a head-word, so they can never form a valid component phrase.
#
# SAFE head-words: almost always a bought-in component. Recognise and price freely.
# AMBIGUOUS head-words: name things SDI both MAKES and BUYS (a "base plate" is usually a
#   fabricated DXF part, not bought). These are recognised but NOT priced when the item is
#   already accounted for as a fabricated part — they surface as a flagged QUERY for the
#   estimator so they can never silently double-count.
# ---------------------------------------------------------------------------
_HEADWORDS_SAFE = set("""
screw bolt nut nutsert insert washer rivet stud bush glide grommet magnet hinge castor
clip strap tie cable loom downlight transformer driver lamp bulb plug socket connector
gland sleeve cap knob handle catch latch lock pin spacer fastener clamp fixing
tape edging seal sticker label pad foam
""".split())

_HEADWORDS_AMBIGUOUS = set("""
plate channel rail bar panel frame foot bracket cover profile
""".split())

_HEADWORDS = _HEADWORDS_SAFE | _HEADWORDS_AMBIGUOUS


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
        # vocab maps a head-word-anchored phrase -> the head-word it is anchored on,
        # so the recogniser knows whether a hit is SAFE or AMBIGUOUS.
        self.vocab: Dict[str, str] = {}
        self.priced: List[Dict[str, Any]] = []  # [{desc, desc_tokens, price, code, source}]
        self.loaded = False

    def load(self, get_connection, *, min_term_freq: int = 5,
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

        # Build priced reference (keep descriptions VERBATIM) + tally HEAD-WORD-ANCHORED
        # multi-word phrases only. A phrase qualifies as vocabulary ONLY if it is multi-word
        # AND contains a component head-word. This is what removes the boilerplate noise that
        # a naive single-word mine produced (CLIENT/BARN/SURFACE/TABLE etc.).
        from collections import Counter
        phrase_freq: Counter = Counter()
        phrase_head: Dict[str, str] = {}
        for desc, price, code in rows:
            toks = _tokens(str(desc))
            if not toks:
                continue
            # bigrams + trigrams that contain at least one head-word
            for n in (2, 3):
                for i in range(len(toks) - n + 1):
                    gram = toks[i:i + n]
                    heads = [w for w in gram if w in _HEADWORDS]
                    if not heads:
                        continue
                    phrase = " ".join(gram)
                    phrase_freq[phrase] += 1
                    # record the head-word (prefer a safe one if the phrase has several)
                    if phrase not in phrase_head:
                        safe = [h for h in heads if h in _HEADWORDS_SAFE]
                        phrase_head[phrase] = (safe[0] if safe else heads[0])
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

        # Vocabulary = head-word-anchored phrases recurring at least min_term_freq times.
        self.vocab = {ph: phrase_head[ph] for ph, n in phrase_freq.items() if n >= min_term_freq}
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
            # Jaccard (shared / union), NOT shared/smaller. shared/smaller let a 2-token
            # phrase ("foam tape") score 1.0 against any longer line containing both words
            # (e.g. a £132 "foam tape gasket kit 25m"), producing confidently-wrong prices.
            # Jaccard penalises unexplained tokens on the historical side, so a short phrase
            # only matches a similarly-short, genuinely-equivalent description.
            union = ptoks | rtoks
            score = len(shared) / len(union) if union else 0.0
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
    fabricated_descriptions: Optional[Set[str]] = None,
    stub_builder=None,
) -> List[Dict[str, Any]]:
    """Deterministically recognise bought-in items described in THIS drawing's prose.

    Scans the prose for head-word-anchored vocabulary phrases (mined from SDI history).
    For each hit:
      * SAFE head-word (screw/clip/strap/cable...): recognise + price from history if a
        confident match exists, else surface flagged "no price - estimator to price".
      * AMBIGUOUS head-word (plate/rail/bar...): recognise, but if the item is already
        accounted for as a fabricated part, surface it as a flagged QUERY with NO price
        (so it can never silently double-count a made-in part). Otherwise treat like SAFE.

    Deterministic: same note_text + same DB -> same items + prices, every run. No LLM. No DXF.
    """
    if not note_text or stub_builder is None:
        return []
    existing_pns = existing_pns or set()
    existing_descriptions = existing_descriptions or set()
    fabricated_descriptions = fabricated_descriptions or set()

    ref = get_reference(get_connection)
    if not ref.vocab:
        return []  # nothing mined (e.g. no DB) -> layer-2 no-op, backstop carries

    up = " " + re.sub(r"[^a-z0-9 ]", " ", (note_text or "").lower()) + " "
    up = re.sub(r"\s+", " ", up)

    # Pre-compute fabricated-part token sets once (for the double-count guard).
    fab_token_sets = [_sig_token_set(f) for f in fabricated_descriptions if f]

    def _is_already_fabricated(phrase: str) -> bool:
        pts = _sig_token_set(phrase)
        if not pts:
            return False
        for fts in fab_token_sets:
            if not fts:
                continue
            shared = pts & fts
            if len(shared) >= max(2, int(0.6 * len(pts))):
                return True
        return False

    # Scan: longest phrases first (most specific). A phrase matches only as a whole-word
    # run in the prose. Track character spans so we don't double-emit overlapping phrases.
    phrases = sorted(ref.vocab.keys(), key=lambda p: len(p), reverse=True)
    claimed_spans: List[Tuple[int, int]] = []

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in claimed_spans)

    out: List[Dict[str, Any]] = []
    emitted: Set[str] = set()

    for phrase in phrases:
        needle = " " + phrase + " "
        idx = up.find(needle)
        if idx < 0:
            continue
        s, e = idx, idx + len(needle)
        if _overlaps(s, e):
            continue
        claimed_spans.append((s, e))

        head = ref.vocab[phrase]
        ambiguous = head in _HEADWORDS_AMBIGUOUS

        desc = phrase.strip().title()
        key = _norm(desc)
        if not key or key in emitted:
            continue

        # Dedup against layer-1 bought-in descriptions already found.
        dts = _sig_token_set(desc)
        if any(len(dts & _sig_token_set(x)) >= max(2, int(0.6 * len(dts)))
               for x in existing_descriptions if x):
            continue

        code_guess = "BI-" + re.sub(r"[^A-Z0-9]", "", phrase.upper())[:18]
        if code_guess in existing_pns:
            continue

        # DOUBLE-COUNT GUARD: if this phrase matches something already counted as a
        # fabricated (DXF/grid) part, do NOT add a priced line. For ambiguous head-words
        # this is the common case (e.g. "base plate"); surface as a flagged query instead.
        already_fab = _is_already_fabricated(desc)

        stub = stub_builder(code_guess, desc, 1)
        stub["source"] = "prose_recogniser_layer2"
        stub["_layer2_recognised"] = True
        stub["_headword"] = head
        stub["page_roles"] = ["bought_in"]
        stub["review_flag"] = True
        flags = [f"Deterministically recognised in drawing notes (head-word: '{head}')"]

        if already_fab:
            # Recognise but DON'T price — it's likely the fabricated part counted elsewhere.
            stub["cost_source"] = "layer2_possible_fabricated_query"
            stub["_no_price_reason"] = "matches a fabricated part — possible double-count"
            flags.append("QUERY: also appears as a fabricated part — estimator confirm "
                         "bought-in vs made-in (NOT priced, to avoid double-counting)")
        else:
            match = ref.best_priced_match(desc)
            # Plausibility guard: a small loose consumable (clip/tie/tape/strap/rivet/etc.)
            # priced implausibly high is almost certainly a bad token match (e.g. "foam tape"
            # matching a £132 assembly line). Reject the price rather than apply a confidently
            # wrong figure — fall through to "estimator to price" (honest gap beats wrong number).
            _CONSUMABLE_HEADS = {"clip", "tie", "tape", "strap", "rivet", "screw", "washer",
                                 "nut", "bolt", "insert", "grommet", "cap", "pin", "spacer",
                                 "sleeve", "gland", "seal", "sticker", "label", "pad", "foam"}
            if match and head in _CONSUMABLE_HEADS and match["price"] > 20.0:
                match = None  # implausible for a loose consumable — do not apply
                flags.append("A possible historical price match was rejected as implausibly "
                             "high for a loose consumable — estimator to price")
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
                    + (f" [{match['code']}]" if match["code"] else "") + " \u2014 verify")
            else:
                # Recognised, no historical price. Flag for estimator + (future) web/LLM price
                # + queue for promotion into the bought-in catalogue.
                stub["cost_source"] = "layer2_no_price_match"
                stub["_queue_for_catalogue"] = True
                flags.append("Type recognised, no historical price \u2014 estimator to price; "
                             "queue for catalogue (UDEF) so it is known next time")
        stub["review_flags"] = flags
        out.append(stub)
        emitted.add(key)

    if out:
        names = [s.get("part_number") or s["description"][:20] for s in out]
        print(f"[DEBUG] Layer-2 prose recogniser (deterministic) found {len(out)} item(s): {names}")
    else:
        print("[DEBUG] Layer-2 prose recogniser ran; 0 items recognised in prose")
    return out
