"""Which machine cuts a sheet part, read off the sheets that draw it (D-440).

The acrylic route keeps its laser only on a laser signal and drops it otherwise — and then
charged nothing to cut the part at all. 8188-08-015, a 2,355 x 100 acrylic wave layer with a
measured DXF flat, lost its only cutting operation the moment its material was read as acrylic.
The shop's own rule names the cutter for a material (config CUT_METHOD_BY_MATERIAL: acrylic is
lasered "unless the drawing or the issued CAM calls for CNC"), and the drawing's words say when
it does: the sheet that draws the three wave layers prints both "LASERED EDGES" and "CNC IN TWO
HALVES".

So the part's own pages are read, with the standing specification removed:
  * only laser words (config CUT_METHOD_WORDS["laser"])  -> cut_method "laser"
  * only router words (config CUT_METHOD_WORDS["router"]) -> cut_method "router"
  * both -> nothing is stamped; the question is put on the part, and the shop rule prices the
    working figure (the brief's own open question: laser or CNC on the waves)
A cut method already on the part (the merge's shop-rule stamp, a person's answer) stands.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

import config
from extractor_patterns import strip_specification_legend
from source_precedence import raise_manufacturing_question

_DEFAULT_WORDS = {"laser": ("LASER", "LASERED", "LASER CUT"),
                  "router": ("CNC", "ROUTED", "ROUTER", "PIN ROUT", "PIN-ROUT")}


def _words() -> Dict[str, Sequence[str]]:
    cfg = getattr(config, "CUT_METHOD_WORDS", None)
    return dict(cfg) if isinstance(cfg, dict) and cfg else dict(_DEFAULT_WORDS)


def cut_methods_named(page_text: Any) -> Dict[str, List[str]]:
    """{method: [the words found]} on one sheet's words, legend removed."""
    text = " ".join(strip_specification_legend(str(page_text or "")).upper().split())
    out: Dict[str, List[str]] = {}
    for method, words in _words().items():
        hits = [w for w in words
                if re.search(rf"(?<![A-Z]){re.escape(str(w).upper())}(?![A-Z])", text)]
        if hits:
            out[method] = hits
    return out


def _is_made_sheet_part(part: Dict[str, Any]) -> bool:
    roles = {str(r).lower() for r in (part.get("page_roles") or [])}
    if part.get("is_bought_in") or "bought_in" in roles:
        return False
    if part.get("is_assembly_parent") or part.get("is_sub_assembly") \
            or part.get("assembly_children"):
        return False
    return bool(part.get("part_number"))


def apply_cut_method_from_sheets(parts: Sequence[Dict[str, Any]],
                                 pages: Sequence[Dict[str, Any]]) -> int:
    """Stamp cut_method on made parts whose sheets name one machine; ask where they name two.
    Returns the parts stamped or asked."""
    texts: Dict[str, str] = {}
    for pg in pages or ():
        if isinstance(pg, dict) and str(pg.get("page_number") or "").strip():
            texts[str(pg["page_number"]).strip()] = " ".join(
                str(pg.get(k) or "") for k in ("pdfplumber_text", "pypdf_text", "normalized_text"))
    n = 0
    for part in parts or ():
        if not isinstance(part, dict) or not _is_made_sheet_part(part) or part.get("cut_method"):
            continue
        drawn_on = [str(p).strip() for p in (part.get("pages") or []) if str(p).strip() in texts]
        if not drawn_on:
            continue
        named = cut_methods_named(" ".join(texts[p] for p in drawn_on))
        if not named:
            continue
        where = ", ".join(f"p.{p}" for p in drawn_on)
        if len(named) == 1:
            (method, hits), = named.items()
            part["cut_method"] = method
            part["cut_method_source"] = f"the sheet that draws it ({where}): {', '.join(hits)}"
            n += 1
            continue
        said = "; ".join(f"{m}: {', '.join(h)}" for m, h in sorted(named.items()))
        if raise_manufacturing_question(
                part,
                f"{part.get('part_number')}: the sheet that draws it ({where}) names more than "
                f"one way to cut it — {said}",
                "cut as the shop rule for its material says, as a working figure",
                "say which machine cuts this part; the cutting row follows the answer",
                "cut_method_reader.apply_cut_method_from_sheets"):
            n += 1
    return n
