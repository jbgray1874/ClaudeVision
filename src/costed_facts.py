"""
costed_facts.py — the single post-costing answer to "what did we actually price?"

Every customer- and estimator-facing deliverable has to describe the SAME job. They were
each deriving that independently:

  client_quote_html._collect_operations   costed ops
  client_quote_html._finish_line          costed ops OR powder_coating_summary
  job_report_html   powder bullet         powder_coating_summary.by_part
  job_decision_report._ops_explanation    raw textual + inferred op lists

Four derivations of one fact drift apart, and they drift in the direction that hurts: a
quote promising powder coating and weld dressing on a lacquered timber crate the Estimate
sheet charges neither for. The drawing's own routing text cannot be the source, because
these packs carry a range-wide specification legend ("POWDER COATED STEEL", "WELD
SPECIFICATION") that applies to the customer's whole product family, not to this job.

The rule this module encodes: **if an operation carries no cost on this job, it did not
happen.** Nothing here reads drawing text.

SOURCE ORDER, and the distinction matters:

  1. `workbook_labour.rows`  — CANONICAL. The labour rows wb_populate actually accepted,
     after its spurious-op, finish and material filters, after department mapping, and
     including injected operations. This is the route the Estimate sheet charges.
  2. `estimate_summary.part_estimates[].labour_estimate.costs_gbp` — FALLBACK ONLY, for a
     summary with no workbook built. It is PRE-FILTER: it still carries powder on timber
     panels and weld/dress on artefact records the workbook drops, so anything described
     from it can name operations the sheet does not contain.

The workbook is the authority on the price (wep-readback stamps its totals back); it is
equally the authority on the route, which is why (1) exists.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "costed_operations",
    "has_operation",
    "parts_with_operation",
    "part_numbers_with_operation",
    "operations_for_part",
    "costed_finish_label",
    "costed_finish_ops",
    "reconcile_risk_flags",
]

# Operations that describe a FINISH rather than a fabrication step, most-specific first —
# a part can be both sprayed and polished, and the headline should name the dominant one.
_FINISH_OPS: List[tuple] = [
    ("powder_coating", "Powder coated"),
    ("wet_spray", "Wet-spray painted"),
    ("diamond_polish", "Diamond polished"),
    ("diamond_polishing", "Diamond polished"),
    ("anodising", "Anodised"),
    ("plating", "Plated"),
]


def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and abs(f) != float("inf") else 0.0


def _part_estimates(source: Any) -> List[Dict[str, Any]]:
    """Accept a whole job summary, an estimate_summary, or a list of part estimates."""
    if isinstance(source, list):
        return [p for p in source if isinstance(p, dict)]
    if not isinstance(source, dict):
        return []
    for path in (("estimate_summary", "part_estimates"), ("part_estimates",)):
        node: Any = source
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, list):
            return [p for p in node if isinstance(p, dict)]
    return []


def _workbook_rows(source: Any) -> Optional[List[Dict[str, Any]]]:
    """The workbook's own accepted labour rows, if wb_populate has run and stamped them.

    THIS IS THE CANONICAL SOURCE. wb_populate applies filters the engine-side estimate never
    sees — spurious-op removal by stock form, the finish gate that drops powder from a part
    whose drawing finish is not powder, the diamond-polish-on-powder drop — and then maps
    departments and injects operations. None of that is written back to part_estimates, so
    `labour_estimate.costs_gbp` is a whole filtering stage upstream of the sheet: it still
    carries powder on timber panels and weld/dress on artefact records the workbook drops.
    """
    if not isinstance(source, dict):
        return None
    node = source.get("workbook_labour")
    if not isinstance(node, dict):
        node = (source.get("estimate_summary") or {}).get("workbook_labour") \
            if isinstance(source.get("estimate_summary"), dict) else None
    if isinstance(node, dict) and isinstance(node.get("rows"), list):
        return [r for r in node["rows"] if isinstance(r, dict)]
    return None


def costed_operations(source: Any) -> Dict[str, float]:
    """{operation: total cost or time across the job} for operations we actually charged.

    Prefers the workbook's accepted labour rows where available (the route the Estimate
    sheet charges). Falls back to the engine-side costed fields only when the workbook has
    not been built — a quote generated from a JSON alone, say — and that fallback is
    PRE-FILTER, so it can name operations the sheet would have dropped.

    An operation appears only where it carries a non-zero labour cost or process time.
    Zero-valued keys are dropped: the engine writes a key for every op it considered, so
    presence alone is not evidence that anything was priced."""
    rows = _workbook_rows(source)
    if rows is not None:
        totals: Dict[str, float] = {}
        for r in rows:
            op = r.get("engine_operation") or r.get("wb_operation")
            if op:
                totals[str(op)] = totals.get(str(op), 0.0) + max(_num(r.get("qty_per_unit")), 1.0)
        return totals

    totals = {}
    for p in _part_estimates(source):
        for block, field in (("labour_estimate", "costs_gbp"),
                             ("process_estimate", "times_min")):
            d = p.get(block)
            d = d.get(field) if isinstance(d, dict) else None
            if not isinstance(d, dict):
                continue
            for op, val in d.items():
                v = _num(val)
                if v > 0:
                    totals[str(op)] = totals.get(str(op), 0.0) + v
    return totals


def has_operation(source: Any, *ops: str) -> bool:
    """True when ANY of the named operations carries cost on this job."""
    costed = costed_operations(source)
    return any(o in costed for o in ops)


def part_numbers_with_operation(source: Any, *ops: str) -> List[str]:
    """Part numbers carrying one of the named operations, from the workbook rows where
    available. Preferred over parts_with_operation() for anything that only needs to count
    or name parts, because the workbook rows survive the filters the estimate does not."""
    rows = _workbook_rows(source)
    if rows is not None:
        want = {str(o).lower() for o in ops}
        out: List[str] = []
        for r in rows:
            keys = {str(r.get("engine_operation") or "").lower(),
                    str(r.get("wb_operation") or "").lower()}
            if keys & want or any(w in k for k in keys if k for w in want):
                for pn in (r.get("part_numbers") or []):
                    if pn and pn not in out:
                        out.append(str(pn))
        return out
    return [str(p.get("part_number")) for p in parts_with_operation(source, *ops)
            if p.get("part_number")]


def operations_for_part(source: Any, part_number: Any,
                        part_estimate: Optional[Dict[str, Any]] = None) -> List[str]:
    """Operations charged against ONE part, canonical where the workbook rows exist.

    A per-part view is what the Decision Report needs, and it must come from the same place
    as the job-level view or the two sheets in one workbook will disagree. Falls back to the
    part's own PRE-FILTER costed fields only when no workbook rows are present."""
    pn = str(part_number or "").strip().upper()
    rows = _workbook_rows(source)
    if rows is not None and pn:
        out: List[str] = []
        for r in rows:
            if any(str(x or "").strip().upper() == pn for x in (r.get("part_numbers") or [])):
                op = r.get("engine_operation") or r.get("wb_operation")
                if op and str(op) not in out:
                    out.append(str(op))
        return out
    if isinstance(part_estimate, dict):
        return list(costed_operations([part_estimate]))
    return []


def parts_with_operation(source: Any, *ops: str) -> List[Dict[str, Any]]:
    """The part estimates that actually carry one of the named operations.

    Engine-side and therefore PRE-FILTER — prefer part_numbers_with_operation()."""
    out: List[Dict[str, Any]] = []
    for p in _part_estimates(source):
        found = False
        for block, field in (("labour_estimate", "costs_gbp"),
                             ("process_estimate", "times_min")):
            d = p.get(block)
            d = d.get(field) if isinstance(d, dict) else None
            if isinstance(d, dict) and any(_num(d.get(o)) > 0 for o in ops):
                found = True
                break
        if found:
            out.append(p)
    return out


def costed_finish_ops(source: Any) -> List[str]:
    """Finish operations charged on this job, most-specific first."""
    costed = costed_operations(source)
    seen: List[str] = []
    for op, _label in _FINISH_OPS:
        if op in costed and op not in seen:
            seen.append(op)
    return seen


def costed_finish_label(source: Any, default: str = "As drawing") -> str:
    """The headline finish for a quote — named from what was CHARGED.

    Deliberately does NOT consult powder_coating_summary or any drawing finish field. A
    powder line can survive in a material summary after the powder labour has been gated
    off a part, and the customer-facing sentence must not promise a process the priced
    sheet does not contain."""
    for op, label in _FINISH_OPS:
        if has_operation(source, op):
            return label
    return default


# ── risk flags vs the route that was actually priced ─────────────────────────
# A risk flag that ASSERTS AN OPERATION is a claim about the route. Once the workbook
# gates have removed that operation, the claim is stale — and it is stale in the worst
# possible way, because it appears in the review list of a report that accompanies a sheet
# showing the opposite. "Verify weld/dress content" against a part with no weld line reads
# as the engine contradicting itself, and an estimator cannot tell which half to believe.
#
# Flags asserting GEOMETRY (large_flat, hanging_holes) are untouched: geometry is not a
# route claim and the gates do not speak to it.
_OP_ASSERTING_FLAGS: Dict[str, tuple] = {
    "weld_required": ("welding", "dress_welds", "spot_welding", "spotweld",
                      "resistance_welding", "Weld (CO2)", "Spotweld", "Dress Welds"),
    "many_bends": ("folding", "fold", "linebend", "line_bending", "tubebend",
                   "tube_bending", "Fold", "Linebend", "Tubebend"),
}


def reconcile_risk_flags(summary: Any) -> Dict[str, int]:
    """Demote risk flags the priced route does not support, in place.

    Not deleted — moved to `superseded_risk_flags` with the reason. The cue WAS read on the
    drawing, and a gate removed the operation it implied. Both facts matter: silently
    dropping the flag hides a genuine drawing cue that a gate may have stripped wrongly,
    while leaving it as a review item makes the report contradict the sheet. Recording the
    disposition keeps the audit trail and the consistency.

    No-op until the workbook rows exist, because before that there is no priced route to
    reconcile against and every flag would be demoted on missing evidence."""
    out = {"superseded": 0, "kept": 0}
    if _workbook_rows(summary) is None:
        return out

    buckets: List[List[Dict[str, Any]]] = []
    if isinstance(summary, dict):
        est = summary.get("estimate_summary")
        if isinstance(est, dict) and isinstance(est.get("part_estimates"), list):
            buckets.append(est["part_estimates"])
        mw = summary.get("manufacturing_writeup")
        if isinstance(mw, dict) and isinstance(mw.get("parts"), list):
            buckets.append(mw["parts"])

    for parts in buckets:
        for p in parts:
            if not isinstance(p, dict) or not isinstance(p.get("risk_flags"), list):
                continue
            route = {str(o).lower() for o in
                     operations_for_part(summary, p.get("part_number"), p)}
            kept, gone = [], []
            for flag in p["risk_flags"]:
                needed = _OP_ASSERTING_FLAGS.get(str(flag))
                if needed and not any(str(n).lower() in route for n in needed):
                    gone.append({
                        "flag": str(flag),
                        "reason": (f"read from the drawing, but the priced route contains "
                                   f"no {needed[0]} — the operation was removed by a "
                                   f"costing gate, so this is no longer a review item"),
                    })
                else:
                    kept.append(flag)
            if gone:
                p["risk_flags"] = kept
                p.setdefault("superseded_risk_flags", []).extend(gone)
                out["superseded"] += len(gone)
            out["kept"] += len(kept)
    return out
