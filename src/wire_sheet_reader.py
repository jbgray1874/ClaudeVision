"""A wire part's gauge and outline, read off the sheet that draws it (D-437).

8188-08-004 WIRE WORK MESH FRAME has no sheet of its own: it is drawn on the grill assembly's
sheet, with a callout "6 WIRE WORK FRAME" (the gauge, beside the part's own words) and the
frame's outline "1081 EXT." by "206 EXT.". Nothing read either, so the part was priced on the
config default gauge and the "formed" developed-length band — an ASSUMED Ø8 × 900 mm — while
the sheet in the pack stated 6 mm and the size of the thing.

What is read, and how far it is trusted:
  * the GAUGE is a figure immediately before the word WIRE whose following words are the part's
    own, within the largest gauge a callout can state (config WIRE_GAUGE_CALLOUT_MAX_MM); a figure
    after an X ("25MM X 25MM WIRE MESH") is a pitch, never a gauge; two different figures name
    none. Printed, so it enters at drawing rank.
  * the OUTLINE is exactly two figures labelled as external (config WIRE_OUTLINE_LABEL_WORDS:
    EXT., EXTERNAL, O/A, OVERALL); three or more name none.
  * a FRAME's developed length is its outline's perimeter, 2 × (a + b) — DERIVED, never written
    as the schedule length the bar formula trusts; it is recorded beside it, the costing says it
    was derived and asks for it to be confirmed, and a stated schedule length always stands.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config
from source_precedence import apply_field

_DEFAULT_LABELS = ("EXT.", "EXT", "EXTERNAL", "O/A", "OVERALL")
_DEFAULT_WIRE_WORDS = ("WIRE MESH", "WELDED WIRE", "WIRE FORM", "WIREWORK", "WIRE WORK", "WIRE ")
_DEFAULT_FRAME_WORDS = ("FRAME", "LOOP", "RING", "HOOP")


def _cfg(name: str, default: Any) -> Any:
    value = getattr(config, name, None)
    return value if value else default


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _words(text: Any) -> set:
    return {t for t in re.findall(r"[A-Z0-9]+", str(text or "").upper())
            if len(t) >= 3 and not t.isdigit()}


def wire_callouts_on_sheet(part_description: Any, page_text: Any) -> Dict[str, Any]:
    """{gauge_mm, gauge_text, outline_mm, outline_text} read for one wire part off one sheet's
    words. None where the sheet states nothing, or states two things."""
    text = " ".join(str(page_text or "").upper().split())
    out: Dict[str, Any] = {"gauge_mm": None, "gauge_text": "", "outline_mm": None,
                           "outline_text": ""}
    desc_words = _words(part_description)
    max_gauge = float(_cfg("WIRE_GAUGE_CALLOUT_MAX_MM", 12.0))
    gauges: Dict[float, str] = {}
    for m in re.finditer(r"(?<![\dA-Z.])(\d{1,2}(?:\.\d)?)\s*(?:MM)?\s+WIRE\b((?:\s+[A-Z]+){0,4})",
                         text):
        if re.search(r"X\s*$", text[max(0, m.start() - 4):m.start()]):
            continue                                      # a pitch: 25MM X 25MM WIRE MESH
        gauge = float(m.group(1))
        if not 0 < gauge <= max_gauge:
            continue
        after = {w for w in m.group(2).split() if len(w) >= 3}
        if after and not after <= desc_words:
            continue                                      # another part's callout
        gauges.setdefault(gauge, m.group(0).strip())
    if len(gauges) == 1:
        (gauge, said), = gauges.items()
        out["gauge_mm"], out["gauge_text"] = gauge, said
    labels = sorted((str(l).upper() for l in _cfg("WIRE_OUTLINE_LABEL_WORDS", _DEFAULT_LABELS)),
                    key=len, reverse=True)
    lab_re = "|".join(re.escape(l) for l in labels)
    figures: List[Tuple[float, str]] = []
    for m in re.finditer(rf"(?<![\d.])(\d{{2,5}}(?:\.\d+)?)\s*(?:MM)?\s*(?:{lab_re})(?![A-Z])",
                         text):
        figures.append((float(m.group(1)), m.group(0).strip()))
    distinct = sorted({f for f, _ in figures}, reverse=True)
    if len(distinct) == 2:
        out["outline_mm"] = (distinct[0], distinct[1])
        out["outline_text"] = " × ".join(
            next(t for f, t in figures if f == d) for d in distinct)
    return out


def _is_wire_part(part: Dict[str, Any]) -> bool:
    roles = {str(r).lower() for r in (part.get("page_roles") or [])}
    if part.get("is_bought_in") or "bought_in" in roles:
        return False
    if part.get("_bar_recognised"):
        return True
    for holder in (part.get("manufacturing_interpretation"), part.get("material_estimate")):
        if isinstance(holder, dict) and str(holder.get("stock_form") or "").lower() == "wire":
            return True
    desc = " ".join(str(part.get("description") or "").upper().split()) + " "
    return any(str(w).upper() in desc for w in _cfg("WIRE_PART_WORDS", _DEFAULT_WIRE_WORDS))


def apply_wire_callouts_to_parts(parts: Sequence[Dict[str, Any]],
                                 pages: Sequence[Dict[str, Any]]) -> int:
    """Read each wire part's gauge and outline off the sheets that draw it. A part with a stated
    schedule length is left alone. Returns the parts changed."""
    texts: Dict[str, str] = {}
    for pg in pages or ():
        if not isinstance(pg, dict):
            continue
        key = str(pg.get("page_number") or "").strip()
        if key:
            texts[key] = " ".join(str(pg.get(k) or "")
                                  for k in ("pypdf_text", "pdfplumber_text", "normalized_text"))
    frame_words = tuple(str(w).upper() for w in _cfg("WIRE_FRAME_WORDS", _DEFAULT_FRAME_WORDS))
    changed = 0
    for part in parts or ():
        if not isinstance(part, dict) or not _is_wire_part(part):
            continue
        if _num(part.get("wire_length_mm")) or _num(part.get("wire_length_derived_mm")):
            continue                                      # a schedule length stands
        drawn_on = [str(p).strip() for p in (part.get("pages") or []) if str(p).strip() in texts]
        if not drawn_on:
            continue
        got = wire_callouts_on_sheet(part.get("description"),
                                     " ".join(texts[p] for p in drawn_on))
        touched = False
        where = ", ".join(f"p.{p}" for p in drawn_on)
        if got["gauge_mm"] and not _num(part.get("wire_gauge_mm")):
            if apply_field(part, "wire_gauge_mm", got["gauge_mm"], "drawing_deterministic"):
                touched = True
                part.setdefault("review_flags", []).append(
                    f"wire gauge Ø{got['gauge_mm']:g} read off the sheet that draws it ({where}): "
                    f"the callout '{got['gauge_text']}'")
        if got["outline_mm"]:
            a, b = got["outline_mm"]
            part["wire_outline_mm"] = [a, b]
            desc = " ".join(str(part.get("description") or "").upper().split())
            if any(w in desc for w in frame_words):
                part["wire_length_derived_mm"] = round(2.0 * (a + b), 1)
                part["wire_length_derived_from"] = (
                    f"the frame outline {got['outline_text']} on {where}, as its perimeter "
                    f"2 × ({a:g} + {b:g})")
                touched = True
        if touched:
            changed += 1
    return changed
