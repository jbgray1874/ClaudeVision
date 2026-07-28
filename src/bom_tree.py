"""
bom_tree.py  —  resolve effective per-bay quantities across the assembly tree.

The run's bom_rows carry two levels that never get combined:
  * top-level GA rows from the main drawing      (1448-GA x2, 3886-GA x2, ...)
  * child rows from each sub-assembly drawing     (1448-01 x1, 3886-01 x1, ...)

A leaf part's true per-bay quantity is the product down its path:
  1448-01 = own 1  x  parent 1448-GA 2  = 2.

This walker groups rows by source drawing, identifies the top GA (the drawing
that references the others), reads each family's top-level multiplier, and
multiplies it into that family's leaves. Families whose top-level row is missing
(e.g. 1455 when row 7 was dropped) are reported as ungoverned rather than
silently defaulting — they keep qty as-is but are flagged for confirmation.

    resolve_effective_quantities(bom_rows, main_ga=None)
        -> {"effective": {part_number: qty}, "multipliers": {...}, "flags": [...]}

BOUGHT-IN INHERITANCE (added):
  Bought-in rows (FIXING5, VINYL76, ...) have non-numeric part codes, so _family()
  returns "" and they were previously invisible to the tree — passing through at
  their raw per-sub-assembly quantity (e.g. FIXING125 stuck at 2 instead of 4).
  A bought-in fitted to a sub-assembly is needed once per instance of that
  assembly, so it must inherit the SAME multiplier as the numeric parts on its own
  source drawing. FIXING125 sits on the 3886 lower-leg drawing (x2 per bay) ->
  it inherits x2 -> 2 x 2 = 4. A bought-in on a x1 drawing inherits x1. This keys
  purely off drawing membership + the multiplier the tree already computes, so it
  generalises to any bought-in on any job — nothing part-number-specific.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from collections import defaultdict
import re

from source_precedence import apply_field

_ASSEMBLY_SUFFIX = re.compile(r"-(GA|WA\d*|WELD(?:MENT)?)\b", re.IGNORECASE)


def _norm(code: Any) -> str:
    return re.sub(r"\s+", "", str(code or "")).upper()


def _family(code: str) -> str:
    """Number family prefix: '1448-01' -> '1448', '1455-C-101' -> '1455'."""
    m = re.match(r"(\d{3,})", _norm(code))
    return m.group(1) if m else ""


def _qty(row: Dict[str, Any]) -> int:
    for k in ("quantity", "qty", "qty_per_bay"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    return 1


def _dominant_family_multiplier_by_source(
    groups: Dict[str, List[Dict[str, Any]]],
    multipliers: Dict[str, int],
    main_ga: str,
) -> Dict[str, int]:
    """For each source drawing, find the numeric family that dominates it (the most
    common non-empty family among its rows) and return that family's multiplier.
    This is what a bought-in row on that drawing inherits.

    Only sub-assembly drawings are considered (never the main GA — a bought-in
    listed directly on the main GA is a per-bay item and keeps its own qty).
    A drawing whose dominant family has no governing multiplier yields no entry,
    so the caller can flag those bought-ins rather than guess.
    """
    result: Dict[str, int] = {}
    for src, rows in groups.items():
        if src == main_ga:
            continue
        fam_counts: Dict[str, int] = defaultdict(int)
        for r in rows:
            fam = _family(r.get("part_number"))
            if fam:
                fam_counts[fam] += 1
        if not fam_counts:
            continue
        dominant = max(fam_counts, key=lambda f: fam_counts[f])
        mult = multipliers.get(dominant)
        if mult is not None:
            result[src] = mult
    return result


def resolve_effective_quantities(
    bom_rows: List[Dict[str, Any]],
    main_ga: Optional[str] = None,
) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in bom_rows:
        src = str(r.get("source_pdf") or "")
        if src:                      # rows without a source drawing don't participate in the tree
            groups[src].append(r)

    # the main GA is the drawing that references the most distinct families
    # (it lists every sub-assembly); override is honoured when given.
    if main_ga is None or main_ga not in groups:
        main_ga = max(groups, key=lambda s: len({_family(r.get("part_number")) for r in groups[s]})) if groups else ""

    sub_families = {
        _family(r.get("part_number"))
        for src, rows in groups.items() if src != main_ga
        for r in rows
    }
    sub_families.discard("")

    # top-level multiplier per family, from the main GA rows
    multipliers: Dict[str, int] = {}
    for r in groups.get(main_ga, []):
        fam = _family(r.get("part_number"))
        if fam:
            multipliers[fam] = _qty(r)

    # per-source-drawing multiplier that bought-in (non-numeric) rows inherit
    boughtin_inherit = _dominant_family_multiplier_by_source(groups, multipliers, main_ga)

    effective: Dict[str, int] = {}
    flags: List[Dict[str, Any]] = []

    # leaves listed directly on the main GA (families with no sub-assembly drawing)
    for r in groups.get(main_ga, []):
        code = _norm(r.get("part_number"))
        fam = _family(code)
        if fam in sub_families:
            continue  # this is an assembly node; its leaves come from the sub drawing
        # NOTE: bought-in rows on the main GA (fam == "") are per-bay items -> keep own qty.
        effective[code] = _qty(r)

    # leaves from each sub-assembly drawing: own qty x parent's top-level multiplier
    for src, rows in groups.items():
        if src == main_ga:
            continue
        for r in rows:
            code = _norm(r.get("part_number"))
            fam = _family(code)

            if fam:
                # numeric fabricated part: multiply by its own family's top-level multiplier
                parent = multipliers.get(fam)
                if parent is None:
                    # no governing top-level row (e.g. the dropped 1455-C-GA): keep own qty, flag it
                    effective[code] = _qty(r)
                    flags.append({
                        "severity": "warning",
                        "code": code,
                        "detail": (
                            f"'{code}' (from {src}) has no governing top-level GA row for family "
                            f"{fam or '?'} \u2014 effective qty left at {_qty(r)}; the parent line was "
                            f"likely dropped on the main GA, confirm the per-bay quantity"
                        ),
                    })
                else:
                    effective[code] = _qty(r) * parent
            else:
                # BOUGHT-IN row (non-numeric code): inherit the multiplier of the numeric
                # family that dominates its own source drawing.
                parent = boughtin_inherit.get(src)
                if parent is None:
                    # source drawing has no governed numeric family to inherit from: keep own qty, flag
                    effective[code] = _qty(r)
                    flags.append({
                        "severity": "warning",
                        "code": code,
                        "detail": (
                            f"bought-in '{code}' (from {src}) has no governed numeric family on its "
                            f"source drawing to inherit a per-bay multiplier from \u2014 effective qty "
                            f"left at {_qty(r)}; confirm whether it should be multiplied"
                        ),
                    })
                else:
                    effective[code] = _qty(r) * parent

    return {"main_ga": main_ga, "effective": effective, "multipliers": multipliers, "flags": flags}


# --------------------------------------------------------------------------
# Pipeline integration helpers
# --------------------------------------------------------------------------
def merge_table_bom_rows(bom_rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Recover BOM rows the text/regex path dropped (e.g. the wrapped 1455-C-GA
    header line) using the structural table rows attached per page. Adds only
    drawing-reference rows whose code is not already present — never duplicates."""
    have = {_norm(r.get("part_number")) for r in bom_rows if _norm(r.get("part_number"))}
    out = list(bom_rows)
    for pg in summary.get("pages") or []:
        for tr in pg.get("bom_table_rows") or []:
            if tr.get("kind") != "drawing_ref":
                continue  # commodities are handled by the bought-in path, not here
            code = _norm(tr.get("part_number"))
            if not code or code in have:
                continue
            out.append({
                "item_number": tr.get("item_number"),
                "part_number": code,
                "description": tr.get("description"),
                "quantity": _qty(tr),
                "source_pdf": tr.get("source_pdf"),
                "source": "bom_table_recovered",
            })
            have.add(code)
    return out


def apply_effective_quantities(bom_rows: List[Dict[str, Any]]):
    """Replace each leaf's per-bay quantity with its effective (tree-multiplied)
    quantity, and DROP top-level assembly rows whose children are present — so the
    children carry the full quantity and the costing rollup can't double-count.
    Returns (transformed_rows, flags)."""
    res = resolve_effective_quantities(bom_rows)
    eff, main_ga = res["effective"], res["main_ga"]

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in bom_rows:
        groups[str(r.get("source_pdf") or "")].append(r)
    sub_families = {
        _family(r.get("part_number"))
        for src, rows in groups.items() if src != main_ga for r in rows
    }
    sub_families.discard("")

    out: List[Dict[str, Any]] = []
    for r in bom_rows:
        code = _norm(r.get("part_number"))
        fam = _family(code)
        src = str(r.get("source_pdf") or "")
        # drop a top-level assembly parent whose family has captured children
        if src == main_ga and fam in sub_families:
            continue
        nr = dict(r)
        if code in eff:
            # Through the resolver. This is rank 60 — a reading of a printed table, which is
            # a real observation but a weaker one than the assembly the shop builds from.
            # Writing straight to the record meant this pass, which runs late, silently
            # replaced quantities that had come from the SolidWorks BOM.
            if apply_field(nr, "quantity", eff[code], "bom_tree"):
                nr["effective_qty_source"] = "bom_tree"
        out.append(nr)
    return out, res["flags"]
