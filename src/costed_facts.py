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

import re

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

__all__ = [
    "costed_operations",
    "has_operation",
    "parts_with_operation",
    "part_numbers_with_operation",
    "operations_for_part",
    "priced_route_known",
    "priced_rows_for_part",
    "canonical_identity",
    "canonical_quantity",
    "decision_ids_for_part",
    "part_material_cost",
    "is_placeholder_price",
    "job_totals",
    "costed_finish_label",
    "costed_finish_ops",
    "reconcile_risk_flags",
    "undrawn_bom_lines",
]


def undrawn_bom_lines(summary: Any) -> List[Dict[str, Any]]:
    """BOM lines naming a drawing the pack does not contain — nothing read them, nothing costed
    them, and the total still reads as a finished estimate.

    ONE READER, FOUR SURFACES. The Estimate sheet, the AI Provenance tab, the Decision Report and
    the job report all have to tell the same story about the same parts, and the invariant that
    finds them has already done the work. Recomputing it in each place is how two documents from
    one run come to name different parts.

    Returns [{part_number, description}], empty when the pack is complete.
    """
    if not isinstance(summary, dict):
        return []
    out: List[Dict[str, Any]] = []
    for violation in ((summary.get("invariants") or {}).get("violations") or []):
        if not isinstance(violation, dict):
            continue
        if str(violation.get("code") or "") != "bom_names_a_drawing_the_pack_does_not_contain":
            continue
        for m in ((violation.get("detail") or {}).get("missing") or []):
            if isinstance(m, dict) and str(m.get("part_number") or "").strip():
                out.append({"part_number": str(m.get("part_number")).strip(),
                            "description": str(m.get("description") or "").strip()})
    return out

def pack_shortfalls(source: Any) -> List[str]:
    """What the DRAWING PACK failed to supply or staged wrongly, in plain sentences.

    James's rule: when the engine has to code around a pack — a drawing export staged as
    a flat, a stray file matching no part, a BOM line with no drawing behind it — the
    covering e-mail and the report must SAY so, or the drawing office never hears it and
    every pack costs another engine fix. This is the one list both writers read.

    EVIDENCE-ONLY. Every sentence here traces to something the run recorded: the
    invariant violations engine_discoveries classifies as the drawing office's, the BOM
    lines naming drawings the pack does not contain, and the DXF augmentation ledger's
    own skip/unmatched entries. Nothing is inferred here, because a complaint to the
    drawing office that the engine invented is worse than silence."""
    if not isinstance(source, dict):
        return []
    out: List[str] = []
    _seen: Set[str] = set()

    def _add(s: str) -> None:
        k = " ".join(s.split()).upper()
        if s and k not in _seen:
            _seen.add(k)
            out.append(s)

    def _fname(p: Any) -> str:
        return str(p or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    for m in undrawn_bom_lines(source):
        _add(f"The BOM names {m['part_number']}"
             + (f" ({m['description']})" if m.get("description") else "")
             + " but the pack contains no drawing for it — the line is carried, "
               "not measured.")
    try:
        import engine_discoveries as _ed
        for v in ((source.get("invariants") or {}).get("violations") or []):
            if not isinstance(v, dict):
                continue
            code = str(v.get("code") or "")
            if code == "bom_names_a_drawing_the_pack_does_not_contain":
                continue                     # itemised per part above
            if _ed.classify(code) == "drawing":
                _add(str(v.get("message") or code.replace("_", " ")))
    except Exception:                                            # noqa: BLE001
        pass
    dxf = source.get("dxf_augmentation") or {}
    for s in (dxf.get("skipped") or []):
        if isinstance(s, dict) and str(s.get("reason") or "") == "drawing_export_not_a_flat":
            _add(f"'{_fname(s.get('path'))}' is a drawing export, not a manufacturing "
                 f"flat — it was staged alongside the real flats and had to be "
                 f"recognised by its content and set aside, never measured as cut path.")
    for u in (dxf.get("unmatched_dxf") or []):
        if isinstance(u, dict) and u.get("path"):
            _add(f"'{_fname(u.get('path'))}' matched no part in this job — a stray or "
                 f"mis-named file in the pack.")
    return out


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
    # 1. final_estimate.v1 — rows AS EXCEL CALCULATED THEM. Preferred, because it is the
    #    only structure carrying hours, rates and values: workbook_labour records what was
    #    handed TO the sheet, not what came out. A row here whose Total Value calculated to
    #    zero or errored is not part of the priced job and is dropped.
    fe = source.get("final_estimate")
    if not isinstance(fe, dict) and isinstance(source.get("estimate_summary"), dict):
        fe = source["estimate_summary"].get("final_estimate")
    if isinstance(fe, dict) and isinstance(fe.get("labour_rows"), list):
        # ROUTE IDENTITY comes from the accepted grouping, VALUE from Excel. The calculated
        # rows know what a line cost but not which engine operations or parts produced it;
        # the accepted rows know exactly that but nothing about cost. Joined on the sheet
        # row they share. Without the join the department name is all that survives, and
        # inverting it expands every alias — which is how the quote came to list both
        # "Assembly" and "Assemble", "Fold" and "Folding", "Weld" and "Welding".
        _accepted = {}
        _acc_node = source.get("workbook_labour")
        if not isinstance(_acc_node, dict) and isinstance(source.get("estimate_summary"), dict):
            _acc_node = source["estimate_summary"].get("workbook_labour")
        for _a in ((_acc_node or {}).get("rows") or []):
            if isinstance(_a, dict) and _a.get("workbook_row"):
                _accepted[int(_a["workbook_row"])] = _a
        rows = []
        for r in fe["labour_rows"]:
            if not isinstance(r, dict):
                continue
            # A line the sheet priced at nothing is not part of the job. Hours alone are not
            # enough: a row can carry time and still resolve to no charge, and putting that
            # on a client quote promises work we are not billing for.
            if _num(r.get("total_value_gbp")) <= 0:
                continue
            _acc = _accepted.get(int(_num(r.get("workbook_row")) or 0)) or {}
            rows.append({
                "wb_operation": r.get("operation") or _acc.get("wb_operation"),
                "engine_operations": _acc.get("engine_operations") or [],
                "part_numbers": _acc.get("part_numbers") or [],
                # The canonical decision(s) this sheet row exists because of. Carried
                # through the join or the audit trail stops at the workbook: once Excel has
                # been read back, `final_estimate` is preferred over `workbook_labour`, and
                # a projection that drops these makes the compiler's decision IDs
                # unreachable from every downstream deliverable precisely on the runs where
                # the route IS canonical.
                "decision_id": _acc.get("decision_id"),
                "decision_ids": list(_acc.get("decision_ids") or []),
                "route_group_id": _acc.get("route_group_id"),
                "rate_basis": _acc.get("rate_basis"),
                "qty_per_unit": r.get("qty_per_unit"),
                "batch_hours": r.get("batch_hours"),
                "total_value_gbp": r.get("total_value_gbp"),
                "workbook_row": r.get("workbook_row"),
                "_calculated": True,
            })
        if rows:
            return rows
    # 2. workbook_labour — the accepted INPUT grouping. Correct about WHICH operations and
    #    which parts, silent about what they cost.
    node = source.get("workbook_labour")
    if not isinstance(node, dict):
        node = (source.get("estimate_summary") or {}).get("workbook_labour") \
            if isinstance(source.get("estimate_summary"), dict) else None
    if isinstance(node, dict) and isinstance(node.get("rows"), list):
        return [r for r in node["rows"] if isinstance(r, dict)]
    return None


_DEPT_TO_ENGINE_OPS: Optional[Dict[str, List[str]]] = None


def _dept_to_engine_ops() -> Dict[str, List[str]]:
    """DEPARTMENT name -> engine operation key(s), inverted from wb_populate's own maps.

    A workbook row is labelled with the department ("Spray / Wet Paint"), which is what the
    estimators' template needs; the engine speaks in operation keys ("wet_spray"). Every
    consumer here matches on operation keys, so without the inverse a row whose engine op
    was not recorded resolves to nothing and the job silently looks like it has no finish.
    Inverted from the source maps rather than duplicated, so a new department cannot be
    added in one place and forgotten here."""
    global _DEPT_TO_ENGINE_OPS
    if _DEPT_TO_ENGINE_OPS is not None:
        return _DEPT_TO_ENGINE_OPS
    inv: Dict[str, List[str]] = {}
    try:
        import wb_populate as _wb
        for _map in (getattr(_wb, "OP_NAME_MAP", {}), getattr(_wb, "OP_NAME_MAP_ACRYLIC", {}),
                     getattr(_wb, "_TUBE_OP_REMAP", {})):
            for eng, dept in (_map or {}).items():
                if not dept:
                    continue
                bucket = inv.setdefault(str(dept).strip().lower(), [])
                if str(eng) not in bucket:
                    bucket.append(str(eng))
    except Exception:
        pass
    # HISTORICAL TITLES MUST KEEP RESOLVING.
    #
    # The titles the engine writes were corrected against the workbook's own rate table
    # ("Spray / Wet Paint" is really "Wet Spray", "CNC / Joinery machining" is "CNC
    # Joinery"). Every job JSON already saved on disk carries the OLD string, and inverting
    # only the current map makes those rows read as an unknown operation — so a finished job
    # re-opened tomorrow silently loses its finish.
    #
    # department_codes resolves both spellings to the same code, so an old title finds the
    # engine ops of whatever the row is called now. Added under the live map, never over it.
    try:
        from department_codes import LEGACY_TITLES, CODE_TITLES
        for _old_title, _code in LEGACY_TITLES.items():
            _entry = CODE_TITLES.get(_code)
            if not _entry:
                continue
            _key = str(_old_title).strip().lower()
            _current = str(_entry[0]).strip().lower()
            if _key in inv or _current not in inv:
                continue
            inv[_key] = list(inv[_current])
    except Exception:
        pass
    _DEPT_TO_ENGINE_OPS = inv
    return inv


def _row_engine_ops(row: Dict[str, Any]) -> List[str]:
    """The engine operation key(s) a workbook labour row represents.

    Prefers what wb_populate recorded when the group was formed; falls back to inverting the
    department name. Never returns the department string itself dressed up as an operation —
    that is what made the earlier version depend on luck."""
    inv = _dept_to_engine_ops()
    ops = [str(o) for o in (row.get("engine_operations") or []) if o]
    if not ops and row.get("engine_operation"):
        ops = [str(row["engine_operation"])]
    # An earlier version wrote the group KEY into engine_operation, which is the DEPARTMENT
    # name. Runs made with it are already on disk, so detect the shape rather than trust the
    # field: if the value is itself a known department, invert it instead of passing it
    # through as an operation nobody matches.
    # BUT AN OP SPELLED LIKE ITS DEPARTMENT IS STILL AN OP. "linebend" is both the engine
    # word and (lowercased) the Linebend department, so the department-shape detection
    # exploded it into every synonym — and the customer quote printed "Precision folding"
    # for a job whose route had explicitly ruled folding out. A value that is a real
    # engine vocabulary word passes through as itself; only a value that is ONLY a
    # department title gets inverted.
    _engine_words = {str(k).strip().lower() for ops_list in inv.values()
                     for k in ops_list}
    ops = [o for o in ops
           if o.strip().lower() in _engine_words or o.strip().lower() not in inv] or [
        e for o in ops for e in inv.get(o.strip().lower(), [])]
    if ops:
        return ops
    # ONE canonical operation per department, not every synonym mapping to it. OP_NAME_MAP
    # carries aliases ("assemble"/"assembly", "fold"/"folding", "weld"/"welding") so a
    # department inverts to several keys, and a consumer rendering each in plain language
    # printed the same operation twice under different names.
    dept = str(row.get("wb_operation") or "").strip().lower()
    hit = inv.get(dept)
    return [hit[0]] if hit else ([dept] if dept else [])


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
            for op in _row_engine_ops(r):
                totals[op] = totals.get(op, 0.0) + max(_num(r.get("qty_per_unit")), 1.0)
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
            keys = {o.lower() for o in _row_engine_ops(r)}
            keys.add(str(r.get("wb_operation") or "").lower())
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
                for op in _row_engine_ops(r):
                    if op not in out:
                        out.append(op)
        return out
    if isinstance(part_estimate, dict):
        return list(costed_operations([part_estimate]))
    return []


def priced_route_known(source: Any) -> bool:
    """True once the workbook has told us which operations this job actually charges.

    The distinction every narrating deliverable needs. While this is False there is no
    priced route, so falling back to the drawing's own textual/inferred operation lists is
    the best available answer. Once it is True, a part named in NO workbook row carries no
    charged operation — and printing the drawing's words for it instead of saying so puts a
    route on the page that the Estimate sheet two tabs away does not contain. That is the
    exact failure this module exists to prevent, and an `or raw_lists` fallback reintroduces
    it for every part the gates dropped."""
    return _workbook_rows(source) is not None


# ── canonical BOM identity and multiplicity ──────────────────────────────────
# The route compiler rolls quantity THROUGH the hierarchy: a node's `qty_per_unit` is how
# many are needed per top-level unit. A BOM row's own `quantity` is per PARENT, so for
# anything reached through a sub-assembly the two differ by the parent's multiplicity — a
# knob at qty 2 inside a sub-assembly used twice is 4 per unit, and the BOM row says 2.
#
# wb_populate already applies this when it builds the sheet (canonicalise_part_estimates_
# for_workbook overwrites `quantity` from the node), but it does that on a LOCAL copy that
# is never stamped back. So the sheet charges the rolled quantity while every report reading
# manufacturing_writeup still prints the per-parent one.


def _canonical_nodes(source: Any) -> Dict[str, Dict[str, Any]]:
    """identity -> canonical graph node, from the compiled route."""
    if not isinstance(source, dict):
        return {}
    payload = ((source.get("estimate_summary") or {}).get("canonical_route_shadow")
               if isinstance(source.get("estimate_summary"), dict) else None) \
        or source.get("canonical_route_shadow") or {}
    if not isinstance(payload, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for node in payload.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        identity = str(node.get("part_number") or "").strip().upper()
        if identity:
            out[identity] = node
    return out


def canonical_identity(source: Any, part_number: Any) -> str:
    """The canonical part identity for a part number, resolving raw aliases.

    A record can reach a report under a spelling the graph merged away (a synthesised BI-
    code, a raw variant). Looking the number up verbatim then misses the node and silently
    falls back to the uncanonical value, which is indistinguishable from having no node."""
    pn = str(part_number or "").strip().upper()
    if not pn:
        return ""
    nodes = _canonical_nodes(source)
    if pn in nodes:
        return pn
    for identity, node in nodes.items():
        for alias in ((node.get("evidence") or {}).get("raw_aliases") or []):
            if str(alias).strip().upper() == pn:
                return identity
    return pn


def canonical_quantity(source: Any, part_number: Any) -> Optional[float]:
    """Quantity PER TOP-LEVEL UNIT, from the compiled hierarchy.

    None when the graph does not know the part — the caller keeps whatever it had, rather
    than being handed a defaulted 1 that looks like a real answer."""
    node = _canonical_nodes(source).get(canonical_identity(source, part_number))
    if not isinstance(node, dict) or node.get("qty_per_unit") is None:
        return None
    qty = _num(node.get("qty_per_unit"))
    return qty if qty > 0 else None


def priced_rows_for_part(source: Any, part_number: Any) -> List[Dict[str, Any]]:
    """The workbook labour rows this part is charged on, in sheet order.

    The join that makes a report auditable: a part on the page -> the sheet rows it is
    priced in -> the compiler decisions that put it there. Matched through canonical
    identity, so a record that reached the caller under a merged-away alias still finds its
    rows instead of silently looking unpriced."""
    pn = canonical_identity(source, part_number)
    rows = _workbook_rows(source)
    if not pn or rows is None:
        return []
    out = [r for r in rows
           if any(canonical_identity(source, x) == pn
                  for x in (r.get("part_numbers") or []))]
    return sorted(out, key=lambda r: _num(r.get("workbook_row")))


def _decisions_by_id(source: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(source, dict):
        return {}
    payload = ((source.get("estimate_summary") or {}).get("canonical_route_shadow")
               if isinstance(source.get("estimate_summary"), dict) else None) \
        or source.get("canonical_route_shadow") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for decision in (payload or {}).get("decisions") or []:
        if isinstance(decision, dict) and decision.get("decision_id"):
            out[str(decision["decision_id"])] = decision
    return out


def decision_ids_for_part(source: Any, part_number: Any) -> List[str]:
    """Canonical OperationDecision ids behind the rows this part is charged on.

    SCOPED TO THE PART, not to the row. A workbook row is a tooling SETUP and can group
    several parts — 2085's two tubes share one Tube row, which carries both tube-cut
    decisions. Returning every id on every row the part appears in therefore told each tube
    it was cut by the other tube's decision as well as its own, which is precisely the
    mis-join the canonical route exists to prevent, reappearing in the sheet that documents
    it.

    A decision belongs to a part when the part is its target or one of its participants.
    An ASSEMBLY-scoped decision legitimately belongs to every participant — the weld event
    is one event across three parts — so this narrows part events without hiding shared
    ones.

    Taken from the workbook rows rather than the decision list directly, so it names only
    decisions that survived every gate and reached the sheet."""
    pn = canonical_identity(source, part_number)
    known = _decisions_by_id(source)
    out: List[str] = []
    for r in priced_rows_for_part(source, part_number):
        ids = [str(d) for d in (r.get("decision_ids") or []) if d]
        if not ids and r.get("decision_id"):
            ids = [str(r["decision_id"])]
        for d in ids:
            decision = known.get(d)
            if decision is not None and pn:
                members = {canonical_identity(source, x) for x in
                           ([decision.get("target_id")]
                            + list(decision.get("participants") or []))}
                # An unresolvable decision keeps the old behaviour rather than vanishing:
                # a missing shadow must not silently empty the audit trail.
                if members and pn not in members:
                    continue
            if d not in out:
                out.append(d)
    return out


def part_material_cost(part: Mapping[str, Any]) -> tuple:
    """(unit, extended) MATERIAL cost for one part — the only per-part money there is.

    THERE IS NO PER-PART LABOUR FIGURE ON A CANONICAL JOB. Labour is charged per DEPARTMENT
    ROW, as a batch value across every part in that tooling setup, so any per-part labour
    number is an engine-era apportionment that reconciles to nothing. On 2085 that showed as
    GBP 19.25 against each tube on a sheet whose whole unit price is GBP 6.33 — a
    labour-inclusive engine total sitting in a column headed like a cost.

    Material is different: it IS costed per part, it is what the sheet's material blocks
    are built from, and it sums to the workbook's own material total. So that is what the
    per-part column shows, and it is labelled material."""
    if not isinstance(part, Mapping):
        return 0.0, 0.0
    me = part.get("material_estimate")
    me = me if isinstance(me, Mapping) else {}
    unit = _num(me.get("unit_material_cost_gbp"))
    if not unit:
        unit = _num(me.get("cost_per_part_gbp"))
    qty = _num(part.get("quantity")) or 1.0
    return unit, unit * qty


def is_placeholder_price(part: Mapping[str, Any]) -> bool:
    """True when this line carries no price because nobody has priced it yet.

    Distinct from a line that costs nothing. PACKAGING and DELIVERY are per-unit shares an
    estimator fills in; describing them as "priced from catalogue/history" states a
    provenance that does not exist, on the two lines most likely to be forgotten."""
    if not isinstance(part, Mapping):
        return False
    if part.get("_price_explicitly_withheld"):
        return True
    unit, _ext = part_material_cost(part)
    if unit:
        return False
    text = " ".join(str(part.get(k) or "") for k in
                    ("description", "review_flag")).lower()
    flags = " ".join(str(f) for f in (part.get("review_flags") or [])).lower()
    return "estimator to price" in text or "estimator to price" in flags


def job_parts(source: Any) -> List[Dict[str, Any]]:
    """THE ONE PART LIST EVERY DELIVERABLE MUST DESCRIBE.

    Five deliverables were reading three different lists:

      Estimate sheet                      the canonicalised list
      Decision Report, AI Provenance      manufacturing_writeup.parts
      quote HTML, job report, xlsx        estimate_summary.part_estimates

    and the first of those was a local variable in populate_workbook, discarded the moment
    the workbook was saved. Canonicalising is not cosmetic: it merges recogniser-minted
    duplicates into the drawing's own code, rolls sub-assembly multiplicity into every
    quantity, and ADDS explicit bought-in BOM lines that never got a pricing record. So a
    bought-in the sheet charges appeared on no other page, a duplicate appeared on every
    page but the sheet, and quantities differed wherever a part sits below the first level.
    Totals were only the visible end of it.

    Each record is the canonical estimate — identity, quantity, cost, material — overlaid on
    the manufacturing_writeup record for the same part, which is where the provenance and
    geometry fields live that the Decision Report and AI Provenance columns are built from.
    Joined through canonical identity, so a record that reached us under a merged-away alias
    still finds its evidence.

    Falls back to part_estimates when no workbook has been built, because then there is no
    canonical list and the engine's own is the only one there is."""
    if not isinstance(source, dict):
        return []
    est_summary = source.get("estimate_summary")
    canonical = (est_summary or {}).get("canonical_part_estimates") \
        if isinstance(est_summary, dict) else None
    if not isinstance(canonical, list) or not canonical:
        canonical = _part_estimates(source)

    provenance: Dict[str, Dict[str, Any]] = {}
    for record in ((source.get("manufacturing_writeup") or {}).get("parts") or []):
        if isinstance(record, dict) and record.get("part_number"):
            provenance.setdefault(
                canonical_identity(source, record["part_number"]), record)

    node = source.get("workbook_labour")
    if not isinstance(node, dict) and isinstance(est_summary, dict):
        node = est_summary.get("workbook_labour")
    skipped = {str(x).strip().upper()
               for x in ((node or {}).get("skipped_part_numbers") or [])}

    out: List[Dict[str, Any]] = []
    for estimate in canonical:
        if not isinstance(estimate, dict):
            continue
        identity = str(estimate.get("part_number") or "").strip().upper()
        merged = dict(provenance.get(identity) or {})
        # The estimate wins on everything it actually carries. A key present but empty must
        # not clobber a real reading from the drawing record — that is how a part with a
        # costed thickness and no geometry fields ended up looking like it had neither.
        for key, value in estimate.items():
            if value not in (None, "", [], {}) or key not in merged:
                merged[key] = value
        # ...except identity and multiplicity, which are the canonical answer by definition.
        merged["part_number"] = estimate.get("part_number")
        if estimate.get("quantity") is not None:
            merged["quantity"] = estimate.get("quantity")
        # A part the workbook set aside is still part of the job and must stay visible, but
        # nothing may present it as priced.
        merged["_sheet_skipped"] = identity in skipped
        out.append(merged)
    return out


def job_totals(source: Any) -> Dict[str, Any]:
    """The authoritative per-unit totals, and where they came from.

    `final_estimate.totals` is what the Estimate sheet CALCULATED; everything the engine
    summed on its own is a different calculator and can differ materially. Reports need both
    — the workbook figure to show, and the engine sum to reconcile against — plus an honest
    label for which is which. `source` is "excel_calculated" or "engine_part_sum"."""
    out: Dict[str, Any] = {
        "material_gbp": None, "labour_gbp": None, "unit_gbp": None,
        "engine_part_sum_gbp": None, "source": "engine_part_sum",
    }
    engine = sum(_num(p.get("extended_total_cost_gbp"))
                 for p in _part_estimates(source))
    out["engine_part_sum_gbp"] = round(engine, 4) if engine else 0.0
    fe = source.get("final_estimate") if isinstance(source, dict) else None
    if not isinstance(fe, dict) and isinstance(source, dict) \
            and isinstance(source.get("estimate_summary"), dict):
        fe = source["estimate_summary"].get("final_estimate")
    totals = fe.get("totals") if isinstance(fe, dict) else None
    if isinstance(totals, dict):
        for key in ("material_gbp", "labour_gbp", "unit_gbp"):
            # Excel errors are carried as null by the read-back and must stay null here:
            # coercing a #DIV/0! to 0.0 turns missing data into a figure that reconciles.
            if totals.get(key) is not None:
                out[key] = _num(totals.get(key))
        if out["unit_gbp"] is not None:
            out["source"] = "excel_calculated"
    return out


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
    sheet does not contain.

    EVERY CHARGED FINISH, NOT THE FIRST ONE FOUND. This returned on the first match, so a
    stand carrying BOTH a diamond-polished acrylic lens and £15.83 of subcontract plating went
    to the customer described as "Diamond polished" alone — the plating paid for and unnamed.
    The reverse of the promise-what-you-do-not-charge rule, and just as wrong: the quote must
    name what the price contains.

    Plating is charged as a subcontract BOM LINE rather than an operation, so it is not in
    _FINISH_OPS and has to be recognised from the priced rows."""
    labels = [label for op, label in _FINISH_OPS if has_operation(source, op)]
    if _subcontract_plating_is_costed(source) and "Plated" not in labels:
        labels.append("Plated")
    labels = list(dict.fromkeys(labels))
    if not labels:
        return default
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1].lower()


def _subcontract_plating_is_costed(source: Any) -> bool:
    """True when a subcontract plating line carries money on this job.

    Plating does not appear as an operation — it is a bought-in/commercial row priced on the
    plated mass — so the finish label cannot find it the way it finds powder or polish."""
    try:
        rows = job_parts(source) or []
    except Exception:                                                # noqa: BLE001
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        method = str((row.get("material_estimate") or {}).get("cost_method")
                     or row.get("cost_source") or row.get("source") or "").lower()
        if "plating" not in method:
            continue
        try:
            if float(row.get("unit_cost_gbp") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


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

    # ── stale PRE-COST learning flags ─────────────────────────────────────────
    # ZERO_COST_STEEL is raised by the learning engine when a MILD_STEEL part with a DXF
    # still costs nothing. It runs BEFORE the workbook, and nothing ever revisited it — so
    # 2085-01 carried "review material/thickness" onto the audit tab while the sheet two
    # tabs away charged it £0.13 of material and a laser row. A flag that the finished job
    # contradicts is worse than no flag: it sends an estimator to check something that is
    # already answered, and it makes the engine look like it disagrees with itself.
    #
    # Superseded, not deleted. The cue was real at the time it fired.
    for parts in buckets:
        for p in parts:
            if not isinstance(p, dict):
                continue
            _lf = str(p.get("_learning_flag") or "")
            if "ZERO_COST_STEEL" in _lf:
                _unit, _ext = part_material_cost(p)
                _priced = bool(_unit) or bool(priced_rows_for_part(summary,
                                                                   p.get("part_number")))
                if _priced:
                    p["_learning_flag"] = " | ".join(
                        s for s in _lf.split(" | ") if "ZERO_COST_STEEL" not in s)
                    p.setdefault("superseded_risk_flags", []).append({
                        "flag": "ZERO_COST_STEEL",
                        "reason": ("raised before costing, when this part had no cost; the "
                                   "finished workbook prices its material and charges it on "
                                   "a labour row, so it is no longer a review item"),
                    })
                    out["superseded"] += 1
            if not isinstance(p.get("risk_flags"), list):
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


# ── ONE ANSWER TO "WHAT BLANK IS THIS PART?" ────────────────────────────────────────
# A part's blank is written to as many as four places, and the readers disagreed about
# which to believe:
#
#   wb_populate (and the cost)   material_estimate -> normalized_geometry
#   invariants._blank_num        part -> normalized_geometry -> geometry_rollup
#
# _blank_num never looks at material_estimate. On 11650-01-05A DOOR that is the difference
# between 1202 x 689 -- the size that actually priced the job, confirmed by the run's own
# "largest part 0.8282 m2" throughput flag, which is 1.202 x 0.689 -- and 5 x 3.5, which
# priced nothing. The blocking blank_and_cut_path_disagree therefore described a blank the
# estimate had never used, and sent two separate diagnoses after a costing fault that did
# not exist.
#
# _blank_num's own docstring records being widened once already after a false positive from
# looking in too few places. It was still one holder short. So the fix is not a fourth
# holder in a fourth reader: it is one reader, and a DISAGREEMENT REPORTED RATHER THAN
# SILENTLY RESOLVED. Two blanks on one part is a real defect; picking one quietly is how it
# stayed invisible while its symptom was blamed on something else.
_BLANK_HOLDERS = ("material_estimate", "normalized_geometry", "geometry_rollup")

# Two readings of one blank are the same reading if they agree to a millimetre. Below that
# is rounding between a flat-pattern extractor and a title block, not a conflict.
_BLANK_SAME_MM = 1.0


def _blank_pair(holder: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(holder, Mapping):
        return None
    for lk, wk in (("blank_length_mm", "blank_width_mm"),
                   ("overall_length_mm", "overall_width_mm")):
        length, width = _num(holder.get(lk)), _num(holder.get(wk))
        if length and width:
            return (float(length), float(width))
    return None


def blank_dimensions(part: Any) -> Dict[str, Any]:
    """The blank this part was COSTED from, plus every other blank recorded for it.

    Precedence is material_estimate first because that is the record the costing wrote and
    the sheet was built from -- the operative blank is the one that produced the money, not
    the one a later reader happens to find first.

    Returns {length_mm, width_mm, holder, readings, conflict}. `readings` lists every holder
    that carries a blank, so a caller can NAME the disagreement instead of resolving it out
    of sight.
    """
    out: Dict[str, Any] = {"length_mm": None, "width_mm": None, "holder": None,
                           "readings": [], "conflict": False}
    if not isinstance(part, Mapping):
        return out
    for name in _BLANK_HOLDERS:
        pair = _blank_pair(part.get(name))
        if pair:
            out["readings"].append({"holder": name, "length_mm": pair[0], "width_mm": pair[1]})
    root = _blank_pair(part)
    if root:
        out["readings"].append({"holder": "part", "length_mm": root[0], "width_mm": root[1]})
    if not out["readings"]:
        return out
    first = out["readings"][0]
    out.update({"length_mm": first["length_mm"], "width_mm": first["width_mm"],
                "holder": first["holder"]})
    out["conflict"] = any(
        abs(r["length_mm"] - first["length_mm"]) > _BLANK_SAME_MM
        or abs(r["width_mm"] - first["width_mm"]) > _BLANK_SAME_MM
        for r in out["readings"][1:])
    return out


# ── which cost stream a part belongs to, asked once ──────────────────────────────────
# THREE ANSWERS TO ONE QUESTION, AND THEY DISAGREED.
#
#   wb_populate._is_board   substring tokens  -- "MR MDF" is board, "6MM ABS" is board
#   xlsx_output._is_board   an exact-match set -- neither of those is board
#
# So the workbook put a part in Other Sheet Material and the AI spreadsheet put the same
# part somewhere else, on the same run, from the same record. The engine had no opinion at
# all, which is how it came to nest a polycarbonate door by a rule written for steel.
#
# The token lists below are wb_populate's, unchanged -- they are the ones that have been
# reading real drawings. The exact-match set is what goes, because it fails on every
# material anybody actually writes on a drawing: MR MDF, 6MM ABS, CLEAR POLYCARB.
_PLASTIC_SHEET_TOKENS = (
    "ACRYLIC", "PERSPEX", "POLY",            # POLY catches POLYCARBONATE/PROP/STYRENE/ETHYLENE
    "PETG", "PET ",                          # PET with a space: "PET" alone matches PETROL, PETG
    "HIPS", "ABS", "PVC", "FOAM", "NYLON",
    "ACETAL", "DELRIN", "HDPE", "UHMW", "PMMA",
    # Aluminium composite panel (ACM) — costed by AREA on a board sheet, CNC-ROUTED not lasered
    # (the laser melts the polyethylene core). Brand names because that is what drawings write;
    # "COMPOSITE" is the generic. Dyson 10575-02-009 is DIBOND 3mm.
    "DIBOND", "ALUPANEL", "REYNOBOND", "ETALBOND", "COMPOSITE",
)
_BOARD_TIMBER_TOKENS = (
    "MDF", "BOARD", "MELAMINE", "MFC",
    "TIMBER", "WOOD", "PINE", "PLYWOOD", "SOFTWOOD", "HARDWOOD", "OAK",
    "SPRUCE", "BEECH", "BIRCH",
)


def is_other_sheet_material(material) -> bool:
    """True when this material is costed in the workbook's Other Sheet Material block.

    Not sheet metal -- so it is costed by area on a board/plastic sheet rather than by
    mass on steel. The name follows the WORKBOOK's block, not a guess about the shop:
    what this decides is which nesting rule and which price stream apply.
    """
    m = str(material or "").upper()
    return any(k in m for k in _PLASTIC_SHEET_TOKENS + _BOARD_TIMBER_TOKENS)


# The Other Sheet Material block nests by its own rule, and it is NOT the steel one.
#
#   Estimate sheet, Sheet Steel        K38:  INT(I/(F+20)) × INT((J-80)/(G+10))
#   Estimate sheet, Other Sheet Material J51: INT(I/(F+20)) × INT((J-5)/(G+20))
#
# estimator.select_sheet_size implements K38 exactly, and its own docstring says the other
# block "uses a different rule (-5 margin, +20 both axes); that is handled separately for
# non-steel materials". It was not handled anywhere. The plastic path divided full sheet
# area by part area instead -- not nesting at all, just arithmetic that ignores the gaps
# between parts and the unusable strip down the edge.
#
# On 11650's door, 1202 x 689 out of a 3050 x 2050 sheet, that is the difference between
# 7 parts per sheet and 4. The workbook computes J51 itself from the dimensions written
# into the row, so the sheet said 4 and the engine's own record said 7 -- for the same
# part, on the same run. Nearly a factor of two on the material, in the direction of
# under-charging.
_OTHER_SHEET_LENGTH_GAP = 20.0    # J51: I/(F+20)
_OTHER_SHEET_WIDTH_MARGIN = 5.0   # J51: (J-5)
_OTHER_SHEET_WIDTH_GAP = 20.0     # J51: /(G+20)

_SHEET_STEEL_LENGTH_GAP = 20.0    # K38: I/(F+20)
_SHEET_STEEL_WIDTH_MARGIN = 80.0  # K38: (J-80)
_SHEET_STEEL_WIDTH_GAP = 10.0     # K38: /(G+10)

# ── BOTH RULES, IN ONE PLACE, KEYED ON THE MATERIAL ──────────────────────────────────
# Adding J51 above fixed the money and left the record lying. estimator.select_sheet_size
# still ran K38 over EVERY material and wrote its answer into stock_estimate, so
# 11650-04's PETG side panels came back carrying
#
#   nesting_formula='INT(3050/(1250+20)) x INT((2050-80)/(525+10)) [template K38, ...]'
#
# on a part priced by J51. Two answers to one question on one record, and the one a reader
# sees is the one that did not charge the job -- which is how a diagnostic run to explain a
# handed pair reported the steel rule for a plastic panel and nearly sent the next fix in
# the wrong direction.
#
# They agree on 1250 x 525 (6 either way), so nothing was mispriced by it HERE. That is
# exactly why it survived: a wrong rule that happens to agree on the part in front of you
# is invisible until the geometry moves.
#
# Worse, the LLM-market-rate branch in estimator applies J51 to anything that reaches it,
# and it is entered whenever an LLM returns a GBP/m2 rate -- including for a steel the
# engine holds no price for. The rule has to follow the MATERIAL, not the code path that
# happened to price the line.
_NESTING_RULES = {
    "workbook_other_sheet_J51": (_OTHER_SHEET_LENGTH_GAP, _OTHER_SHEET_WIDTH_MARGIN,
                                 _OTHER_SHEET_WIDTH_GAP, "template J51"),
    "workbook_sheet_steel_K38": (_SHEET_STEEL_LENGTH_GAP, _SHEET_STEEL_WIDTH_MARGIN,
                                 _SHEET_STEEL_WIDTH_GAP, "template K38"),
}


def nesting_rule_for(material) -> str:
    """Which of the workbook's two nesting rules charges this material.

    The same question the block classifier already answers -- a part costed in the Other
    Sheet Material block is nested by that block's rule. Asking it through
    is_other_sheet_material means the two can never disagree about one part.
    """
    return ("workbook_other_sheet_J51" if is_other_sheet_material(material)
            else "workbook_sheet_steel_K38")


def nest_on_sheet(material, part_length_mm, part_width_mm,
                  sheet_length_mm, sheet_width_mm):
    """How this part nests on this sheet, by the rule its material is charged under.
    None when it will not nest -- a fact, not a quantity of zero.

    FIXED ORIENTATION, like the template. The workbook does not rotate parts, so an engine
    that did would produce a number the sheet disagrees with, which is the whole defect.
    """
    return _nest_by_rule(nesting_rule_for(material), part_length_mm, part_width_mm,
                         sheet_length_mm, sheet_width_mm)


def _nest_by_rule(rule, part_length_mm, part_width_mm, sheet_length_mm, sheet_width_mm):
    length_gap, width_margin, width_gap, label = _NESTING_RULES[rule]
    try:
        pl, pw = float(part_length_mm), float(part_width_mm)
        sl, sw = float(sheet_length_mm), float(sheet_width_mm)
    except (TypeError, ValueError):
        return None
    if pl <= 0 or pw <= 0 or sl <= 0 or sw <= 0:
        return None
    # NO SEPARATE "DOES IT FIT" GUARD. One was written here and no mutant could kill it:
    # a part that does not fit gives nx or ny of 0 and falls out as None on its own, because
    # the gap and margin are subtracted before the division. A branch no input can reach is
    # not documentation, it is a claim that something is being checked when it is not.
    nx = int(sl / (pl + length_gap))
    ny = int((sw - width_margin) / (pw + width_gap))
    qty = max(0, nx) * max(0, ny)
    if not qty:
        return None
    return {
        "parts_per_sheet": qty,
        "nx": nx,
        "ny": ny,
        "nesting_rule": rule,
        "nesting_formula": (f"INT({sl:g}/({pl:g}+{length_gap:.0f})) × "
                            f"INT(({sw:g}-{width_margin:.0f})/({pw:g}+{width_gap:.0f}))"
                            f"  [{label}, fixed orientation]"),
    }


def other_sheet_parts_per_sheet(part_length_mm, part_width_mm,
                                sheet_length_mm, sheet_width_mm):
    """Parts per sheet by the workbook's Other Sheet Material rule (J51). None if it will
    not fit, which is a fact and not a quantity -- 0 would divide into a cost of infinity
    and 1 would quietly claim a part fits on a sheet it is bigger than.

    Named for the BLOCK because callers that know they are in it should not have to name a
    material to ask. It names the RULE, not a material that happens to classify to it -- an
    example material here would be a second classifier, and the point of nesting_rule_for is
    that there is only ever one.
    """
    nest = _nest_by_rule("workbook_other_sheet_J51", part_length_mm, part_width_mm,
                         sheet_length_mm, sheet_width_mm)
    return (nest or {}).get("parts_per_sheet")


# ═══════════════════════════════════════════════════════════════════════════════════════
# THE ONE RECORD EVERY DELIVERABLE READS
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# On 7332-01's 17:17 run the workbook said one thing and its own paperwork said four others
# about the same twelve lines. The covering e-mail called two configured house rates "AI
# market indications" (the Explanation tab, on the next sheet, said no line rested on one),
# summed them to £16.03 in its banner and £16.63 in its footer, and printed "not named" for
# a leg whose provenance row named the rate. The AI Provenance tab listed folding on a tube
# the route had ruled out of folding, showed a 9,106 mm cut path against a 1,397 mm leg, and
# labelled £5.13 of nest-versus-net-part basis "Powder / scrap" under a heading that said
# nothing was coated. The report warned that plating was uncharged beside a £15.83 plating
# line, and the quote promised "Boxed for transport" with packaging at £0.
#
# None of those writers was wrong about the job. Each was right about its own reading and
# there were five readings. This block is the sixth, and it is the only one: built ONCE from
# the calculated workbook rows joined to the canonical parts and the compiled route, and
# every surface below it reads what it says rather than working the answer out again.
#
# WHAT IS IN IT, and why each thing is a field rather than a sentence:
#
#   charged vs engine     The sheet charges a nested part its share of a whole sheet; the
#                         engine's own figure is net-part. Both are real. CHARGED is the
#                         money; ENGINE is provenance. A writer that has both cannot print
#                         £2.02 as the price of a £2.82 line.
#   price origin          WHERE the figure came from (nest, config house rate, catalogue,
#                         market/AI, nobody yet) — separately from
#   firmness              HOW FIRM it is (firm, indicative house rate, indicative market
#                         figure, unpriced, nil by design). "Indicative" is not a source and
#                         "AI" is not a firmness; conflating them is how a config rate was
#                         reported as a model guess.
#   operations            From the compiler decisions that actually put the part on a priced
#                         row — never from a department name inverted through its aliases.
#   length                For section stock: the millimetres, the rung, and the reader.
#   gaps                  The lists the banner, the Explanation, the footer and §5 all print.
#                         One list each, summed once.
#   release               provisional / reviewable, with the reasons, for the quote's banner.

COSTED_JOB_SCHEMA = "costed_job.v1"

# Firmness — how far the figure can be leaned on. Five words, used everywhere.
FIRM = "firm"                           # the sheet's own arithmetic or a catalogue price
INDICATIVE_HOUSE = "indicative_house"   # a configured SDI rate, reproducible, to VERIFY
INDICATIVE_MARKET = "indicative_market" # an AI / market lookup, moves between runs, to REPLACE
UNPRICED = "unpriced"                   # carries no money and somebody owes a figure
NIL = "nil"                             # correctly nothing — an assembly, a cross-reference

# The engine's own source tokens, said in words an estimator can act on. Kept HERE so the
# Explanation tab, the covering e-mail and the two provenance tabs phrase one origin one way.
PRICE_ORIGIN_LABELS: Dict[str, str] = {
    "standard_commodity_provisional":
        "SDI standard-commodity rate (INDICATIVE) — confirm against a supplier quote",
    "config_commercial_indicative":
        "SDI house rate for this commercial line (INDICATIVE) — confirm",
    "config rate card":
        "SDI standard-commodity rate (INDICATIVE) — confirm against a supplier quote",
    "subcontract_plating_indicative":
        "SDI subcontract plating rate, £/kg from config (INDICATIVE) — confirm against a plater quote",
    # The section trade rate is a house MATERIAL rate — the same standing as the sheet's own
    # £/tonne cell, which nobody calls provisional. Named, so the line no longer reads "not
    # named"; not on the to-verify list, so the leg is not counted beside the plating hold.
    "section_stock_config_rate":
        "SDI section-stock trade rate, £/kg from config — verify against the section size",
    "section_stock_flat_rate":
        "flat-product £/kg rate (INDICATIVE, likely UNDER-READS section) — set the section trade rate",
    "market_ai_indicative": "AI market indication — NOT A QUOTE, replace it",
    "system_cost_not_found": "no rate found — estimator to price",
}

_MARKET_AI_TOKENS = ("grok", "llm", "xai", "market")
_CATALOGUE_TOKENS = ("udef", "pma", "erp", "bought_in_price", "price_book", "catalog",
                     "historical", "supplier_quote", "sheet_rate_live")
_FABRICATED_BLOCKS = {"steel": "Sheet Steel", "other_sheet": "Other Sheet Material",
                      "tube": "Tube", "wire": "Wire"}


def _final_estimate_of(source: Any) -> Dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    fe = source.get("final_estimate")
    if not isinstance(fe, dict) and isinstance(source.get("estimate_summary"), dict):
        fe = source["estimate_summary"].get("final_estimate")
    return fe if isinstance(fe, dict) else {}


def _material_row_key(row: Mapping[str, Any]) -> str:
    """The identity a read-back material row joins on — the BOM's code column, or the first
    word of a fabricated block's description, which is where wb_populate writes the part
    number. Same rule as wep_readback_from_xlsx._row_key, restated here so this module has
    no import of the Excel adapter.

    THE HAND IS PART OF THE IDENTITY. 11350-01's right arm writes its steel row as
    "11350-01-02 MIR  RIGHT ARM 200MM" — the first word alone is the LEFT arm's code, so
    the right arm's £0.45 joined its twin (and was dropped by setdefault), its own line
    found only the unpriced BOM row, and every surface but the nest called a charged part
    free — one count said 6 prices missing over a five-item list. A separate MIR/MIRROR
    token after the code belongs to the code."""
    code = str(row.get("part_code") or "").strip()
    if code:
        return code.upper()
    toks = str(row.get("description") or "").strip().split()
    if not toks:
        return ""
    key = toks[0].upper()
    if len(toks) > 1 and toks[1].upper() in ("MIR", "MIRROR"):
        key += " " + toks[1].upper()
    return key


_THICKNESS_SOURCE_WORDS = ("dxf", "solidworks", "native", "model", "cutlist", "cut_list",
                           "title_block", "drawing", "filename")


def boilerplate_thickness_values(source: Any) -> Dict[float, List[str]]:
    """Document-level thickness text masquerading as per-part readings — with names.

    On 7332-01 the deterministic drawing reader put 1.2 mm on EVERY steel part — the
    same figure from the GA's boilerplate, not six measurements — and the moment gauge
    disagreements became decisions, five phantom decisions buried the two real ones.

    Two probes then broke the first cut of this census. It counted displaced ENTRIES,
    so one part whose provenance log repeated the same refusal three times crossed the
    threshold alone and its genuine disagreement vanished. And it treated the threshold
    as proof of boilerplate, dismissing the value with "no action" — but three genuine
    detail drawings can state the same gauge, and the engine cannot tell those apart
    from a title-block note. So: the census counts DISTINCT part identities, and the
    caller turns each value into ONE grouped decision naming the parts, never a
    dismissal. Returns {value: sorted part numbers} for values refused on >=3 parts."""
    census: Dict[float, Set[str]] = {}
    _pool = list(job_parts(source)) if isinstance(source, dict) else []
    _pool += [p for p in ((source.get("manufacturing_writeup") or {}).get("parts") or [])
              if isinstance(source, dict)]
    _seen_pns: Set[str] = set()
    for part in _pool:
        if not isinstance(part, Mapping):
            continue
        _pn = str(part.get("part_number") or "").strip().upper()
        if not _pn or _pn in _seen_pns:
            continue
        _seen_pns.add(_pn)
        displaced = ((part.get("_displaced") or {}).get("normalized_thickness_mm")
                     if isinstance(part.get("_displaced"), Mapping) else None) or []
        for entry in displaced:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("applied") and not entry.get("displaced_by"):
                continue
            if "drawing" not in str(entry.get("source") or "").lower():
                continue
            v = _num(entry.get("value"))
            kept = _num(part.get("normalized_thickness_mm"))
            if v and kept and abs(v - kept) > 0.05:
                census.setdefault(round(v, 2), set()).add(_pn)
    return {v: sorted(pns) for v, pns in census.items() if len(pns) >= 3}


def thickness_conflict(part: Mapping[str, Any],
                       boilerplate_mm: Optional[Mapping[float, List[str]]] = None
                       ) -> Optional[Dict[str, Any]]:
    """The gauge disagreement on this part that a person must resolve, or None.

    GENERIC, NOT ACRYLIC-SHAPED. Two credible sources disagreeing about how thick the
    stock is happens on steel and timber exactly as it happened on 10975-02, where the
    SolidWorks model said 3 mm and the drawing's own DXF said 2 mm and the rank-winner
    took it silently — the nest price and the cut time both ride on the answer, so a
    silent winner is a silent re-price. The provenance log (_displaced) keeps every
    refused observation with its source; a refused thickness from a drawing-or-model
    class source that differs from the kept value by more than rounding is a decision,
    not an arbitration the engine is entitled to."""
    if not isinstance(part, Mapping):
        return None
    kept = _num(part.get("normalized_thickness_mm"))
    if not kept or not (0.2 <= kept <= 50):
        return None
    displaced = ((part.get("_displaced") or {}).get("normalized_thickness_mm")
                 if isinstance(part.get("_displaced"), Mapping) else None) or []
    try:
        from source_precedence import source_of
        kept_src = source_of(part, "normalized_thickness_mm") or "the winning reader"
    except Exception:                                            # noqa: BLE001
        kept_src = str(part.get("normalized_thickness_mm_source") or "the winning reader")
    rivals: List[Tuple[float, str]] = []
    for entry in displaced:
        # A reading that LOST is a rival whichever way it lost: refused on rank
        # (applied: False) or overwritten by a later, stronger source (applied: True
        # with displaced_by). Only the entry that still IS the value is not a rival.
        if not isinstance(entry, Mapping):
            continue
        if entry.get("applied") and not entry.get("displaced_by"):
            continue
        v = _num(entry.get("value"))
        src = str(entry.get("source") or "")
        if not v or not (0.2 <= v <= 50) or abs(v - kept) <= 0.05:
            continue
        if not any(w in src.lower() for w in _THICKNESS_SOURCE_WORDS):
            continue
        # A drawing-read value refused across the job is raised ONCE by the caller as a
        # grouped decision naming every affected part — not once per part here. Skipping
        # it is deferral to that group, never dismissal.
        if boilerplate_mm and "drawing" in src.lower() and any(
                abs(v - b) <= 0.05 for b in boilerplate_mm):
            continue
        rivals.append((v, src))
    if not rivals:
        return None
    others = "; ".join(f"{v:g} mm from {s}" for v, s in
                       sorted(set(rivals), key=lambda t: t[0]))
    return {
        "part": str(part.get("part_number") or ""), "kind": "manufacturing_decision",
        "issue": f"Gauge of {part.get('part_number')}: {kept:g} mm was kept "
                 f"({kept_src}) against {others}",
        "assumption": f"nested and cut at {kept:g} mm — the sheet price and the cut "
                      f"time both ride on the gauge",
        "action": "confirm the gauge against the drawing revision; two readers measured "
                  "different stock and neither outranks a person",
        "owner": "estimator", "gbp_at_stake": None,
    }


def _same_value_spelled_twice(a: str, b: str) -> bool:
    """MILD_STEEL and MILD STEEL are one value. A 'disagreement' between two spellings of
    the same token is extraction housekeeping, not a manufacturing question, and it must
    never reach an estimator as something to resolve."""
    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", str(t).replace("_", " ").replace("-", " ")).strip().upper()
    return norm(a) == norm(b) and bool(norm(a))


def _estimator_flags(flags: Any) -> List[str]:
    """The review flags a person can act on — plain sentences only.

    The record used to carry str(flag) for everything, which put raw Python dicts
    ({'severity': 'warning', 'field': 'thickness', ...}) into the report's BOM notes, and
    asked the estimator to choose between 'MILD STEEL' and 'MILD_STEEL' as if the underscore
    were a manufacturing disagreement. Dict flags are the extractor talking to itself — they
    stay in the JSON for diagnosis and off every estimator surface. A kept/not-applied
    sentence survives only when the two values actually differ."""
    out: List[str] = []
    for f in flags or []:
        if not f or isinstance(f, Mapping):
            continue
        t = str(f).strip()
        if not t or (t.startswith("{") and t.endswith("}")):
            continue
        m = re.search(r"'([^']*)' from \S+ (?:was |NOT )", t)
        pair = re.findall(r"'([^']*)'", t)
        if m and len(pair) >= 2 and _same_value_spelled_twice(pair[0], pair[1]):
            continue
        out.append(t)
    return out


def _line_kind(part: Mapping[str, Any], node: Optional[Mapping[str, Any]]) -> str:
    """leaf / assembly / bought_in / commercial / service — the canonical node's kind with
    the two kinds the graph does not distinguish named on top of it."""
    pn = str(part.get("part_number") or "").strip().upper()
    method = str((part.get("material_estimate") or {}).get("cost_method")
                 or part.get("cost_source") or part.get("source") or "").lower()
    # PLATING BEFORE COMMERCIAL. The plating stub is minted down the same placeholder path
    # as PACKAGING and DELIVERY, so on a live run it arrives wearing _commercial_placeholder.
    # With the commercial test first, 7332-01-101-PLATE classified as a commercial line —
    # which filed £15.83 of subcontract plate under "Packaging / delivery" in the material
    # breakdown AND silenced the plate-membership decision (the plating field is only built
    # from a service line). A -PLATE line is a service whatever path minted it.
    if part.get("_plating_placeholder") or "plating" in method or pn.endswith("-PLATE"):
        return "service"
    if part.get("_commercial_placeholder") or str(part.get("source") or "") == \
            "commercial_placeholder" or pn in ("PACKAGING", "DELIVERY"):
        return "commercial"
    if isinstance(node, Mapping) and node.get("kind"):
        return str(node["kind"])
    if str(part.get("canonical_kind") or ""):
        return str(part["canonical_kind"])
    roles = [str(r).lower() for r in (part.get("page_roles") or [])]
    if "bought_in" in roles or str(part.get("normalized_material") or "").upper() == "BOUGHT_IN":
        return "bought_in"
    return "leaf"


def _material_label(part: Mapping[str, Any], kind: str) -> str:
    """What the Material column should say. A commercial line and a subcontract service are
    not made of anything; the stub that minted them carries MILD STEEL because every stub
    does, and printing that put 'MILD STEEL' beside PACKAGING on three tabs."""
    if kind == "commercial":
        return "— (commercial line)"
    if kind == "service":
        return "— (subcontract service)"
    mat = str(part.get("normalized_material") or part.get("material") or "").strip()
    if kind == "bought_in":
        return mat if mat and mat.upper() != "BOUGHT_IN" else "— (bought-in)"
    return mat or "Unknown"


def _price_origin(part: Mapping[str, Any], kind: str, block: Optional[str],
                  charged_unit: Optional[float], engine_unit: float,
                  sheet_row: Any, cross_ref: bool,
                  row_text: str = "") -> Dict[str, Any]:
    """{class, firmness, owner, label} — where the figure came from and how firm it is.

    ONE CLASSIFIER. The covering e-mail tested the words 'indicative' and 'market' on the
    same string and treated a hit as an AI lookup; the Explanation tab tested only the
    supplier cell; the AI Price Provenance tab printed the raw method token or 'not named'.
    Three tests, three answers about one line."""
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), Mapping) else {}
    ps = me.get("price_source") if isinstance(me.get("price_source"), Mapping) else {}
    method = str(me.get("cost_method") or part.get("cost_source") or part.get("source") or "")
    supplier = str(part.get("supplier") or "").strip()
    # THE ROW'S OWN TAG IS A WITNESS TOO. The 08:08 tape line printed "[AI ESTIMATE -
    # INDICATIVE, NOT A QUOTE]" on the sheet while the part record behind it had lost its
    # price_source through the identity fold — so one surface called it a market figure
    # and the record called it "source unrecorded", and the headline tally stopped asking
    # anyone to replace it. What wb_populate stamped onto the row travels with the row.
    tokens = " ".join(str(x) for x in (
        method, ps.get("source_name"), ps.get("source_type"), ps.get("supplier_source"),
        supplier, row_text)).lower()
    money = charged_unit if charged_unit is not None else engine_unit
    _row_says_ai = "ai estimate" in tokens and "indicative" in tokens

    if cross_ref and block in _FABRICATED_BLOCKS:
        # A BOM row whose money is on a fabricated block. Nil HERE by design; the money is
        # reported on the fabricated line for the same part.
        pass
    if block in _FABRICATED_BLOCKS and money:
        label = f"costed by nest on the {_FABRICATED_BLOCKS[block]} block"
        if block in ("tube", "wire"):
            label = f"costed by length on the {_FABRICATED_BLOCKS[block]} block"
        if sheet_row:
            label += f" — Estimate!{int(sheet_row)}"
        return {"class": f"nest_{block}", "firmness": FIRM, "owner": None, "label": label}
    if kind == "assembly" and not money:
        return {"class": "nil_by_design", "firmness": NIL, "owner": "nobody",
                "label": "nothing to charge here — an assembly's material is its members'"}
    if kind == "commercial" and not money:
        return {"class": "unpriced_commercial", "firmness": UNPRICED, "owner": "estimator",
                "label": "NOT PRICED — held at £0 until the estimators' own figure lands; "
                         "enter the per-unit amount"}
    if any(t in tokens for t in _MARKET_AI_TOKENS) or (money and _row_says_ai):
        who = supplier or ps.get("supplier_source") or "AI/market lookup"
        return {"class": "market_ai", "firmness": INDICATIVE_MARKET, "owner": "estimator",
                "label": f"AI market indication ({who}) — NOT A QUOTE, replace it"}
    for key, label in PRICE_ORIGIN_LABELS.items():
        if key in ("market_ai_indicative", "system_cost_not_found"):
            continue
        if key.replace(" ", "_") in tokens.replace(" ", "_"):
            if not money:
                break
            # A section priced at the config trade rate names the rate it used.
            if key == "section_stock_config_rate":
                if me.get("rate_gbp_per_kg"):
                    label = (f"SDI section-stock trade rate £{_num(me.get('rate_gbp_per_kg')):.2f}/kg "
                             f"from config — verify against the section size")
                return {"class": "section_config_rate", "firmness": FIRM, "owner": None,
                        "label": label}
            return {"class": ("section_flat_rate" if key.startswith("section_stock")
                              else "config_house_rate"),
                    "firmness": INDICATIVE_HOUSE, "owner": "estimator", "label": label}
    if money and any(t in tokens for t in _CATALOGUE_TOKENS):
        who = supplier or str(ps.get("supplier_source") or ps.get("source_name") or "catalogue")
        return {"class": "catalogue", "firmness": FIRM, "owner": None,
                "label": f"catalogue — {who}"}
    if money and supplier:
        return {"class": "catalogue", "firmness": FIRM, "owner": None,
                "label": f"catalogue — {supplier}"}
    if money:
        return {"class": "unrecorded", "firmness": FIRM, "owner": None,
                "label": "priced — the line records no source; see AI Provenance"}
    # No money and not nil by design: somebody owes a figure. Ask the shared reason
    # vocabulary who, rather than inventing a fourth opinion here.
    owner, why = "estimator", "no catalogue row, price file or quote holds a rate for this"
    try:
        from estimator_inputs import unpriced_reason_for_row
        reason = unpriced_reason_for_row(part) or {}
        owner = str(reason.get("owner") or owner)
        why = str(reason.get("why") or reason.get("detail") or why)
    except Exception:                                                # noqa: BLE001
        pass
    if owner == "nobody":
        return {"class": "nil_by_design", "firmness": NIL, "owner": "nobody", "label": why}
    return {"class": "unpriced", "firmness": UNPRICED, "owner": owner,
            "label": f"NOT PRICED — {why}"}


def _operations_from_decisions(source: Any, part_number: Any) -> List[str]:
    """The operations that put this part on a priced row, named by the compiler's decisions.

    NOT the department inverted. A Tubebend row inverts to tube_bending, tubebend, folding
    AND fold because the tube remap sends folding to that department — so the leg's
    provenance listed the very operation the route had ruled out. The decision on the row
    says 'tubebend' and nothing else."""
    known = _decisions_by_id(source)
    out: List[str] = []
    for did in decision_ids_for_part(source, part_number):
        d = known.get(did) or {}
        op = str(d.get("operation") or "").strip()
        if op and str(d.get("status") or "required") == "required" and op not in out:
            out.append(op)
    if out:
        return out
    # No decision ids on the rows (a pre-cutover run): the first alias of each department,
    # never all of them.
    for r in priced_rows_for_part(source, part_number):
        ops = _row_engine_ops(r)
        if ops and ops[0] not in out:
            out.append(ops[0])
    return out


def removed_identities(source: Any) -> Set[str]:
    """Every identity the identity gates removed from the costed population.

    The fold and quarantine ledgers are the evidence that a line was deliberately taken
    off the job. Any panel that lists parts — review flags, confidence lists, ask-the-
    drawing-office rows — must exclude these, or a ghost's NAME outlives its line and the
    reader is asked about a part that nothing costs and nothing holds."""
    out: Set[str] = set()
    if not isinstance(source, dict):
        return out
    for key in ("folded_bom_row_fragments", "quarantined_interleave_artefacts"):
        for e in (source.get(key) or []):
            if isinstance(e, dict):
                pn = str(e.get("part_number") or "").strip().upper()
                if pn:
                    out.add(pn)
    return out


def costed_job(source: Any) -> Dict[str, Any]:
    """THE record. Pure: same summary in, same record out. Cheap enough to call from every
    writer; persisted by main.py after the read-back for the audit trail only."""
    if not isinstance(source, dict):
        return {"schema": COSTED_JOB_SCHEMA, "lines": [], "gaps": {}, "release": {}}
    nodes = _canonical_nodes(source)
    fe = _final_estimate_of(source)
    totals = job_totals(source)
    mat_rows = [r for r in (fe.get("material_rows") or []) if isinstance(r, dict)]
    calculated = bool(mat_rows) and totals.get("source") == "excel_calculated"

    # Material rows by canonical identity: the fabricated block row carries the money, the
    # BOM row for the same part is its cross-reference.
    money_rows: Dict[str, Dict[str, Any]] = {}
    bom_rows: Dict[str, Dict[str, Any]] = {}
    for r in mat_rows:
        key = canonical_identity(source, _material_row_key(r))
        if not key:
            continue
        if str(r.get("block") or "bom") == "bom":
            bom_rows.setdefault(key, r)
        else:
            money_rows.setdefault(key, r)

    es = source.get("estimate_summary") if isinstance(source.get("estimate_summary"), dict) else {}
    order_qty = None
    try:
        order_qty = int(((es or {}).get("estimate_workbook_inputs") or {}).get("assumed_job_quantity")
                        or source.get("assumed_job_quantity") or 0) or None
    except (TypeError, ValueError):
        order_qty = None

    lines: List[Dict[str, Any]] = []
    for part in job_parts(source):
        pn = str(part.get("part_number") or "").strip()
        if not pn:
            continue
        identity = canonical_identity(source, pn)
        node = nodes.get(identity)
        kind = _line_kind(part, node)
        qty = canonical_quantity(source, pn)
        if qty is None:
            qty = _num(part.get("quantity")) or 1.0
        engine_unit, engine_ext = part_material_cost(part)

        row = money_rows.get(identity)
        bom = bom_rows.get(identity)
        block = str(row.get("block")) if row else ("bom" if bom else None)
        cross_ref = bool(bom) and "costed in" in str(bom.get("description") or "").lower()
        charged_unit = charged_ext = None
        sheet_row = None
        if calculated:
            if row is not None:
                charged_ext = _num(row.get("total_value_gbp"))
                q = _num(row.get("qty_per_unit")) or qty or 1.0
                charged_unit = round(charged_ext / q, 4) if q else charged_ext
                sheet_row = row.get("workbook_row") or row.get("row")
            elif bom is not None:
                charged_ext = _num(bom.get("total_value_gbp"))
                charged_unit = _num(bom.get("unit_price_gbp"))
                sheet_row = bom.get("workbook_row") or bom.get("row")
        _row_text = " ".join(str((r or {}).get("description") or "")
                             for r in (row, bom) if isinstance(r, dict))
        origin = _price_origin(part, kind, block, charged_unit, engine_unit, sheet_row,
                               cross_ref, row_text=_row_text)

        me = part.get("material_estimate") if isinstance(part.get("material_estimate"), Mapping) else {}
        se = me.get("stock_estimate") if isinstance(me.get("stock_estimate"), Mapping) else {}
        length = None
        if se.get("section_length_mm") or se.get("wire_length_mm"):
            length = {"mm": _num(se.get("section_length_mm") or se.get("wire_length_mm")),
                      "source": str(se.get("section_length_source") or ""),
                      "reader": str(se.get("section_length_reader") or ""),
                      "indicative": bool(se.get("section_length_indicative"))}
        profile = None
        if isinstance(part.get("section_stock"), Mapping):
            ss = part["section_stock"]
            profile = {k: ss.get(k) for k in ("a", "b", "t", "profile_form") if ss.get(k) is not None}

        lines.append({
            "part_number": pn,
            "identity": identity,
            "description": str(part.get("description") or ""),
            "kind": kind,
            "qty_per_unit": qty,
            "material_label": _material_label(part, kind),
            "thickness_mm": part.get("normalized_thickness_mm"),
            "block": block,
            "sheet_row": sheet_row,
            "cross_reference": cross_ref,
            "charged_unit_gbp": charged_unit,
            "charged_ext_gbp": charged_ext,
            "engine_unit_gbp": round(engine_unit, 4),
            "engine_ext_gbp": round(engine_ext, 4),
            "money_basis": "excel_calculated" if charged_ext is not None else "engine_pre_excel",
            "price_origin": origin,
            "operations": _operations_from_decisions(source, pn),
            "length": length,
            "section_profile": profile,
            "review_flags": _estimator_flags(part.get("review_flags")),
            "plating_members": list(part.get("_plating_members_costed") or []),
            "plating_excluded": list(part.get("_plating_members_deferred") or []),
        })

    # ── the gap lists, once ─────────────────────────────────────────────────────
    def _money_of(line: Dict[str, Any]) -> float:
        v = line.get("charged_ext_gbp")
        return _num(v) if v is not None else _num(line.get("engine_ext_gbp"))

    unpriced = [l for l in lines if l["price_origin"]["firmness"] == UNPRICED]
    house = [l for l in lines if l["price_origin"]["firmness"] == INDICATIVE_HOUSE]
    market = [l for l in lines if l["price_origin"]["firmness"] == INDICATIVE_MARKET]
    gaps = {
        "unpriced": [l["part_number"] for l in unpriced],
        "unpriced_owners": {l["part_number"]: l["price_origin"]["owner"] for l in unpriced},
        "indicative_house": [l["part_number"] for l in house],
        "indicative_house_gbp": round(sum(_money_of(l) for l in house), 2),
        "indicative_market": [l["part_number"] for l in market],
        "indicative_market_gbp": round(sum(_money_of(l) for l in market), 2),
    }

    # ── plating, as a field and not a truncated description ─────────────────────
    plating: Dict[str, Any] = {"charged": False}
    for l in lines:
        if l["kind"] == "service" and _money_of(l) > 0:
            parent = None
            node = nodes.get(l["identity"]) or {}
            parents = node.get("parents") if isinstance(node, Mapping) else None
            if isinstance(parents, (list, tuple)) and parents:
                parent = str(parents[0])
            elif isinstance(parents, Mapping) and parents:
                parent = str(next(iter(parents)))
            if not parent and l["part_number"].upper().endswith("-PLATE"):
                parent = l["part_number"][:-6]
            plating = {"charged": True, "line": l["part_number"], "parent": parent,
                       "members": l["plating_members"], "excluded": l["plating_excluded"],
                       "ext_gbp": _money_of(l), "label": l["price_origin"]["label"]}
            break

    # ── what a person has to decide, worst first ────────────────────────────────
    decisions: List[Dict[str, Any]] = []
    for l in unpriced:
        decisions.append({
            "part": l["part_number"], "kind": "missing_price",
            "issue": f"{l['part_number']} carries no price",
            "assumption": "held at £0 — the unit cost is understated by whatever it is worth",
            "action": ("enter the per-unit figure" if l["kind"] == "commercial"
                       else "supply a rate or a supplier quote"),
            "owner": l["price_origin"]["owner"], "gbp_at_stake": None})
    if plating.get("charged"):
        decisions.append({
            "part": plating.get("parent") or plating.get("line"), "kind": "manufacturing_decision",
            "issue": f"Which members of {plating.get('parent') or 'the weldment'} are plated after welding",
            "assumption": (f"mass priced on {', '.join(plating.get('members') or []) or 'no member'}"
                           + (f"; excluded because their own detail states another finish: "
                              f"{', '.join(plating.get('excluded'))}" if plating.get("excluded") else "")),
            "action": "confirm the plated member list and the process against the plater's quote",
            "owner": "estimator", "gbp_at_stake": plating.get("ext_gbp")})
    for l in lines:
        ln = l.get("length") or {}
        if ln and ln.get("reader") and ln.get("reader") not in ("none",):
            transcribed = ln.get("reader") in ("llm_full_extract", "inference") or ln.get("indicative")
            if transcribed:
                decisions.append({
                    "part": l["part_number"], "kind": "manufacturing_decision",
                    "issue": f"Cut length of {l['part_number']}: {ln.get('mm'):,.0f} mm",
                    "assumption": (f"{'taken as the largest dimension on the part' if ln.get('indicative') else 'transcribed by ' + str(ln.get('reader'))}"
                                   f" — priced per metre, so the length is the money"),
                    "action": "confirm the developed length against the GA / model",
                    "owner": "estimator", "gbp_at_stake": _money_of(l)})
    # ── the disagreements a person owns: gauge, and a BOM that states one line twice ──
    _by_pn = {str(l.get("part_number") or "").upper(): l for l in lines}
    _boiler = boilerplate_thickness_values(source)
    # ONE decision per repeated value, naming every part it touched — never "no action".
    # The threshold cannot tell a title-block note from three genuine detail drawings
    # that state the same gauge, so a person confirms it once, not once per part.
    for _bv in sorted(_boiler):
        _bparts = _boiler[_bv]
        decisions.append({
            "part": ", ".join(_bparts), "kind": "manufacturing_decision",
            "issue": (f"{', '.join(_bparts)} each show {_bv:g} mm from the drawing "
                      f"against their own stronger gauges — one document figure "
                      f"repeated across {len(_bparts)} parts, or {len(_bparts)} real "
                      f"specs"),
            "assumption": (f"each part priced on its own strongest source, not the "
                           f"repeated {_bv:g} mm"),
            "action": (f"confirm once whether {_bv:g} mm is a document-level note or "
                       f"the intended gauge for these parts — the nest and cut time "
                       f"ride on it"),
            "owner": "estimator", "gbp_at_stake": None,
        })
    # A MIXED COATING SCOPE BLOCKS RELEASE. When the route records powder required on an
    # assembly AND on some (not all) of its members, both charges stand — and the ruling
    # is a person's, so it must sit in the decision tally that keeps the quote a draft,
    # never as an easily-missed warning in a ledger nobody reads before issuing.
    _shadow_issues = (((source.get("estimate_summary") or {})
                       .get("canonical_route_shadow") or {}).get("issues") or [])
    for _iss in _shadow_issues:
        if not isinstance(_iss, Mapping) \
                or str(_iss.get("code")) != "powder_scope_mixed_members":
            continue
        decisions.append({
            "part": str(_iss.get("part_number") or ""),
            "kind": "manufacturing_decision",
            "issue": str(_iss.get("message") or "the powder scope is mixed between "
                         "the assembly and its members"),
            "assumption": "both the assembly coat and the coated members' lines stand "
                          "until ruled",
            "action": "rule whether the assembly coat covers the coated members (drop "
                      "their lines) or is a separate finishing stage (keep both)",
            "owner": "estimator", "gbp_at_stake": None,
        })
    for part in job_parts(source):
        if not isinstance(part, Mapping):
            continue
        _tc = thickness_conflict(part, boilerplate_mm=_boiler)
        if _tc:
            _line = _by_pn.get(str(part.get("part_number") or "").upper())
            if _line is not None:
                _tc["gbp_at_stake"] = _money_of(_line) or None
            decisions.append(_tc)
        for _bc in (part.get("_bom_numeric_conflicts") or []):
            if not isinstance(_bc, Mapping):
                continue
            decisions.append({
                "part": str(part.get("part_number") or ""),
                "kind": "manufacturing_decision",
                "issue": (f"The BOM states this line twice with different figures: "
                          f"{_bc.get('kept')!r} and {_bc.get('other')!r}"),
                "assumption": f"priced on {_bc.get('kept')!r} — the other reading is "
                              f"kept beside it, not chosen",
                "action": "pick which figure is right; the drawing contradicts itself",
                "owner": "estimator", "gbp_at_stake": None,
            })
    for l in house:
        decisions.append({
            "part": l["part_number"], "kind": "indicative_rate",
            "issue": f"{l['part_number']} is priced on an SDI house rate marked INDICATIVE",
            "assumption": l["price_origin"]["label"],
            "action": "verify against a supplier / plater quote, or accept it deliberately",
            "owner": "estimator", "gbp_at_stake": _money_of(l)})
    for l in market:
        decisions.append({
            "part": l["part_number"], "kind": "market_figure",
            "issue": f"{l['part_number']} rests on an AI market indication",
            "assumption": l["price_origin"]["label"],
            "action": "replace it with a catalogue or supplier price — it moves between runs",
            "owner": "estimator", "gbp_at_stake": _money_of(l)})

    # ── release status ──────────────────────────────────────────────────────────
    reasons: List[str] = []
    if unpriced:
        reasons.append(f"{len(unpriced)} line(s) carry no price: {', '.join(gaps['unpriced'])}")
    if market:
        reasons.append(f"{len(market)} line(s) rest on an AI market indication")
    inv = source.get("invariants") if isinstance(source.get("invariants"), dict) else None
    if inv is not None:
        blocking = [v for v in (inv.get("violations") or [])
                    if isinstance(v, dict) and v.get("severity") == "blocking"]
        if blocking:
            reasons.append(f"{len(blocking)} consistency check(s) blocking")
    else:
        reasons.append("the consistency checks have not run")
    if not calculated:
        reasons.append("the calculated sheet was not read back")
    manufacturing = [d for d in decisions if d["kind"] == "manufacturing_decision"]
    if manufacturing:
        reasons.append(f"{len(manufacturing)} manufacturing decision(s) open")
    blocking_n = (sum(1 for v in (inv.get("violations") or [])
                      if isinstance(v, dict) and v.get("severity") == "blocking")
                  if inv is not None else 0)
    status = ("provisional" if (unpriced or market or not calculated or blocking_n or inv is None)
              else ("reviewable" if (house or manufacturing) else "firm"))
    # DRAFT is narrower than PROVISIONAL. A quote is a draft while a person still owes it
    # something — a price, a replacement for a market guess, a manufacturing decision, or a
    # blocking check to clear. "The checks have not run yet" and "the sheet was not read
    # back" keep the estimate provisional but say nothing about the quote's scope; the
    # LLM-only path already marks those runs in its own words.
    draft = bool(unpriced or market or blocking_n or manufacturing)
    outstanding = len(unpriced) + len(market) + len(manufacturing) + blocking_n

    return {
        "schema": COSTED_JOB_SCHEMA,
        "run": {
            "order_qty": order_qty,
            "unit_gbp": totals.get("unit_gbp"),
            "material_gbp": totals.get("material_gbp"),
            "labour_gbp": totals.get("labour_gbp"),
            "totals_source": totals.get("source"),
            "code_version": str(source.get("engine_version") or source.get("commit")
                                or (source.get("run") or {}).get("commit") or ""),
        },
        "lines": lines,
        "gaps": gaps,
        "plating": plating,
        "finishes_charged": costed_finish_label(source, default=""),
        "decisions_required": decisions,
        "release": {"status": status, "reasons": reasons, "draft": draft,
                    "outstanding": outstanding,
                    "prices_outstanding": len(unpriced) + len(market),
                    "decisions_open": len(manufacturing)},
    }


def costed_line(source: Any, part_number: Any) -> Optional[Dict[str, Any]]:
    """One line of the record, by part number or any alias of it."""
    pn = canonical_identity(source, part_number)
    for line in costed_job(source).get("lines") or []:
        if line.get("identity") == pn or str(line.get("part_number") or "").upper() == \
                str(part_number or "").strip().upper():
            return line
    return None


def outstanding_summary(source: Any) -> Dict[str, Any]:
    """THE ONE TALLY of what still needs a person, printed identically on every surface.

    On the 12:10 run of 7332-01 the same five open items were counted three different ways:
    the report banner said 3 inputs, its own table listed 5, the explanation said 4 lines +
    1 decision, the quote said 2 prices + 1 decision. Every writer now calls this and prints
    the phrase, so the tallies cannot drift apart again.

    The rule, in Tim's terms: what BLOCKS release (missing prices, market figures to
    replace, manufacturing decisions) is counted apart from what is ADVISORY (house rates
    marked INDICATIVE — configured and reproducible, to verify or deliberately accept).

    Accepts either a run summary or an already-built costed_job record, because the HTML
    regeneration path reads the record straight from the saved JSON."""
    job = source if (isinstance(source, Mapping) and "decisions_required" in source
                     and "release" in source) else costed_job(source)
    ds = [d for d in (job.get("decisions_required") or []) if isinstance(d, Mapping)]

    def _n(kind: str) -> int:
        return sum(1 for d in ds if d.get("kind") == kind)

    prices, market = _n("missing_price"), _n("market_figure")
    mfg, house = _n("manufacturing_decision"), _n("indicative_rate")
    # A kind none of the four buckets recognises must still be SEEN: on the 12:28 run of
    # 7332-01 an "advisory" entry sat in the list, the headline said "7 to settle" and
    # the phrase added to 6, because total counted every row and the phrase counted four
    # kinds. The headline and the phrase are one tally or they are two lies — so every
    # row lands in a named bucket, and an unclassified kind is counted as blocking, not
    # quietly dropped: an open item nobody classified is not thereby advisory.
    other = len(ds) - (prices + market + mfg + house)
    bits: List[str] = []
    if prices:
        bits.append(f"{prices} price{'s' if prices != 1 else ''} missing")
    if market:
        bits.append(f"{market} market figure{'s' if market != 1 else ''} to replace")
    if mfg:
        bits.append(f"{mfg} manufacturing decision{'s' if mfg != 1 else ''}")
    if house:
        bits.append(f"{house} indicative rate{'s' if house != 1 else ''} to verify")
    if other:
        bits.append(f"{other} other open item{'s' if other != 1 else ''}")
    return {
        "prices_missing": prices, "market_figures": market,
        "manufacturing": mfg, "indicative": house, "other": other,
        "blocking": prices + market + mfg + other, "advisory": house,
        "total": len(ds),
        "phrase": " + ".join(bits) if bits else "nothing outstanding",
    }


RESIDUAL_LABEL = "Rounding / unreconciled residual"


def record_lines(source: Any) -> Dict[str, Dict[str, Any]]:
    """{PART NUMBER (upper): line} for one record — the join every writer needs."""
    out: Dict[str, Dict[str, Any]] = {}
    for line in costed_job(source).get("lines") or []:
        for key in (line.get("part_number"), line.get("identity")):
            k = str(key or "").strip().upper()
            if k and k not in out:
                out[k] = line
    return out


def charged_material_rows_present(source: Any) -> bool:
    """True once the read-back has recorded the sheet's material rows — the condition for
    any per-part money to be the CHARGED figure rather than the engine's."""
    fe = _final_estimate_of(source)
    return any(isinstance(r, dict) for r in (fe.get("material_rows") or [])) \
        and job_totals(source).get("source") == "excel_calculated"


def packaging_status(source: Any) -> str:
    """'charged' when a commercial packaging line carries money, 'unpriced' when the line
    exists and is held at £0, 'absent' when the job carries no packaging line at all.

    The quote's 'Boxed for transport' row and its packing bullet promise work the price
    contains. On 7332-01 PACKAGING was on the sheet at £0 by James's decision, and the
    quote promised the box anyway. Only 'unpriced' is that defect; a job with no packaging
    line has not declared packaging as a scope item either way."""
    status = "absent"
    for line in costed_job(source).get("lines") or []:
        if line.get("kind") != "commercial":
            continue
        if "PACK" not in str(line.get("part_number") or "").upper():
            continue
        v = line.get("charged_ext_gbp")
        v = _num(v) if v is not None else _num(line.get("engine_ext_gbp"))
        if v > 0:
            return "charged"
        status = "unpriced"
    return status


def packaging_is_charged(source: Any) -> bool:
    """True when a commercial packaging line carries money on the sheet."""
    return packaging_status(source) == "charged"


def charged_breakdown_by_material(source: Any,
                                  residual_label: str = RESIDUAL_LABEL) -> List[Tuple[str, float]]:
    """The material money by type, from the CHARGED figures, so it adds back to the sheet.

    The residual row that used to be called 'Powder / scrap / other workbook material'
    was the difference between the engine's net-part column and the sheet's nest-based
    total — a basis difference, not a consumable. Built from the charged lines it is a
    few pence of rounding at most, and it is labelled as rounding rather than as a process
    the job does not have."""
    job = costed_job(source)
    totals: Dict[str, float] = {}
    for l in job.get("lines") or []:
        if l.get("cross_reference") and l.get("charged_ext_gbp") in (None, 0, 0.0):
            continue
        v = l.get("charged_ext_gbp")
        v = _num(v) if v is not None else _num(l.get("engine_ext_gbp"))
        if not v:
            continue
        label = l["material_label"]
        if l["kind"] == "commercial":
            label = "Packaging / delivery"
        elif l["kind"] == "service":
            label = "Subcontract plating"
        elif l["kind"] == "bought_in":
            label = "Bought-in"
        totals[label] = totals.get(label, 0.0) + v
    sheet = job.get("run", {}).get("material_gbp")
    if sheet is not None and totals:
        residual = round(float(sheet) - sum(totals.values()), 4)
        if abs(residual) >= 0.005:
            totals[residual_label] = residual
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


__all__ += ["outstanding_summary", "thickness_conflict"]
__all__ += ["costed_job", "costed_line", "record_lines", "charged_breakdown_by_material",
            "charged_material_rows_present", "packaging_is_charged", "packaging_status",
            "RESIDUAL_LABEL",
            "PRICE_ORIGIN_LABELS", "FIRM", "INDICATIVE_HOUSE", "INDICATIVE_MARKET",
            "UNPRICED", "NIL", "COSTED_JOB_SCHEMA"]
