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

from typing import Any, Dict, Iterable, List, Mapping, Optional

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
    ops = [o for o in ops if o.strip().lower() not in inv] or [
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
