"""Which edges take ABS, and how long they are. Never the whole perimeter by default.

James Gray, 18 September 2026, on Tony Ford's 11908-21 review:

    "The engine should derive banded metres from the drawing/DXF, not ask Tony to type a
     length already shown by the design... identify the banded edges from a DXF layer, edge
     callout, note, hatch, or detail; measure only those edges; create the EDGE line using
     that measured length; get its rate from SDI Live/supplier/evidenced research.

     We must not use the whole visible perimeter by default: Tony's own 5 m shows that only
     selected exposed edges are banded. Geometry can measure an edge precisely, but cannot
     know it needs ABS unless the drawing marks it."

THE TWO HALVES, AND THEY ARE DIFFERENT KINDS OF QUESTION.

    HOW LONG IS THIS EDGE      geometry, and the engine is good at it - a DXF measures to
                               the millimetre and needs nobody's opinion.

    DOES THIS EDGE TAKE ABS    a DESIGN DECISION. Nothing in the geometry says it. A tray
                               with four sides may band one, two or all four, and the only
                               place that is recorded is the drawing: a layer the drawing
                               office puts the banded edges on, a note, a callout, a hatch
                               against an edge, or an edge detail.

Conflating them is the failure this module exists to prevent, and it fails in the expensive
direction. The old behaviour measured 2*(L+W) of every faced part and offered that as "the
drawn edge metreage"; on 11908-21 that is several times Tony's 5 m, because his 5 m is the
exposed edges and the rest of the tray is not banded. A number that large, sitting in an
estimate labelled as edging, is not a small error - it is most of a material line.

SO: NO EVIDENCE, NO LENGTH. Where the drawing marks nothing, this returns no banded length
at all and says what it looked for. That is not the engine giving up; it is the difference
between a fact and an assumption, and an estimator can act on the first.

AND A PERSON WHO KNOWS THE JOB CAN ANSWER IT TOO.

James Gray, 17 September 2026: "confirmed banded metres x current GBP/metre... we can get a
current GBP/metre from an LLM or from SDI Live... so, we should be able to price in this
case." He is right, and the missing half was never the money. Tony's "5.0 m a tray" is the
SECOND fact this line needs, and it is a physical measurement of the product - the same kind
of statement as "the tube bend is not required", not a price copied off a sheet. An
estimator's confirmed extent therefore ranks ABOVE everything measured here, because it is
the one source that knows the design intent rather than inferring it.

    edging = CONFIRMED BANDED METRES x CURRENT GBP/METRE

The metres are the drawing's or the estimator's. The rate is SDI Live, the supplier
catalogue, a current quote, or evidenced research. Neither half is ever guessed from the
other, and the perimeter is not a stand-in for either.

WHAT COUNTS AS THE DRAWING SAYING SO, in the order it is trusted:

    0  AN ESTIMATOR'S CONFIRMED EXTENT, from the job's answers file. A person who has read
       the drawing and knows the product, saying how much edge is banded. Nothing measured
       overrides it.
    1  A DXF LAYER whose name means edging. Measured directly - the drawing office drew
       exactly the edges that take ABS, so their length IS the answer.
    2  A NOTE OR CALLOUT naming which edges. "ALL ROUND" is a statement, not a default,
       and it does mean the perimeter. "FRONT EDGE", "TWO LONG EDGES", "LONG EDGES BOTH
       SIDES" name a subset, and the subset is measured from the blank.
    3  A HATCH or an EDGE DETAIL against an edge - recorded as evidence that banding
       exists even where the extent cannot be resolved, so the line is raised rather than
       lost.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "EDGE_LAYER_WORDS",
    "banded_length_mm",
    "layer_means_edging",
]

# A layer name means edging when it says so. Matched on the letters, so EDGE-BAND,
# EDGE_BANDING and EDGEBAND are one name - the same tolerance the operations rulings use,
# for the same reason: a ruling that fails on an underscore did nothing.
EDGE_LAYER_WORDS = (
    "EDGEBAND", "EDGEBANDING", "EDGING", "ABSEDGE", "ABSEDGING",
    "LIPPING", "EDGETAPE", "EDGESTRIP",
)

# Words that name the WHOLE perimeter. A drawing that says this has made a decision, and
# taking it at its word is not the same as assuming it in silence.
_ALL_ROUND = ("ALL ROUND", "ALL EDGES", "ALL FOUR EDGES", "ALL SIDES", "ALLROUND",
              "EDGED ALL ROUND", "BANDED ALL ROUND")

# Words that name SOME edges. Each maps to how many of the blank's four sides it describes,
# and which dimension those sides run along.
_NAMED_EDGES = (
    (r"\b(FOUR|4)\s+(LONG\s+|SHORT\s+)?EDGES?\b", 4, None),
    (r"\b(THREE|3)\s+EDGES?\b", 3, None),
    (r"\b(TWO|2)\s+LONG\s+EDGES?\b", 2, "long"),
    (r"\b(TWO|2)\s+SHORT\s+EDGES?\b", 2, "short"),
    (r"\b(TWO|2)\s+EDGES?\b", 2, None),
    (r"\bBOTH\s+LONG\s+EDGES?\b", 2, "long"),
    (r"\bBOTH\s+SHORT\s+EDGES?\b", 2, "short"),
    (r"\bLONG\s+EDGES?\s+BOTH\s+SIDES\b", 2, "long"),
    (r"\b(ONE|1)\s+EDGE\b", 1, None),
    (r"\bFRONT\s+EDGE\b", 1, "long"),
    (r"\bTOP\s+EDGE\b", 1, "long"),
    (r"\bLEADING\s+EDGE\b", 1, "long"),
    (r"\bVISIBLE\s+EDGES?\b", None, None),      # named, extent unresolved
    (r"\bEXPOSED\s+EDGES?\b", None, None),
)

# The word has to be about banding, not about any edge. "EDGE OF PLINTH" is not a banding
# instruction; "ABS EDGE" and "EDGE BANDED" are.
_BANDING_WORDS = ("EDGE BAND", "EDGEBAND", "EDGE-BAND", "ABS EDGE", "ABS EDGING",
                  "EDGING", "LIPPING", "EDGE TAPE", "BANDED", "EDGED")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _letters(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def layer_means_edging(layer_name: Any) -> bool:
    """Does this DXF layer hold the edges that take ABS?

    Matched on the letters alone, so EDGE-BAND, EDGE_BANDING and EDGEBAND are one layer.
    """
    _l = _letters(layer_name)
    return bool(_l) and any(word in _l for word in EDGE_LAYER_WORDS)


def _text_of(part: Dict[str, Any]) -> str:
    """Every place a drawing might say the edges are banded, as one upper-case string."""
    bits: List[str] = []
    for key in ("description", "normalized_finish", "finish", "note", "notes"):
        bits.append(_clean(part.get(key)))
    for key in ("drawing_notes", "textual_notes", "notes_text", "surface_finishes",
                "callouts"):
        _v = part.get(key)
        if isinstance(_v, (list, tuple)):
            bits.extend(_clean(x) for x in _v)
        else:
            bits.append(_clean(_v))
    _ng = part.get("normalized_geometry") or {}
    _tx = _ng.get("texts") or part.get("dxf_texts") or []
    if isinstance(_tx, (list, tuple)):
        bits.extend(_clean(x) for x in _tx)
    return " ".join(b for b in bits if b).upper().replace("-", " ")


def _blank(part: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    _ng = part.get("normalized_geometry") or {}
    _l = part.get("blank_length_mm") or _ng.get("blank_length_mm")
    _w = part.get("blank_width_mm") or _ng.get("blank_width_mm")
    try:
        _l = float(_l) if _l else None
        _w = float(_w) if _w else None
    except (TypeError, ValueError):
        return None, None
    if _l and _w and _w > _l:
        _l, _w = _w, _l          # long side first, so "long edge" means something
    return _l, _w


def _named_edge_length(text: str, part: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """Length of the edges a note NAMES, from the blank. None when it names none."""
    _l, _w = _blank(part)
    if not _l or not _w:
        return None, ""
    for pattern, count, which in _NAMED_EDGES:
        if not re.search(pattern, text):
            continue
        if count is None:
            return None, (f"the note names the visible or exposed edges without saying "
                          f"which — the extent needs the drawing office or the estimator")
        if which == "long":
            return _l * count, f"{count} long edge(s) at {_l:g} mm, from the note"
        if which == "short":
            return _w * count, f"{count} short edge(s) at {_w:g} mm, from the note"
        # A count with no side named: take them long-first, which is what "2 edges" on a
        # tray almost always means and is the conservative reading of an ambiguous note.
        sides = [_l, _w, _l, _w][:count]
        return sum(sides), (f"{count} edge(s) from the note, taken as the longest {count} "
                            f"of the blank — say which if that is wrong")
    return None, ""


def banded_length_mm(part: Any) -> Dict[str, Any]:
    """How many millimetres of this part take ABS, and on whose authority.

    Returns {"mm": float|None, "basis": str, "evidence": str, "drawn_perimeter_mm": float}.

    `mm` is None whenever the drawing has not said which edges are banded. That is the
    whole point: the perimeter is always computable and is almost never the answer.
    `drawn_perimeter_mm` is reported alongside so an estimator can see the ceiling the
    banded length sits under, WITHOUT it ever being used as the length.
    """
    part = dict(part or {})
    _l, _w = _blank(part)
    perimeter = round(2.0 * ((_l or 0) + (_w or 0)), 1) if (_l and _w) else 0.0
    out: Dict[str, Any] = {"mm": None, "basis": "", "evidence": "",
                           "drawn_perimeter_mm": perimeter}

    # 0 ── A PERSON WHO KNOWS THE JOB HAS SAID HOW MUCH. Above every measurement below,
    #      because those infer the design intent and this one states it. It is a LENGTH,
    #      not a price: the rate still has to come from SDI Live, the catalogue, a quote
    #      or evidenced research, exactly as it does on any other bought-in line.
    _confirmed = part.get("_confirmed_banded_mm")
    try:
        _confirmed = float(_confirmed) if _confirmed is not None else None
    except (TypeError, ValueError):
        _confirmed = None
    if _confirmed is not None and _confirmed > 0:
        _who = _clean(part.get("_confirmed_banded_by")) or "the estimator"
        out.update(mm=round(_confirmed, 1), basis="estimator_confirmed",
                   evidence=(f"{_confirmed / 1000.0:g} m confirmed by {_who} in the job's "
                             f"answers file — a stated physical extent, which outranks "
                             f"anything inferred from the geometry"))
        return out

    # 1 ── A LAYER OF ITS OWN. The drawing office drew exactly the banded edges, so their
    #      measured length IS the answer and nothing has to be inferred from a word.
    _ng = part.get("normalized_geometry") or {}
    by_layer = (_ng.get("length_mm_by_layer") or part.get("length_mm_by_layer") or {})
    if isinstance(by_layer, dict) and by_layer:
        hits = {k: v for k, v in by_layer.items() if layer_means_edging(k)}
        if hits:
            total = 0.0
            for _v in hits.values():
                try:
                    total += float(_v)
                except (TypeError, ValueError):
                    continue
            if total > 0:
                out.update(mm=round(total, 1), basis="dxf_edge_layer",
                           evidence=(f"measured off the DXF layer(s) "
                                     f"{', '.join(sorted(hits))} — the drawing office drew "
                                     f"the banded edges, and this is their length"))
                return out

    text = _text_of(part)
    says_banding = any(w in text for w in _BANDING_WORDS)

    # 2 ── A NOTE THAT NAMES THE EDGES. "All round" is a statement, not a default.
    if says_banding and any(w in text for w in _ALL_ROUND):
        if perimeter > 0:
            out.update(mm=perimeter, basis="note_all_round",
                       evidence=("the drawing says the edges are banded ALL ROUND, so the "
                                 "perimeter is the answer because it was stated — not "
                                 "because it was assumed"))
            return out

    if says_banding:
        _mm, _how = _named_edge_length(text, part)
        if _mm:
            out.update(mm=round(_mm, 1), basis="note_named_edges", evidence=_how)
            return out
        if _how:
            out.update(basis="banding_stated_extent_unknown", evidence=_how)
            return out

    # 3 ── SOMETHING SAYS BANDING BUT NOTHING SAYS WHERE. Raised, not measured.
    if says_banding:
        out.update(basis="banding_stated_extent_unknown",
                   evidence=("the drawing mentions edging but does not say which edges — "
                             "the length is the drawing office's to state, and the "
                             "perimeter is a ceiling rather than an answer"))
        return out

    # 4 ── NOTHING SAYS SO. No length, and what was looked for is named, so the estimator
    #      can tell the difference between "no banding" and "we could not find the note".
    out.update(basis="no_evidence",
               evidence=("no edging layer, note or callout on this part. Looked for: a DXF "
                         "layer named EDGEBAND/EDGING/LIPPING, and a note naming the "
                         "banded edges. If this part is banded, the drawing does not "
                         "currently say so"))
    return out
