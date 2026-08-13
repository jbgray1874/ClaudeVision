"""
invariants.py — the checks every job must pass before anything describes it.

WHY THIS EXISTS. Each defect this repository has shipped had the same shape: a number was
produced, nothing compared it to anything, and it reached a spreadsheet or a client quote
looking exactly like a number that had been checked. The material rows summed to GBP 9.64
against the sheet's own GBP 10.07 and nothing noticed. Labour rows joined to the wrong parts
and nothing noticed. A quote promised powder coating on a lacquered timber crate and nothing
noticed. In every case the engine had both figures in front of it.

These are the assertions that make a wrong answer LOUD. They run on the finished summary,
after Excel has calculated and the read-back has stamped, before any report, quote or ERP
export is produced. A violation does not silently correct anything — correcting a number
nobody has checked is how the original defects got in. It marks the job so that whatever
consumes it can say "provisional" instead of quoting a figure it cannot stand behind.

None of these checks name a job, a part number or a customer. They compare the engine's own
outputs to each other, so a drawing nobody has seen yet is held to the same standard.

    from invariants import check_job
    result = check_job(summary)        # -> {"ok": bool, "violations": [...], ...}
                                       #    also written to summary["invariants"]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# The one place that decides what a price source IS. Shared with the estimator and the
# pricing service so a writer and a checker cannot reach different verdicts about the same
# source — which is how an AI market estimate came to be stamped, and read, as "external".
# Dependency-free by design: no config, no database, no connectors.
import re
import price_provenance

SCHEMA = "invariants.v1"

# The contract versions this module knows how to read. A structure carrying a different
# version is not silently reinterpreted: the shape may have moved under us, and a check that
# reads the wrong shape reports a pass it did not verify.
KNOWN_SCHEMAS = {
    "final_estimate": {"final_estimate.v1", "final_estimate.v2"},
    "workbook_labour": {
        "workbook_labour_rows.v1", "workbook_labour_rows.v2",
        "workbook_labour_rows.v3",
    },
}

# Money agrees to the penny. The only legitimate slack is Excel's own per-row rounding, so
# the allowance scales with the NUMBER OF ROWS, not the size of the estimate: a proportional
# tolerance lets a GBP 50 discrepancy pass on a GBP 10,000 job, which is a real error hiding
# inside a percentage. Each row can round by at most half a penny.
_ABS_TOL_GBP = 0.01
_PER_ROW_TOL_GBP = 0.005

BLOCKING = "blocking"      # the job must not be presented as a firm price
WARNING = "warning"        # flag it, but the number still stands
UNVERIFIED = "unverified"  # the check could not run — it has proved NOTHING

# A check that finds nothing because it had nothing to look at is not a pass. The read-back
# can fail (Excel COM dies, a workbook will not open), leaving no final_estimate at all — and
# every reconciliation check then returned "no violations", which reads on a console and in a
# JSON exactly like a job that reconciled. FAIL CLOSED: an unevaluated check is recorded as
# UNVERIFIED, and a job with any unverified check cannot be released as a firm price.


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").replace("£", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _money_agrees(a: float, b: float, row_count: int = 0) -> bool:
    return abs(a - b) <= _ABS_TOL_GBP + _PER_ROW_TOL_GBP * max(0, int(row_count))


def _node(summary: Any, key: str) -> Dict[str, Any]:
    """Read a top-level contract from wherever it was stamped. Some writers put these on the
    summary root and some inside estimate_summary; a check that looks in one place only
    reports a clean pass on a job it never examined."""
    if not isinstance(summary, dict):
        return {}
    n = summary.get(key)
    if not isinstance(n, dict):
        es = summary.get("estimate_summary")
        n = es.get(key) if isinstance(es, dict) else None
    return n if isinstance(n, dict) else {}


def _parts(summary: Any) -> List[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return []
    # THESE ARE THE RAW PART RECORDS, AND DELIBERATELY SO. Every caller of this helper is a
    # geometry or attribution check: it reads geometry_source, blank_length_mm,
    # flat_arbitration, dxf_geometry_rejected. Those fields exist on the top-level `parts`
    # list and NOT on estimate_summary.part_estimates, which carries costed rows.
    #
    # Which is why no price check may use this helper. The reproducibility check did, found
    # geometry records with no money in them, and reported CLEAR on a job with three AI-priced
    # bought-ins. Reordering this to prefer part_estimates would have fixed that one check by
    # silently blinding four others — the same trade in the other direction. Price checks walk
    # the whole job for price stamps instead; see check_prices_are_reproducible.
    for holder in (summary, summary.get("estimate_summary") or {}):
        if isinstance(holder, dict):
            for key in ("part_estimates", "parts"):
                v = holder.get(key)
                if isinstance(v, list):
                    return [p for p in v if isinstance(p, dict)]
    return []


def _violation(code: str, severity: str, message: str, **detail) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "detail": detail or {}}


def _unevaluated(code: str, reason: str, **detail) -> List[Dict[str, Any]]:
    """The check could not run. This is NOT a pass and must never read as one."""
    return [_violation(f"{code}_not_evaluated", UNVERIFIED,
                       f"{reason} This check has verified nothing.", **detail)]


# ── contracts ────────────────────────────────────────────────────────────────────────
def check_schemas(summary: Any) -> List[Dict[str, Any]]:
    """A structure whose version we do not recognise must not be read as if we did."""
    out = []
    for key, known in KNOWN_SCHEMAS.items():
        node = _node(summary, key)
        if not node:
            out.extend(_unevaluated(f"{key}_schema",
                                    f"This job carries no {key} contract at all."))
            continue
        schema = str(node.get("schema") or "")
        if schema not in known:
            out.append(_violation(
                "unknown_schema", BLOCKING,
                f"{key} carries schema '{schema or 'none'}', which this build does not know "
                f"how to read (expected one of {sorted(known)}). Its shape may have changed; "
                f"reading it anyway would report checks that were never actually performed.",
                contract=key, found=schema))
    return out


# ── 1 & 2. rows reconcile to totals ──────────────────────────────────────────────────
def _check_rows_sum_to_total(fe: Dict[str, Any], rows_key: str, total_key: str,
                             label: str) -> List[Dict[str, Any]]:
    if not fe:
        return _unevaluated(f"{label}_rows_reconcile",
                            "No final_estimate on this job, so nothing was read back from the "
                            "calculated sheet and no total could be reconciled.")
    rows = fe.get(rows_key)
    totals = fe.get("totals") or {}
    total = _num(totals.get(total_key))
    if not isinstance(rows, list):
        return _unevaluated(f"{label}_rows_reconcile",
                            f"final_estimate carries no {rows_key} to reconcile.")
    if total is None:
        return _unevaluated(f"{label}_rows_reconcile",
                            f"final_estimate carries no {total_key}, so the {label} rows have "
                            f"nothing to be checked against.")
    # An Excel error reads back as None, never as zero. Summing it as zero would manufacture
    # agreement out of missing data — the one thing these checks exist to prevent.
    missing = [r for r in rows if isinstance(r, dict) and _num(r.get("total_value_gbp")) is None]
    summed = sum(_num(r.get("total_value_gbp")) or 0.0
                 for r in rows if isinstance(r, dict))
    if missing:
        return [_violation(
            f"{label}_rows_incomplete", BLOCKING,
            f"{len(missing)} {label} row(s) read back with no value — an Excel error carries "
            f"through as null. The rows cannot be reconciled to the GBP {total:.2f} total "
            f"because part of the sheet did not calculate.",
            rows_missing_value=len(missing), total_gbp=round(total, 4))]
    if not _money_agrees(summed, total, len(rows)):
        return [_violation(
            f"{label}_rows_do_not_sum_to_total", BLOCKING,
            f"{label} rows sum to GBP {summed:.2f} but the sheet's own {label} total is "
            f"GBP {total:.2f} (out by GBP {abs(summed - total):.2f}). A snapshot that will "
            f"not reconcile to its own total cannot be exported or quoted from.",
            rows_sum_gbp=round(summed, 4), total_gbp=round(total, 4),
            difference_gbp=round(summed - total, 4), row_count=len(rows))]
    return []


def check_material_rows_reconcile(summary: Any) -> List[Dict[str, Any]]:
    return _check_rows_sum_to_total(_node(summary, "final_estimate"),
                                    "material_rows", "material_gbp", "material")


def check_labour_rows_reconcile(summary: Any) -> List[Dict[str, Any]]:
    return _check_rows_sum_to_total(_node(summary, "final_estimate"),
                                    "labour_rows", "labour_gbp", "labour")


# ── 3. every priced row has exactly one identity ─────────────────────────────────────
def check_totals_reconcile_to_the_unit_price(summary: Any) -> List[Dict[str, Any]]:
    """The unit price must be the sum of its parts.

    The existing checks reconcile material ROWS to the material total and labour ROWS to the
    labour total, and both passed on 12120 — while the two subtotals summed to GBP 25.73
    against a Total Unit Cost Price of GBP 27.67. GBP 1.94, seven per cent of the price,
    belonging to nothing on the sheet. Every row reconciled to its own subtotal and nobody
    ever asked whether the subtotals reconciled to the price.

    If the template legitimately adds something between the subtotals and the unit price —
    downtime, consumables, an overhead percentage — then that is a component of the price and
    belongs in the contract as its own figure. It does not belong in the gap between two
    numbers that are supposed to add up.
    """
    fe = _node(summary, "final_estimate")
    if not fe:
        return _unevaluated("totals_reconcile",
                            "No final_estimate on this job, so the unit price could not be "
                            "reconciled against its components.")
    totals = fe.get("totals") or {}
    material = _num(totals.get("material_gbp"))
    labour = _num(totals.get("labour_gbp"))
    unit = _num(totals.get("unit_gbp"))
    if material is None or labour is None or unit is None:
        return _unevaluated("totals_reconcile",
                            "final_estimate does not carry all three of material, labour and "
                            "unit, so they could not be reconciled.")
    # Anything the template adds on purpose is declared here and accounted for by name.
    _declared = _num(totals.get("other_gbp")) or 0.0
    _sum = material + labour + _declared
    if _money_agrees(_sum, unit, 3):
        return []
    return [_violation(
        "unit_price_does_not_equal_its_parts", BLOCKING,
        f"Material GBP {material:.2f} + labour GBP {labour:.2f}"
        + (f" + declared other GBP {_declared:.2f}" if _declared else "")
        + f" = GBP {_sum:.2f}, but the sheet's Total Unit Cost Price is GBP {unit:.2f} — "
          f"GBP {abs(unit - _sum):.2f} ({abs(unit - _sum) / unit * 100:.1f}% of the price) "
          f"belongs to nothing on the sheet. Either a cost component is not being read back, "
          f"or the template adds something between the subtotals and the price that is not "
          f"declared as a figure of its own.",
        material_gbp=round(material, 4), labour_gbp=round(labour, 4),
        declared_other_gbp=round(_declared, 4), unit_gbp=round(unit, 4),
        unexplained_gbp=round(unit - _sum, 4))]


def check_priced_rows_join_once(summary: Any) -> List[Dict[str, Any]]:
    """A calculated row knows what a line cost but not which parts produced it; the accepted
    row knows exactly that but nothing about cost. They are joined on the sheet row they
    share. If a calculated row joins to none, its cost is reported against no parts; if it
    joins to more than one, the same cost is reported against several. Both were possible
    while rows were matched by department name."""
    fe = _node(summary, "final_estimate")
    wl = _node(summary, "workbook_labour")
    rows = fe.get("labour_rows")
    accepted = wl.get("rows")
    if not isinstance(rows, list):
        return _unevaluated("priced_row_identity",
                            "No calculated labour rows were read back, so no priced row could "
                            "be joined to the route that produced it.")
    if not isinstance(accepted, list) or not accepted:
        return _unevaluated("priced_row_identity",
                            "No accepted route rows were recorded by wb_populate, so the "
                            "calculated costs have nothing to be joined to.")

    counts: Dict[Any, int] = {}
    for a in accepted:
        if isinstance(a, dict) and a.get("workbook_row") is not None:
            counts[int(_num(a.get("workbook_row")) or 0)] = \
                counts.get(int(_num(a.get("workbook_row")) or 0), 0) + 1

    unjoined, duplicated = [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (_num(r.get("total_value_gbp")) or 0.0) <= 0:
            continue                       # not part of the priced job
        key = _num(r.get("workbook_row"))
        n = counts.get(int(key), 0) if key is not None else 0
        if n == 0:
            unjoined.append({"workbook_row": r.get("workbook_row"),
                             "operation": r.get("operation"),
                             "total_value_gbp": r.get("total_value_gbp")})
        elif n > 1:
            duplicated.append({"workbook_row": r.get("workbook_row"), "matches": n})

    out = []
    if unjoined:
        out.append(_violation(
            "priced_row_without_identity", BLOCKING,
            f"{len(unjoined)} priced labour row(s) join to no accepted route row, so their "
            f"cost belongs to no known parts or operations. Anything describing this job "
            f"would have to guess which work was charged.",
            rows=unjoined[:10], count=len(unjoined)))
    if duplicated:
        out.append(_violation(
            "priced_row_with_ambiguous_identity", BLOCKING,
            f"{len(duplicated)} priced labour row(s) join to more than one accepted route "
            f"row, so one cost would be reported against several groups of parts.",
            rows=duplicated[:10], count=len(duplicated)))

    # A ROUTE THAT CALCULATED TO NOTHING. Rows at zero are skipped above because they are
    # not part of the priced job — but an ACCEPTED route row landing at zero is a different
    # fact entirely: wb_populate decided this work happens, wrote it to the sheet, and the
    # sheet charged nothing for it. An unmapped department does exactly that, reconciles
    # perfectly against the total, and quietly gives the work away.
    _priced_rows = {}
    for r in rows:
        if isinstance(r, dict) and r.get("workbook_row") is not None:
            _priced_rows[int(_num(r.get("workbook_row")) or 0)] = _num(r.get("total_value_gbp"))
    _free = []
    for a in accepted:
        if not isinstance(a, dict) or a.get("workbook_row") is None:
            continue
        if a.get("no_charge"):            # explicitly free work, deliberately recorded
            continue
        _v = _priced_rows.get(int(_num(a.get("workbook_row")) or 0))
        if _v is not None and _v <= 0:
            _free.append({"workbook_row": a.get("workbook_row"),
                          "wb_operation": a.get("wb_operation"),
                          "part_numbers": (a.get("part_numbers") or [])[:5]})
    if _free:
        out.append(_violation(
            "accepted_route_priced_at_zero", BLOCKING,
            f"{len(_free)} accepted route row(s) calculated to GBP 0: "
            f"{', '.join(sorted({str(f['wb_operation']) for f in _free}))}. The engine decided "
            f"this work happens and the sheet charged nothing for it — most often a department "
            f"that did not map to a rate. It reconciles against the total and gives the work "
            f"away.",
            rows=_free[:10], count=len(_free)))

    # Stable identity, where the writer supplied it. Row numbers move when the template
    # changes; a group's identity does not, which is what makes a baseline comparable
    # between runs at all.
    missing_id = [a.get("workbook_row") for a in accepted
                  if isinstance(a, dict) and not a.get("route_group_id")]
    if missing_id:
        out.append(_violation(
            "route_group_without_stable_id", WARNING,
            f"{len(missing_id)} accepted route row(s) carry no route_group_id. The join still "
            f"works on sheet row, but nothing survives a template change, so runs of the same "
            f"job cannot be compared row for row.",
            workbook_rows=missing_id[:10]))
    return out


# ── 4. reports cannot name an unpriced operation ─────────────────────────────────────
def check_no_unpriced_operations_named(summary: Any) -> List[Dict[str, Any]]:
    """Every filter wb_populate applies — spurious ops, the finish gate, the material gates —
    happens after the engine has written its own operation list, and none of it is written
    back. Describing the job from the engine's list therefore describes a route the workbook
    does not contain. That is exactly how a quote came to promise powder coating and weld
    dressing on a lacquered timber crate."""
    try:
        from costed_facts import costed_operations
    except Exception as exc:
        return _unevaluated("unpriced_operation",
                            f"costed_facts could not be loaded ({exc}), so what the job was "
                            f"actually charged for is unknown.")
    try:
        costed = set(costed_operations(summary) or {})
    except Exception as exc:
        return _unevaluated("unpriced_operation",
                            f"The costed route could not be read ({exc}).")
    if not costed:
        return _unevaluated("unpriced_operation",
                            "No costed operations could be resolved for this job, so nothing "
                            "can be compared against what the reports name.")

    # ALIASES OF ONE DEPARTMENT ARE ONE OPERATION.
    #
    # OP_NAME_MAP carries synonyms, so Assemble/pack (Metal) inverts to handling, assembly
    # AND assemble. The canonical workbook row declares engine_operations ['assembly']; the
    # part record carries 'handling'. Same bench work, two names for it -- and comparing the
    # NAMES reported 12120's handling as work nobody charged for, while the three PACM rows
    # on the sheet were charging for exactly that.
    #
    # A false positive here is not noise. It invites the wrong correction: adding a handling
    # row on top of the assembly/pack that already contains it, and double-charging the
    # bench. The comparison belongs at the department, which is what the rate table pays.
    #
    # An earlier attempt treated this as SUPERSESSION -- excusing handling wherever a
    # canonical assembly decision covered the part. That was a guess at the cause, it was a
    # no-op in the case its fixture tested, and it would have excused a genuinely uncharged
    # handling operation on any part an assembly event touched. This is the actual cause,
    # and it fixes every alias pair rather than one.
    try:
        from costed_facts import _dept_to_engine_ops
        _siblings: Dict[str, set] = {}
        for _ops in (_dept_to_engine_ops() or {}).values():
            _low = {str(x).strip().lower() for x in _ops}
            for _o in _low:
                _siblings.setdefault(_o, set()).update(_low)
    except Exception:
        _siblings = {}
    # COVERAGE IS PER PART, NOT JOB-WIDE.
    #
    # Expanding aliases across the whole job excused `handling` on EVERY part the moment any
    # row charged the assembly department -- including parts no assembly/pack row names. A
    # part whose bench time genuinely never reached the sheet would have gone unreported,
    # which is an under-charge dressed as a clean check.
    #
    # A row names the parts it covers, so ask the question where it belongs: is THIS part's
    # operation charged on a row that includes THIS part.
    _by_part: Dict[str, set] = {}
    _job_wide: set = set()
    try:
        from costed_facts import _workbook_rows as _wb_rows, _row_engine_ops as _row_ops
        _rows = _wb_rows(summary)
    except Exception:
        _rows = None
    for _r in (_rows or []):
        _ops = {str(o).strip().lower() for o in (_row_ops(_r) or [])}
        for _o in set(_ops):
            _ops |= _siblings.get(_o, set())
        _pns = [str(x or "").strip().upper() for x in (_r.get("part_numbers") or []) if x]
        if _pns:
            for _pn in _pns:
                _by_part.setdefault(_pn, set()).update(_ops)
        else:
            # A row naming no parts can only be judged job-wide.
            _job_wide |= _ops

    # Fallback when no workbook rows are available (a quote built from JSON alone): the
    # job-wide set is all there is, and saying so beats inventing per-part precision.
    _fallback = {str(o).strip().lower() for o in costed}
    for _o in list(_fallback):
        _fallback |= _siblings.get(_o, set())
    if not _rows:
        _by_part, _job_wide = {}, _fallback

    # AN OPERATION THE COMPILER DECIDED AGAINST IS NOT AN OPERATION NOBODY CHARGED FOR.
    #
    # 2085's tube records still carry laser_cutting -- inherited from the shared assembly
    # page the plate's route was read off -- and the canonical route correctly rules it
    # not_applicable: a tube has no flat blank to profile. Reading the raw part field and
    # reporting it as unpriced resurrects the very word the compiler rejected, and invites
    # someone to add the laser row back.
    #
    # Decided-against is not the same as uncharged. Only a REQUIRED decision, or no decision
    # at all, leaves an operation answerable to this check.
    _decided_against: Dict[str, set] = {}
    _canon = ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
              or summary.get("canonical_route_shadow") or {})
    for _d in (_canon.get("decisions") or []):
        if not isinstance(_d, dict) or str(_d.get("status") or "") == "required":
            continue
        _op = str(_d.get("operation") or "").strip().lower()
        if not _op:
            continue
        for _pn in ([_d.get("target_id")] + list(_d.get("participants") or [])):
            _k = str(_pn or "").strip().upper()
            if _k:
                _decided_against.setdefault(_k, set()).add(_op)

    named: Dict[str, List[str]] = {}
    for p in _parts(summary):
        pn = str(p.get("part_number") or "?")
        _covered = (_by_part.get(pn.strip().upper(), set()) | _job_wide
                    | _decided_against.get(pn.strip().upper(), set()))
        for op in (p.get("operations") or p.get("textual_operations") or []):
            if isinstance(op, str) and op and op.strip().lower() not in _covered:
                named.setdefault(op, []).append(pn)
    if not named:
        return []
    return [_violation(
        "operation_named_but_not_priced", WARNING,
        f"{len(named)} operation(s) appear on parts but carry no cost on the workbook: "
        f"{', '.join(sorted(named))}. Any report built from the parts rather than from the "
        f"priced rows would describe work this job is not charging for.",
        operations={k: v[:5] for k, v in sorted(named.items())})]


# ── 5. measured geometry is really measured ──────────────────────────────────────────
_MEASURED_TOKENS = ("dxf_flat_pattern", "dxf", "solidworks_flat_pattern", "native_flat")


def _blank_num(part: Dict[str, Any], *keys: str) -> Optional[float]:
    """A blank dimension, from wherever the writer happened to put it.

    THE CHECK WAS LOOKING IN TWO OF THE THREE PLACES. drawing_job_merge writes a measured
    flat pattern to part["normalized_geometry"] and mirrors the extents to overall_length_mm
    / overall_width_mm; it does not write blank_length_mm to the part root. Reading only the
    root and geometry_rollup, this check reported "claims measured geometry but carries no
    outline" against four parts on 12120 whose blanks are on the populated sheet in front of
    you — 126.39 x 82.2, 45 x 20, 33.3 x 27.8, 79 x 37.79.

    A false positive here is not harmless noise: it blocks a firm quote, and it sent a real
    defect hunt after the wrong cause for several runs. Look everywhere the value is written,
    and if it is genuinely absent from all of them, then say so.
    """
    holders = (part, part.get("normalized_geometry") or {}, part.get("geometry_rollup") or {})
    for key in keys:
        for holder in holders:
            if isinstance(holder, dict):
                value = _num(holder.get(key))
                if value:
                    return value
    return None


def check_measured_geometry_is_complete(summary: Any) -> List[Dict[str, Any]]:
    """"Measured" is the word that unlocks the credibility gate, the blank-allowance skip and
    the fabricated-part tests. A part claiming it must actually carry an outline and an area,
    or the claim is doing all that work on the strength of a matched filename."""
    if not _parts(summary):
        return _unevaluated("measured_geometry",
                            "No part records were found on this job, so no geometry claim "
                            "could be checked.")
    bad = []
    for p in _parts(summary):
        src = str(p.get("geometry_source") or "").lower()
        claims = p.get("dxf_measured_outline") is True or any(t in src for t in _MEASURED_TOKENS)
        if not claims:
            continue
        # A file that measured something less than a blank is an honest state and says so in
        # its own name. cut_length_only is the case that made this check fire on five parts:
        # the cut path was genuinely measured, the outline was not, and one flag was claiming
        # both. Now that they are separate claims, this one is true and takes the allowance.
        if "no_geometry" in src or "matched_no_geometry" in src or "cut_length_only" in src:
            continue
        length = _blank_num(p, "blank_length_mm", "overall_length_mm")
        width = _blank_num(p, "blank_width_mm", "overall_width_mm")
        area = _blank_num(p, "blank_area_mm2")
        # AN AREA NOBODY STORED IS NOT AN OUTLINE NOBODY MEASURED. 12120's DXF-sourced parts
        # carry their blank as overall_length_mm / overall_width_mm and leave blank_area_mm2
        # unset — 01M is 126.393 x 82.197 with area None — so this check failed four parts
        # for a field that was merely never written. The question it asks is whether the part
        # has an outline; two extents are an outline, and the envelope area follows from them.
        # Only the two parts with native flats passed, which is what gave the game away.
        if not area and length and width:
            area = length * width
        if not (length and width and length > 0 and width > 0) or not (area and area > 0):
            bad.append({"part_number": p.get("part_number"), "geometry_source": src,
                        "blank_length_mm": length, "blank_width_mm": width,
                        "blank_area_mm2": area})
    if not bad:
        return []
    return [_violation(
        "measured_geometry_without_outline", BLOCKING,
        f"{len(bad)} part(s) claim measured geometry but carry no usable outline or area. "
        f"The claim unlocks the credibility gate and the blank-allowance skip, so an empty "
        f"one prices a part as if it had been measured when it has not.",
        parts=bad[:10], count=len(bad))]


# ── 6. stronger evidence is never silently overwritten ───────────────────────────────
# The fields whose SOURCE must be recorded, because each of them decides money and each is
# written by more than one reader. A field not in this tuple is not attributed and nothing
# says so — which is the difference between "we know where this came from" and "nobody has
# asked".
#
# blank_width_mm was missing while blank_length_mm was audited, and the metal is priced on
# the AREA: half of every blank on every job was unattributable and no check minded.
#
# Deliberately still short. Finish, operations, cut length and bend count are also written
# by several readers and are NOT audited yet; adding them is a real extension and belongs
# with the work that makes them stamped, not before it. Listing a field here that nothing
# stamps produces a warning on every part of every job, which is noise wearing rigour's
# clothes.
_ATTRIBUTED_FIELDS = ("normalized_material", "quantity", "normalized_thickness_mm",
                      "blank_length_mm", "blank_width_mm")


def _source_key_for(field: str) -> str:
    """The key the PRECEDENCE MODULE writes a source to — asked of that module rather than
    guessed. Guessing produced "normalized_material_source" while apply_field writes
    "material_source", so a properly attributed job was warned about on every part."""
    try:
        from source_precedence import _SOURCE_FIELDS
        return _SOURCE_FIELDS.get(field, f"{field}_source")
    except Exception:
        return {"normalized_material": "material_source",
                "quantity": "quantity_source",
                "normalized_thickness_mm": "thickness_source"}.get(field, f"{field}_source")


def check_evidence_is_attributed(summary: Any) -> List[Dict[str, Any]]:
    """Precedence can only be enforced on a datum whose source is recorded. A field written
    without one is invisible to arbitration: the next pass has nothing to compare against and
    overwrites it silently, which is the whole failure mode."""
    if not _parts(summary):
        return _unevaluated("evidence_attribution",
                            "No part records were found on this job.")
    unattributed: Dict[str, int] = {}
    for p in _parts(summary):
        for f in _ATTRIBUTED_FIELDS:
            if p.get(f) in (None, "", 0):
                continue
            if not p.get(_source_key_for(f)):
                unattributed[f] = unattributed.get(f, 0) + 1
    if not unattributed:
        return []
    return [_violation(
        "datum_written_without_source", WARNING,
        f"Values written with no recorded source: "
        f"{', '.join(f'{k} ({v} part(s))' for k, v in sorted(unattributed.items()))}. "
        f"Arbitration cannot protect a datum it cannot attribute — the next pass to touch it "
        f"has nothing to weigh itself against.",
        fields=unattributed)]


# ── 7. an unsupported drawing is provisional, not confidently wrong ──────────────────
def check_low_confidence_is_declared(summary: Any) -> List[Dict[str, Any]]:
    """The engine is allowed not to know. It is not allowed to not know quietly."""
    ds = _node(summary, "data_sufficiency")
    if not ds:
        return []
    weak = bool(ds.get("suppress_headline_total")) or bool(ds.get("provisional"))
    if not weak:
        return []
    declared = bool(ds.get("reasons")) or bool(ds.get("provisional_reason")) \
        or bool(_node(summary, "estimate_summary").get("provisional")) \
        or bool(summary.get("provisional") if isinstance(summary, dict) else False)
    if declared:
        return []
    return [_violation(
        "low_confidence_not_declared", BLOCKING,
        "The credibility gate has judged the measured coverage too low to stand behind, but "
        "nothing on the job says so. A number this weak must reach the reader marked "
        "provisional, with the reason attached.",
        data_sufficiency={k: ds.get(k) for k in ("suppress_headline_total", "provisional")})]


def check_workbook_adapters_read_everything(summary: Any) -> List[Dict[str, Any]]:
    """A block the adapter could not read contributes nothing and looks exactly like a block
    with nothing in it. The read-back records which ones failed; this turns that record into
    a failure rather than a footnote."""
    fe = _node(summary, "final_estimate")
    if not fe:
        return _unevaluated("workbook_adapters",
                            "No final_estimate on this job — the read-back did not run or did "
                            "not complete, so which workbook blocks were readable is unknown.")
    problems = fe.get("adapter_problems")
    if problems is None:
        return _unevaluated("workbook_adapters",
                            "The read-back recorded no adapter status, so whether every "
                            "workbook block was readable is unknown. (Present and empty means "
                            "'we checked'; absent means we did not.)")
    if not isinstance(problems, list) or not problems:
        return []
    return [_violation(
        "workbook_block_not_read", BLOCKING,
        f"{len(problems)} workbook block(s) could not be read: "
        f"{', '.join(sorted({str(p.get('block')) for p in problems if isinstance(p, dict)}))}. "
        f"Their rows are absent from this snapshot, so any total built from it is short by "
        f"whatever they contained.",
        problems=[p for p in problems if isinstance(p, dict)][:10])]


def check_geometry_is_reconciled(summary: Any) -> List[Dict[str, Any]]:
    """A part whose two measurements disagreed and could not be resolved is not a part we
    know the size of. geometry_arbitration keeps the DXF and marks the part when it measures
    materially LARGER than the model develops — the right call, because swapping in the model
    would trade one unverified number for another — but a review flag alone changed nothing:
    the fixture's own 400x300-against-60x34 case could still leave as a firm quote."""
    if not _parts(summary):
        return _unevaluated("geometry_reconciled", "No part records were found on this job.")
    unreconciled, rejected = [], []
    for p in _parts(summary):
        _v = p.get("flat_arbitration") if isinstance(p.get("flat_arbitration"), dict) else {}
        if p.get("flat_unreconciled") or _v.get("unreconciled"):
            unreconciled.append({"part_number": p.get("part_number"),
                                 "reason": _v.get("reason"),
                                 "area_ratio": _v.get("area_ratio")})
        elif p.get("dxf_geometry_rejected"):
            # Resolved, not unresolved: the model superseded an incomplete DXF and the part
            # is costed from a complete measurement. Worth seeing, not worth blocking.
            rejected.append({"part_number": p.get("part_number"), "reason": _v.get("reason")})
    out = []
    if unreconciled:
        out.append(_violation(
            "geometry_unreconciled", BLOCKING,
            f"{len(unreconciled)} part(s) have two measurements of the same blank that "
            f"disagree beyond tolerance and could not be resolved. The size these parts were "
            f"costed at is unconfirmed, so the price cannot be firm.",
            parts=unreconciled[:10], count=len(unreconciled)))
    if rejected:
        out.append(_violation(
            "dxf_geometry_superseded", WARNING,
            f"{len(rejected)} part(s) were costed from the model because their DXF measured "
            f"materially smaller than the flat the model develops. The price stands; the DXF "
            f"export should be fixed.",
            parts=rejected[:10], count=len(rejected)))
    return out


def check_native_evidence_is_current(summary: Any) -> List[Dict[str, Any]]:
    """The models are the strongest source this engine has. Two ways that goes wrong quietly.

    STALE: an extract is a photograph of the models at the moment it was taken. Costing from
    one that predates a design change produces a confident number describing a part that no
    longer exists.

    UNREAD: native files sitting in the job folder with no extract. Until the analyser was
    made to run, that was indistinguishable from a job that simply has no models — the best
    evidence in the building, unused, with nothing on screen to say so."""
    sw = _node(summary, "solidworks_native")
    if not sw:
        return []          # no models involved in this job; nothing to be current about
    out = []
    if sw.get("extract_stale"):
        out.append(_violation(
            "native_extract_stale", BLOCKING,
            "The SolidWorks extract predates the model files it was taken from — the design "
            "has changed since. This estimate is built on older geometry, materials and "
            "quantities than the models now hold.",
            native_files_present=sw.get("native_files_present")))
    if sw.get("top_assembly_candidates"):
        # WHICH ASSEMBLY IS THE JOB. Its full-depth BOM becomes the job's component list at
        # rank 90, so choosing the wrong one replaces every quantity on the sheet. The extract
        # can rule out anything that is somebody else's child; it cannot tell a released GA
        # from a scratch assembly that nothing includes, and a folder of fifteen assemblies
        # usually holds both. A warning rather than a block: the chosen BOM is probably right
        # and is certainly better than none, but nobody should read it as having been read.
        _cands = sw.get("top_assembly_candidates") or []
        out.append(_violation(
            "native_top_assembly_ambiguous", WARNING,
            f"{len(_cands)} assemblies in this extract could each be the top of the job, and "
            f"'{sw.get('top_assembly') or '?'}' was CHOSEN by {sw.get('top_assembly_chosen_by')}"
            f" — not read from the models. Its full-depth BOM is now the job's component list, "
            f"so if the wrong one won, every quantity on the sheet came from the wrong "
            f"assembly. Candidates: {', '.join(str(c) for c in _cands[:8])}.",
            candidates=_cands[:20], chosen=sw.get("top_assembly")))
    if sw.get("native_folder_unreachable"):
        # "I COULD NOT LOOK" MUST NOT READ AS "THERE IS NOTHING THERE". A count of zero from
        # an unreachable folder is indistinguishable downstream from a genuinely drawings-only
        # job, and that case is silent by design -- so a dropped VPN removed the native-models
        # blocker instead of raising one, and the estimate looked more complete than the one
        # taken while the drive was up.
        out.append(_violation(
            "native_folder_unreachable", BLOCKING,
            f"The folder that should hold this job's SolidWorks models could not be opened "
            f"from this machine: {sw.get('native_folder_unreachable')}. Nothing was read and "
            f"nothing can be concluded -- this is NOT evidence that the job has no models. "
            f"Reconnect the VPN or map the drive and re-run before treating this estimate as "
            f"drawings-only.",
            folder=sw.get("native_folder_unreachable")))
    if sw.get("native_present_but_unread"):
        out.append(_violation(
            "native_models_not_read", BLOCKING,
            f"{sw.get('native_files_present')} SolidWorks model file(s) are in this job folder "
            f"but were not read: {sw.get('reason') or 'no extract was generated'}. The job has "
            f"been costed from the drawings alone while the models were available.",
            reason=sw.get("reason"), analyser_error=sw.get("analyser_error")))
    if sw.get("refused_wrong_job"):
        # A DISCARDED MODEL PACK CHANGES EVERY NUMBER ON THE SHEET, AND SAID SO ONLY IN A
        # CONSOLE LINE. Job 11350's own extract was refused because the connector did not
        # know the material-suffix convention; the run continued on drawings alone, the
        # right arm lost its geometry, and an AI market estimate became 97% of the material
        # total. Nothing in the invariants, the reports or the sheet mentioned that the best
        # evidence in the building had been thrown away.
        #
        # REFUSING OUR OWN EXTRACT IS A DIFFERENT SEVERITY FROM REFUSING A FOREIGN ONE. The
        # second is this guard working and a pointer to fix; the first is a defect in our
        # matching, and it is silent, and it is expensive.
        _own = sw.get("refused_own_job")
        out.append(_violation(
            "native_extract_refused", BLOCKING if _own else WARNING,
            (f"The SolidWorks extract was REFUSED and nothing from it was applied — this job "
             f"is costed from drawings alone. "
             + (f"Its codes share a job number with this job's, so it IS this job's extract "
                f"and the connector could not match it: a naming convention it does not know."
                if _own else
                f"Its codes share no job number with this job's, so it describes a different "
                f"job — the pointer is wrong, and this job's own models were never read.")),
            extract_path=sw.get("extract_path"),
            extract_top_assembly=sw.get("extract_top_assembly"),
            extract_codes=sw.get("extract_codes"),
            job_codes=sw.get("job_codes")))
    if sw.get("changed_during_extraction"):
        out.append(_violation(
            "native_models_changed_during_extraction", BLOCKING,
            "The model files changed while the extract was being taken, so its results "
            "describe the files as they were when each was opened and the manifest describes "
            "what is on disk now. The two are not the same snapshot; re-run the extraction.",
            fingerprint_before=sw.get("fingerprint_before")))
    if sw.get("source_unreachable"):
        out.append(_violation(
            "native_source_unreachable", UNVERIFIED,
            f"The folder this extract was generated from is not reachable "
            f"({sw.get('fingerprint_folder')}), so its freshness could not be checked. That "
            f"is not evidence the extract is stale — only that nothing could be verified.",
            fingerprint_folder=sw.get("fingerprint_folder")))
    if sw.get("extract_incomplete"):
        out.append(_violation(
            "native_extract_incomplete", BLOCKING,
            f"The SolidWorks extraction read no files successfully "
            f"({sw.get('files_failed')} failed). Per-file failures are written as error-only "
            f"records and the analyser still exits zero, so a wholly failed extraction "
            f"produces a non-empty file that reads downstream as a successful read.",
            files_read=sw.get("files_read"), files_failed=sw.get("files_failed")))
    elif sw.get("files_failed"):
        # BLOCKING, not a warning. "Some files failed" cannot be waved through, because
        # nothing here knows whether the failures were irrelevant fixtures or a released
        # component of the assembly being priced — and if it was the latter, the job is
        # undercosted by whatever that part contributes. The analyser can clear this by
        # showing the failures fall outside the BOM closure; until it does, the honest
        # position is that we do not know what is missing.
        _outside = sw.get("failed_outside_bom_closure")
        out.append(_violation(
            "native_extract_partial", WARNING if _outside else BLOCKING,
            f"{sw.get('files_failed')} model file(s) could not be read by the analyser "
            f"({sw.get('files_read')} succeeded)"
            + (". They are outside the assembly BOM, so nothing priced depends on them."
               if _outside else
               ". Until they are shown to be outside the assembly BOM, a released component "
               "may be missing and the job undercosted by whatever it contributes."),
            files_failed=sw.get("files_failed"),
            failed_paths=(sw.get("extract_errors") or [])[:10]))
    if sw.get("freshness_unverifiable"):
        out.append(_violation(
            "native_freshness_unverifiable", UNVERIFIED,
            "The extract was supplied from outside the job folder and carries no manifest "
            "saying which models it was generated from, so nothing about its freshness could "
            "be checked. Treat this run as diagnostic: regenerate the extract immediately "
            "before the run, or use one that carries a manifest.",
            fingerprint_folder=sw.get("fingerprint_folder")))
    elif sw.get("manifest_absent") and sw.get("found") is not False:
        out.append(_violation(
            "native_freshness_unverified", UNVERIFIED,
            "This extract carries no manifest, so it could only be checked for freshness on "
            "its file timestamp. A copy, a restore or a touched file defeats that, and a "
            "model deleted or renamed since is invisible to it. Regenerate the extract to "
            "get a fingerprint check.",
            freshness_check=sw.get("freshness_check")))
    if sw.get("analyser_error"):
        out.append(_violation(
            "native_analyser_failed", WARNING,
            f"The SolidWorks analyser reported a problem: {sw.get('analyser_error')}. An "
            f"existing extract was used if one was present.",
            analyser_error=sw.get("analyser_error")))
    return out


# Sources that CANNOT produce the same answer twice. An LLM asked what a knurled knob costs
# returns a different number each time; that is what these are for, and it is a legitimate way
# to fill a gap — but it is an estimate OF a price, not a price.
# Kept as a name for existing readers, but the list itself lives in one place now. Two copies
# of "which sources are guesses" is how a writer and a checker come to disagree.
NON_REPRODUCIBLE_PRICE_SOURCES = price_provenance.NON_REPRODUCIBLE_SOURCES


def check_prices_are_reproducible(summary: Any) -> List[Dict[str, Any]]:
    """Was any priced line costed from a source that cannot answer the same way twice?

    Job 12120 priced three times on identical inputs at GBP 27.67, GBP 29.39 and GBP 32.86.
    Labour was identical to the penny every run and the steel never moved. SQL missed on
    THUM620, the knurled knob and the screen cable every time, so the lookup fell through to
    an LLM market estimate — confidence 0.3-0.4, described in its own output as INDICATIVE —
    and the cable came back at GBP 4.54, then GBP 6.00, then GBP 8.54.

    That is not drift and no tie-break fixes it. An LLM is being asked what a part costs, and
    it is answering differently each time because that is what it does. As a way of filling a
    gap it is defensible; as the applied unit cost on a quote it is not, because the number
    cannot be reproduced, audited, or defended to a customer who asks how it was arrived at.

    Every one of those three runs RECONCILED — rows to subtotals, subtotals to unit price.
    The engine was internally perfect and externally unrepeatable, and no other check here
    can see that, because each run is individually consistent.

    HOW THIS CHECK FAILED ONCE ALREADY. Its first version read part["price_source"] over
    _parts(summary), and reported CLEAR on the very job above. Two reasons, both of them the
    same mistake: it looked at the top-level `parts` list, which carries geometry and no
    prices, never reaching estimate_summary.part_estimates; and even there the AI prices were
    bought-in unit costs at cost_breakdown.system_cost.source, not at price_source. A check
    that has to be told where money lives will keep passing jobs whose money is somewhere
    else. So it is now handed the whole job and finds every price stamp in it by marker.
    """
    if not isinstance(summary, dict):
        return _unevaluated("price_reproducibility", "This job is not a readable structure.")
    stamps = list(price_provenance.iter_price_stamps(summary))
    if not stamps:
        return _unevaluated(
            "price_reproducibility",
            "No priced lines carrying a price-source stamp were found anywhere on this job.")

    # LINES THE WORKBOOK REFUSED TO PRICE. Declared by the branch that refused them, so a
    # part whose stamp is written in two places is honoured in both — see mark_withheld.
    # Deliberately NOT a way to silence this check: only the code that writes GBP 0.00 onto
    # the sheet adds a code here, and a price that reached the total never appears.
    _withheld = {str(c).strip().upper()
                 for c in (summary.get("withheld_price_lines") or []) if str(c).strip()}
    guessed = []
    for path, block, owner in price_provenance.applied_ai_prices(summary):
        if str(owner or "").strip().upper() in _withheld:
            continue
        _sel = block.get("selected") if isinstance(block.get("selected"), dict) else {}
        guessed.append({
            "part": owner, "where": path,
            "source": block.get("source_name") or _sel.get("source"),
            "unit_cost_gbp": _sel.get("price") if _sel.get("price") is not None
                             else block.get("unit_price_gbp"),
            "confidence": block.get("confidence"),
        })
    if not guessed:
        return []
    # NAME THE CODES, NOT THE ARRAY INDICES. "part_estimates[11]" cannot be added to a
    # catalogue; the whole instruction this violation ends with depends on the reader knowing
    # which items to go and price.
    _names = sorted({str(g["part"]) for g in guessed if g.get("part")}) \
        or sorted({str(g["where"]) for g in guessed})
    return [_violation(
        "price_not_reproducible", BLOCKING,
        f"{len(guessed)} priced line(s) that reached the total were costed by an AI market "
        f"estimate rather than a catalogue: {', '.join(_names[:8])}"
        f"{f' (+{len(_names) - 8} more)' if len(_names) > 8 else ''}. Those figures change "
        f"every run — the same job has priced at three different totals on identical inputs, "
        f"one cable line moving from GBP 4.54 to GBP 8.54 on its own — so the estimate cannot "
        f"be reproduced or defended. Add these codes to the price catalogue, or price the "
        f"lines by hand.",
        parts=_names, lines=guessed[:10], count=len(guessed))]


def check_price_disagreement_is_declared(summary: Any) -> List[Dict[str, Any]]:
    """Where several sources answered with different prices, is the spread visible?

    Determinism is not correctness. If the catalogue holds THUM620 at both GBP 1.16 and
    GBP 1.32, picking the same row every run is repeatable and still hides a data problem
    that belongs in front of a person. The resolver records the spread; this makes sure a
    reader is told about it rather than shown only the survivor.

    A warning, not blocking: the number that was applied came from a real catalogue row, so
    the price stands — it is the catalogue that needs attention.
    """
    if not isinstance(summary, dict):
        return _unevaluated("price_disagreement", "This job is not a readable structure.")
    disputed = price_provenance.declared_price_disagreements(summary)
    if not disputed:
        return []
    detail = []
    for path, block in disputed:
        dis = (block.get("provenance") or {}).get("disagreement") or {}
        detail.append({"where": path, "low_gbp": dis.get("low_gbp"),
                       "high_gbp": dis.get("high_gbp"),
                       "spread_pct": dis.get("spread_pct"),
                       "sources": dis.get("sources")})
    _worst = max(detail, key=lambda d: float(d.get("spread_pct") or 0.0))
    return [_violation(
        "price_sources_disagree", WARNING,
        f"{len(detail)} priced line(s) had sources that disagreed on the price — the widest "
        f"spread is {_worst.get('spread_pct')}% between GBP {_worst.get('low_gbp')} and "
        f"GBP {_worst.get('high_gbp')} at {_worst.get('where')}. The applied figure is a real "
        f"catalogue row, so the price stands, but the catalogue holds more than one answer "
        f"for the same item and an estimator should see which is right.",
        lines=detail[:10], count=len(detail))]


def check_every_cad_file_was_used(summary: Any) -> List[Dict[str, Any]]:
    """Did anything the customer supplied go unopened?

    The engine reads .pdf, .dxf and the three SolidWorks document types, and ignores
    everything else without a word. A customer sending DWG flat patterns gets an estimate
    built from the PDF alone — transcribed blanks, inferred cut lengths — while the measured
    geometry sits unread in the same folder.

    Reported, never corrected: whether a STEP file matters is a judgement about that job, and
    the engine is not the one to make it. What it can do is stop the omission being silent.
    """
    # NOT FAIL-CLOSED, AND DELIBERATELY. Every other check here verifies a NUMBER, so an
    # unevaluated one is recorded as UNVERIFIED and the job cannot go out firm. This one
    # reports what was in a folder. A run driven from a single file has no folder to
    # inventory, and marking those jobs unverified for ever would say a price was unsafe on
    # the strength of a question that did not apply to it.
    inv = _node(summary, "cad_inputs")
    if not inv or not inv.get("present"):
        return []
    unread = [str(n) for n in (inv.get("unread") or [])]
    if not unread:
        return []
    _dwg = [n for n in unread if n.lower().endswith(".dwg")]
    _rest = [n for n in unread if n not in _dwg]
    _msg = f"{len(unread)} CAD file(s) in the job folder were not read: {', '.join(unread[:8])}"
    if len(unread) > 8:
        _msg += f" (+{len(unread) - 8} more)"
    if _dwg:
        _msg += (f". {len(_dwg)} of them are DWG — the same geometry as a DXF in a different "
                 f"container, which the ODA File Converter turns into something this engine "
                 f"reads. Those parts are being sized from drawing text while their measured "
                 f"outline sits unopened")
        # WHY THEY WERE NOT CONVERTED, IN THE SAME SENTENCE AS THE FACT THAT THEY WERE NOT.
        #
        # convert_dwgs already distinguishes the cases and writes one of them down: the
        # converter is not installed (a five-minute free download), the converter ran and
        # produced nothing (3D DWGs, which hold no flat pattern — nothing to do), or it
        # failed. This check reported none of it, so the only sentence anybody read told them
        # a tool would fix it without saying whether the tool was even present. Two different
        # actions, one message, and the one that costs nothing to fix looked like the one that
        # cannot be fixed at all.
        _conv = _node(summary, "dwg_conversion") or {}
        # The reason is a whole sentence of its own and this message gets its full stop added
        # at the end, so trim the one it already carries rather than print "on PATH..".
        _why = str(_conv.get("reason") or "").strip().rstrip(".")
        if _why:
            _msg += f". {_why[0].upper()}{_why[1:]}"
        elif _conv.get("converted"):
            _msg += (f". The converter DID run on this job and produced "
                     f"{len(_conv['converted'])} DXF — these are the files it could not "
                     f"convert or that were not part flat patterns")
    if _rest:
        _msg += (". The rest carry geometry and none of the things an estimate needs — no "
                 "part numbers, no quantities, no material — so they are skipped by design")
    return [_violation("cad_files_not_read", WARNING, _msg + ".",
                       files=unread[:12], count=len(unread), dwg_count=len(_dwg))]


def check_uncorroborated_bom_lines_are_not_silent(summary: Any) -> List[Dict[str, Any]]:
    """A BOM row only one reader could see, carrying real money.

    The BOM is read twice on purpose: a deterministic table reader and a vision pass. Where
    both agree a row is HIGH confidence; where only one saw it, the row is emitted and
    FLAGGED, because a vision pass missing a real line is as likely as a table reader
    inventing one. That design is right and it worked — on M&S 2085 the phantom border-grid
    row came back A_ONLY with "vision did not corroborate — review" against it.

    And then it was priced at GBP 219.21 of a GBP 273.98 unit cost. Eighty percent of the job
    from a row the engine had already doubted, because the flag reached a JSON field and
    nothing downstream weighed it.

    Not dropped here — dropping a real part is silent and far worse than costing a phantom
    one, which is at least visible in the total. Named, with what it is worth, so nobody has
    to notice it themselves.
    """
    if not isinstance(summary, dict):
        return _unevaluated("uncorroborated_bom", "This job is not a readable structure.")
    rows = ((summary.get("document_analysis") or {}).get("bom_rows")
            or (summary.get("document_analysis") or {}).get("pooled_bom") or [])
    if not isinstance(rows, list) or not rows:
        return []

    flagged = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        _src = str(r.get("bom_source") or "").upper()
        _flag = str(r.get("bom_flag") or "").strip()
        if _flag or _src in ("A_ONLY", "B_ONLY", "B_RECOVERED", "B_OVERRIDE"):
            _pn = str(r.get("part_number") or "").strip()
            if _pn:
                flagged[_pn.upper()] = {"part_number": _pn,
                                        "description": r.get("description"),
                                        "bom_source": r.get("bom_source"),
                                        "bom_flag": _flag or None,
                                        "quantity": r.get("quantity")}
    if not flagged:
        return []

    # What did each flagged row actually cost? Only money makes it worth interrupting for.
    fe = _node(summary, "final_estimate")
    total = _num((fe.get("totals") or {}).get("material_gbp")) or 0.0
    costed, worth = [], 0.0
    for row in (fe.get("material_rows") or []):
        if not isinstance(row, dict):
            continue
        _code = str(row.get("part_code") or row.get("description") or "").upper()
        for pn, meta in flagged.items():
            if _code.startswith(pn):
                _v = _num(row.get("total_value_gbp")) or 0.0
                # A ZERO ROW IS NOT A COSTED LINE, and the sentence above says so —
                # "only money makes it worth interrupting for" — while the code counted
                # every match. A fabricated part appears in material_rows TWICE: once in
                # the Bill of Materials at GBP 0.00, listed for completeness because its
                # metal is costed in the Sheet Steel block, and once in that block for
                # real. Counting both reported "2 BOM line(s)" for one part and named the
                # same panel twice, at GBP 0.00 and at GBP 4.31, in a message about how
                # much money the doubt covers.
                if _v <= 0:
                    break
                costed.append({**meta, "value_gbp": round(_v, 2)})
                worth += _v
                break
    if not costed:
        return []

    _share = (worth / total * 100.0) if total > 0 else 0.0
    _sev = BLOCKING if _share >= 25.0 else WARNING
    return [_violation(
        "uncorroborated_bom_line_costed", _sev,
        f"{len(costed)} BOM line(s) that only one reader could see carry "
        f"GBP {worth:,.2f} of a GBP {total:,.2f} material total ({_share:.0f}%): "
        + "; ".join(f"{c['part_number']} \u2014 {c['description']} @ GBP {c['value_gbp']:,.2f}"
                    for c in costed[:6])
        + ". The BOM is read twice so that a row only one reader finds is doubted, not "
          "trusted; here the doubt was recorded and then priced anyway.",
        lines=costed[:10], count=len(costed), value_gbp=round(worth, 2),
        share_pct=round(_share, 1))]


def check_uncorroborated_route_operations(summary: Any) -> List[Dict[str, Any]]:
    """Labour charged for work nothing read off the drawing.

    THE BOM IS READ TWICE AND THE ROUTE IS NOT. A BOM row only one reader saw is emitted,
    flagged, and blocked when it carries real money — check_uncorroborated_bom_lines_are_
    not_silent. The route has had no equivalent: an operation reasoned by the model and an
    operation measured off a cut list both arrive as REQUIRED, distinguishable only by a
    rank number nothing downstream weighed.

    A route decision is corroborated when some claim behind it was READ — a bend count, a
    weld symbol, a finish note, a cut-list property — or quotes the drawing's own words.
    Everything else is proposal, and proposal that reaches the labour column is exactly the
    work an estimator would want to look at first.

    NOT A DEMOTION. Dropping an uncorroborated operation would be worse than keeping it:
    work the model saw and we did not is precisely what gets forgotten, and forgetting it
    costs real minutes on the shop floor. This names it and prices the doubt.
    """
    if not isinstance(summary, dict):
        return _unevaluated("uncorroborated_route", "This job is not a readable structure.")
    fe = _node(summary, "final_estimate")
    rows = fe.get("labour_rows") or fe.get("calculated_labour_rows") or []
    if not isinstance(rows, list) or not rows:
        return []

    # WHERE THE ROUTE ACTUALLY IS. This asked summary["canonical_route"], which nothing
    # writes — the compiler stamps estimate_summary["canonical_route_shadow"] and
    # check_canonical_route_shadow reads it through _node. So on 12392 this check found no
    # decisions, returned nothing, and reported clean on a job where most of the labour is
    # uncorroborated. A check that cannot find its data is worse than no check: it occupies
    # the place where somebody would have looked.
    decisions = {}
    for _d in (_node(summary, "canonical_route_shadow").get("decisions") or []):
        if isinstance(_d, dict) and _d.get("status") == "required":
            _op = str(_d.get("operation") or "").strip().lower()
            _tgt = str(_d.get("target_id") or "").strip().upper()
            if _op:
                decisions[(_op, _tgt)] = _d
    if not decisions:
        # NOT unevaluated. A job with no canonical route decisions has not hidden this
        # answer — it has no canonical route, which check_canonical_route_shadow owns and
        # reports. Claiming "unverified" here made every complete, consistent job
        # unreleasable over a route this check was never given.
        return []

    total = 0.0
    flagged, worth = [], 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        _v = _num(row.get("total_value_gbp")) or _num(row.get("labour_cost_gbp")) or 0.0
        total += _v
        if _v <= 0:
            continue
        _op = str(row.get("operation") or "").strip().lower().replace(" ", "_")
        for (_dop, _dtgt), _d in decisions.items():
            if _dop != _op and _dop not in _op:
                continue
            if _d.get("corroborated") is False:
                flagged.append({"operation": row.get("operation"), "target": _dtgt,
                                "value_gbp": round(_v, 2),
                                "sources": _d.get("source"),
                                "evidence": _d.get("evidence") or None})
                worth += _v
            break
    if not flagged:
        return []

    _share = (worth / total * 100.0) if total > 0 else 0.0
    _sev = BLOCKING if _share >= 40.0 else WARNING
    return [_violation(
        "route_operation_not_corroborated", _sev,
        f"{len(flagged)} priced operation(s) carry GBP {worth:,.2f} of a GBP {total:,.2f} "
        f"labour total ({_share:.0f}%) on work nothing read off the drawing — no measured "
        f"feature, no quoted note: "
        + "; ".join(f"{f['operation']} on {f['target'] or '?'} @ GBP {f['value_gbp']:,.2f}"
                    for f in flagged[:6])
        + ". Kept on the estimate deliberately, because work the model saw and we did not "
          "is what gets forgotten — but an estimator should confirm it before this is a "
          "quote.",
        operations=flagged[:10], count=len(flagged), value_gbp=round(worth, 2),
        share_pct=round(_share, 1))]


def check_both_bom_readers_ran(summary: Any) -> List[Dict[str, Any]]:
    """A BOM read by one reader must not be reported as a BOM read by two.

    The parts list is read twice on purpose — a deterministic word-geometry reader and a
    vision pass over the rendered page — and the check above
    (check_uncorroborated_bom_lines_are_not_silent) doubts any row only one of them saw.
    That check works entirely from per-row flags, so it is completely silent when a whole
    reader never ran: no row is marked A_ONLY if nothing was ever asked to corroborate it.

    Every row then looks unflagged, which is the appearance of agreement rather than
    agreement. This is the one BOM failure that cannot be seen in the output, because what
    is wrong with the output is what is not in it.

    Not a warning about a missing feature. A vision pass that could not run is the reason
    a whole parent BOM can be absent from a job and nothing say so.
    """
    if not isinstance(summary, dict):
        return _unevaluated("bom_readers_ran", "This job is not a readable structure.")
    da = summary.get("document_analysis")
    if not isinstance(da, dict):
        return []
    unread = da.get("bom_readers_unread")
    if unread is None:
        return _unevaluated(
            "bom_readers_ran",
            "This job carries no record of which BOM readers ran. Re-run it; a scan "
            "produced before the readers reported their own coverage cannot answer this.")
    if not isinstance(unread, list) or not unread:
        return []

    rows = da.get("bom_rows")
    row_count = len(rows) if isinstance(rows, list) else 0
    job_scope = [u for u in unread if isinstance(u, dict) and u.get("scope") == "job"]
    page_scope = [u for u in unread if isinstance(u, dict) and u.get("scope") != "job"]

    out: List[Dict[str, Any]] = []
    if job_scope:
        _who = ", ".join(sorted({("deterministic" if u.get("path") == "A" else "vision")
                                 for u in job_scope}))
        _why = "; ".join(str(u.get("detail") or "").strip() for u in job_scope if u.get("detail"))
        out.append(_violation(
            "bom_reader_never_ran", BLOCKING,
            f"The {_who} BOM reader did not run on this job ({_why}). The {row_count} BOM "
            f"line(s) costed here were read once, not twice, so none of them carries "
            f"corroboration and no line only one reader could see has been flagged as such. "
            f"A parent BOM missing from this estimate would look exactly like a job that "
            f"has none.",
            readers=_who, unread=job_scope[:6], bom_rows=row_count))
    if page_scope:
        _pages = "; ".join(
            f"{u.get('pdf') or '?'}"
            + (f" page {int(u['page']) + 1}" if u.get("page") is not None else "")
            + f" ({'deterministic' if u.get('path') == 'A' else 'vision'}: {u.get('detail')})"
            for u in page_scope[:6])
        out.append(_violation(
            "bom_page_not_read_by_both", WARNING,
            f"{len(page_scope)} page(s) were read by only one BOM reader: {_pages}. Rows on "
            f"those pages are uncorroborated even where they are not flagged.",
            count=len(page_scope), pages=page_scope[:10]))
    return out


def check_bom_lines_survive_the_merge(summary: Any) -> List[Dict[str, Any]]:
    """A part used by two assemblies must still be two BOM lines when costing sees it.

    A BOM line is the statement "this assembly uses N of that part". The same part under two
    assemblies is two lines, two quantities and two owners, and the readers record it that
    way — bom_pipeline stamps every row with its parent page and deliberately does not
    deduplicate, because "the same code legitimately recurs across parent BOMs".

    Then the rollup merged by part number. On job 12392 — one enquiry, two GAs — the 02
    drawing's 16 M4x8 fixings and the 04 drawing's 4 survived as one line of 16; the 04
    brackets lost the edge that named their parent and arrived at costing as orphans. The
    engine held both lists the whole time and compared them to nothing.

    So this compares them. Deliberately narrow: it asks only about codes the readers
    themselves recorded under MORE THAN ONE parent, and only where some of those lines
    survived. A code that vanishes entirely has a different cause — drawing furniture, a
    weldment parent shadowed by its children, a catalogue reclassification — and those are
    legitimate whole-row drops that other checks and other rules govern. Partial survival
    cannot be any of them: it is a merge that treated two lines as one.
    """
    if not isinstance(summary, dict):
        return _unevaluated("bom_line_survival", "This job is not a readable structure.")
    da = summary.get("document_analysis")
    if not isinstance(da, dict):
        return []
    raw = da.get("bom_rows")
    final = da.get("bay_bom_rows")
    # No rollup ran on this job, so there is no merge to check. Not a failure and not a
    # silent pass either — there are genuinely no two lists here to compare.
    if not isinstance(raw, list) or not isinstance(final, list) or not raw or not final:
        return []

    # ONE DEFINITION OF A LINE, shared with the code that does the merging. A private copy
    # here would agree with it today and drift the first time either is touched — which is
    # the failure this check exists to catch, reproduced inside the check itself.
    try:
        from bay_rollup import _row_code, _row_parent
    except Exception as exc:                                        # noqa: BLE001
        return _unevaluated("bom_line_survival",
                            f"The BOM line identity could not be imported ({exc}).")

    def _lines(rows: List[Any]) -> Dict[str, set]:
        out: Dict[str, set] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            code, parent = _row_code(r), _row_parent(r)
            if code and parent:
                out.setdefault(code, set()).add(parent)
        return out

    before, after = _lines(raw), _lines(final)
    collapsed = []
    for code, parents in sorted(before.items()):
        if len(parents) < 2:
            continue                       # one owner: nothing could have been collapsed
        kept = after.get(code) or set()
        if not kept:
            continue                       # dropped whole, which is not this check's claim
        if len(kept) < len(parents):
            collapsed.append({"part_number": code,
                              "parents_read": sorted(parents),
                              "parents_kept": sorted(kept),
                              "lines_lost": len(parents) - len(kept)})
    if not collapsed:
        return []

    _lost = sum(c["lines_lost"] for c in collapsed)
    return [_violation(
        "bom_lines_collapsed_by_part_number", BLOCKING,
        f"{_lost} BOM line(s) across {len(collapsed)} part(s) were merged away between the "
        f"drawing read and costing. Each was a separate assembly's use of the part, with its "
        f"own quantity: "
        + "; ".join(f"{c['part_number']} read under {len(c['parents_read'])} assemblies "
                    f"({', '.join(c['parents_read'])}), costed under "
                    f"{len(c['parents_kept'])}" for c in collapsed[:6])
        + ". The quantities of the lost lines are not in the estimate and the parts they "
          "belonged to have no parent.",
        parts=collapsed[:10], count=len(collapsed), lines_lost=_lost)]


# The closest two cut lines can credibly run in sheet metal, in millimetres. A laser kerf is
# nearer 0.2mm, so this is generous by a factor of five on purpose: the test exists to catch a
# blank that is impossible, not one that is merely dense. A part whose whole cut path implies
# an average line spacing under this did not come from the blank recorded beside it.
_MIN_CREDIBLE_CUT_SPACING_MM = 1.0

# And then only complain at several times over. A long narrow strip is nearly all perimeter —
# 2500 x 2 has 5,004mm of outline in 5,000mm2 of room — so a bare "over one" would fire on
# geometry that is unusual rather than impossible. The cases this exists for clear the bar by
# a hundredfold, so the margin costs nothing and buys the check the right to be BLOCKING.
_CUT_PATH_ABSURDITY_MARGIN = 3.0


def check_a_material_we_cannot_price_is_declared(summary: Any) -> List[Dict[str, Any]]:
    """A part whose material this engine holds no rate for, and what happened about it.

    THE WORST OUTCOME IS THE SILENT ONE. 11650-01-05A DOOR -- 1202 x 689 x 6mm, laser cut,
    drilled and assembled, all of that costed -- carried GBP 0.00 of material because the
    arbitration winner was ABS, which has no sheet rate and no GBP/kg. Nothing on the sheet,
    in the reports or in the checks said so. It read as a door that costs nothing to make.

    An unpriceable material is OURS, not the estimator's: no input they can supply fixes a
    rate the engine does not have. That is NO_VOCABULARY in the price vocabulary and it is
    the category that means the job is UNDER-CHARGED by an amount nobody has seen.

    Two outcomes, both reported. Where a better-supported reading rescued the price, the
    substitution is a conflict an estimator must rule on -- the figure is real but the
    material is unconfirmed. Where nothing rescued it, the line is simply not costed and the
    engine needs a rate before this job is quoted.
    """
    if not isinstance(summary, dict):
        return [_violation("material_we_cannot_price", UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")]
    parts = _parts(summary)
    if not parts:
        return []
    substituted, unpriceable, indicated = [], [], []
    for part in parts:
        # PRICED FROM A MARKET LOOKUP IS NOT UNPRICED, and it is not a rate either. The line
        # carries money, so the under-charge is closed; the money is an LLM estimate, so the
        # job cannot go out firm on it -- check_prices_are_firm sees the stamp and says so.
        # What remains is the thing an estimator has to know: this figure is not a supplier
        # price and nobody has agreed to it.
        indication = part.get("material_market_indication")
        if isinstance(indication, dict) and indication.get("gbp_per_m2") and \
                str((part.get("material_estimate") or {}).get("cost_method") or "") == \
                "llm_market_sheet_rate":
            indicated.append({
                "part_number": part.get("part_number"),
                "material": indication.get("material"),
                "gbp_per_m2": indication.get("gbp_per_m2"),
                "source": indication.get("source"),
            })
            continue
        conflict = part.get("material_priced_as")
        if isinstance(conflict, dict) and conflict.get("priced_material"):
            substituted.append({
                "part_number": part.get("part_number"),
                "arbitrated": conflict.get("arbitrated_material"),
                "priced_as": conflict.get("priced_material"),
                "from": conflict.get("priced_material_source"),
            })
            continue
        material = str(part.get("normalized_material") or "").strip()
        if not material:
            continue                      # absence of a material is a different check
        # A LINE THAT COSTS SOMETHING IS NOT A LINE THAT COSTS NOTHING.
        #
        # This check exists to catch material priced at GBP 0.00 for want of a rate. It read
        # normalized_material alone and assumed that field always holds a material -- on
        # 11650's bought-in fixings it holds the pointer text "SEE INDIVIDUAL DRAWINGS", which
        # no rate table knows, so four fixings priced at GBP 0.10, GBP 0.08 and GBP 0.02 on
        # the same sheet were reported as BLOCKING under-charges. A check that cries wolf on
        # priced lines gets ignored on the day it is right, and this one was introduced today.
        #
        # The claim is about MONEY, so ask about money: if the line carries a material cost,
        # whatever its material string says, there is no under-charge to report here.
        _me = part.get("material_estimate") if isinstance(part.get("material_estimate"), dict) else {}
        _cost = _me.get("unit_material_cost_gbp") or _me.get("cost_per_part_gbp") \
            or part.get("unit_material_cost_gbp")
        try:
            if _cost is not None and float(_cost) > 0:
                continue
        except (TypeError, ValueError):
            pass
        # And a pointer is not a material. "SEE INDIVIDUAL DRAWINGS" names no substance for
        # anyone to find a rate for, so demanding one is asking for the impossible.
        if any(w in material.upper() for w in _FINISH_POINTER_WORDS):
            continue
        try:
            import config as _cfg
            if _cfg.material_has_a_rate(material):
                continue
        except Exception:                                    # noqa: BLE001
            continue
        unpriceable.append({"part_number": part.get("part_number"), "material": material})

    out: List[Dict[str, Any]] = []
    if unpriceable:
        out.append(_violation(
            "material_has_no_rate_in_this_engine", BLOCKING,
            f"{len(unpriceable)} part(s) are made of a material this engine holds no rate "
            f"for, so their material costs NOTHING on the sheet: "
            + "; ".join(f"{u['part_number']} ({u['material']})" for u in unpriceable[:6])
            + ". No estimator input fixes this -- there is no rate to enter against, and a "
              "line at zero reads as a part that is free to make. THE JOB IS UNDER-CHARGED "
              "BY THIS MATERIAL. Add a rate for the material, or confirm the part is "
              "something we can already price.",
            count=len(unpriceable), parts=unpriceable[:20]))
    if indicated:
        out.append(_violation(
            "material_priced_from_a_market_lookup", WARNING,
            f"{len(indicated)} part(s) are made of a material this engine holds no rate for, "
            f"and were priced from a MARKET LOOKUP rather than a supplier price: "
            + "; ".join(f"{i['part_number']} ({i['material']}) at £{i['gbp_per_m2']:.2f}/m2 "
                        f"from {i['source']}" for i in indicated[:4])
            + ". The line is costed, so the job is no longer under-charged by an invisible "
              "gap -- but NOBODY HAS AGREED TO THIS PRICE. It is a model's reading of the "
              "market, it may differ on the next run, and this job cannot be released as "
              "firm while it stands. Get a trade rate from Purchasing and it takes "
              "precedence automatically.",
            count=len(indicated), parts=indicated[:20]))
    if substituted:
        out.append(_violation(
            "material_priced_from_a_lower_ranked_reading", WARNING,
            f"{len(substituted)} part(s) were priced from a material other than the one "
            f"arbitration chose, because the chosen one has no rate: "
            + "; ".join(f"{s['part_number']} is recorded as {s['arbitrated']} and priced as "
                        f"{s['priced_as']} (from {s['from']})" for s in substituted[:4])
            + ". The figure is real and the MATERIAL IS UNCONFIRMED. An estimator must rule "
              "on which it is: if the recorded material is right, the price is wrong and the "
              "engine needs a rate for it.",
            count=len(substituted), parts=substituted[:20]))
    return out


def check_a_blank_and_its_cut_path_can_both_be_true(summary: Any) -> List[Dict[str, Any]]:
    """The cut path must fit inside the blank it was cut from.

    ON 12392 THE ENGINE HELD BOTH NUMBERS AND COMPARED THEM TO NOTHING. The back panel was
    recorded as a 16 x 3.7 blank and a 6,678mm cut path — six and a half metres of cutting
    inside a rectangle the size of a staple. It priced at GBP 0.01, the sheet claimed 5,865
    parts out of one 2500 x 1250, and the material total for a steel panel job came to GBP
    1.54. Nothing said a word, because each number is plausible on its own and only the pair
    is absurd.

    THE TEST IS AREA, NOT PERIMETER. Comparing cut length to the bounding perimeter looks
    obvious and is wrong in both directions: a disc's outline is shorter than its bounding
    box, and a legitimately busy panel has far more internal cutting than perimeter. What
    cannot happen is cut path that will not FIT — a length of line needs width to live in, so
    the blank's area divided by the total cut length is the average spacing between cuts, and
    below about a millimetre that is not a part, it is two readings of different things.

    WHICH ONE IS WRONG IS NOT DECIDED HERE. The blank may be in the wrong unit, or the cut
    length may have come from a different part. Both are real causes and the repair differs,
    so the violation states the contradiction and the ratio and leaves the reading to whoever
    can open the drawing. BLOCKING because the material price is computed from the blank: a
    job that reaches this state is not merely uncertain, it is quoting the wrong metal.
    """
    if not isinstance(summary, dict):
        return _unevaluated("blank_vs_cut_path", "This job is not a readable structure.")
    parts = _parts(summary)
    if not parts:
        return []

    impossible: List[Dict[str, Any]] = []
    conflicting: List[Dict[str, Any]] = []
    for part in parts:
        # THE BLANK THAT PRICED THE JOB, NOT WHICHEVER ONE THIS READER FINDS FIRST.
        #
        # _blank_num looks in part, normalized_geometry and geometry_rollup -- never in
        # material_estimate, which is what the costing writes and the workbook reads. On
        # 11650-01-05A DOOR that is the difference between 1202 x 689, the size that
        # actually produced the money (confirmed by the run's own "largest part 0.8282 m2",
        # which is 1.202 x 0.689), and 5 x 3.5, which priced nothing. This check blocked the
        # job over a blank the estimate had never used, and two separate diagnoses went
        # after a costing fault that did not exist.
        #
        # costed_facts.blank_dimensions is the one reader. It prefers material_estimate
        # because that is the record the money came from, and it REPORTS a disagreement
        # rather than resolving it out of sight -- two blanks on one part is a real defect
        # and it is reported below as itself, not as a cut path that does not fit.
        import costed_facts as _cf
        _blank = _cf.blank_dimensions(part)
        length = _blank["length_mm"] or 0.0
        width = _blank["width_mm"] or 0.0
        if _blank["conflict"]:
            conflicting.append({
                "part_number": part.get("part_number"),
                "readings": _blank["readings"],
                "priced_from": _blank["holder"],
            })
        cut = _blank_num(part, "cut_length_mm", "dxf_measured_cut_length",
                         "estimated_cut_length_mm", "total_cut_length_mm")
        # ONE DEFINITION OF IMPOSSIBLE, shared with the estimator that prices from the
        # blank. A private copy here would let this block a job the pricer had already
        # costed at a hundredth of its value — a second opinion nobody acted on, arriving
        # after the money was written down.
        import blank_credibility as _bc
        verdict = _bc.assess(length, width, cut)
        if not verdict["evaluated"] or verdict["credible"]:
            continue                      # nothing to compare; other checks own absence
        area = length * width
        room = _bc.cut_path_a_blank_could_hold_mm(length, width) or 0.0
        impossible.append({
            "part_number": part.get("part_number"),
            "blank_mm": [round(length, 2), round(width, 2)],
            "blank_area_mm2": round(area, 1),
            "cut_length_mm": round(cut, 1),
            # How much bigger the cut path is than the blank could hold. Named because "it
            # is wrong" is not actionable and "169 times" points straight at a unit error.
            "times_too_long": round(cut / room, 1) if room else None,
            "implied_cut_spacing_mm": round(area / cut, 4) if cut else None,
        })
    out: List[Dict[str, Any]] = []
    if conflicting:
        # TWO BLANKS ON ONE PART, SAID PLAINLY. Whichever is right, the record holds a
        # second size that some other reader will believe -- and did.
        _names = ", ".join(
            f"{c['part_number']} ("
            + " vs ".join(f"{r['length_mm']:g}x{r['width_mm']:g} in {r['holder']}"
                          for r in c["readings"][:3]) + ")"
            for c in conflicting[:4])
        out.append(_violation(
            "part_carries_two_different_blanks", BLOCKING,
            f"{len(conflicting)} part(s) have more than one blank size recorded, and the "
            f"readers of that record do not all look in the same place: {_names}. The money "
            f"was priced from the first named holder. A second size sitting on the same part "
            f"will be believed by whichever reader finds it first -- which is how a blocking "
            f"flag came to describe a blank this estimate never used.",
            count=len(conflicting), parts=conflicting[:20]))
    if not impossible:
        return out

    out.append(_violation(
        "blank_and_cut_path_disagree", BLOCKING,
        f"{len(impossible)} part(s) carry a cut path that will not fit inside the blank "
        f"recorded for them, so one of the two is wrong and the material is priced from the "
        f"blank: "
        + "; ".join(f"{p['part_number']} is {p['blank_mm'][0]:g} x {p['blank_mm'][1]:g} mm "
                    f"with a {p['cut_length_mm']:,.0f} mm cut path "
                    f"({p['times_too_long']:g}x more than it could hold, implying cuts "
                    f"{p['implied_cut_spacing_mm']:g} mm apart)"
                    for p in impossible[:6])
        + ". A blank in the wrong unit prices the metal at a fraction of its cost and puts "
          "an impossible number of parts on a sheet.",
        parts=impossible[:10], count=len(impossible)))
    return out


def check_an_assembly_is_not_charged_as_a_blank(summary: Any) -> List[Dict[str, Any]]:
    """A parent carrying its children's material or their single-blank operations.

    THE ANSWER WAS RIGHT AND THE READER WAS LOOKING AT A DIFFERENT FIELD. estimator.py
    records the defect in its own comment — "both suppressions here and in estimate_part
    keyed on is_assembly_parent, a different name for the same idea" — and 12120-01-103,
    correctly identified as a sub-assembly from the GA tree, was still given sheet material,
    a laser and a fold. 12392's panel assembly collected CNC routing, edge banding and
    laminating from an MDF title block on another sheet.

    So this asks the question at the end, where the four spellings have collapsed into one
    observable fact: does a record everything agrees is a parent still carry material money
    or a leaf operation? Both are double counts — the children carry them — and both are
    money, so BLOCKING.

    Joining and finishing are deliberately not asked about. Welding a parent is the work, and
    a welded frame is coated as one thing.

    AND IT ASKS THE WORKBOOK, NOT THE DRAWING. The first version read the operations sitting
    on the part record and blocked 12392 for CNC routing and edge banding on 12392-02-201 —
    on a run whose own log says "excluded canonical assembly parent: 12392-02-201 (material
    belongs to leaf children)" and whose priced rows charge that assembly nothing. The record
    carried a cue; the sheet had already refused it; the check called it money. A blocker
    that fires on evidence rather than on cost is noise in front of the real failures, and
    an estimator who learns to scroll past one learns to scroll past all of them.

    So a leaf operation counts only where a calculated labour row charges this part for it.
    Where no priced rows exist to read — a run that never reached the workbook — the check
    says so rather than falling back to the record and guessing.
    """
    if not isinstance(summary, dict):
        return _unevaluated("assembly_scope", "This job is not a readable structure.")
    parts = _parts(summary)
    if not parts:
        return []
    try:
        import bought_in_policy
    except Exception as exc:                                        # noqa: BLE001
        return _unevaluated("assembly_scope",
                            f"The assembly predicate could not be imported ({exc}).")

    # WHICH PARTS A CALCULATED LABOUR ROW ACTUALLY CHARGES, and for what. The rows name their
    # participants; a part absent from all of them is charged nothing whatever its record says.
    rows = _node(summary, "workbook_labour").get("rows")
    if not isinstance(rows, list):
        rows = (_node(summary, "final_estimate").get("labour_rows")
                if isinstance(_node(summary, "final_estimate").get("labour_rows"), list) else None)
    charged: Dict[str, set] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (_num(row.get("labour_cost_gbp")) or _num(row.get("total_value_gbp")) or 0.0) <= 0.005:
                continue                  # a row costing nothing charges nobody
            op = str(row.get("operation") or "").strip().lower()
            for who in (row.get("participants") or row.get("part_numbers") or []):
                charged.setdefault(str(who).strip().upper(), set()).add(op)

    offenders: List[Dict[str, Any]] = []
    for part in parts:
        if not bought_in_policy.is_assembly(part):
            continue
        # A MEASURED FLAT OUTRANKS A TRANSCRIBED TREE, and the estimator says so where it
        # decides. A part with its own geometry is a fabricated leaf whatever a hierarchy
        # called it, and claiming here would contradict the pass that priced it.
        if part.get("dxf_measured_outline") or part.get("native_flat_pattern") \
                or part.get("flat_pattern_detected"):
            continue
        money = _num(part.get("unit_material_cost_gbp")) or 0.0
        # Only what a priced row charges THIS part. Reading the record instead is what made
        # this a false blocker on a job the workbook had already got right.
        ops = sorted({op for op in charged.get(str(part.get("part_number") or "").strip().upper(), set())
                      if op in bought_in_policy.LEAF_ONLY_OPS})
        if money > 0.005 or ops:
            offenders.append({
                "part_number": part.get("part_number"),
                "reason_it_is_a_parent": bought_in_policy.assembly_reason(part),
                "material_gbp": round(money, 4) if money else 0.0,
                "leaf_operations": ops,
            })
    if not offenders:
        return []

    _money = sum(o["material_gbp"] for o in offenders)
    return [_violation(
        "assembly_charged_as_a_blank", BLOCKING,
        f"{len(offenders)} record(s) the hierarchy calls a parent still carry material or "
        f"single-blank operations that belong to their children"
        + (f", worth GBP {_money:,.2f} of material" if _money else "") + ": "
        + "; ".join(f"{o['part_number']} ({o['reason_it_is_a_parent']})"
                    + (f" GBP {o['material_gbp']:,.2f}" if o["material_gbp"] else "")
                    + (f" + {', '.join(o['leaf_operations'])}" if o["leaf_operations"] else "")
                    for o in offenders[:6])
        + ". Each is counted twice — once here and once on the parts it is made from.",
        parts=offenders[:10], count=len(offenders), material_gbp=round(_money, 2))]


def check_prices_are_firm(summary: Any) -> List[Dict[str, Any]]:
    """Is every applied price one we have actually committed to honour?

    REPRODUCIBLE AND FIRM ARE DIFFERENT QUESTIONS. A public distributor list price repeats
    perfectly and is still not a quote: no contract, no validity date, no commitment. Only
    an agreed rate, a live account feed, a written quotation, or a recent purchase is
    something to stand behind — and each of those only while it is unexpired.

    SEVERITY FOLLOWS INTENT AND COVERAGE, NOT A GLOBAL SWITCH. An estimate produced to inform
    is not lying when it uses a list price, so on an indicative job this is a warning. A job
    someone intends to send as a firm price is different, and there the answer depends on
    whether a firm-capable source for that MATERIAL exists at all:

        indicative                                  -> warning, always
        firm intent, class has a connector          -> BLOCKING: the price is missing or stale
        firm intent, class has no connector         -> BLOCKING: nothing could have been firm

    Those are different failures and deserve different sentences. Firm pricing arrives one
    supplier at a time, so a single constant flipped when the first feed lands would claim
    every other material was integrated too.
    """
    if not isinstance(summary, dict):
        return _unevaluated("price_firmness", "This job is not a readable structure.")
    stamps = list(price_provenance.iter_price_stamps_with_context(summary))
    if not stamps:
        return _unevaluated("price_firmness", "No priced lines carrying a stamp were found.")

    try:
        import config as _cfg
        coverage = dict(getattr(_cfg, "FIRM_PRICING_COVERAGE", {}) or {})
        default_intent = str(getattr(_cfg, "DEFAULT_QUOTE_INTENT", "indicative"))
    except Exception:
        coverage, default_intent = {}, "indicative"
    intent = str(summary.get("quote_intent") or _node(summary, "estimate_summary").get("quote_intent")
                 or default_intent).strip().lower()
    firm_intent = intent == "firm"

    import datetime
    today = datetime.date.today().isoformat()
    uncovered: List[Dict[str, Any]] = []
    unfirm: List[Dict[str, Any]] = []
    for _path, block, ctx in stamps:
        if not price_provenance.stamp_affects_total(block):
            continue
        # A LABOUR RATE IS NOT A SUPPLIER PRICE. Every operation on every part stamps its
        # rate, so on 12120 this check reported 83 lines of which 80 were labour — burying
        # the three that an estimator can actually do something about. Firmness is a question
        # about what we BUY: whether someone outside SDI has committed to a price and for how
        # long. Our own rate card is a different question with different governance, and
        # answering it here would make the advisory unreadable, which is how a check stops
        # being read at all.
        _sel = block.get("selected") if isinstance(block.get("selected"), dict) else {}
        if "labour" in str(_sel.get("kind") or "").lower() or "rate_sources" in _path:
            continue
        verdict = price_provenance.price_firmness(block, today=today)
        if verdict.get("firm"):
            continue
        mclass = price_provenance.material_class_of(ctx)
        line = {"part": ctx.get("part_number") or ctx.get("description"),
                "material_class": mclass, "class": verdict.get("class"),
                "reason": verdict.get("reason"), "where": _path}
        if firm_intent and not (coverage.get(mclass) or {}).get("firm_capable"):
            line["intended_source"] = (coverage.get(mclass) or {}).get("intended_source")
            uncovered.append(line)
        else:
            unfirm.append(line)

    def _by_reason(rows):
        out: Dict[str, int] = {}
        for r in rows:
            out[str(r["reason"])] = out.get(str(r["reason"]), 0) + 1
        return out

    out: List[Dict[str, Any]] = []
    if uncovered:
        _classes = sorted({str(r["material_class"]) for r in uncovered})
        _want = sorted({str(r.get("intended_source")) for r in uncovered if r.get("intended_source")})
        out.append(_violation(
            "no_firm_pricing_source", BLOCKING,
            f"This job is marked as a firm quote, but {len(uncovered)} applied price(s) are "
            f"in material class(es) with no firm-capable pricing source configured: "
            f"{', '.join(_classes)}"
            + (f" — intended source: {', '.join(_want)}" if _want else "")
            + ". Nothing on those lines could have been firm, whatever the price says.",
            lines=uncovered[:12], count=len(uncovered), material_classes=_classes))
    if unfirm:
        by_reason = _by_reason(unfirm)
        out.append(_violation(
            "price_not_firm", BLOCKING if firm_intent else WARNING,
            f"{len(unfirm)} applied price(s) are not something to stand behind: "
            + "; ".join(f"{v} because {k}" for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1]))
            + ". Reproducible is not the same as firm — a list price repeats perfectly and "
              "commits nobody. A firm quote needs an agreed rate, a live account feed, a "
              "written quotation, or a purchase still covered by an unexpired agreement."
            + ("" if firm_intent else " This job is an indicative estimate, so the figures "
                                      "stand; they are simply not a quote."),
            lines=unfirm[:12], count=len(unfirm), reasons=by_reason, quote_intent=intent))
    return out


def check_a_measured_plate_is_not_charged_for_folding(summary: Any) -> List[Dict[str, Any]]:
    """A part the model measured as flat must not carry a fold on the priced rows.

    12120's 04M is 60 x 34.04 x 1.5mm at 1.5mm gauge with a cut-list bend count of zero. The
    fold was stripped at extraction, stripped again at costing, and STILL arrived in the
    Fold 1.5mm group with GBP 0.16 of folding on it — because a 30-degree callout on the PDF
    re-inferred the operation after each strip, and the money was written before anyone
    looked again.

    Removing the op in more places is whack-a-mole; each new pass is another chance to
    re-add it. This asks the only question that matters, at the only point where it is
    settled: is the engine CHARGING to fold something it has measured as flat? Any future
    path that resurrects the op fails here, whatever route it took.
    """
    records = _parts(summary)
    holders = [h for h in (summary if isinstance(summary, dict) else {},
                           (summary or {}).get("estimate_summary") or {}) if isinstance(h, dict)]
    for holder in holders:
        for key in ("part_estimates", "parts"):
            v = holder.get(key)
            if isinstance(v, list):
                records = records + [p for p in v if isinstance(p, dict)]
    if not records:
        return _unevaluated("plate_not_folded", "No part records were found on this job.")

    # The verdict and the money can live on different records for the same part, so gather
    # both by part number before judging either.
    flat: Dict[str, Any] = {}
    folded: Dict[str, float] = {}
    for p in records:
        pn = str(p.get("part_number") or "").strip()
        if not pn:
            continue
        if p.get("native_flat_solid"):
            flat[pn] = True
        _costs = ((p.get("labour_estimate") or {}).get("costs_gbp")
                  or ((p.get("cost_breakdown") or {}).get("labour") or {}).get("costs_gbp") or {})
        if isinstance(_costs, dict):
            for op, val in _costs.items():
                if "fold" in str(op).lower() or "bend" in str(op).lower():
                    folded[pn] = max(folded.get(pn, 0.0), _num(val) or 0.0)
    bad = [{"part_number": pn, "folding_gbp": round(folded[pn], 2)}
           for pn in sorted(set(flat) & set(folded))]
    if not bad:
        return []
    return [_violation(
        "plate_charged_for_folding", BLOCKING,
        f"{len(bad)} part(s) the model measured as flat are being charged to fold: "
        f"{', '.join(b['part_number'] for b in bad)}. A part one thickness thick has nowhere "
        f"for a bend to be, so this is drawing text outvoting a measurement — and it reaches "
        f"the sheet as a Fold row and a press-brake setup that will not happen.",
        parts=bad, count=len(bad))]


def check_canonical_route_shadow(summary: Any) -> List[Dict[str, Any]]:
    """Report route-compiler discrepancies without changing the live gate during shadow mode.

    These become BLOCKING at cutover. While the workbook still renders legacy rows they are
    WARNINGs: the purpose of shadow mode is to expose every difference before changing a
    price, not to make an unused diagnostic prevent an otherwise valid estimate.
    """
    shadow = _node(summary, "canonical_route_shadow")
    if not shadow:
        return []
    workbook_labour = _node(summary, "workbook_labour")
    cutover = (
        shadow.get("mode") == "cutover"
        or workbook_labour.get("mode") == "canonical"
    )
    severity = BLOCKING if cutover else WARNING

    out: List[Dict[str, Any]] = []
    if shadow.get("compiler_error"):
        return [_violation(
            "canonical_route_compiler_failed", severity,
            f"The canonical route compiler failed: {shadow.get('compiler_error')}. "
            + (
                "The authoritative workbook route cannot be produced."
                if cutover else
                "Legacy pricing still stands; cutover is forbidden until this is resolved."
            ))]

    decisions = {
        str(item.get("decision_id")): item
        for item in (shadow.get("decisions") or [])
        if isinstance(item, dict) and item.get("decision_id")
    }
    for decision in decisions.values():
        if decision.get("status") == "unverified":
            # SAY WHICH KIND OF UNVERIFIED, BECAUSE THEY NEED DIFFERENT ACTIONS.
            #
            # This asserted "contains conflicts" for EVERY unverified decision. The predicate
            # above is status alone; the conflicts list is attached as detail and is often
            # empty. route_compiler sets UNVERIFIED in two places that involve no conflict at
            # all (~2063, ~2073): a leaf whose finish says SEE ASSEMBLY and no extracted route
            # owns it, and an unattributed operation stranded on an assembly record. Both mean
            # NOBODY IN THIS PACK CLAIMS TO PERFORM THE WORK -- which is a question for the
            # drawing office, not a tie between competing readings for us to settle.
            #
            # All six of 11650's blockers are the second kind. An estimator told "conflicts"
            # goes looking for two claims to choose between and finds none.
            _conflicts = decision.get("conflicts") or []
            _why = (
                (f"has {len(_conflicts)} conflicting claim(s) at equal rank and cannot be "
                 f"priced automatically.")
                if _conflicts else
                ("is UNOWNED: nothing in this pack says who performs it. The drawing names "
                 "the work and no route claims it, so pricing it would be a guess about "
                 "which assembly does the job -- and could charge it twice. NOT a tie "
                 "between readings: there is no second reading. ASK WHO PERFORMS THIS.")
            ) if cutover else (
                f"has {len(_conflicts)} equal-ranked or metadata conflict(s). Legacy pricing "
                f"still stands." if _conflicts else
                "is UNOWNED -- nothing claims to perform it. Legacy pricing still stands."
            )
            out.append(_violation(
                "canonical_route_decision_unverified", severity,
                f"Route decision {decision.get('decision_id')} for "
                f"{decision.get('operation')} on {decision.get('target_id')} " + _why,
                decision_id=decision.get("decision_id"),
                operation=decision.get("operation"),
                target_id=decision.get("target_id"),
                conflicts=decision.get("conflicts") or []))

    seen_rows: Dict[str, int] = {}
    for row in shadow.get("priced_route_rows") or []:
        if not isinstance(row, dict):
            continue
        decision_id = str(row.get("decision_id") or "")
        seen_rows[decision_id] = seen_rows.get(decision_id, 0) + 1
        decision = decisions.get(decision_id)
        if not decision:
            out.append(_violation(
                "priced_route_row_without_decision", severity,
                f"A shadow priced route row for {row.get('operation')} has no canonical "
                "OperationDecision. It cannot be used at cutover.",
                row=row))
        elif decision.get("status") != "required":
            out.append(_violation(
                "non_required_decision_has_priced_row", severity,
                f"Decision {decision_id} is {decision.get('status')} but produced a shadow "
                "priced row. A ruled-out operation must never reach pricing.",
                decision_id=decision_id, row=row))
    for decision_id, count in seen_rows.items():
        if decision_id and count > 1:
            out.append(_violation(
                "decision_joined_to_multiple_priced_rows", severity,
                f"Decision {decision_id} joined to {count} shadow priced rows. One job event "
                "must produce at most one route row.",
                decision_id=decision_id, row_count=count))

    if not cutover:
        important_codes = {
            "forbidden_decision_priced",
            "required_operation_unpriced",
            "assembly_operation_costed_on_multiple_participants",
            "legacy_cost_maps_multiple_decisions",
            "legacy_cost_without_canonical_decision",
            "assembly_scope_without_target",
            "bom_node_disconnected",
            "bom_leaf_without_estimate",
        }
        for issue in shadow.get("issues") or []:
            if not isinstance(issue, dict) or issue.get("code") not in important_codes:
                continue
            out.append(_violation(
                f"canonical_route_{issue.get('code')}", WARNING,
                f"Shadow route comparison found {issue.get('code')}. Legacy pricing still "
                "stands; this must be resolved before workbook cutover.",
                issue=issue))
        return out

    for issue in shadow.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if issue.get("code") in {
            "assembly_scope_without_target", "bom_node_disconnected",
            "bom_leaf_without_estimate",
        }:
            # NAME THE THING. The compiler records which part it means; this message did not
            # render it, so a blocking failure read as "something in this job has no owner"
            # and the only way to learn WHICH was to open the JSON. A blocker nobody can act
            # on from what it says costs a run every time it fires — and it has fired on
            # every run of this job. The identity is in the same dict the detail already
            # carried; it simply never reached the sentence.
            _bits = [str(issue.get(k)) for k in ("part_number", "kind", "description")
                     if str(issue.get(k) or "").strip()]
            _who = " / ".join(_bits) if _bits else "an unnamed node"
            # AND WHICH FIX IT NEEDS. A stem of a longer code on the same job is a truncated
            # read, not a part — the repair is to stop creating it, and pointing at the
            # fuller code says so without anyone opening the JSON. A node the extract never
            # saw is a phantom from somewhere else. A node both sources carry is a real part
            # nobody claimed, which is the only case an ownership edge fixes.
            _stems = [str(s) for s in (issue.get("longer_codes_sharing_this_stem") or [])]
            _stated = str(issue.get("stated_parent_part_number") or "")
            if _stated and issue.get("stated_parent_is_a_known_node"):
                # NOT A MISSING FACT, AN UNREAD ONE. The record names its owner and the
                # graph did not join on it. That is a wiring fault in the compiler, not a
                # gap in the drawing, and it is the only case where the repair is upstream
                # of the hierarchy rather than in it.
                _why = (f" Its own record already states parent {_stated}, which IS a node "
                        f"in this job — the owner was read from the drawing and the graph "
                        f"did not join on it. Fix the join, not the hierarchy.")
            elif _stated:
                _why = (f" Its record states parent {_stated}, which is not a node in this "
                        f"job — the owner was read under a code the graph does not know.")
            elif _stems:
                _why = (f" It is a prefix of {', '.join(_stems)} on this same job, which is "
                        f"the signature of a TRUNCATED code rather than a real part — the "
                        f"fix is to stop creating it, not to give it a parent.")
            elif issue.get("in_raw_records") and not issue.get("in_extract"):
                _why = (" It appears in the raw part records and NOT in the extract, so it "
                        "was invented downstream of the drawing read — check what created "
                        "it before giving it an owner.")
            elif issue.get("in_extract"):
                _why = (" Both the raw records and the extract carry it, so it is a real "
                        "part that no assembly claimed. It needs an ownership edge.")
            else:
                _why = ""
            out.append(_violation(
                f"canonical_route_{issue.get('code')}", BLOCKING,
                f"Canonical BOM/route compilation found {issue.get('code')} on "
                f"{_who} — it has no defensible owner in the job hierarchy.{_why}",
                issue=issue))

    required_ids = {
        decision_id for decision_id, decision in decisions.items()
        if decision.get("status") == "required"
    }
    non_required_ids = set(decisions) - required_ids
    accepted_rows = workbook_labour.get("rows") or []
    accepted_counts: Dict[str, int] = {}
    rows_without_decision = []
    forbidden_rows = []
    for row in accepted_rows:
        if not isinstance(row, dict):
            continue
        decision_ids = [
            str(item) for item in (row.get("decision_ids") or [])
            if str(item)
        ]
        if not decision_ids and row.get("decision_id"):
            decision_ids = [str(row.get("decision_id"))]
        if not decision_ids:
            rows_without_decision.append(row.get("workbook_row"))
            continue
        for decision_id in set(decision_ids):
            accepted_counts[decision_id] = accepted_counts.get(decision_id, 0) + 1
            if decision_id in non_required_ids or decision_id not in decisions:
                forbidden_rows.append({
                    "workbook_row": row.get("workbook_row"),
                    "decision_id": decision_id,
                })

    missing = sorted(required_ids - set(accepted_counts))
    duplicated = sorted(
        decision_id for decision_id, count in accepted_counts.items()
        if count > 1
    )
    if rows_without_decision:
        out.append(_violation(
            "canonical_workbook_row_without_decision", BLOCKING,
            f"{len(rows_without_decision)} accepted workbook route row(s) have no canonical "
            "decision identity.",
            workbook_rows=rows_without_decision))
    if forbidden_rows:
        out.append(_violation(
            "canonical_non_required_decision_priced", BLOCKING,
            f"{len(forbidden_rows)} workbook route row(s) reference a ruled-out, "
            "not-applicable, unverified or unknown decision.",
            rows=forbidden_rows))
    if missing:
        out.append(_violation(
            "canonical_required_decision_not_rendered", BLOCKING,
            f"{len(missing)} required route decision(s) did not reach the workbook.",
            decision_ids=missing))
    if duplicated:
        out.append(_violation(
            "canonical_decision_rendered_more_than_once", BLOCKING,
            f"{len(duplicated)} route decision(s) reached more than one workbook row.",
            decision_ids=duplicated))
    return out


def check_an_operation_is_not_charged_on_a_parent_and_its_child(
        summary: Any) -> List[Dict[str, Any]]:
    """POWDER COATED AS A PART, AND AGAIN AS THE ASSEMBLY THAT CONTAINS ONLY IT.

    12422-24 charges P.Coat on 12422-24-102 inside a group of four, and again on 05M on its
    own row. The SolidWorks tree says 102 holds 05M and nothing else. Either the shop coats
    the parts and then the assembly — two real events — or one of those rows is the same
    metal through the oven twice.

    NOT A VERDICT. Coating before and after assembly is a real process, and this check has
    no way to know which the shop does. It is a WARNING because the answer is the estimator's
    and the cost of it being wrong is not small: on this job, ruling one way removes about
    GBP 10 per unit and the other about GBP 1.12.

    It exists because nothing said so. The tree that makes this visible only started
    applying today, and until an operation's participants could be tested against the
    hierarchy, a parent and its own child sitting in one route looked like four parts.
    """
    if not isinstance(summary, dict):
        return []
    # THE TREE, FROM WHEREVER IT WAS READ. The native extract stamps its own; the parts carry
    # whatever every hierarchy source agreed on. Unioned, because this asks only "is one of
    # these the ancestor of another", which no single source has to answer alone.
    children: Dict[str, set] = {}
    _sw = (summary.get("solidworks_native") or {}).get("hierarchy") or {}
    for parent, kids in _sw.items():
        for kid in (kids or []):
            code = kid[0] if isinstance(kid, (list, tuple)) and kid else kid
            if str(code or "").strip():
                children.setdefault(str(parent).upper(), set()).add(str(code).upper())
    for part in ((summary.get("manufacturing_writeup") or {}).get("parts") or []):
        if not isinstance(part, dict):
            continue
        for kid in (part.get("assembly_children") or []):
            if str(kid or "").strip():
                children.setdefault(
                    str(part.get("part_number") or "").upper(), set()).add(str(kid).upper())
    if not children:
        return []

    def _descendants(code: str, seen: Optional[set] = None) -> set:
        seen = seen if seen is not None else set()
        out: set = set()
        for kid in children.get(code, set()):
            if kid in seen:
                continue
            seen.add(kid)
            out.add(kid)
            out |= _descendants(kid, seen)
        return out

    # ACROSS EVERY ROW OF ONE OPERATION, NOT WITHIN A SINGLE ROW.
    #
    # The first version of this tested participants inside one decision, and 12422-24 is
    # precisely the case it therefore missed: P.Coat is TWO rows — 102 grouped with three
    # brackets, and 05M on its own — so the parent and its child never appeared in the same
    # list. The check reported nothing on the job it was written for.
    #
    # The question is "is this operation charged on an item and on something that item
    # contains", and an operation is the set of all its rows. Grouped by operation name,
    # which is what the workbook prices by.
    shadow = _node(summary, "canonical_route_shadow")

    # A DECISION IS NOT A CHARGE. This bucketed EVERY decision on the job, whatever its
    # status and whether or not it ever produced a priced row — so on 12392 it reported
    # folding and laser_cutting as "charged on 12392-02-201" against a workbook whose Fold
    # and Laser rows list only (01M, 02M) and (04-01M, 04-02M). 201 appears in one
    # Assemble/pack row and nowhere else.
    #
    # Ruled-out decisions are the point of the ruling: a NOT_APPLICABLE powder claim exists
    # precisely so the reason survives, and counting it as money undoes that. Same defect
    # class as check_an_assembly_is_not_charged_as_a_blank had, one check along, and the same
    # answer: ask the priced rows.
    _priced_ids = {str(r.get("decision_id") or "")
                   for r in (shadow.get("priced_route_rows") or [])
                   if isinstance(r, dict)}
    _priced_ids.discard("")

    by_operation: Dict[str, Dict[str, Any]] = {}
    for decision in (shadow.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        # A decision that STATES a status other than required is ruled out. One that states
        # none is not: some writers do not set the field, and requiring it would silently
        # blind this check on those paths — the failure direction that matters here, because
        # the thing it guards is metal through the oven twice.
        _status = str(decision.get("status") or "").strip().lower()
        if _status and _status != "required":
            continue
        # Where priced rows exist, a decision counts only if one of them joined to it. Where
        # none exist at all — a run that never reached the workbook — required status is the
        # best evidence available, and that is still narrower than counting everything.
        if _priced_ids and str(decision.get("decision_id") or "") not in _priced_ids:
            continue
        op = str(decision.get("operation") or "").strip()
        if not op:
            continue
        bucket = by_operation.setdefault(op, {"parts": set(), "ids": []})
        bucket["parts"] |= {str(p).upper() for p in (decision.get("participants") or []) if p}
        if decision.get("decision_id"):
            bucket["ids"].append(str(decision.get("decision_id")))

    out: List[Dict[str, Any]] = []
    for op, bucket in sorted(by_operation.items()):
        parts_in = bucket["parts"]
        if len(parts_in) < 2:
            continue
        for candidate in sorted(parts_in):
            overlap = sorted(_descendants(candidate) & (parts_in - {candidate}))
            if not overlap:
                continue
            decision = {"operation": op, "decision_id": ", ".join(bucket["ids"][:6])}
            out.append(_violation(
                # UNVERIFIED, NOT A WARNING. Pricing both is a decision the engine cannot
                # defend, and a warning lets it be quoted firm anyway. Unverified says the
                # check could not settle it — the figures stand, the quote does not.
                # Not BLOCKING: staged finishing is a real process, and refusing to price a
                # job that legitimately coats twice would be a wrong answer of its own.
                "operation_charged_on_a_parent_and_its_child", UNVERIFIED,
                f"{decision.get('operation') or 'An operation'} is charged on "
                f"{candidate} and separately on {', '.join(overlap)}, which the job "
                f"hierarchy says {candidate} contains. Either the shop does this before AND "
                f"after assembly — two real events — or the same item is being charged "
                f"twice. An estimator must rule; the engine cannot.",
                operation=decision.get("operation"),
                assembly=candidate, descendants=overlap,
                decision_id=decision.get("decision_id")))
    return out


def check_the_pack_contains_the_drawings_its_bom_names(summary: Any) -> List[Dict[str, Any]]:
    """A BOM line naming a drawing this pack does not contain is UNREAD, not free.

    Job 11650's cabinet costed at GBP 7.37 a unit with GBP 1.81 of material, on a fragrance
    coffret cabinet at 45 off. Nothing was broken. The GA's bill of materials is
    11650-01-GA, 11650-02-GA and 11650-03-GA -- three sub-assemblies whose detail drawings
    are not in the folder. The engine correctly declined to charge material on an assembly
    parent, correctly found no leaves to charge it on, and produced a number that looks
    exactly like a finished estimate for a nearly empty one.

    That is the worst shape a wrong answer can take here, and it is not a pricing failure:
    every individual decision was right. The pack is incomplete, and only a check that
    compares what the BOM NAMES against what the pack CONTAINS can say so.

    WHAT COUNTS AS CONTAINED. A drawing is present if any page in this job names it -- the
    same title-block reading the hierarchy is built from -- or if a part record carries
    measured geometry for it. Either means somebody read the thing itself.

    WHAT IS NOT ASKED. Bought-in lines name catalogue items, not drawings: a fastener, a
    lock, a knurled knob has no detail sheet in the pack and never will. Only codes that
    look like SDI drawing numbers are considered, through part_code_conventions, so the
    rule cannot drift from what the rest of the engine calls a drawing.

    BLOCKING, because a missing child is missing MONEY and the total reads as complete. An
    estimator who sees GBP 7.37 and no blocker has been told the cabinet is cheap.
    """
    if not isinstance(summary, dict):
        return _unevaluated("pack_completeness", "This job is not a readable structure.")

    rows = _node(summary, "document_analysis").get("bom_rows")
    if not isinstance(rows, list) or not rows:
        # No BOM to check against. check_both_bom_readers_ran owns that failure; saying
        # nothing here is right, and saying "clean" would be a lie about a job with no BOM.
        return []

    try:
        import part_code_conventions as pcc
    except Exception as exc:                                        # noqa: BLE001
        return _unevaluated("pack_completeness",
                            f"The drawing-number convention could not be imported ({exc}).")

    def _bare(code: Any) -> str:
        return str(pcc.bare_code(code) or "").strip().upper()

    # EVERYTHING THIS PACK DEMONSTRABLY READ. A page that names a drawing was read; a part
    # carrying measured geometry was read. Both are recorded already.
    present = set()
    for page in (summary.get("pages") or []):
        if not isinstance(page, dict):
            continue
        for key in ("drawing_number", "page_drawing_number"):
            if page.get(key):
                present.add(_bare(page[key]))
        tb = ((page.get("page_analysis") or {}).get("title_block") or {})
        for value in (tb.get("drawing_numbers") or []):
            present.add(_bare(value))
    for part in _parts(summary):
        code = _bare(part.get("part_number"))
        if not code:
            continue
        _geom = part.get("geometry_rollup") or {}
        if (part.get("blank_length_mm") or part.get("normalized_thickness_mm")
                or _geom.get("estimated_cut_length_mm") or part.get("flat_pattern_detected")):
            present.add(code)
    present.discard("")

    missing = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("part_number") or "").strip()
        if not code or not pcc.looks_like_a_drawing_number(code):
            continue
        if _bare(code) in present:
            continue
        # A MIRROR HAS NO DRAWING OF ITS OWN. "11350-01-02 MIR" and 11650's
        # "11650-04-01A-HANDED" are the other hand of a part detailed on ONE sheet; the
        # pack is complete when that sheet is present. Asking for a drawing that was never
        # going to exist would put a blocker on every handed pair in the system, and a
        # blocker that fires on correct packs is how estimators learn to scroll past all of
        # them.
        _seed = pcc.mirror_base(code)
        if _seed and _bare(_seed) in present:
            continue
        missing.append({"part_number": code,
                        "description": str(row.get("description") or "").strip(),
                        "quantity": row.get("quantity"),
                        "named_by": str(row.get("bom_parent") or "").strip()})

    if not missing:
        return []

    _named = ", ".join(f"{m['part_number']}"
                       + (f" ({m['description']})" if m["description"] else "")
                       for m in missing[:6])
    _more = f" and {len(missing) - 6} more" if len(missing) > 6 else ""
    return [_violation(
        "bom_names_a_drawing_the_pack_does_not_contain", BLOCKING,
        f"{len(missing)} bill-of-materials line(s) name a drawing that is not in this pack: "
        f"{_named}{_more}. Nothing read those parts, so nothing costed them -- and the "
        f"total still reads as a finished estimate. This is an incomplete pack, not a cheap "
        f"job: ask for the missing detail drawings before quoting.",
        missing=missing, count=len(missing))]


def check_the_quantity_costed_is_the_quantity_ordered(summary: Any) -> List[Dict[str, Any]]:
    """THE HEADER SAID 10 AND THE MATHS SAID 180.

    --order-qty was applied to the summary AFTER the scan returned, and by then every part
    had been costed. Setup is amortised as (rate/60 x setup_mins) / qty, so the setup
    component of every operation was spread over the default batch and then presented under
    a ten-off heading. Nothing was wrong on the face of the estimate: the quantity shown
    was the quantity asked for, and it was not the quantity used.

    A price that was computed for a different batch than the one it is labelled with is a
    wrong price, not a caveat — and it is invisible unless someone compares the two numbers.
    labour_estimate.job_quantity_used is what the amortisation ACTUALLY divided by, recorded
    by the calculation itself rather than by anything that describes it afterwards.

    Parts with no labour at all (bought-in lines) carry no such number and are not evidence
    either way; they are excluded rather than counted as agreeing. A part that DID charge
    labour and does not say what batch it charged it over is a different matter — that is
    the check being unable to run, and it fails closed.
    """
    if not isinstance(summary, dict):
        return []
    header = (summary.get("quantity")
              or summary.get("assumed_job_quantity")
              or (summary.get("estimate_summary") or {}).get("assumed_job_quantity"))
    try:
        header = int(header) if header is not None else None
    except (TypeError, ValueError):
        header = None

    rows = ((summary.get("estimate_summary") or {}).get("part_estimates")
            or summary.get("part_estimates") or [])
    used: Dict[int, List[str]] = {}
    silent: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lab = row.get("labour_estimate") or {}
        # ONLY A ROW THAT CHARGED LABOUR HAS AN OPINION ABOUT THE BATCH. A bought-in line
        # is bought at a price, not made over a run, and demanding an amortisation quantity
        # from it would turn every hardware row into an unverified job.
        charged = (_num(lab.get("total_labour_cost_gbp")) or _num(lab.get("unit_labour_cost_gbp"))
                   or _num(lab.get("extended_labour_cost_gbp")) or 0.0)
        if not charged and not (lab.get("costs_gbp") or {}):
            continue
        qty_used = lab.get("job_quantity_used")
        if qty_used is None:
            silent.append(str(row.get("part_number") or "?"))
            continue
        try:
            qty_used = int(qty_used)
        except (TypeError, ValueError):
            silent.append(str(row.get("part_number") or "?"))
            continue
        used.setdefault(qty_used, []).append(str(row.get("part_number") or "?"))

    if silent:
        return _unevaluated(
            "quantity_costed",
            f"{len(silent)} part(s) charged labour without recording the quantity their "
            f"setup was amortised over, so the batch the price was computed for cannot be "
            f"compared with the batch it is presented as.",
            parts=silent[:12])
    if not used:
        return []
    if header is None:
        return _unevaluated(
            "quantity_costed",
            f"The parts were costed at {sorted(used)} off but the job states no quantity, "
            "so there is nothing to check the costing against.")

    out: List[Dict[str, Any]] = []
    # THE NUMBER THE DOCUMENTS RENDER. The client quote takes its "Order quantity" from
    # estimate_workbook_inputs, which carried the WORKBOOK DEFAULT — so a job costed at 10
    # went out saying "180 off" beside the ten-off price. The quantity being right in the
    # calculation is not the same as it being right on the page a customer reads, and this
    # is the only check that looks at the page.
    _rendered = ((summary.get("estimate_summary") or {}).get("estimate_workbook_inputs")
                 or {}).get("assumed_job_quantity")
    try:
        _rendered = int(_rendered) if _rendered is not None else None
    except (TypeError, ValueError):
        _rendered = None
    if _rendered is not None and header is not None and _rendered != header:
        out.append(_violation(
            "quantity_rendered_is_not_quantity_costed", BLOCKING,
            f"The client quote and workbook inputs state {_rendered} off while the job was "
            f"costed at {header} off. The price is for one batch and the document names "
            f"another — do not issue it.",
            rendered_quantity=_rendered, costed_quantity=header))

    wrong = {q: pns for q, pns in used.items() if q != header}
    if wrong:
        out.append(_violation(
            "quantity_costed_is_not_quantity_ordered", BLOCKING,
            f"The job is presented as {header} off, but "
            f"{sum(len(v) for v in wrong.values())} part(s) were costed with setup "
            f"amortised over {sorted(wrong)} off. Every labour figure on those lines is "
            f"for a different batch than the one being quoted.",
            header_quantity=header,
            costed_quantities={str(q): v[:12] for q, v in sorted(wrong.items())}))
    # MORE THAN ONE BATCH INSIDE ONE JOB is wrong even where one of them matches the
    # header — the lines cannot be added together as a per-unit price.
    if len(used) > 1:
        out.append(_violation(
            "quantity_costed_is_not_uniform", BLOCKING,
            f"Different parts of this job were costed over different batch quantities "
            f"({sorted(used)}), so their per-unit labour cannot be summed.",
            costed_quantities={str(q): v[:12] for q, v in sorted(used.items())}))
    return out



# Finishes the engine can actually cost. Anything else a drawing states is real work with
# no rate behind it, and the sheet charges nothing for it.
_COSTABLE_FINISH_OPS = ("p.coat", "powder", "diamond polish", "polish", "peel")
_COSTABLE_FINISH_OPS_UPPER = tuple(w.upper() for w in _COSTABLE_FINISH_OPS)

# Words that name a finish PROCESS on a drawing. Deliberately not "any finish text": a
# finish field reading RAW or SELF COLOUR states that there is no finish, and flagging
# those would put a warning on every bare-metal job in the system.
_FINISH_PROCESS_WORDS = (
    "VINYL", "PAINT", "SPRAY", "LACQUER", "LAMINATE", "VENEER", "FOIL", "PRINT",
    "ANODIS", "ANODIZ", "PLATE", "PLATED", "GALVANIS", "CHROME", "BRUSHED",
    "ETCH", "WRAP", "FILM",
)
# SHEENS ARE NOT PROCESSES. GLOSS, MATT, SATIN and SILK were in the list above and every
# powder finish SDI writes says "POWDER COATED - MATT". 11650's cabinet fired this check on
# ten powder-coated steel parts whose P.Coat row was costed on the same sheet -- the exact
# cry-wolf failure this check was written to avoid. A sheen qualifies a finish; it is never
# the finish.
_FINISH_SHEEN_WORDS = ("GLOSS", "MATT", "SATIN", "SILK", "TEXTURE", "TEXTURED")

# A FINISH FIELD THAT POINTS SOMEWHERE ELSE NAMES NO WORK. "SEE ASSEMBLY DRAWING" is on ten
# parts of 11650 and is a cross-reference, not a process; whether the thing it points at was
# followed is a different check's question.
_FINISH_POINTER_WORDS = ("SEE ", "AS PER", "REFER", "PER DRAWING", "PER DWG", "AS DRAWING")

# A finish field stating there is NO finish. These carry no process word either, so the
# process-word requirement already excluded them from the uncostable list -- but the
# UNRECOGNISED bucket below has no such requirement by design, and would flag every bare
# steel part in the system without them.
_NO_FINISH_WORDS = ("RAW", "SELF COLOUR", "SELF-COLOUR", "MILL FINISH", "AS ROLLED",
                    "NONE", "N/A", "UNSPECIFIED", "FINISH-UNSPECIFIED", "UNFINISHED",
                    "BARE", "PLAIN")


def _states_no_finish(text: str) -> bool:
    """True when the finish field says there ISN'T one.

    WHOLE WORDS. A substring test made "SEE ASSEMBLY DRAWING" state that it has no finish,
    because RAW is inside DRAWING -- so ten parts of 11650 were filtered by the right verdict
    for a completely wrong reason, and a mutation that deleted the rule which SHOULD have
    caught them changed nothing. An accidental match is worse than a miss: it hides the miss.
    """
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in _NO_FINISH_WORDS)

# The list above must never name a finish the engine CAN cost, or a correctly-costed powder
# job reports itself as supplied free. Asserted at import so it cannot drift quietly.
assert not any(w in _FINISH_PROCESS_WORDS for w in ("POWDER", "DIAMOND", "POLISH", "PEEL")), \
    "a costable finish is in the uncostable list -- powder jobs will report as free"
# And the two lists that decide the UNRECOGNISED bucket must not overlap each other, or a
# finish would be simultaneously "no finish at all" and "a process we cannot cost".
assert not (set(_NO_FINISH_WORDS) & set(_FINISH_PROCESS_WORDS)), \
    "a word means both 'no finish' and 'an uncostable process'"
# NO "_NO_FINISH_WORDS" LIST. There was one -- RAW, SELF COLOUR, MILL FINISH, AS ROLLED --
# and a mutation proved it never fired: none of those strings contains a finish PROCESS
# word, so requiring a process word already excludes every one of them. A second rule that
# can only agree with the first is not a safety net, it is a thing to keep in step with no
# way to notice when it drifts. The tests for RAW and SELF COLOUR stay, and now prove the
# process-word requirement is what does the work.



# A FINISH FIELD HOLDING RAW DRAWING TEXT IS A FAILED READ, NOT A FINISH.
#
# 11650-04-03A's finish came back as "TO MATCH THE MAIN PANEL A A B B MAKE AS HANDED PAIR
# FILM SIDE DENOTES WHICH HAND C C 4 X 6.2 THRU 30 211 164 D D E E". That is the drawing's
# text, scraped whole: a note, the view labels down both margins, a hole callout, and three
# bare dimensions. It is not a statement of finish and must not be read as one.
#
# It matters twice over. It made check_a_stated_finish_is_costed fire on "FILM" -- from
# "FILM SIDE DENOTES WHICH HAND", which is about the protective film's orientation -- and a
# check that cries wolf on garbled text is a check estimators learn to ignore. And the
# numbers in it are the more interesting half: see check_a_finish_field_holds_drawing_text.
_DIM_CALLOUT = re.compile(r"\d+\s*[Xx]\s*\d|\bTHRU\b|\bR\d|\bDIA\b|\u00f8")
_VIEW_LABEL = re.compile(r"(?:\b[A-E]\b[\s]+){4,}")


def _looks_like_raw_drawing_text(text: str) -> bool:
    """True when a finish field holds scraped drawing text rather than a finish."""
    t = str(text or "").upper()
    if not t.strip():
        return False
    if _DIM_CALLOUT.search(t):
        return True
    if _VIEW_LABEL.search(t):
        return True
    # Three or more bare numbers in a finish field is a dimension list, not a finish.
    return len(re.findall(r"\b\d{2,4}\b", t)) >= 3


def check_a_stated_finish_is_costed(summary: Any) -> List[Dict[str, Any]]:
    """A finish the drawing states and the sheet charges nothing for.

    POWDER IS THE ONLY FINISH THIS ENGINE CAN COST. That is fine for steel and wrong for
    everything else, and the gap is invisible because the two halves look correct
    separately: the non-metal rule correctly refuses to powder-coat a plastic, and the
    route correctly contains no powder operation -- so nothing is flagged, and a stated
    finish is silently free.

    11650-05 is the live case. Its side panels state "1/2 INCH REEDED VINYL + UV OR CLEAR
    VINYL". The engine read that, printed it as an observation, and costed Laser, Manual
    labour and Assemble/pack. There is no vinyl operation in the vocabulary, no rate for
    one, and no line on the sheet. The vinyl is free.

    THIS IS THE SHAPE THAT MATTERS FOR BOARD AND PLASTIC GENERALLY. Powder coating is an
    oven process and metals only; paint, vinyl, laminate, print and foil are applied to
    wood, MDF, acrylic and PETG every day. Ruling powder out on a non-metal is right;
    leaving nothing in its place is an under-charge that grows with every non-metal job.

    NOT AN INVENTED RATE. This check does not guess what the finish costs -- there is no
    measured rate for it, and inventing one would be worse than the gap. It says the work
    was named and not charged, and puts it in front of the estimator.
    """
    try:
        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
        # THE KEY THIS READS MUST BE ONE SOMETHING WRITES. The first version asked for
        # "workbook_route_rows", which nothing in the engine produces -- so `priced` was
        # ALWAYS empty, finish_is_costed was ALWAYS False, and the check fired on every
        # stated finish whether or not the sheet charged for it. Built is not wired, in the
        # check written to catch exactly that. The readback stamps the priced route at
        # final_estimate.labour_rows, which is where the unpriced-line check already looks.
        priced = (((summary.get("estimate_summary") or {}).get("final_estimate") or {})
                  .get("labour_rows") or [])
    except AttributeError:
        return [_violation(
            "stated_finish_not_costed", UNVERIFIED,
            "the summary could not be read, so this check verified nothing")]
    if not parts:
        return []

    costed_ops = " ".join(
        str(r.get("operation") or r.get("op") or r.get("operation_name")
            or r.get("description") or "")
        for r in priced if isinstance(r, dict)).lower()
    finish_is_costed = any(op in costed_ops for op in _COSTABLE_FINISH_OPS)

    uncosted, unrecognised = [], []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = " ".join(str(x) for x in (
            part.get("normalized_finish"), part.get("surface_finish"),
            " ".join(str(v) for v in (part.get("surface_finishes") or []))
        ) if x).upper()          # skip absent fields: str(None) puts "NONE" in the message,
                                 # which then reads as the finish being called None
        if not text.strip():
            continue
        if _looks_like_raw_drawing_text(text):
            continue        # not a finish statement; check_a_finish_field_holds_drawing_text
                            # reports it, and claiming an uncosted finish here would be a
                            # warning raised on a word that is not a finish at all
        named = [w for w in _FINISH_PROCESS_WORDS if w in text]
        if not named and any(w in text for w in _FINISH_SHEEN_WORDS):
            continue        # a sheen with no process word names no work of its own
        # PER PART, NOT PER JOB. This asked "is ANY costable finish on this route?" and
        # went silent for the whole job if one was. 11650's cabinet costs P.Coat on its
        # steel, so the vinyl on its PETG panels got a free pass -- the under-charge this
        # check exists to find, hidden by a different part being finished properly.
        #
        # _FINISH_PROCESS_WORDS is already the set of processes this engine has NO rate
        # for; powder and diamond polish are deliberately absent. So naming one is
        # sufficient on its own and the job-level flag is not consulted.
        if named:
            uncosted.append({"part_number": part.get("part_number"),
                             "finish": text[:80], "words": named[:3]})
            continue
        # A FINISH THIS ENGINE HAS NEVER HEARD OF IS NOT A FINISH THAT IS FREE.
        #
        # Everything above is a WHITELIST: costable ops, uncostable processes we already know
        # about, sheens. A finish matching none of them produced no cost AND no flag, so the
        # vocabulary's own gaps were invisible. 11650-01-05A DOOR states "UV HARDCOAT ALL
        # SIDES" -- not powder, not vinyl, not a sheen -- and it went through this check, the
        # route and the sheet without one word about it.
        #
        # Naming it does not decide what it is, and deliberately so. An unrecognised finish
        # may be a shop process nobody has costed, or a property of the sheet we BUY -- UV
        # hardcoat arrives on polycarbonate from the mill, so it belongs in the material rate
        # and not in the route, and adding a labour line for it would invent work SDI does
        # not do. The engine cannot tell those apart. An estimator can, in seconds, once it
        # is in front of them.
        if any(w in text for w in _FINISH_POINTER_WORDS):
            continue
        if _states_no_finish(text):
            continue
        if any(w in text for w in _COSTABLE_FINISH_OPS_UPPER):
            continue                    # costable and costed, or costable and caught above
        unrecognised.append({"part_number": part.get("part_number"), "finish": text[:80]})
    if not uncosted and not unrecognised:
        return []

    out: List[Dict[str, Any]] = []
    if uncosted:
        listed = "; ".join(f"{u['part_number']} ({u['finish']})" for u in uncosted[:4])
        out.append(_violation(
            "stated_finish_not_costed", WARNING,
            f"{len(uncosted)} part(s) state a finish the sheet charges nothing for: {listed}. "
            f"Powder is the only finish this engine can cost, and no powder operation is on "
            f"this route. Paint, vinyl, laminate, print and foil are real work on board and "
            f"plastic and are being supplied free. ESTIMATOR TO PRICE THE FINISH.",
            count=len(uncosted), parts=uncosted[:20]))
    if unrecognised:
        listed = "; ".join(f"{u['part_number']} ({u['finish']})" for u in unrecognised[:4])
        out.append(_violation(
            "stated_finish_not_recognised", WARNING,
            f"{len(unrecognised)} part(s) state a finish this engine has no vocabulary for, "
            f"so it was neither costed nor questioned: {listed}. It is one of two things and "
            f"the engine cannot tell which. A SHOP PROCESS nobody has a rate for -- in which "
            f"case the work is being supplied free. Or a PROPERTY OF THE SHEET WE BUY, like "
            f"a UV-hardcoated or pre-laminated grade, which costs more per square metre and "
            f"belongs in the material rate rather than as an operation. Adding a labour line "
            f"for the second kind would invent work that is not done. AN ESTIMATOR CAN TELL "
            f"THESE APART IN SECONDS; this engine cannot, and until now said nothing.",
            count=len(unrecognised), parts=unrecognised[:20]))
    return out



def check_a_finish_field_holds_drawing_text(summary: Any) -> List[Dict[str, Any]]:
    """A finish field full of drawing text means the finish was never read -- and the
    numbers in it are usually the part's own dimensions.

    11650-04-03A is the case. Its finish reads "... FILM SIDE DENOTES WHICH HAND C C
    4 X 6.2 THRU 30 211 164 D D E E" -- a note, view labels, a hole callout and three bare
    numbers. The same job carries DIMS REQUIRED on that panel because the blank reader took
    6.2 x 4 (the hole) and correctly rejected it as a feature dimension.

    So the panel is marked unmeasurable while 211 and 164 sit in a field two lines away.
    That is not missing data, it is MISREAD data, and the difference decides what to do
    about it: an unmeasurable part is for the estimator, a misread one is for us. This
    check exists to stop the first being reported when it is really the second.

    IT DOES NOT USE THE NUMBERS. Reading a blank size out of scraped text is exactly the
    guess that put 6.2 x 4 on the sheet in the first place. It reports that a readable
    source appears to exist so a person can look, and nothing more.
    """
    try:
        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    except AttributeError:
        return [_violation("finish_field_holds_drawing_text", UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")]
    hits = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = " ".join(str(x) for x in (
            part.get("normalized_finish"), part.get("surface_finish")) if x)
        if not _looks_like_raw_drawing_text(text):
            continue
        numbers = [n for n in re.findall(r"\b\d{2,4}\b", text.upper())]
        hits.append({"part_number": part.get("part_number"),
                     "text": text[:90], "numbers_seen": numbers[:6]})
    if not hits:
        return []
    listed = "; ".join(f"{h['part_number']} (numbers seen: {', '.join(h['numbers_seen'])})"
                       for h in hits[:4])
    return [_violation(
        "finish_field_holds_drawing_text", WARNING,
        f"{len(hits)} part(s) have a finish field holding raw drawing text rather than a "
        f"finish: {listed}. The finish was not read on those parts. The numbers in that "
        f"text are frequently the part's own dimensions -- if the same part is marked DIMS "
        f"REQUIRED, the size is probably MISREAD rather than missing, and is worth a look "
        f"before it is handed back to the estimator.",
        count=len(hits), parts=hits[:20])]



def check_the_price_source_was_reached(summary: Any) -> List[Dict[str, Any]]:
    """Was SDILive/UDEF reachable while this job was costed?

    A JOB PRICED WITH NO PRICE SOURCE IS NOT A CHEAP JOB. PricingService connects in its
    constructor, so a dropped VPN, a stopped SQL service or a rotated login raises there --
    and estimator._get_pricing_service caught it, set a flag and returned None WITHOUT A
    WORD. Every catalogue and history lookup then took the None branch and returned no
    price. The run finished, the workbook calculated, the reports were written, and the unit
    cost came out LOW with nothing anywhere saying the primary source had never been asked.

    That estimate is indistinguishable from a correct one, which makes it the most expensive
    thing this engine can do quietly -- exactly the shape as native_folder_unreachable above,
    where "I could not look" read as "there is nothing there". Same answer: BLOCKING, and
    say to re-run rather than trust the number.
    """
    if not isinstance(summary, dict):
        return [_violation("price_source_reached", UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")]
    why = summary.get("price_source_unreachable")
    if not why:
        return []
    return [_violation(
        "price_source_unreachable", BLOCKING,
        f"The price source (SDILive/UDEF) could not be reached while this job was costed: "
        f"{why}. Every catalogue and purchase-history price on this estimate is MISSING, not "
        f"nil -- the lines were costed from fallbacks or left blank, so the unit cost is LOW "
        f"by an unknown amount. This is not a job with cheap parts. Restore the connection "
        f"and re-run before this figure goes to estimating.",
        reason=str(why))]


def check_every_unpriced_line_says_why(summary: Any) -> List[Dict[str, Any]]:
    """A line with no price must say which kind of nothing it is.

    A price says where it came from. A BLANK said nothing at all, so every unpriced line
    looked identical -- and on 11650-05 five BOM lines carried no price for four different
    reasons. Only one of those was a reason an estimator should have to act on.

    THE CATEGORY SAYS WHOSE PROBLEM IT IS, and that is the point. "Not priced" hides the
    difference between work the estimator must supply (a dimension nobody measured) and
    work the ENGINE is failing to charge for (a vinyl finish it has no rate for). The
    second silently under-quotes every job it touches, and looks exactly like the first.

    Two findings, deliberately separate:
      * lines with NO recorded reason -- a blank that reads as free, which is the failure
        this check exists to make impossible;
      * lines whose reason is an ENGINE gap -- real work, really invoiced, that nothing on
        the sheet is asking anybody to price.
    """
    # READ THROUGH _node, LIKE EVERY OTHER CHECK IN THIS FILE. Some writers stamp
    # final_estimate on the summary root and some inside estimate_summary, which is the whole
    # reason that helper exists -- and its docstring says what a private path does: "a check
    # that looks in one place only reports a clean pass on a job it never examined." This one
    # reached into estimate_summary directly and was doing exactly that on every job of the
    # other shape, silently, from the day it was written.
    if not isinstance(summary, dict):
        return [_violation("unpriced_line_says_why", UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")]
    _fe = _node(summary, "final_estimate")
    # NO READ-BACK IS NOT A CLEAN SHEET, and this check said it was. The Excel COM read-back
    # fails for reasons that have nothing to do with the estimate -- Excel busy or absent, a
    # workbook that will not open, Excel busy -- and it leaves no final_estimate at all. Every
    # reconciliation check in this module already fails CLOSED on that, by the rule stated at
    # the top of the file; this one, added later, returned [] and read on a console exactly
    # like a job whose every blank was explained. A guard that goes green when its input
    # vanishes is worse than no guard, because it is quoted as evidence.
    if not _fe:
        return _unevaluated("unpriced_line_says_why",
                            "No final_estimate on this job, so no material row was read back "
                            "from the calculated sheet and no blank price could be examined.")
    rows = _fe.get("material_rows")
    if not isinstance(rows, list):
        return _unevaluated("unpriced_line_says_why",
                            "final_estimate carries no material_rows, so nothing could be "
                            "checked for an unexplained blank.")
    if not rows:
        return []

    silent, gaps = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not price_provenance.row_is_unpriced(row):
            continue
        reason = row.get("unpriced_reason")
        code = price_provenance.row_label(row)
        if not isinstance(reason, dict) or not reason.get("category") or \
                reason.get("category") == price_provenance.UNEXPLAINED:
            silent.append(code)
        elif reason.get("undercharging"):
            gaps.append(f"{code} ({reason.get('why')})")

    out = []
    if silent:
        out.append(_violation(
            "unpriced_line_says_why", WARNING,
            f"{len(silent)} line(s) carry no price and no reason: {', '.join(silent[:6])}. "
            f"A blank on an estimate reads as free. Every unpriced line must say which kind "
            f"of nothing it is -- not measured, withheld by policy, no rate in the engine, "
            f"misread, or correctly nil -- because those need different people to act.",
            count=len(silent), lines=silent[:20]))
    if gaps:
        out.append(_violation(
            "unpriced_because_the_engine_cannot", WARNING,
            f"{len(gaps)} line(s) are unpriced because the ENGINE has no way to price them, "
            f"not because anything is missing from the drawings: {'; '.join(gaps[:4])}. "
            f"This work will be done and invoiced. THE JOB IS UNDER-CHARGED BY THIS AMOUNT, "
            f"and no estimator input can fix it -- it needs a rate in the engine.",
            count=len(gaps), lines=gaps[:20]))
    return out



# ONE THRESHOLD, A RATIO. Below this it is not worth an estimator's attention: material
# scales linearly with gauge and the cut rate steps with it, so a 25% disagreement is real
# money on every part cut from that sheet, while a check that fires on every hairline
# difference gets ignored on the day it is right. That has already happened here once today.
#
# An absolute "same gauge" tolerance was written beside this and then removed: no mutant
# could kill it, because a 1.25x ratio on the thinnest sheet this engine will accept
# (0.3mm) is already a 0.075mm gap. Two guards where one decides everything is not
# belt-and-braces, it is a claim that something is being checked when it is not.
_GAUGE_WORTH_SAYING = 1.25


def check_two_sources_disagree_about_the_gauge(summary: Any) -> List[Dict[str, Any]]:
    """A part whose thickness two sources read differently, by enough to move the money.

    ARBITRATION PICKED A WINNER AND THREW THE ARGUMENT AWAY. 11650-01-05A DOOR is a 6mm
    polycarbonate panel by its flat pattern -- 11650-01-05A_6MM POLYCARB_REVC.DXF, the file
    the router is actually set from -- and its detail drawing reads 3. The DXF outranks
    drawing text, so 6mm won and 6mm is almost certainly right. Nothing anywhere said that
    something on the drawing says half that.

    Gauge is the most leveraged number on a sheet part. Material cost scales with it
    directly and the cut rate steps with it, so being wrong by a factor of two is being
    wrong about the part twice over. When the winner is a flat pattern the disagreement is
    usually a stale revision or a misread callout and the estimator wants to know which;
    when the winner is an inference and a MEASUREMENT disagrees with it, the estimate is
    standing on the weaker of two answers and that is worth saying out loud.

    Not blocking. The engine's precedence is sound and the number still stands -- what is
    missing is that anybody was told there was an argument.
    """
    if not isinstance(summary, dict):
        return [_violation("gauge_disagreement", UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")]
    parts = _parts(summary)
    if not parts:
        return []
    disputed = []
    for part in parts:
        won = part.get("normalized_thickness_mm")
        try:
            won = float(won)
        except (TypeError, ValueError):
            continue
        if won <= 0:
            continue
        for entry in ((part.get("_displaced") or {}).get("normalized_thickness_mm") or []):
            if not isinstance(entry, dict):
                continue
            try:
                other = float(entry.get("value"))
            except (TypeError, ValueError):
                continue
            if other <= 0:
                continue
            ratio = max(won, other) / min(won, other)
            if ratio < _GAUGE_WORTH_SAYING:
                continue
            disputed.append({
                "part_number": part.get("part_number"),
                "costed_mm": won,
                "costed_from": part.get("thickness_source") or "the winning source",
                "other_mm": other,
                "other_from": entry.get("source") or "an earlier pass",
                "ratio": round(ratio, 2),
            })
    if not disputed:
        return []
    _worst = max(d["ratio"] for d in disputed)
    return [_violation(
        "two_sources_disagree_about_the_gauge", WARNING,
        f"{len(disputed)} part(s) have two different thicknesses read from two different "
        f"sources, the widest disagreeing by {_worst:.2f}x: "
        + "; ".join(f"{d['part_number']} costed at {d['costed_mm']}mm from "
                    f"{d['costed_from']}, but {d['other_from']} says {d['other_mm']}mm"
                    for d in disputed[:6])
        + ". Gauge drives material directly and steps the cut rate, so a part costed at the "
          "wrong one is wrong twice. The higher-ranked source has been used and the figure "
          "stands -- confirm which gauge the part is actually made from.",
        parts=disputed)]


# How much unbought sheet is worth saying. Below a quarter of a sheet across a whole
# material, the offcut is ordinary stock-keeping and every job in the system would carry this
# flag -- which is how a real warning gets ignored.
_SHEET_REMNANT_WORTH_SAYING = 0.25


def check_a_short_run_is_charged_for_the_sheet_it_uses(summary: Any) -> List[Dict[str, Any]]:
    """A one-off is charged a fraction of a sheet, and a one-off buys a whole sheet.

    Both sheet paths cost a part as sheet_price / parts_per_sheet. Over 180 off that is
    exactly right: the sheets are used up and the arithmetic is the invoice. Over ONE off it
    is not -- a panel that nests 6-up is charged a sixth of a sheet, and the other five sixths
    are bought, paid for and sitting in the rack.

    THE WORKBOOK DOES THE SAME THING, so this is not the engine disagreeing with the sheet and
    it is not a defect against the template. It is a commercial assumption that is invisible
    at batch quantities and dominant at short ones, and the Dyson displays are one and two off.
    Whether the offcut is chargeable is a real question -- it may go into the next job, or it
    may be a bespoke colour nobody will use again -- and it is the estimator's to answer, not
    something to settle quietly inside a formula.

    GROUPED BY MATERIAL AND GAUGE, because parts of the same stock share sheets. Five small
    PETG 2mm parts that together fill a sheet waste nothing; flagging them individually would
    be crying wolf on exactly the jobs where the nesting is efficient.

    WARNING, not blocking: the number is defensible, it is the assumption behind it that needs
    stating.
    """
    import math

    if not isinstance(summary, dict):
        return []
    header = (summary.get("quantity")
              or summary.get("assumed_job_quantity")
              or (summary.get("estimate_summary") or {}).get("assumed_job_quantity"))
    try:
        order_qty = int(header) if header is not None else None
    except (TypeError, ValueError):
        order_qty = None
    if not order_qty or order_qty < 1:
        # NOT AN ALL-CLEAR. Without a stated quantity there is no way to know how many sheets
        # this job buys, and check_the_quantity_costed_is_the_quantity_ordered already reports
        # a job that states none. Two checks shouting the same thing is noise.
        return []

    groups: Dict[tuple, Dict[str, Any]] = {}
    for row in ((summary.get("estimate_summary") or {}).get("part_estimates")
                or summary.get("part_estimates") or []):
        if not isinstance(row, dict):
            continue
        me = row.get("material_estimate") if isinstance(row.get("material_estimate"), dict) else {}
        fraction = _num(me.get("sheet_fraction_per_part"))
        if not fraction or fraction <= 0:
            continue
        per_unit = _num(row.get("quantity")) or 1.0
        key = (str(me.get("material") or row.get("normalized_material") or "?").upper(),
               me.get("thickness_mm") if me.get("thickness_mm") is not None
               else row.get("normalized_thickness_mm"))
        g = groups.setdefault(key, {"sheets": 0.0, "parts": []})
        g["sheets"] += fraction * per_unit * order_qty
        g["parts"].append(str(row.get("part_number") or "?"))

    out: List[Dict[str, Any]] = []
    for (material, thickness), g in sorted(groups.items(), key=lambda kv: -kv[1]["sheets"]):
        charged = g["sheets"]
        bought = math.ceil(charged - 1e-9)
        remnant = bought - charged
        if remnant < _SHEET_REMNANT_WORTH_SAYING:
            continue
        out.append(_violation(
            "short_run_pays_for_sheet_it_does_not_use", WARNING,
            f"At {order_qty} off, {material}"
            f"{f' {thickness}mm' if thickness is not None else ''} is charged "
            f"{charged:.2f} sheet(s) and {bought} whole sheet(s) have to be bought. "
            f"{remnant:.2f} of a sheet is paid for and not charged. The workbook divides a "
            f"sheet price by parts-per-sheet the same way, so the figure is not wrong — but "
            f"at this quantity the offcut is most of the material. Charge it, or decide it "
            f"goes to stock: {', '.join(sorted(set(g['parts']))[:8])}",
            material=material, thickness_mm=thickness, order_quantity=order_qty,
            sheets_charged=round(charged, 3), sheets_bought=bought,
            sheets_unaccounted=round(remnant, 3), parts=sorted(set(g["parts"]))[:24]))
    return out


CHECKS = (
    check_a_short_run_is_charged_for_the_sheet_it_uses,
    check_the_price_source_was_reached,
    check_a_material_we_cannot_price_is_declared,
    check_two_sources_disagree_about_the_gauge,
    check_every_unpriced_line_says_why,
    check_a_finish_field_holds_drawing_text,
    check_a_stated_finish_is_costed,
    check_schemas,
    check_workbook_adapters_read_everything,
    check_material_rows_reconcile,
    check_labour_rows_reconcile,
    check_totals_reconcile_to_the_unit_price,
    check_priced_rows_join_once,
    check_no_unpriced_operations_named,
    check_measured_geometry_is_complete,
    check_evidence_is_attributed,
    check_low_confidence_is_declared,
    check_geometry_is_reconciled,
    check_native_evidence_is_current,
    check_prices_are_reproducible,
    check_price_disagreement_is_declared,
    check_a_measured_plate_is_not_charged_for_folding,
    check_canonical_route_shadow,
    check_bom_lines_survive_the_merge,
    check_an_assembly_is_not_charged_as_a_blank,
    check_a_blank_and_its_cut_path_can_both_be_true,
    check_prices_are_firm,
    check_every_cad_file_was_used,
    check_uncorroborated_bom_lines_are_not_silent,
    check_both_bom_readers_ran,
    check_uncorroborated_route_operations,
    check_the_quantity_costed_is_the_quantity_ordered,
    check_an_operation_is_not_charged_on_a_parent_and_its_child,
    check_the_pack_contains_the_drawings_its_bom_names,
)


def check_job(summary: Any, write_back: bool = True) -> Dict[str, Any]:
    """Run every invariant over a finished job.

    Returns {"ok", "violations", "blocking", "warnings", "checks_run"}. `ok` is False only
    for BLOCKING violations — a warning is worth seeing but does not make the price wrong.

    This never edits a price. A check that quietly corrected what it found would be the same
    class of unverified write these checks exist to catch; the job is marked instead, and the
    caller decides whether to present it.
    """
    violations: List[Dict[str, Any]] = []
    ran: List[str] = []
    for check in CHECKS:
        try:
            violations.extend(check(summary) or [])
        except Exception as exc:                       # a broken check must not stop a run
            violations.append(_violation(
                "check_failed", UNVERIFIED,
                f"invariant {check.__name__} could not run ({exc}); it has verified nothing.",
                check=check.__name__))
        ran.append(check.__name__)

    blocking = [v for v in violations if v.get("severity") == BLOCKING]
    unverified = [v for v in violations if v.get("severity") == UNVERIFIED]
    result = {
        "schema": SCHEMA,
        # ok        — nothing we checked came back wrong
        # verified  — every check actually had the data to run
        # A job can be `ok` and unverified at the same time, and that combination is exactly
        # what a read-back failure produces: nothing found wrong because nothing was looked
        # at. Only `may_quote_firm` answers the question a quote needs to ask.
        "ok": not blocking,
        "verified": not unverified,
        "may_quote_firm": not blocking and not unverified,
        "checks_run": ran,
        "violations": violations,
        "blocking": len(blocking),
        "unverified": len(unverified),
        "warnings": len(violations) - len(blocking) - len(unverified),
    }
    if write_back and isinstance(summary, dict):
        summary["invariants"] = result
    return result


def format_report(result: Dict[str, Any]) -> str:
    """One block of text for the console and the log."""
    if not isinstance(result, dict):
        return "[invariants] no result"
    if result.get("may_quote_firm") and not result.get("violations"):
        return f"[invariants] all {len(result.get('checks_run') or [])} checks passed"
    lines = [f"[invariants] {result.get('blocking', 0)} blocking, "
             f"{result.get('unverified', 0)} unverified, "
             f"{result.get('warnings', 0)} warning(s)"
             f"{'' if result.get('may_quote_firm') else '  -> NOT A FIRM PRICE'}"]
    _mark = {BLOCKING: "BLOCKING  ", UNVERIFIED: "UNVERIFIED", WARNING: "warning   "}
    for v in result.get("violations") or []:
        lines.append(f"   {_mark.get(v.get('severity'), 'warning   ')}  "
                     f"{v.get('code')}: {v.get('message')}")
    return "\n".join(lines)


_SCAN_DIRS = ("output/json", "output", ".")


def _resolve_job_files(arguments: List[str]) -> List[str]:
    """Turn whatever the shell handed us into job files that exist.

    EVERY JOB HERE HAS SPACES IN ITS NAME. "12120-01-GA- DIGITAL TICKETING BRACKET.json"
    unquoted in PowerShell arrives as four arguments, and the first attempt opened
    'output\\json\\12120-01-GA-' and died. A re-check tool that cannot be pointed at a real
    filename does not get used, and a check nobody runs verifies nothing — which is the
    failure this whole module exists to prevent.

    So: a path is used as given when it exists; otherwise the arguments are rejoined with
    spaces and tried as one name; otherwise each is matched as a fragment against the output
    folders. Anything still unresolved is reported by name rather than raising.
    """
    import glob
    import os

    def _hits(text: str) -> List[str]:
        text = text.strip().strip('"').strip("'")
        if not text:
            return []
        if os.path.isfile(text):
            return [text]
        found = sorted(p for p in glob.glob(text) if os.path.isfile(p))
        if found:
            return found
        for folder in _SCAN_DIRS:
            found = sorted(glob.glob(os.path.join(folder, f"*{text}*.json")))
            if found:
                return found
        return []

    # The rejoined form first: it is the case the shell mangled, and matching it is what the
    # user meant. Only fall back to per-argument matching if that finds nothing.
    whole = _hits(" ".join(arguments))
    if whole:
        return whole
    resolved: List[str] = []
    for arg in arguments:
        got = _hits(arg)
        if got:
            resolved.extend(g for g in got if g not in resolved)
        else:
            print(f"  no job file matched: {arg!r}")
    return resolved


if __name__ == "__main__":
    # Re-check a job that has already been stamped, without re-running the estimate.
    #
    #     python src\invariants.py "output\json\12120-01-GA- DIGITAL TICKETING BRACKET.json"
    #     python src\invariants.py 12120            # a fragment of the name is enough
    #     python src\invariants.py output\json\*.json
    #
    # The checks read only what is in the document, so this answers "would this job be
    # released as firm?" against a JSON already on disk. It exists because the alternative —
    # believing a check fires because a fixture says it does — is how a reproducibility check
    # reported CLEAR on a job with three AI-priced bought-ins in it.
    import json
    import sys

    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: python invariants.py <stamped-job.json | name fragment | glob> [...]")
        raise SystemExit(2)

    _args = [a for a in sys.argv[1:] if a not in ("--all", "-a")]
    _all = len(_args) != len(sys.argv[1:])
    _files = _resolve_job_files(_args)
    if not _files:
        print(f"\nNothing to check. Looked in: {', '.join(_SCAN_DIRS)}")
        raise SystemExit(2)

    _worst = 0
    for _path in _files:
        with open(_path, "r", encoding="utf-8") as _fh:
            _doc = json.load(_fh)
        _res = check_job(_doc, write_back=False)
        # WHEN WAS THIS WRITTEN? Two consecutive re-checks came back byte-identical after a
        # re-run, and the only way to tell "the fix did not fire" from "this is the previous
        # file" was to notice that the guessed prices had not moved — which they always do.
        # A verdict with no timestamp on the document it read cannot answer that at all.
        try:
            import datetime
            import os as _os
            _age = datetime.datetime.fromtimestamp(_os.path.getmtime(_path))
            _mins = (datetime.datetime.now() - _age).total_seconds() / 60.0
            _when = (f"{_age:%Y-%m-%d %H:%M:%S}  "
                     f"({_mins:.0f} min ago)" if _mins >= 1 else
                     f"{_age:%Y-%m-%d %H:%M:%S}  (just now)")
        except OSError:
            _when = "unknown"
        print(f"\n=== {_path}")
        print(f"    written: {_when}")
        print(format_report(_res))
        # Name the priced lines, whatever they turned out to be. A verdict with no lines
        # under it cannot be acted on, and cannot be disbelieved either.
        #
        # But a real job stamps every labour rate on every part, which is over a hundred
        # lines of "sqlserver, applied" — and a listing nobody reads to the end hides the
        # five that matter. So: one row per source with a count, then every guessed line in
        # full. --all prints the lot when someone actually wants to audit it.
        _by_source: Dict[str, Dict[str, int]] = {}
        _guessed: List[str] = []
        for _p, _b, _own in price_provenance.iter_price_stamps_with_owner(_doc):
            _cls = price_provenance.stamp_source_class(_b)
            _name = str(_b.get("source_name") or "?")
            _used = price_provenance.stamp_affects_total(_b)
            _row = _by_source.setdefault(f"{_cls}|{_name}", {"applied": 0, "unused": 0})
            _row["applied" if _used else "unused"] += 1
            if price_provenance.stamp_is_ai_estimate(_b) and _used:
                # The price itself, because it is the one field that proves this is a fresh
                # run: a guessed number that comes back identical did not come back at all.
                _sel = _b.get("selected") if isinstance(_b.get("selected"), dict) else {}
                _amt = _sel.get("price", _b.get("unit_price_gbp"))
                _amt = f"GBP {float(_amt):>8.2f}" if isinstance(_amt, (int, float)) else "GBP        ?"
                _guessed.append(f"     GUESSED  {str(_own or '?'):<22} {_amt}  {_name:<22} {_p}")
            if _all:
                print(f"     {'GUESSED' if price_provenance.stamp_is_ai_estimate(_b) else '       '}"
                      f"  {_cls:<12} {_name:<34} "
                      f"{'applied' if _used else 'not applied':<11} {_p}")
        if not _all:
            print("  price sources on this job:")
            for _key in sorted(_by_source):
                _cls, _name = _key.split("|", 1)
                _c = _by_source[_key]
                _flag = "  <-- GUESSED" if _cls == "ai_estimate" else ""
                print(f"     {_cls:<12} {_name:<34} "
                      f"{_c['applied']:>3} applied, {_c['unused']:>3} unused{_flag}")
        if _guessed:
            print("  lines that reached the total on a guessed price:")
            for _line in _guessed:
                print(_line)
        if not _res.get("may_quote_firm"):
            _worst = 1
    raise SystemExit(_worst)
