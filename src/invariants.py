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
    for part in parts:
        length = _blank_num(part, "blank_length_mm", "overall_length_mm")
        width = _blank_num(part, "blank_width_mm", "overall_width_mm")
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
    if not impossible:
        return []

    return [_violation(
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
        parts=impossible[:10], count=len(impossible))]


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
            out.append(_violation(
                "canonical_route_decision_unverified", severity,
                f"Route decision {decision.get('decision_id')} for "
                f"{decision.get('operation')} on {decision.get('target_id')} contains "
                + (
                    "conflicts and cannot be priced automatically."
                    if cutover else
                    "equal-ranked or metadata conflicts. Legacy pricing still stands."
                ),
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


CHECKS = (
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
