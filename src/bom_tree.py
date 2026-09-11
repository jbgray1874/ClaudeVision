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
    found = install_context_codes(bom_rows, main_ga)
    return next(iter(found)) if len(found) == 1 else None


def install_context_codes(bom_rows: List[Dict[str, Any]],
                          main_ga: str) -> "set":
    """Every code on the main GA whose quantity is WHERE THEY GO rather than what is made.

    "exactly one structural code" was too narrow, and 12349-02 is the proof. Its GA lists
    12349-02-69-100, -101 and -08J, ALL AT THREE. Three codes, so the old guard returned
    nothing, no unit assembly was found, and every part on the job came out at three times its
    quantity — the Lid at 3, the Front Cover at 3 where the estimator has 1, powder coating
    booked six times for two parts. The comment above resolve_effective_quantities predicted the
    numbers exactly: "the screws at 12 where Tim has 4, the bumpons at 18 where Tim has 6".

    THE DISCRIMINATOR IS ALREADY IN THIS FILE, and it is the family:

      A BAY is MULTI-FAMILY by construction — 2 x 1448-GA, 2 x 3886-GA, 1 x 1455-GA. Those are
      different articles bolted into one composite thing, and multiplying is exactly right.

      AN INSTALL ARRANGEMENT is ONE family shown several times — 3 x 12349-02-69-100 and
      3 x -101 are two variants of one module, three of each on a wall. The drawing is a picture
      of where the articles go; the article is the unit.

    So: one family, every structural code on it showing the SAME quantity, and that quantity
    greater than one. All three conditions, because each one rules out a real case that must not
    be touched —

      more than one family  a genuine bay, left exactly as it was
      mixed quantities      2 x A and 1 x B is a bill for a composite, not an arrangement
      quantity of one       nothing to reinterpret

    Deliberately conservative: where this says nothing the old behaviour stands, and the
    ambiguity is reported rather than guessed at.
    """
    return _install_context(bom_rows, main_ga)[0]


def install_context_decision(bom_rows: List[Dict[str, Any]],
                             main_ga: str) -> str:
    """WHY this said what it said, in one line, whether or not it found anything.

    THE DEFECT THIS EXISTS FOR, and it cost a run. Every caller of the rule above prints only
    when the rule FIRES. So a pack where it found nothing produced no line at all, and the
    11 September runner log carries no `[bom_tree]` entry whatsoever — which was read, reasonably,
    as "that code never ran". It may equally have run and declined, and the log cannot tell the
    two apart. A correction that is invisible when it does nothing is a correction nobody can
    check, and three of its conditions can each silently rule a real pack out.

    So the decision is stated either way: which drawing was taken as the general arrangement,
    what structural codes were found on it at what quantities, and if it declined, WHICH
    condition declined it. No costing depends on this string.
    """
    return _install_context(bom_rows, main_ga)[1]


def _install_context(bom_rows: List[Dict[str, Any]],
                     main_ga: str) -> "tuple":
    """The rule and its reason, computed once so the two can never disagree."""
    codes: Dict[str, int] = {}
    for r in bom_rows:
        if str(r.get("source_pdf") or "") != main_ga:
            continue
        code = _norm(r.get("part_number"))
        if code and _family(code):          # structural rows only; a fixing is not an assembly
            codes[code] = max(codes.get(code, 0), _qty(r))
    _where = f"'{main_ga}'" if main_ga else "no drawing"
    if not codes:
        return set(), (
            f"install context: NOT recognised — {_where} was taken as the general arrangement "
            f"and carries no structural parts-list row at all (of {len(bom_rows)} row(s) read "
            f"across the pack). Quantities stand as each drawing prints them")
    _listed = ", ".join(f"{c} x{q}" for c, q in sorted(codes.items()))
    if len({_family(c) for c in codes}) != 1:
        return set(), (
            f"install context: NOT recognised — {_where} lists more than one number family "
            f"({_listed}), which is a bay: several different articles in one composite, and the "
            f"parent quantities are real multipliers. Nothing reinterpreted")
    quantities = set(codes.values())
    if len(quantities) != 1:
        return set(), (
            f"install context: NOT recognised — {_where} lists one family at MIXED quantities "
            f"({_listed}), which is a bill for a composite rather than a picture of where the "
            f"articles go. Nothing reinterpreted — if this IS an arrangement, the parts list "
            f"needs checking")
    _n = next(iter(quantities))
    if _n <= 1:
        return set(), (
            f"install context: nothing to reinterpret — {_where} lists {_listed}, one of each, "
            f"so no parent quantity is being multiplied into anything")
    return set(codes), (
        f"install context: RECOGNISED — {_where} shows {_n} arrangements of one family "
        f"({_listed}). Those quantities are where they go, not what is made, so each is divided "
        f"by {_n} to give one quoted unit")


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
    # A NAMED ASSEMBLY IS ONE CODE; A READ ARRANGEMENT CAN BE SEVERAL. When somebody says which
    # article this estimate is for, that is the one. When it is read off the GA's shape, an
    # install arrangement may show several variants of one module — 12349-02-69-100 AND -101,
    # three of each — and all of them are install context, not a bill.
    _named = _norm(unit_assembly)
    # A PERSON NAMING THE UNIT REPLACES THE TREE'S READING — it does not join it. That is
    # deliberate (see test_the_folder_wins_when_it_has_something_to_say): the named article is
    # what one of is, and the rule does not get to extend somebody's judgement to codes they did
    # not name.
    #
    # Naming a SIBLING costs nothing: the arrangement division below applies to every row on the
    # main GA, not only to the named code, so the other variants still come down to one per unit.
    # What the name CAN do is silence the division altogether — see the flag after the loop.
    _rule_units = install_context_codes(bom_rows, main_ga)
    _units = {_named} if _named else _rule_units
    multipliers: Dict[str, int] = {}
    install_context: Dict[str, int] = {}
    for r in groups.get(main_ga, []):
        fam = _family(r.get("part_number"))
        if not fam:
            continue
        _code = _norm(r.get("part_number"))
        if _code in _units and _qty(r) != 1:
            install_context[_code] = _qty(r)
            multipliers[fam] = 1
            continue
        multipliers.setdefault(fam, _qty(r))

    # per-source-drawing multiplier that bought-in (non-numeric) rows inherit
    boughtin_inherit = _dominant_family_multiplier_by_source(groups, multipliers, main_ga)

    effective: Dict[str, int] = {}
    flags: List[Dict[str, Any]] = []

    # WHICH CODES ARE ACTUALLY ASSEMBLY NODES. "its family has a sub-drawing" was a proxy for
    # it, and on a SINGLE-FAMILY job the proxy catches everything: 12349-02's parts are all
    # family "12349", so 12349-02-69-08J — a leaf, an MDF packer, listed only on the GA — was
    # skipped as though its children lived on another sheet. Nothing ever gave it an effective
    # quantity, so it kept the GA's 3 and Tim asked "where did 3 per unit come from for 6mm
    # MDF(Packer)".
    #
    # A node is an assembly when other rows are grouped UNDER it. That is the fact, and it is
    # sitting in `groups` already.
    # AN ASSEMBLY NODE IS ONE OF THREE THINGS, and none of them is "its family has a
    # sub-drawing" — that proxy caught every leaf on a single-family job, which is how the MDF
    # packer kept the GA's 3.
    #
    #   it has children grouped under it          (a real parent in this tree)
    #   its own row lives on a sub-drawing too    (the GA row is a reference to that sheet)
    #   somebody NAMED it as the unit being quoted
    #
    # Anything else on the main GA is a leaf listed directly there, and gets a quantity.
    parents = {_norm(src) for src in groups}
    codes_on_subs = {_norm(r.get("part_number"))
                     for src, rows_ in groups.items() if src != main_ga for r in rows_}
    assembly_nodes = parents | codes_on_subs | ({_named} if _named else set())
    # How many arrangements the GA is showing. Every install-context code carries the same
    # quantity by construction — that is one of the three conditions — so there is one number.
    _install_n = next(iter(set(install_context.values())), 1) if install_context else 1
    # A ROW WITH NO PART NUMBER IS NOT A PART, AND IT MUST NOT BECOME A KEY. A nameless row —
    # a wrapped line, a notes line, a table artefact — normalises to "", and every branch below
    # would then write effective[""]. Any later record whose own part number is also missing
    # matches that same empty key and takes a quantity belonging to nothing: the log line
    # `None qty 4 KEPT (GA tree said 1)`, which has appeared on several jobs. Recorded as a
    # flagged unreadable row rather than given a quantity under a name it does not have.
    _nameless = 0
    for r in groups.get(main_ga, []):
        code = _norm(r.get("part_number"))
        if not code:
            _nameless += 1
            continue
        if code in assembly_nodes:
            continue  # its leaves come from its own group, or it is the unit itself
        # EVERYTHING ON AN ARRANGEMENT IS ARRANGEMENTS' WORTH, bought-in rows included. The GA
        # showing three of every structural code means three arrangements, and the eighteen wood
        # screws printed beside them are eighteen for three — six each. Tim's note says the
        # fastener quantities are wrong as well as unpriced, and this is why.
        #
        # Divided rather than set to 1, so a GA showing 6 of a part across 3 arrangements gives
        # 2 and not 1. Only where it divides evenly: 5 across 3 is not a per-arrangement
        # quantity and guessing one would be worse than leaving it alone.
        #
        # The older rule — "bought-in rows on the main GA are per-bay items, keep own qty" — is
        # untouched on a bay, because a bay has no install context at all.
        if _install_n > 1 and _qty(r) % _install_n == 0:
            effective[code] = _qty(r) // _install_n
            continue
        if _install_n > 1:
            flags.append({
                "severity": "warning", "code": code,
                "detail": (f"'{code}' shows {_qty(r)} on a general arrangement of {_install_n} "
                           f"— that does not divide evenly, so it was left at {_qty(r)}. "
                           f"Confirm the per-unit quantity."),
            })
        effective[code] = _qty(r)

    # leaves from each sub-assembly drawing: own qty x parent's top-level multiplier
    for src, rows in groups.items():
        if src == main_ga:
            continue
        for r in rows:
            code = _norm(r.get("part_number"))
            if not code:               # see the nameless-row note on the main-GA loop above
                _nameless += 1
                continue
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

    # THE ONE CASE WHERE NAMING THE UNIT COSTS SOMETHING. The named code replaces the rule's
    # reading, and the arrangement division is driven by the quantity the named code shows on the
    # general arrangement. So if the name is for something the GA does NOT show more than one of
    # — an assembly off the arrangement entirely, or a code read differently from the name — the
    # division does not happen at all, even though the GA's own shape says it should. Every part
    # then keeps the parent multiple, which is the whole ×3 defect back again, and silently.
    if _named and not install_context and _rule_units:
        flags.append({
            "severity": "warning",
            "code": _named,
            "detail": (f"'{_named}' was named as the unit being quoted, but the general "
                       f"arrangement does not show more than one of it, so no arrangement "
                       f"division was applied. The GA's own shape reads "
                       f"{', '.join(sorted(_rule_units))} as arrangement quantities — if this IS "
                       f"an install arrangement, every quantity here is still multiplied by it. "
                       f"Check the unit name against the codes on the drawing"),
        })
    if _nameless:
        flags.append({
            "severity": "warning",
            "code": "",
            "detail": (f"{_nameless} parts-list row(s) carry no part number and were given no "
                       f"effective quantity — a nameless row is an unreadable read, not a part, "
                       f"and a quantity filed under no name is one any other nameless record "
                       f"can pick up. Check these rows on the drawing"),
        })
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
            "install_context": install_context, "flags": flags,
            # STATED WHETHER OR NOT IT FIRED. See install_context_decision: a rule that prints
            # only when it acts leaves a declined pack indistinguishable from one where the code
            # never ran, and that is how a log with no [bom_tree] line at all was read.
            "install_context_decision": install_context_decision(bom_rows, main_ga)}


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
