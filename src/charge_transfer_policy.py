"""Format-independent charge hand-off checks, not another source of prices.

PDF, CAD, DXF and model reads converge before this boundary. A valid costed
run time must survive workbook placement. A supplier table is not evidence
of a calculated charge at every requested quantity.
"""
from math import isfinite, isclose


def positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and value > 0)


def preserve_run_rate(parts_per_product, run_hours_per_product, rate):
    """Validate the writer's per-product arithmetic, not the engineering time.

    Batch-derived times deliberately do not qualify. Stated shop throughput
    keeps precedence in the caller. Unknown/zero/nonfinite inputs never pass.
    """
    return (all(positive_number(v) for v in
                (parts_per_product, run_hours_per_product, rate))
            and isclose(parts_per_product / run_hours_per_product, rate,
                        rel_tol=1e-9, abs_tol=1e-9))


def quantity_charge_coverage(expected, snapshots, quantities):
    """Audit explicit per-product charges from independently calculated breaks.

    This is a diagnostic API: callers must supply paired, calculated snapshots,
    not prices predicted by the engine. Missing snapshots are unknown, never a
    pass. No restriction on file format, row number or material block.
    A free/excluded charge requires an explicit ruling; no default zero.
    """
    issues = []
    if not expected or not quantities:
        return {"passed": False, "issues": [{"code": "coverage_missing"}]}
    identities = [r.get("part_id") for r in expected]
    if any(not ident for ident in identities) or len(set(identities)) != len(identities):
        return {"passed": False, "issues": [{"code": "requirement_identity_ambiguous"}]}
    for qty in quantities:
        if not positive_number(qty) or int(qty) != qty:
            issues.append({"code": "invalid_order_quantity", "quantity": qty})
            continue
        snap = snapshots.get(str(qty), snapshots.get(qty))
        if not isinstance(snap, dict) or snap.get("calculated") is not True or not snap.get("workbook_sha256"):
            issues.append({"code": "calculated_snapshot_missing", "quantity": qty})
            continue
        rows = snap.get("rows") or []
        for req in expected:
            ident = req.get("part_id")
            matches = [r for r in rows if ident and r.get("part_id") == ident]
            if len(matches) != 1:
                issues.append({"code": "charge_missing_or_ambiguous", "part": ident, "quantity": qty})
                continue
            row = matches[0]
            if (not positive_number(req.get("qty_per_product"))
                    or not positive_number(row.get("qty_per_product"))
                    or row.get("qty_per_product") != req["qty_per_product"]
                    or row.get("basis") != "per_finished_product"):
                issues.append({"code": "quantity_basis_unverified", "part": ident, "quantity": qty})
            if not row.get("charged_cell") or not positive_number(row.get("charge_gbp_per_product")):
                issues.append({"code": "charge_unverified", "part": ident, "quantity": qty})
    return {"passed": not issues, "issues": issues}
