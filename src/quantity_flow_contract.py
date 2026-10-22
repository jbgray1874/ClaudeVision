"""A quantity is multiplied along its own edges once, and a unit is a stated thing (D-582).

Read-only reconciliation of the canonical graph the compiler already built. The graph owns
scope; this re-walks the parent-relative edges independently and compares the result with
the node's figure and with the canonical price record's charged quantity. Nothing here
repairs a quantity. Where it cannot be verified, that is a finding, never a default of one.

THE DISTINCTION THIS EXISTS TO HOLD. PartNode.qty_by_parent is already the ROLLED
contribution per finished product through each parent — the figure the BOMs & Routes trail
prints. It is not the local multiplier on the edge. The local edge is the canonical record's
bom_parents[].qty. Two base assemblies each carrying one frame need two frames; a reader
that took the recorded contribution of two and multiplied by the parent's two again would
price four. This module multiplies the local edge by the parent's own rolled figure and then
checks the compiler's contribution against it, so a consumer that multiplies twice is caught
rather than copied. A child under two parents is the sum of its paths (D-561).

The order quantity is deliberately not multiplied in: it governs batch purchasing and set-ups
elsewhere. Missing local edges, orphan parents, cycles, duplicate identities, contradictory
parent lists and missing canonical records are each a finding. An explicitly empty canonical
population is a finding, not a reason to fall back to the old part list.

Units: a continuous quantity keeps its fraction; an explicit `each` cannot be fractional; an
unknown unit is reported, not guessed; a pack, sheet or roll conversion needs a stated factor.
The conversion helper is a check, not a pricing path — using it in production needs the
purchasing evidence the owning adapter must carry (material_charge_contract says where).

Contract and proofs as proposed in the Codex review package of 22 Oct 2026 (accuracy
contracts), merged on the engine's terms.
"""
from __future__ import annotations

from collections import Counter
from math import isclose, isfinite
from typing import Any, Dict, List, Optional

SCHEMA = "quantity_flow_contract.v1"

_UNITS = {"ea": "each", "pcs": "each", "piece": "each", "each": "each",
          "m": "m", "metre": "m", "meter": "m", "mm": "mm",
          "m2": "m2", "m²": "m2", "kg": "kg", "g": "g",
          "l": "l", "litre": "l", "pack": "pack", "sheet": "sheet", "roll": "roll"}
_SCALES = {("mm", "m"): .001, ("m", "mm"): 1000.0, ("g", "kg"): .001, ("kg", "g"): 1000.0}


def numeric(value: Any) -> Optional[float]:
    """A number, or None. Text that looks like a number is not a number, a bool is not a
    count, and nothing infinite is a quantity."""
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) else None)


def identity(value: Any) -> str:
    return str(value or "").strip().upper()


def unit(value: Any) -> Optional[str]:
    """The canonical spelling of a stated unit, or None where the word is not one we know."""
    return _UNITS.get(str(value or "").strip().lower())


def is_commercial(record: Any) -> bool:
    """A packaging, delivery or similar line is not an occurrence in the fabricated product.
    The engine's flag is `commercial_line` on the part record (commercial_lines.collect_lines
    reads the same key); the word on the description is not the test."""
    return isinstance(record, dict) and bool(record.get("commercial_line"))


def convert(quantity: Any, source_unit: Any, target_unit: Any,
            units_per_purchase: Any = None) -> float:
    """Explicit physical conversion only. A pack, sheet or roll needs its factor.

    `units_per_purchase` is how many source units ONE purchase unit holds. Rounding up to
    whole packs is a purchasing policy decided elsewhere; this never rounds."""
    q, factor = numeric(quantity), numeric(units_per_purchase)
    a, b = unit(source_unit), unit(target_unit)
    if q is None or q < 0 or not a or not b:
        raise ValueError("Quantity or unit missing/invalid")
    if a == b:
        return q
    if (a, b) in _SCALES:
        return q * _SCALES[a, b]
    if b in {"pack", "sheet", "roll"} and factor is not None and factor > 0:
        return q / factor
    raise ValueError("Explicit compatible purchase conversion required")


def _canonical_parts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The canonical population where the record has one — EVEN WHEN EMPTY (an empty
    canonical population is a finding, not a reason to read the old list)."""
    es = summary.get("estimate_summary") or {}
    if "canonical_part_estimates" in es:
        return [p for p in (es.get("canonical_part_estimates") or []) if isinstance(p, dict)]
    return [p for p in (es.get("part_estimates") or []) if isinstance(p, dict)]


def _graph(summary: Dict[str, Any]) -> Dict[str, Any]:
    es = summary.get("estimate_summary") or {}
    return es.get("canonical_route_shadow") or summary.get("canonical_route_shadow") or {}


def audit(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The findings and a trace row per node. Mutates nothing."""
    graph = _graph(summary)
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    parts = _canonical_parts(summary)
    issues: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []

    def fail(code: str, part: str = "", **detail: Any) -> None:
        issues.append({"code": code, "part": part, **detail})

    def index(rows: List[Dict[str, Any]], label: str) -> Dict[str, Dict[str, Any]]:
        counts = Counter(identity(p.get("part_number")) for p in rows)
        for pn, n in counts.items():
            if not pn or n != 1:
                fail("duplicate_or_missing_identity", pn, population=label, count=n)
        return {identity(p.get("part_number")): p for p in rows
                if counts[identity(p.get("part_number"))] == 1 and p.get("part_number")}

    ns, ps = index(nodes, "graph"), index(parts, "canonical_prices")
    root = identity(graph.get("product_root") or graph.get("declared_product"))
    if not nodes or root not in ns:
        fail("canonical_product_graph_missing", root)

    active: set = set()
    resolved: Dict[str, Optional[float]] = {}

    def roll(pn: str) -> Optional[float]:
        if pn in resolved:
            return resolved[pn]
        if pn in active:
            fail("quantity_cycle", pn)
            return None
        if pn not in ns:
            fail("quantity_parent_missing", pn)
            return None
        n = ns[pn]
        # THE LOCAL EDGE is the canonical record's bom_parents entry; qty_by_parent on the
        # node is already the rolled contribution and is what we check, never what we
        # multiply.
        edges = [e for e in ((ps.get(pn) or {}).get("bom_parents") or []) if isinstance(e, dict)]
        parent_counts = Counter(identity(e.get("parent")) for e in edges)
        if any(not k or v != 1 for k, v in parent_counts.items()):
            fail("duplicate_or_missing_parent_edge", pn)
        parents = {identity(e.get("parent")): e.get("qty") for e in edges
                   if parent_counts[identity(e.get("parent"))] == 1}
        active.add(pn)
        value: Optional[float]
        if pn == root:
            value = 1.0
            if parents:
                fail("product_root_has_parent", pn)
        elif not parents:
            fail("quantity_path_missing", pn)
            value = None
        else:
            value = 0.0
            if set(map(identity, n.get("parents") or [])) != set(parents):
                fail("parent_edge_disagreement", pn)
            for parent, per_parent in parents.items():
                q, parent_total = numeric(per_parent), roll(parent)
                if q is None or q <= 0 or parent_total is None:
                    fail("relative_quantity_unverified", pn, parent=parent)
                    value = None
                elif value is not None:
                    contribution = q * parent_total
                    recorded = numeric((n.get("qty_by_parent") or {}).get(parent))
                    if recorded is None or not isclose(recorded, contribution, abs_tol=1e-8, rel_tol=0):
                        fail("parent_contribution_mismatch", pn, parent=parent,
                             expected=contribution, actual=recorded)
                    value += contribution
        active.discard(pn)
        resolved[pn] = value
        return value

    for pn, n in ns.items():
        if n.get("qty_per_unit_basis", "per_finished_product") != "per_finished_product":
            fail("quantity_basis_unsupported", pn)
        if (n.get("qty_by_parent_basis", "rolled_contribution_per_finished_product")
                != "rolled_contribution_per_finished_product"):
            fail("parent_quantity_basis_unsupported", pn)
        p = ps.get(pn)
        if n.get("kind") in {"commercial", "consumable"} or is_commercial(p):
            continue
        expected = roll(pn)
        actual = numeric(n.get("qty_per_unit"))
        if p is None:
            fail("canonical_price_record_missing", pn)
        charged_basis = numeric((p or {}).get("quantity"))
        trace.append({"part": pn, "rolled_per_product": expected,
                      "graph_per_product": actual, "price_per_product": charged_basis})
        if expected is not None:
            for stage, value in (("graph", actual), ("price", charged_basis)):
                if value is None or not isclose(value, expected, abs_tol=1e-8, rel_tol=0):
                    fail("quantity_rollup_mismatch", pn, stage=stage, expected=expected, actual=value)
        explicit_unit = (p or {}).get("unit_of_measure") or (p or {}).get("unit")
        u = unit(explicit_unit)
        if explicit_unit and u is None:
            fail("quantity_unit_unknown", pn, unit=explicit_unit)
        if u == "each" and charged_basis is not None and not charged_basis.is_integer():
            fail("fractional_discrete_quantity", pn, quantity=charged_basis)
    for pn, p in ps.items():
        if pn not in ns and not p.get("set_aside") and not is_commercial(p):
            fail("canonical_record_outside_graph", pn)
    return {"schema": SCHEMA, "issues": issues, "trace": trace, "passed": not issues}
