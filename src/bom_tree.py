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


def unit_assembly_from_label(label: Any, bom_rows: List[Dict[str, Any]]) -> Optional[str]:
    """The assembly this estimate is FOR, if the job's own name says so.

    THE ESTIMATOR POINTED AT A FOLDER, AND THE FOLDER IS THE ANSWER. 12349-02's job folder is
    named for 12349-02-69-100 and Tim's sheet costs one of them; the GA that happens to show
    three of them hanging on a wall is where they go, not what is being made.

    Matched against codes the tree already holds rather than parsed out of the name, so a
    folder called something else simply yields None and nothing changes. Longest match wins:
    "12349-02-69-100" and "12349" can both appear in one label and only one of them is an
    assembly somebody builds.
    """
    # A FOLDER IS NOT SPELLED THE WAY A PART NUMBER IS. The assembly is 12349-02-69-100;
    # the folder on the share is "12349-02-GravityFeeder" or "12349-02-69-100 GRAVITY FEEDER
    # MODULES", and Tim's own file for it is "123490269100__GRAVITY_FEEDER_MODULES_REV_A.xls"
    # with no separators at all. Comparing with the hyphens intact means the rule fires on one
    # of those spellings and silently does nothing on the other two — and doing nothing here
    # leaves every part at three times its quantity, which is the failure it exists to stop.
    #
    # So both sides are reduced to letters and digits. That is not a loosening: the codes are
    # still matched whole and the longest still wins, so "12349" cannot beat "12349-02-69-100"
    # for a folder that names the assembly.
    def _flat(t: Any) -> str:
        return re.sub(r"[^A-Z0-9]+", "", str(t or "").upper())

    hay = _flat(label)
    if not hay:
        return None
    best_code, best_len = "", 0
    for r in bom_rows:
        code = _norm(r.get("part_number"))
        flat = _flat(code)
        # Four characters is the shortest thing worth calling a match; below that a bare
        # family number matches half the folders on the share.
        if len(flat) >= 4 and flat in hay and len(flat) > best_len:
            best_code, best_len = code, len(flat)
    return best_code or None


def unit_assembly_from_the_tree(bom_rows: List[Dict[str, Any]],
                                main_ga: str) -> Optional[str]:
    """The assembly this estimate is for, read off the SHAPE of the general arrangement.

    THE FOLDER NAME IS NOT ALWAYS THERE. 12349-02's pack lives in "...\\fanatics\\12349-02",
    which does not contain 12349-02-69-100, so the rule that reads the folder finds nothing
    and every part stays at three times its quantity. A fix that only works when somebody
    named a folder helpfully is not a fix.

    The GA's own shape says it. Two drawings, two different things:

      * A BAY lists SEVERAL assemblies — 2 x 1448-GA, 2 x 3886-GA, 1 x 1455-GA — and the unit
        is all of them together. Multiplying is exactly right there.
      * An INSTALL ARRANGEMENT lists ONE assembly, several times: 3 x 12349-02-69-100 on a
        wall. That drawing is not a bill for a composite article; it is a picture of where the
        articles go, and the article is the unit.

    So: exactly one structural code on the main GA, showing more than one of itself, and that
    code is the unit. Two or more and this says nothing, which leaves every bay job exactly as
    it was. Bought-in rows are ignored — a GA carrying one assembly and a bag of screws is
    still a GA carrying one assembly.
    """
    codes: Dict[str, int] = {}
    for r in bom_rows:
        if str(r.get("source_pdf") or "") != main_ga:
            continue
        code = _norm(r.get("part_number"))
        if code and _family(code):          # structural rows only; a fixing is not an assembly
            codes[code] = max(codes.get(code, 0), _qty(r))
    if len(codes) != 1:
        return None
    only, qty = next(iter(codes.items()))
    return only if qty > 1 else None


def resolve_effective_quantities(
    bom_rows: List[Dict[str, Any]],
    main_ga: Optional[str] = None,
    unit_assembly: Optional[str] = None,
) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in bom_rows:
        src = str(r.get("source_pdf") or "")
        if src:                      # rows without a source drawing don't participate in the tree
            groups[src].append(r)

    # the main GA is the drawing that references the most distinct families
    # (it lists every sub-assembly); override is honoured when given.
    if main_ga is None or main_ga not in groups:
        # DISTINCT NUMBER FAMILIES, AND A BOUGHT-IN IS NOT ONE. _family() returns "" for
        # FIXING/PLAS/POWDER rows, and counting that empty string made a sub-assembly drawing
        # carrying one screw look like it referenced two families — beating the real GA, which
        # references one family and every part in it. The whole tree then hangs off the wrong
        # drawing, and on 12349-02 that put the GA's own row into `effective` as a part.
        def _fam_count(s: str) -> int:
            return len({f for f in (_family(r.get("part_number")) for r in groups[s]) if f})
        main_ga = max(groups, key=_fam_count) if groups else ""

    sub_families = {
        _family(r.get("part_number"))
        for src, rows in groups.items() if src != main_ga
        for r in rows
    }
    sub_families.discard("")

    # top-level multiplier per family, from the main GA rows
    #
    # ONE OF THE THING YOU RAN, NOT THREE OF IT BECAUSE THAT IS HOW MANY GO ON A WALL.
    #
    # _family() is the leading number, so a whole job is usually ONE family: 12349-02-69-03M,
    # -04M, -01A and -08J are all family "12349". The GA row "12349-02-69-100 x3" therefore
    # set the multiplier for every part on the job, and every fabricated line came out at
    # qty 3 — the steel at 3 x GBP 5.74, the screws at 12 where Tim has 4, the bumpons at 18
    # where Tim has 6.
    #
    # The GA is not wrong. Three modules DO hang on that wall. It is the wrong question: the
    # estimate is for one 12349-02-69-100, which is what the estimator pointed at and what
    # Tim sold, and three-per-wall is where they go rather than what is being made.
    #
    # So when the job names the assembly it is for, that assembly's own GA quantity is INSTALL
    # CONTEXT and its multiplier is one. Everything below it still multiplies normally — a
    # sub-assembly used twice inside the module is still needed twice. Recorded as a flag,
    # because a quantity that silently became a third of what it was is exactly as hard to
    # trust as one that silently tripled.
    # The folder name if it gave one, otherwise the GA's own shape. Named first because a
    # folder that spells the assembly out is a person saying which article this is, and that
    # beats reading it off a drawing.
    _unit = _norm(unit_assembly) or _norm(unit_assembly_from_the_tree(bom_rows, main_ga))
    multipliers: Dict[str, int] = {}
    install_context: Dict[str, int] = {}
    for r in groups.get(main_ga, []):
        fam = _family(r.get("part_number"))
        if not fam:
            continue
        if _unit and _norm(r.get("part_number")) == _unit and _qty(r) != 1:
            install_context[_unit] = _qty(r)
            multipliers[fam] = 1
            continue
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

    for _code, _n in install_context.items():
        flags.append({
            "severity": "info",
            "code": _code,
            "detail": (f"the GA shows {_n} x {_code} — that is where they go, not what is "
                       f"being made. This estimate costs ONE {_code}, so the GA quantity is "
                       f"install context and has not multiplied the parts below it. If the "
                       f"unit being quoted is the whole set of {_n}, this sheet is a third of "
                       f"it." if _n == 3 else
                       f"the GA shows {_n} x {_code} — install context, not the unit. This "
                       f"estimate costs ONE {_code} and the GA quantity has not multiplied "
                       f"the parts below it."),
        })
    return {"main_ga": main_ga, "effective": effective, "multipliers": multipliers,
            "install_context": install_context, "flags": flags}


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
