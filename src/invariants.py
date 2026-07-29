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
    "workbook_labour": {"workbook_labour_rows.v1", "workbook_labour_rows.v2"},
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

    named: Dict[str, List[str]] = {}
    for p in _parts(summary):
        pn = str(p.get("part_number") or "?")
        for op in (p.get("operations") or p.get("textual_operations") or []):
            if isinstance(op, str) and op and op not in costed:
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
        # A matched-but-unmeasured file is an honest state and says so in its own name.
        if "no_geometry" in src or "matched_no_geometry" in src:
            continue
        length = _num(p.get("blank_length_mm")) or _num((p.get("geometry_rollup") or {}).get("blank_length_mm"))
        width = _num(p.get("blank_width_mm")) or _num((p.get("geometry_rollup") or {}).get("blank_width_mm"))
        area = _num(p.get("blank_area_mm2")) or _num((p.get("geometry_rollup") or {}).get("blank_area_mm2"))
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
_ATTRIBUTED_FIELDS = ("normalized_material", "quantity", "normalized_thickness_mm",
                      "blank_length_mm")


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

    guessed = []
    for path, block, owner in price_provenance.applied_ai_prices(summary):
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
