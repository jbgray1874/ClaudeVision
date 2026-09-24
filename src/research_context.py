"""What a bought-in line IS, when its own description is only a code.

11650-06, 23 Sep 2026: the Yiree binding screw was researched as "YIREE CODE - DWG491667" —
a supplier code, no noun, no size, no pack — and came back at £126.04 each, £2,621.63 a kit,
72% of the unit. The pack says what it is twice: the same code on sheet 2 is the row named
"Yiree Binding Screw", and its parent 11650-06-SA02 is "BINDING SCREW SPARE SET OF 4". The
market was never told either.

So before pricing, each bought-in line collects its OTHER NAMES in the pack — rows and
records sharing its supplier code (a token of letters and at least four digits: DWG491667)
whose own words differ — and the description of the assembly its BOM row sits in. Added to
the research brief only; the line's description on the sheet does not change.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

_CODE_TOKEN = re.compile(r"\b(?=[A-Z0-9]*\d{4,})(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,}\b")


def _codes(text: Any) -> Set[str]:
    return set(_CODE_TOKEN.findall(str(text or "").upper()))


def _words(text: Any) -> str:
    return " ".join(str(text or "").split())


def _is_bought_in(p: Mapping[str, Any]) -> bool:
    """Do we BUY this line? Every marker the engine writes, and one fact that needs none.

    The Yiree key reached the price lookup with none of the first four markers and was
    researched as a made part ("local sheet metal fabricator quotes", £65 each). A line with
    no material to cut and no measured geometry, that is not an assembly, is not something
    we make — nothing on the job says what we would make it from."""
    roles = [str(r).lower() for r in (p.get("page_roles") or [])]
    if (p.get("is_bought_in") or "bought_in" in roles
            or str(p.get("canonical_kind") or "").lower() == "bought_in"
            or str(p.get("part_type") or "").lower() in ("bought_in", "bought-in")
            or str(p.get("material_family") or "").lower() == "bought_in"
            or str(p.get("normalized_material") or "").upper().replace("-", "_")
            in ("BOUGHT_IN", "PURCHASED")):
        return True
    if p.get("is_assembly_parent") or p.get("is_sub_assembly") or p.get("assembly_children"):
        return False
    geom = p.get("normalized_geometry") or {}
    measured = any(geom.get(k) for k in ("blank_length_mm", "blank_width_mm", "weight_kg")) \
        or any(p.get(k) for k in ("length_mm", "width_mm", "thickness_mm", "dxf_path"))
    material = str(p.get("normalized_material") or p.get("material") or "").strip()
    return not measured and not material


def research_context(part: Mapping[str, Any], others: Iterable[Mapping[str, Any]],
                     bom_rows: Iterable[Mapping[str, Any]] = ()) -> str:
    """"also listed as '…'; part of '…'" — or "" when the pack says nothing more."""
    mine = _codes(part.get("part_number")) | _codes(part.get("description"))
    own = {_words(part.get("part_number")).upper(), _words(part.get("description")).upper()}
    names: List[str] = []
    parents: List[str] = []
    rows = [r for r in bom_rows if isinstance(r, Mapping)]
    pool = [o for o in others if isinstance(o, Mapping)] + rows
    if mine:
        for o in pool:
            if o is part or not (mine & (_codes(o.get("part_number")) | _codes(o.get("description")))):
                continue
            for field in ("part_number", "description"):
                w = _words(o.get(field))
                # A name with words in it that this line does not already carry.
                if w and w.upper() not in own and w not in names \
                        and re.search(r"[A-Za-z]{4,}", re.sub(r"[A-Z0-9]*\d[A-Z0-9]*", "", w.upper())):
                    names.append(w)
    # The assembly the line's own BOM rows sit in, by its description.
    pns = {_words(part.get("part_number")).upper()}
    parent_codes = {_words(r.get("bom_parent")).upper() for r in rows
                    if _words(r.get("part_number")).upper() in pns
                    or (mine and mine & _codes(r.get("part_number")))}
    parent_codes.discard("")
    for r in rows:
        if _words(r.get("part_number")).upper() in parent_codes:
            d = _words(r.get("description"))
            if d and d not in parents:
                parents.append(d)
    bits = []
    if names:
        bits.append("also listed as " + "; ".join(f"'{n}'" for n in names[:3]))
    if parents:
        bits.append("part of " + "; ".join(f"'{p}'" for p in parents[:2]))
    return ", ".join(bits)


def stamp_research_context(parts: List[Dict[str, Any]], summary: Optional[Mapping[str, Any]]
                           ) -> int:
    """Stamp `research_context` on every bought-in part the pack says more about."""
    da = (summary or {}).get("document_analysis") or {} if isinstance(summary, Mapping) else {}
    rows = list(da.get("bom_rows") or []) + list(da.get("bay_bom_rows") or [])
    n = 0
    for p in parts or []:
        if not isinstance(p, dict) or not _is_bought_in(p) or p.get("research_context"):
            continue
        ctx = research_context(p, parts, rows)
        if ctx:
            p["research_context"] = ctx
            n += 1
    return n
