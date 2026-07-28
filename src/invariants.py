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

SCHEMA = "invariants.v1"

# The contract versions this module knows how to read. A structure carrying a different
# version is not silently reinterpreted: the shape may have moved under us, and a check that
# reads the wrong shape reports a pass it did not verify.
KNOWN_SCHEMAS = {
    "final_estimate": {"final_estimate.v1", "final_estimate.v2"},
    "workbook_labour": {"workbook_labour_rows.v1", "workbook_labour_rows.v2"},
}

# Money agrees to the penny, with a small proportional allowance for Excel's own rounding
# across many rows. Anything outside this is a real disagreement, not a rounding artefact.
_ABS_TOL_GBP = 0.01
_REL_TOL = 0.005

BLOCKING = "blocking"      # the job must not be presented as a firm price
WARNING = "warning"        # flag it, but the number still stands


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").replace("£", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _money_agrees(a: float, b: float) -> bool:
    return abs(a - b) <= max(_ABS_TOL_GBP, _REL_TOL * max(abs(a), abs(b)))


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
    for holder in (summary, summary.get("estimate_summary") or {}):
        if isinstance(holder, dict):
            for key in ("part_estimates", "parts"):
                v = holder.get(key)
                if isinstance(v, list):
                    return [p for p in v if isinstance(p, dict)]
    return []


def _violation(code: str, severity: str, message: str, **detail) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "detail": detail or {}}


# ── contracts ────────────────────────────────────────────────────────────────────────
def check_schemas(summary: Any) -> List[Dict[str, Any]]:
    """A structure whose version we do not recognise must not be read as if we did."""
    out = []
    for key, known in KNOWN_SCHEMAS.items():
        node = _node(summary, key)
        if not node:
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
    rows = fe.get(rows_key)
    totals = fe.get("totals") or {}
    total = _num(totals.get(total_key))
    if not isinstance(rows, list) or total is None:
        return []
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
    if not _money_agrees(summed, total):
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
    if not isinstance(rows, list) or not isinstance(accepted, list) or not accepted:
        return []

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
    except Exception:
        return []
    try:
        costed = set(costed_operations(summary) or {})
    except Exception:
        return []
    if not costed:
        return []

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
_ATTRIBUTED_FIELDS = ("normalized_material", "quantity", "thickness_mm", "blank_length_mm")


def check_evidence_is_attributed(summary: Any) -> List[Dict[str, Any]]:
    """Precedence can only be enforced on a datum whose source is recorded. A field written
    without one is invisible to arbitration: the next pass has nothing to compare against and
    overwrites it silently, which is the whole failure mode."""
    unattributed: Dict[str, int] = {}
    for p in _parts(summary):
        for f in _ATTRIBUTED_FIELDS:
            if p.get(f) in (None, "", 0):
                continue
            if not p.get(f"{f}_source"):
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
    problems = fe.get("adapter_problems")
    if not isinstance(problems, list) or not problems:
        return []
    return [_violation(
        "workbook_block_not_read", BLOCKING,
        f"{len(problems)} workbook block(s) could not be read: "
        f"{', '.join(sorted({str(p.get('block')) for p in problems if isinstance(p, dict)}))}. "
        f"Their rows are absent from this snapshot, so any total built from it is short by "
        f"whatever they contained.",
        problems=[p for p in problems if isinstance(p, dict)][:10])]


CHECKS = (
    check_schemas,
    check_workbook_adapters_read_everything,
    check_material_rows_reconcile,
    check_labour_rows_reconcile,
    check_priced_rows_join_once,
    check_no_unpriced_operations_named,
    check_measured_geometry_is_complete,
    check_evidence_is_attributed,
    check_low_confidence_is_declared,
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
                "check_failed", WARNING,
                f"invariant {check.__name__} could not run ({exc}); it has verified nothing.",
                check=check.__name__))
        ran.append(check.__name__)

    blocking = [v for v in violations if v.get("severity") == BLOCKING]
    result = {
        "schema": SCHEMA,
        "ok": not blocking,
        "checks_run": ran,
        "violations": violations,
        "blocking": len(blocking),
        "warnings": len(violations) - len(blocking),
    }
    if write_back and isinstance(summary, dict):
        summary["invariants"] = result
    return result


def format_report(result: Dict[str, Any]) -> str:
    """One block of text for the console and the log."""
    if not isinstance(result, dict):
        return "[invariants] no result"
    if result.get("ok") and not result.get("violations"):
        return f"[invariants] all {len(result.get('checks_run') or [])} checks passed"
    lines = [f"[invariants] {result.get('blocking', 0)} blocking, "
             f"{result.get('warnings', 0)} warning(s)"]
    for v in result.get("violations") or []:
        mark = "BLOCKING" if v.get("severity") == BLOCKING else "warning "
        lines.append(f"   {mark}  {v.get('code')}: {v.get('message')}")
    return "\n".join(lines)
