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

import os
import re

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

__all__ = [
    "review_signals",
    "charges_behind_flag",
    "document_level_gauges",
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

# ── WHAT A DXF RECORD'S REASON CODE MEANS, IN ONE PLACE (D-408, D-409) ──────────────────
#
# drawing_job_merge writes `dxf` on a matched record, `path` on an unmatched, skipped or
# ambiguous one and `candidates` where several flats were weighed — full Windows paths as
# written on the box — and a reason code either on its own with the evidence under `detail`
# or as "code: evidence" in one string. The report and the covering note each read these
# records; one vocabulary here so they cannot call the same file two different things. An
# unknown code is printed de-underscored rather than dropped, so a reason the merge learns to
# give next month reaches every page unaided.
DXF_REASON_SENTENCES: Dict[str, str] = {
    "drawing_export_not_a_flat": ("a drawing of a part, not a flat pattern — it minted no part "
                                  "and measured nothing"),
    "code_belongs_to_another_assembly_in_this_job_number": (
        "its code belongs to another assembly under this job number — not attached to this one"),
    "no_part_number_in_filename": "no part number in its name — matched to no part",
    "ga_dxf_ignored": "a general-arrangement export — not a flat pattern, not measured",
    "missing_file": "listed for the run but not found on disk — NOT READ",
    "not_dxf": "not a DXF — not read as geometry",
    "suffixed_flat_beside_the_parts_own_flat": (
        "could be a piece or a variant of a part that has a flat of its own — not attached; "
        "say which"),
    "numbered_piece_or_separate_item_unresolved": (
        "could be a numbered piece or a separate item — not attached; say which"),
}


def dxf_record_names(it: Any) -> List[str]:
    """The filename(s) a dxf_augmentation record is about, whichever key the merge wrote —
    basenames only, so a staged Windows path reads as the file the drawing office knows."""
    def _base(v: Any) -> str:
        return re.split(r"[\\/]", str(v or "").strip())[-1]
    if not isinstance(it, dict):
        b = _base(it)
        return [b] if b else []
    for k in ("dxf_name", "name", "file", "dxf", "path"):
        if it.get(k):
            b = _base(it.get(k))
            return [b] if b else []
    out = [_base(c) for c in (it.get("candidates") or [])]
    return [b for b in out if b]


def dxf_record_code_and_evidence(it: Any) -> Tuple[str, str]:
    """(reason code, evidence) off a record. The content reader's evidence ends with its own
    verdict ("— this is a drawing of the part…"), which the sentence already says, so for a
    known code only the measurement before the dash is kept."""
    if not isinstance(it, dict):
        return "", ""
    raw = str(it.get("reason") or "").strip()
    code, _, tail = raw.partition(":")
    code = code.strip()
    evidence = str(it.get("detail") or tail or "").strip()
    if code in DXF_REASON_SENTENCES and " — " in evidence:
        evidence = evidence.split(" — ", 1)[0].strip()
    return code, evidence


def dxf_record_reason(it: Any) -> str:
    """The recorded reason as a sentence, with the evidence in brackets when there is any."""
    code, evidence = dxf_record_code_and_evidence(it)
    if not code:
        return ""
    sentence = DXF_REASON_SENTENCES.get(code, code.replace("_", " "))
    return f"{sentence} ({evidence})" if evidence else sentence


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
    # BY THE REASON THE MERGE RECORDED, NOT BY THE LIST IT LANDED IN (D-409). A drawing export
    # the merge refuses BEFORE minting a part (D-406) lands in unmatched_dxf with its reason,
    # and this called it "a stray or mis-named file in the pack" — the name was fine, the file
    # was a drawing — on the same page that had just said what it was.
    for key in ("skipped", "unmatched_dxf"):
        for u in (dxf.get(key) or []):
            if not isinstance(u, dict) or not u.get("path"):
                continue
            code, evidence = dxf_record_code_and_evidence(u)
            if code == "drawing_export_not_a_flat":
                _add(f"'{_fname(u.get('path'))}' is a drawing export, not a manufacturing "
                     f"flat ({evidence or 'dimensions or a title block in the file'}) — it was "
                     f"staged alongside the real flats and had to be recognised by its content "
                     f"and set aside, never measured as cut path and never a part.")
            elif key == "unmatched_dxf":
                if code == "no_part_number_in_filename":
                    _add(f"'{_fname(u.get('path'))}' carries no part number in its name, so it "
                         f"matched no part in this job — a stray or mis-named file in the pack.")
                else:
                    why = dxf_record_reason(u)
                    _add(f"'{_fname(u.get('path'))}' matched no part in this job — "
                         + (why or "a stray or mis-named file in the pack") + ".")
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


def charged_finish_families(source: Any, part_number: Any,
                            ancestors: Iterable[Any] = ()) -> Set[str]:
    """The finish FAMILIES (finish_rules vocabulary) the sheet charges on this part's own
    rows or on the rows of an assembly it is in.

    One vocabulary and one record. 12173-03-01J and -02J state WET SPRAYED - MATT and the
    sheet charges Wet Spray against exactly those parts (Estimate rows 216, 217), while the
    consistency check said the sheet charged nothing for it: the check asked a word list,
    and section 14 asked the priced rows. This is the priced rows, joined to the part, read
    through the finish families the route's own gates use. Rows naming no part are not
    coverage — a row charged somewhere is not a row charged here (the 11650 per-part
    lesson)."""
    try:
        from finish_rules import _OPERATION_FAMILY
    except Exception:                                                # noqa: BLE001
        return set()
    _siblings: Dict[str, Set[str]] = {}
    for _ops in (_dept_to_engine_ops() or {}).values():
        _low = {str(x).strip().lower() for x in _ops}
        for _o in _low:
            _siblings.setdefault(_o, set()).update(_low)
    fams: Set[str] = set()
    for who in (part_number, *(ancestors or ())):
        for r in priced_rows_for_part(source, who):
            _ops = {str(o).strip().lower() for o in _row_engine_ops(r)}
            for _o in set(_ops):
                _ops |= _siblings.get(_o, set())
            fams |= {_OPERATION_FAMILY[o] for o in _ops if o in _OPERATION_FAMILY}
    return fams


def costable_finish_labels() -> List[str]:
    """The finishes this engine can charge as an operation, in words, from the finish
    families that have a workbook department — computed, so the sentence that names them
    cannot fall behind a department added to the sheet (it said powder and diamond polish
    while Wet Spray had a rate)."""
    try:
        from finish_rules import _OPERATION_FAMILY
    except Exception:                                                # noqa: BLE001
        return []
    _with_dept = {str(o).strip().lower() for ops in (_dept_to_engine_ops() or {}).values()
                  for o in ops}
    _words = {"powder": "powder", "wet_spray": "wet spray (paint, lacquer)",
              "polish": "diamond polish", "anodise": "anodising", "plate": "plating"}
    fams = sorted({fam for op, fam in _OPERATION_FAMILY.items() if op in _with_dept})
    return [_words.get(f, f.replace("_", " ")) for f in fams]


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
        _raw_q = list(merged.get("manufacturing_questions") or [])
        # The estimate wins on everything it actually carries. A key present but empty must
        # not clobber a real reading from the drawing record — that is how a part with a
        # costed thickness and no geometry fields ended up looking like it had neither.
        for key, value in estimate.items():
            if value not in (None, "", [], {}) or key not in merged:
                merged[key] = value
        # ONE PART'S QUESTIONS, FROM BOTH RECORDS (D-433): the estimate's snapshot and the raw
        # record's later ones are joined by issue, never one list replacing the other.
        _qs, _seen_issue = [], set()
        for _q in _raw_q + list(estimate.get("manufacturing_questions") or []):
            if isinstance(_q, Mapping) and str(_q.get("issue") or "") not in _seen_issue:
                _seen_issue.add(str(_q.get("issue") or ""))
                _qs.append(_q)
        if _qs:
            merged["manufacturing_questions"] = _qs
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
    # AND IT NAMES WHICH PLATE, WHERE THE JOB KNOWS. "Plated" is true of zinc and true of a
    # £— decorative brass, and on a quote those are not the same sentence. 7332-01's
    # headline read "Diamond polished" alone while £— of Brass — Harrods 01 sat in the
    # price: the plating paid for and unnamed, which is the exact failure the docstring
    # above was written about, recurring because the recogniser knew one spelling.
    _plate = _subcontract_plate_label(source)
    if _plate and not any(_plate.lower() in l.lower() or l.lower() in _plate.lower()
                          for l in labels):
        labels.append(_plate)
    labels = list(dict.fromkeys(labels))
    if not labels:
        return default
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1].lower()


def _plating_row_is_costed(row: Mapping[str, Any]) -> bool:
    """Is THIS row a subcontract plating line carrying money?

    RECOGNISED BY WHAT IT IS, NOT BY ONE SPELLING OF ONE FIELD. The first version tested
    `"plating" in cost_method`, which was true of every method that existed when it was
    written — and then the plating line learned to be priced from a named spec, from an
    estimator's own figure and from an inherited decision, none of which contain the word.
    7332-01's headline went to a customer reading "Diamond polished" with £— of brass in
    the price.

    The placeholder flag and the -PLATE identity are what make the line a plating line. The
    method is a detail of how it got its number."""
    if not isinstance(row, Mapping):
        return False
    method = str((row.get("material_estimate") or {}).get("cost_method")
                 or row.get("cost_source") or row.get("source") or "").lower()
    _is_plate_line = bool(
        row.get("_plating_placeholder")
        or "plating" in method
        or str(row.get("part_number") or "").strip().upper().endswith("-PLATE"))
    if not _is_plate_line:
        return False
    try:
        return float(row.get("unit_cost_gbp") or 0) > 0
    except (TypeError, ValueError):
        return False


def _subcontract_plate_label(source: Any) -> str:
    """"Brass — Harrods 01" where the job knows which plate, "Plated" where it does not.

    A quote that says "Plated" of a £— decorative brass is not wrong so much as useless:
    it is equally true of £15.83 of trade zinc, and the reader cannot tell which he is
    buying. Where a spec was named — read off the pack, stated by an estimator, or inherited
    from a decision — that name is the finish, and it is the name the plater would use.
    """
    try:
        rows = job_parts(source) or []
    except Exception:                                                # noqa: BLE001
        rows = []
    _fallback = ""
    for row in rows:
        if not _plating_row_is_costed(row):
            continue
        _fallback = "Plated"
        # The spec, as the plating pass wrote it onto the line's own description:
        # "<part> plating — Brass — Harrods 01, INHERITED from …"
        _desc = str(row.get("description") or "")
        # The spec's own name CONTAINS an em-dash — "Brass — Harrods 01" — so the capture
        # cannot stop at one. It stops at the comma that separates the spec from how the
        # figure was arrived at ("…, INHERITED from", "…, Howard Thurley's stated price").
        _m = re.search(r"plating\s*—\s*(.+?)\s*(?:,|$)", _desc)
        if _m:
            _spec = _m.group(1).strip()
            if _spec and not _spec.upper().startswith(("SPEC NOT", "INDICATIVE")):
                return _spec
    return _fallback


def _subcontract_plating_is_costed(source: Any) -> bool:
    """True when a subcontract plating line carries money on this job."""
    try:
        rows = job_parts(source) or []
    except Exception:                                                # noqa: BLE001
        rows = []
    return any(_plating_row_is_costed(r) for r in rows)


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
        # THE LIST job_parts AND EVERY DELIVERABLE READ. wb_populate builds these as SHALLOW
        # copies before this pass runs, and the pass rebinds `risk_flags`, so the copies kept
        # the old list: on 12173-02 a ticket strip whose weld the route had ruled out was
        # still counted under "Weld detected" by the report reading job_parts. Idempotent.
        if isinstance(est, dict) and isinstance(est.get("canonical_part_estimates"), list):
            buckets.append(est["canonical_part_estimates"])
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
                    _zc = {
                        "flag": "ZERO_COST_STEEL",
                        "reason": ("raised before costing, when this part had no cost; the "
                                   "finished workbook prices its material and charges it on "
                                   "a labour row, so it is no longer a review item"),
                    }
                    _sup = p.setdefault("superseded_risk_flags", [])
                    if _zc not in _sup:
                        _sup.append(_zc)
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
                # A shallow copy can share this list with its original; never twice.
                _sup = p.setdefault("superseded_risk_flags", [])
                for _g in gone:
                    if _g not in _sup:
                        _sup.append(_g)
                out["superseded"] += len(gone)
            out["kept"] += len(kept)
    return out


def _float_or_none(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def review_signals(parts: Iterable[Any]) -> Dict[str, Any]:
    """Risk flags and quantitative gates rolled up per part, so a person can review early.

    MOVED HERE FROM THE ESTIMATOR, UNCHANGED, SO THE REPORT CAN BUILD IT FROM THE RECORD IT
    PRINTS. The estimator calls it once, before the workbook exists, on its own part list;
    that frozen copy is saved and the parity reports read it. On 12173-02 section 3 listed 29
    parts under "Welding on the drawing" from that frozen copy while its own tally counted
    27 from job_parts — three records describing one set of flags. Once the route is priced
    the report calls this on job_parts (reconciled), and the rows, the tally and section 5's
    group are one list (estimator._build_estimate_review_signals is this function).
    """
    conf_thr = float(os.getenv("ESTIMATE_PART_CONFIDENCE_REVIEW_BELOW", "0.65") or "0.65")
    geom_thr = float(os.getenv("ESTIMATE_GEOMETRY_REVIEW_BELOW", "0.70") or "0.70")
    parts_out: List[Dict[str, Any]] = []
    for p in parts or []:
        if not isinstance(p, Mapping):
            continue
        reasons: List[Dict[str, Any]] = []
        for rf in p.get("risk_flags") or []:
            reasons.append({"code": "risk_flag", "detail": str(rf)})
        assump = (p.get("cost_breakdown") or {}).get("assumptions") or {}
        pc_val = _float_or_none(assump.get("part_confidence_overall"))
        if pc_val is not None and pc_val < conf_thr:
            reasons.append({"code": "low_part_confidence", "detail": pc_val})
        proc = p.get("process_estimate") or {}
        gr = _float_or_none(proc.get("geometry_reliability"))
        times_min = proc.get("times_min") or {}
        if "powder_coating" in times_min and gr is not None and gr < geom_thr:
            reasons.append({"code": "low_geometry_reliability_with_powder", "detail": gr})
        if reasons:
            # Carry a FALLBACK IDENTITY, not just the part_number. A part whose number was
            # rejected as boilerplate (set to None upstream) still has a description and a
            # source file — without them the review report can only show "?" in its Item
            # column, a flag the estimator cannot tie to anything.
            parts_out.append({"part_number": p.get("part_number"),
                              "description": p.get("description"),
                              "source_file": p.get("dxf_source_file") or p.get("source_file"),
                              "reasons": reasons})
    rec = "manual_review_recommended" if parts_out else "no_automatic_flags"
    return {
        "schema": "estimate_review_signals.v1",
        "thresholds": {"part_confidence_below": conf_thr, "geometry_with_powder_below": geom_thr},
        "parts_flagged": parts_out,
        "flagged_part_count": len(parts_out),
        "recommendation": rec,
    }


def charges_behind_flag(source: Any, part_number: Any, flag: Any) -> List[Dict[str, Any]]:
    """The sheet rows a risk flag's operation became on this part — the join reconcile uses
    to DEMOTE a flag, used here to REPORT a kept one.

    12173-02 section 3 opened "None of the following change the arithmetic" over 29 parts
    listed "Welding on the drawing", on a job charging £434.68 on 16 Weld (CO2) and Dress
    Welds rows decided by "a note on the drawing" and "an SDI override rule". Each row comes
    back with its Estimate row, its operation and who decided it in plain words
    (source_precedence.display_name); a decision counts only where this part is its target
    or a participant (decision_ids_for_part's rule). Money is not split per part: one Weld
    row can cover eight parts. [] when the flag asserts no operation or no row is known.
    """
    needed = {str(n).lower() for n in _OP_ASSERTING_FLAGS.get(str(flag or ""), ())}
    pn = canonical_identity(source, part_number)
    if not needed or not pn:
        return []
    try:
        from source_precedence import display_name as _display_name     # noqa: PLC0415
    except Exception:                                                # noqa: BLE001
        def _display_name(s):                                        # noqa: ANN001
            return str(s or "").replace("_", " ")
    known = _decisions_by_id(source)
    out: List[Dict[str, Any]] = []
    for r in priced_rows_for_part(source, part_number) or []:
        if not isinstance(r, Mapping):
            continue
        ops = {str(o).lower() for o in (r.get("engine_operations") or [])}
        ops.add(str(r.get("wb_operation") or "").lower())
        if not ops & needed:
            continue
        ids = [str(d) for d in (r.get("decision_ids") or []) if d]
        if not ids and r.get("decision_id"):
            ids = [str(r["decision_id"])]
        by: List[str] = []
        for d in ids:
            dec = known.get(d) or {}
            if not dec:
                continue
            members = {canonical_identity(source, x)
                       for x in [dec.get("target_id"), *(dec.get("participants") or [])] if x}
            if pn not in members:
                continue
            name = _display_name(dec.get("source"))
            if name and name not in by:
                by.append(name)
        out.append({"workbook_row": r.get("workbook_row"), "wb_operation": r.get("wb_operation"),
                    "decided_by": by})
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


# Timber and board joinery stock — as distinct from acrylic and the other plastics. ONE
# definition: wb_populate._is_timber names departments from it, and the estimator's material
# gates (no weld, no deburr, no separate drilling on a routed board) read the same answer.
TIMBER_BOARD_TOKENS = ("TIMBER", "WOOD", "PINE", "PLYWOOD", "SOFTWOOD", "HARDWOOD", "OAK",
                       "SPRUCE", "BEECH", "BIRCH", "MDF", "CHIPBOARD", "OSB",
                       # MFC — melamine faced chipboard, the commonest shop-fitting board.
                       "MELAMINE", "MFC")


def is_timber_board(mat: Any) -> bool:
    """Timber or wood-based board (MDF, MFC, chipboard, ply, OSB, solid timber)."""
    m = str(mat or "").upper()
    if "ACRYLIC" in m or "PERSPEX" in m or "PMMA" in m:
        return False          # veneered/laminated acrylic products stay acrylic
    return any(k in m for k in TIMBER_BOARD_TOKENS)


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


def stocked_sheet_sizes(material):
    """The sheet sizes config.STANDARD_SHEET_SIZES_MM stocks this material in, whatever the
    material's spelling — "MILD_STEEL", "Mild Steel", "MILD STEEL" — else the DEFAULT row.

    ONE LOOKUP, BECAUSE FOUR DISAGREED. The table is keyed "MILD STEEL"; the estimator asked
    it with the normalised "MILD_STEEL", missed, and fell back to DEFAULT's 2500 x 1250 alone.
    On 12645 (29 Sep, 21:27 book) that called six 2,600-2,975 mm parts "longer than every
    stocked sheet" and asked Dave whether SDI could cut them in one piece, while the workbook
    rows — which normalised the key — nested them on the stocked 3000 x 1500 (D-343)."""
    try:
        import config as _cfg_st
        table = getattr(_cfg_st, "STANDARD_SHEET_SIZES_MM", {}) or {}
    except Exception:                                                # noqa: BLE001
        table = {}
    raw = str(material or "").strip().upper()
    spaced = re.sub(r"[\s_]+", " ", raw).strip()
    found = (table.get(raw) or table.get(spaced) or table.get(spaced.replace(" ", "_"))
             or table.get("DEFAULT") or [])
    out = []
    for pair in found:
        try:
            float(pair[0]), float(pair[1])
            out.append((pair[0], pair[1]))       # the table's own numbers, as it holds them
        except Exception:                                            # noqa: BLE001
            continue
    return out


def oversize_sheet_for(material, part_length_mm, part_width_mm):
    """((sheet_l, sheet_w), nest) for the smallest LISTED oversize sheet this blank nests on,
    or None. Asked only once no stocked sheet holds it: config.OVERSIZE_SHEET_SIZES_MM, by
    the same nesting rule every sheet is asked by (12645's 3,020 mm covers, D-332)."""
    try:
        import config as _cfg_os
        table = getattr(_cfg_os, "OVERSIZE_SHEET_SIZES_MM", {}) or {}
    except Exception:                                                # noqa: BLE001
        return None
    key = str(material or "").replace("_", " ").strip().upper()
    for sl, sw in sorted(table.get(key) or [], key=lambda s: s[0] * s[1]):
        nest = nest_on_sheet(material, part_length_mm, part_width_mm, sl, sw)
        if nest:
            return (float(sl), float(sw)), nest
    return None


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

# v2 (12173-02, 1 Oct 2026): failing checks, findings that need a ruling and sizes assumed
# from a render are ROWS of decisions_required, no longer counts kept beside them in the
# release block. A v1 record re-read from a saved JSON still carries those counts and
# outstanding_summary adds them to its headline, so an old record's tally still adds up.
COSTED_JOB_SCHEMA = "costed_job.v2"
_COUNTS_BESIDE_ROWS = ("", "costed_job.v1")   # schemas whose release block held the counts

# Firmness — how far the figure can be leaned on. Five words, used everywhere.
FIRM = "firm"                           # the sheet's own arithmetic or a catalogue price
INDICATIVE_HOUSE = "indicative_house"   # a configured SDI rate, reproducible, to VERIFY
INDICATIVE_MARKET = "indicative_market" # an AI / market lookup, moves between runs, to REPLACE
UNPRICED = "unpriced"                   # carries no money and somebody owes a figure
NIL = "nil"                             # correctly nothing — an assembly, a cross-reference

# ── ONE TABLE OF DECISION KINDS: its words, its tag, its place in the list ─────────────
# 12173-02's report filed "1 stated row not carried" — money missing from the unit — under
# the catch-all "Decision" and listed it after every manufacturing question, because the
# report's kind table had never heard of three kinds this record emits. The record now
# sorts itself once, by this table, and every surface that lists it (the report's Decisions
# table, the AI Explanation tab, the banner's named items) reads the same order and words.
# kind -> (tag class, label, rank). Rank 0 is money not in the unit at all.
DECISION_KINDS: Dict[str, Tuple[str, str, int]] = {
    # A run that costed nothing is the first row and the whole headline (D-409).
    "nothing_to_cost": ("t-bad", "Nothing to cost", 0),
    "missing_price": ("t-bad", "Missing price", 0),
    "stated_not_carried": ("t-bad", "Stated, not carried", 0),
    "labour_not_on_sheet": ("t-bad", "Labour not on sheet", 0),
    "consistency_check": ("t-bad", "Failing check", 1),
    "market_figure": ("t-bad", "Market figure", 1),
    "provisional_price": ("t-bad", "Provisional price", 1),
    "quantity_check": ("t-warn", "Quantity check", 2),
    "manufacturing_decision": ("t-warn", "Manufacturing decision", 3),
    "ruling": ("t-warn", "Needs a ruling", 3),
    "size_assumed": ("t-warn", "Size assumed", 3),
    "indicative_rate": ("t-info", "Indicative rate", 4),
}
_UNKNOWN_KIND = ("t-info", "Decision", 9)
# The kinds that keep a quote a draft: something a person owes before it goes out. A
# quantity check and an indicative house rate are asked, not owed; labour the block had no
# room for keeps the estimate provisional (D-340) and is listed, as it was.
_DRAFT_KINDS = frozenset({"nothing_to_cost", "missing_price", "stated_not_carried",
                          "market_figure", "manufacturing_decision", "consistency_check",
                          "provisional_price", "ruling", "size_assumed"})


def decision_kind(kind: Any) -> Tuple[str, str, int]:
    """(tag class, label, rank) for a decision kind; an unknown kind sorts last, named."""
    return DECISION_KINDS.get(str(kind or ""), _UNKNOWN_KIND)

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
    # PLAIN WORDS ON A DOCUMENT FOR A PERSON. "AI market indication ... NOT A QUOTE" is
    # internal system language; what an estimator needs to know is that the figure was
    # researched rather than quoted, and that it must be replaced before it reaches a
    # customer. This label is the SOURCE the note, the report and the Provenance tab all
    # render, so it is the one place the wording has to be right.
    "market_ai_indicative": "researched market price — not a quotation, replace before quoting",
    "system_cost_not_found": "no rate found — estimator to price",
}

_MARKET_AI_TOKENS = ("grok", "llm", "xai", "market")
_CATALOGUE_TOKENS = ("udef", "pma", "erp", "bought_in_price", "price_book", "catalog",
                     "historical", "supplier_quote", "sheet_rate_live")
# The fabricated block KEYS. The names are a fallback only: a block is named by
# wb_populate.block_title, the template's own label ("tube" is its Wire block).
_FABRICATED_BLOCKS = {"steel": "Sheet Steel", "other_sheet": "Other Sheet Material",
                      "tube": "Wire", "wire": "Wire"}


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


def _gauge_is_alone_on_the_line(part: Mapping[str, Any]) -> bool:
    """The part's Dimensions cell would print its gauge and nothing else: no cut length, no
    section, no blank of its own (job_report_html._line_dimensions' last branch)."""
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), Mapping) else {}
    se = me.get("stock_estimate") if isinstance(me.get("stock_estimate"), Mapping) else {}
    if se.get("section_length_mm") or se.get("wire_length_mm"):
        return False
    if (me.get("blank_length_mm") or part.get("blank_length_mm")) and \
            (me.get("blank_width_mm") or part.get("blank_width_mm")):
        return False
    return True


def document_level_gauges(source: Any) -> Dict[float, Dict[str, List[str]]]:
    """The census above, and where the same figure STAYED IN FORCE.

    12173-02: the pack's 1.0 mm (a tolerance band and a spec legend on every sheet) was
    refused on nine parts and grouped as one decision — but on the two meshes it WON, because
    the model's 6 mm was refused, and the Dimensions cell printed a bare "1.0 mm" that nothing
    tied to the document figure. boilerplate_thickness_values names only the parts that
    refused it; this adds `kept_on`: parts whose kept gauge is that figure, held only by
    drawing-class readers, and printed alone on their line. Its return shape is left alone
    because thickness_conflict and the grouped decision consume it.
    """
    refused = boilerplate_thickness_values(source)
    out: Dict[float, Dict[str, List[str]]] = {
        v: {"refused_on": list(pns), "kept_on": []} for v, pns in refused.items()}
    if not out or not isinstance(source, dict):
        return out
    try:
        from source_precedence import source_of, support_for          # noqa: PLC0415
    except Exception:                                                # noqa: BLE001
        return out
    seen: Set[str] = set()
    for p in job_parts(source):
        if not isinstance(p, Mapping):
            continue
        pn = str(p.get("part_number") or "").strip()
        k = _num(p.get("normalized_thickness_mm"))
        if not pn or pn.upper() in seen or not k:
            continue
        seen.add(pn.upper())
        v = next((v for v in out if abs(v - k) <= 0.05), None)
        if v is None or pn in out[v]["refused_on"] or not _gauge_is_alone_on_the_line(p):
            continue
        try:
            sup = set(support_for(dict(p), "normalized_thickness_mm", k) or []) \
                or {source_of(dict(p), "normalized_thickness_mm")}
        except Exception:                                            # noqa: BLE001
            sup = set()
        sup = {str(s) for s in sup if str(s or "").strip()}
        if sup and all("drawing" in s.lower() for s in sup):
            out[v]["kept_on"].append(pn)
    return out


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
    # A PRODUCTION RULE IS NOT TWO READERS DISAGREEING. 12527-22-01M is drawn 0.9 mm and
    # production buys 1.0 in lieu; the sheet costs 1.0 and says so ("drawn at 0.9 mm, COSTED
    # AT 1 mm", with how to stand the rule down). This decision then read the drawn figure
    # off the record and told the estimator the rail was "nested and cut at 0.9 mm" against
    # a 1 mm "rival" — the two halves of the rule, presented as a contradiction. Both gauges
    # the rule names are explained by it; the gauge in force is the one it costs at. Any
    # third reading is still a real disagreement and is still raised.
    _ps = part.get("production_substitution")
    if isinstance(_ps, Mapping):
        _costed = _num(_ps.get("costed_thickness_mm"))
        _explained = [g for g in (_num(_ps.get("drawn_thickness_mm")), _costed) if g]
        rivals = [(v, s) for v, s in rivals
                  if not any(abs(v - g) <= 0.05 for g in _explained)]
        if _costed:
            kept, kept_src = _costed, "production_substitution"
        rivals = [(v, s) for v, s in rivals if abs(v - kept) > 0.05]
    if not rivals:
        return None
    # "NEITHER OUTRANKS A PERSON" — so when a person HAS ruled, the question is answered.
    # An estimator_confirmed gauge is rank 100, entered off the drawing by somebody who
    # looked; re-asking them to confirm it is how a decision list teaches people to
    # scroll past all of it.
    if "estimator_confirmed" in str(kept_src).lower():
        return None
    # A PERSON AGREEING WITH THE KEPT VALUE IS ALSO A RULING, whatever rank their reading
    # carried. A confirmations file with no stated basis enters at "read" — a transcription,
    # rank 72 — and for gauge the cut file holds 95, so the person's 2 mm never displaces
    # the DXF's 2 mm and the source stamp stays the machine's. The agreement is still on
    # the record (_agreed, via support_for): the question this flag asks is "confirm the
    # gauge", and a recorded confirmation of the kept figure is that answer. A person
    # naming a DIFFERENT figure closes nothing here — that disagreement must stay visible.
    try:
        from source_precedence import support_for
        _backing = {str(s).lower() for s in
                    support_for(part, "normalized_thickness_mm", kept)}  # type: ignore[arg-type]
    except Exception:                                            # noqa: BLE001
        _backing = set()
    if _backing & {"estimator_confirmed", "estimator_read_drawing"}:
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
    # NO NODE IS NOT EVIDENCE OF MAKING. 12173-02's page counted one bought-in population
    # three ways (7, 12, 10) because a line with no graph node fell to "leaf" here while
    # section 2 asked the make/buy authority. With nothing from the graph, that authority
    # answers — the same one the report's count reads (12120's THUM620 stays bought in).
    if node is None:
        try:
            from bought_in_policy import is_bought_in               # noqa: PLC0415
            if is_bought_in(dict(part)):
                return "bought_in"
        except Exception:                                            # noqa: BLE001
            pass
    return "leaf"


def _material_label(part: Mapping[str, Any], kind: str) -> str:
    """What the Material column should say — asked of `display_material`, not decided here.

    This function KNEW three of the exceptions and was the only surface that did. A commercial
    line and a subcontract service are not made of anything and the stub that minted them
    carries MILD STEEL because every stub does; roll goods carried the sheet material they
    inherited, so the tape printed ACRYLIC beside a description saying EPDM. The quote, the
    report, the explanation and the SQL export each read `normalized_material` raw and knew
    none of it.

    So the exceptions moved to `display_material` and every surface asks the same question —
    including the fourth one this file never knew about: a BOUGHT-IN carrying the drawing
    sheet's title block is carrying the ASSEMBLY's material, which is the defect that reached
    three tabs on two jobs.
    """
    from display_material import material_text
    return material_text(part, kind)


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
    # cost_source ALWAYS joins the witness pool, never only as a fallback. The 11:19
    # PACKAGING stub carried cost_source "stated_method_system_priced" AND a stale
    # material_estimate whose cost_method said market — the or-chain let the stale stamp
    # mask the stub's own classification, so the report called Howard's stated method an
    # AI market indication three sections after the sheet said "Stated method + SDI Live".
    method = str(me.get("cost_method") or part.get("cost_source") or part.get("source") or "")
    _cost_src = str(part.get("cost_source") or "")
    supplier = str(part.get("supplier") or "").strip()
    # THE ROW'S OWN TAG IS A WITNESS TOO. The 08:08 tape line printed "[AI ESTIMATE -
    # INDICATIVE, NOT A QUOTE]" on the sheet while the part record behind it had lost its
    # price_source through the identity fold — so one surface called it a market figure
    # and the record called it "source unrecorded", and the headline tally stopped asking
    # anyone to replace it. What wb_populate stamped onto the row travels with the row.
    tokens = " ".join(str(x) for x in (
        method, _cost_src, ps.get("source_name"), ps.get("source_type"),
        ps.get("supplier_source"), supplier, row_text)).lower()
    money = charged_unit if charged_unit is not None else engine_unit
    _row_says_ai = "ai estimate" in tokens and "indicative" in tokens

    if cross_ref and block in _FABRICATED_BLOCKS:
        # A BOM row whose money is on a fabricated block. Nil HERE by design; the money is
        # reported on the fabricated line for the same part.
        pass
    if block in _FABRICATED_BLOCKS and money:
        # NAMED AS THE TEMPLATE NAMES IT. The key "tube" is the template's WIRE block; this
        # said "the Tube block" on 12173-02's riser and hook arm beside sheet rows reading
        # "costed in Wire below", and Tube is a labour department too. The name comes from
        # the layout map that describes the template (wb_populate.block_title).
        _name = _FABRICATED_BLOCKS[block]
        try:
            from wb_populate import block_title as _block_title          # noqa: PLC0415
            _name = _block_title(block) or _name
        except Exception:                                                # noqa: BLE001
            pass
        label = f"costed by nest on the {_name} block"
        if block in ("tube", "wire"):
            label = f"costed by length on the {_name} block"
        if sheet_row:
            label += f" — Estimate!{int(sheet_row)}"
        return {"class": f"nest_{block}", "firmness": FIRM, "owner": None, "label": label}
    if kind == "assembly" and not money:
        return {"class": "nil_by_design", "firmness": NIL, "owner": "nobody",
                "label": "nothing to charge here — an assembly's material is its members'"}
    # SUPPLIED BY ANOTHER PARTY, PER THE DRAWING: £0 on purpose, with the party named.
    if part.get("supplied_by_third_party") and not money:
        return {"class": "supplied_by_third_party", "firmness": NIL, "owner": "nobody",
                "label": (f"supplied by {str(part['supplied_by_third_party']).title()} per the "
                          f"drawing — listed at £0 so the pack is complete; if SDI is buying "
                          f"it, price the line")}
    # THE SAME ARTICLE UNDER A SECOND NAME IS NOT A MISSING PRICE. wb_populate puts the
    # money on one line and writes "SAME ARTICLE AS <kept>: costed there, not here" on the
    # other. 11650-06: FIXINGTBC read that way beside BI-KNURLEDKNOB (32 x £0.85, charged),
    # and the headline still said "3 prices missing", naming the knob as one of them — the
    # read-back knew the marker, this classifier did not. Nil by design, with the count this
    # line carried stated, so a difference from the charged line's count is visible here.
    _same = re.search(r"SAME ARTICLE AS\s+([^\s:]+)", str(row_text or ""), re.IGNORECASE)
    if _same and not money:
        _own_q = part.get("quantity")
        return {"class": "same_article", "firmness": NIL, "owner": "nobody",
                "label": (f"the same article is costed on {_same.group(1)} — this line is "
                          f"the drawing's second name for it"
                          + (f"; its own count here ({_num(_own_q):g}) is not charged — the "
                             f"quantity on {_same.group(1)} is"
                             if _num(_own_q) else ""))}
    if kind == "commercial" and not money:
        # "Delivery is not required" — Tony Ford, 16 Sep 2026 — is an ANSWER: the line's
        # £0 is a person's decision, and asking somebody to price it on every run is how
        # a settled question becomes a standing irritation.
        if part.get("_commercial_excluded"):
            return {"class": "nil_by_design", "firmness": NIL, "owner": "nobody",
                    "label": "NOT REQUIRED for this job — excluded by the estimator's "
                             "decision; the £0 is deliberate, not missing"}
        return {"class": "unpriced_commercial", "firmness": UNPRICED, "owner": "estimator",
                "label": "NOT PRICED — held at £0 until the estimators' own figure lands; "
                         "enter the per-unit amount"}
    # A DEPARTMENT'S OWN FIGURE IS NOT A MARKET LOOKUP.
    #
    # "Mislabelled as an AI market indication — it is Transport Dept. Relabel; don't drop
    # it." The plater-freight line is £— the round trip, stated by SDI's own transport
    # department through Howard Thurley, held in config and divided by the order quantity.
    # Nothing about it moves between runs and there is no supplier to replace it with.
    #
    # It landed in the market bucket for a structural reason, not a textual one: the
    # commercial-line branch above only recognises a commercial line with NO money, and this
    # is the first commercial line that carries some. So it fell past every branch to the
    # AI/market catch, and the headline asked an estimator to "replace a market figure" that
    # his own transport department had given him.
    #
    # INDICATIVE_HOUSE is the right bucket and the reason is in its own definition — a
    # configured, reproducible SDI rate, to verify or accept deliberately. Advisory, not
    # blocking: the number is real, and whether this job pays it is a question, not a gap.
    if "plater_freight" in tokens:
        try:
            import config as _cfg                                    # noqa: PLC0415
            _plog = getattr(_cfg, "PLATING_LOGISTICS", {}) or {}
        except Exception:                                            # noqa: BLE001
            _plog = {}
        return {"class": "plater_freight", "firmness": INDICATIVE_HOUSE, "owner": "estimator",
                "label": (f"SDI transport department's stated figure — "
                          f"{_plog.get('source', 'transport rate from config')}; "
                          f"divided by the order quantity, so it moves with the order")}
    # A LENGTH OFF A ROLL IS PRICED FROM A BUYING FACT, NOT A LOOKUP — and this is the
    # plater-freight defect again, on the very line the estimator supplied the numbers for.
    #
    # 10975-02's tape is costed by roll_goods_material from config.ROLL_GOODS_CATALOGUE:
    # TAPE113C, a 10 m roll at £—, sourced to "Howard Thurley (SDI estimating/buying),
    # 0355255 review, 9 Sep 2026". It came out of the classifier as
    #
    #     AI market indication (AI/market lookup) — NOT A QUOTE, replace it
    #
    # asking him to replace his own roll price with a quote, on the one line of the job he
    # had already priced by hand. The figure is right; the label is the thing that is wrong,
    # and a wrong label on a right number costs an estimator the time he spends checking it.
    if "roll_goods_by_length" in tokens or "roll_goods_catalogue" in tokens:
        _roll_len = _num(me.get("roll_length_mm"))
        _roll_gbp = _num(me.get("roll_price_gbp"))
        _used = _num(me.get("length_used_mm"))
        _bits = []
        if _used and _roll_len:
            _bits.append(f"{_used:g} mm of a {_roll_len:g} mm roll")
        if _roll_gbp:
            _bits.append(f"£{_roll_gbp:.2f} a roll")
        return {"class": "roll_goods", "firmness": INDICATIVE_HOUSE, "owner": "estimator",
                "label": ("priced by the length used — "
                          + (", ".join(_bits) if _bits else "SDI roll-goods catalogue")
                          + "; verify the roll price, not the arithmetic")}
    # A STATED METHOD PRICED FROM THE LIVE SYSTEM IS NEITHER A GUESS NOR A HOLD.
    #
    # The 19:02 book carried the packing calculation green — Howard's bag-and-box method,
    # consumable prices live from UDEF, the break row stepping exactly as his own sheet
    # steps — while the estimator-facing tabs called the same line unpriced in one place,
    # an AI market indication in another and not reproducible in a third. Every part of
    # that is the opposite of the truth: the method is a person's, the prices are the
    # system's, and the same run reproduces the same figure. INDICATIVE_HOUSE, for the
    # same reason as the plater freight and the roll: a real figure to verify or accept,
    # never one to "replace with a quote".
    if "stated_method_system_priced" in tokens or "packing_method" in tokens:
        return {"class": "stated_method", "firmness": INDICATIVE_HOUSE,
                "owner": "estimator",
                "label": ("priced by the estimator's stated method, consumables live "
                          "from SDI Live — reproducible between runs; verify the "
                          "method's steps, not the arithmetic")}
    # A MARKET LOOKUP THAT RETURNED NOTHING IS A MISSING PRICE, NOT A MARKET FIGURE. On
    # 12567-01's 16:48 book the cord, both Velcro strips, the JST lead, both grommets and
    # both splitters carried "xAI Grok LLM - INDICATIVE" as supplier and no price, and were
    # counted among "14 market figures to replace (£123.95)" — a total that was only the two
    # LED tapes, two diffusers, packaging and delivery. Eight £0 lines read as priced. The
    # lookup's label says where a figure was LOOKED FOR; only money says one was found (D-276).
    if money and (any(t in tokens for t in _MARKET_AI_TOKENS) or _row_says_ai):
        who = supplier or ps.get("supplier_source") or "AI/market lookup"
        return {"class": "market_ai", "firmness": INDICATIVE_MARKET, "owner": "estimator",
                "label": f"researched market price ({who}) — not a quotation, "
                         f"replace before quoting"}
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
    owner, why, detail = "estimator", \
        "no catalogue row, price file or quote holds a rate for this", ""
    try:
        from estimator_inputs import unpriced_reason_for_row
        reason = unpriced_reason_for_row(part) or {}
        owner = str(reason.get("owner") or owner)
        why = str(reason.get("why") or reason.get("detail") or why)
        detail = str(reason.get("detail") or "")
    except Exception:                                                # noqa: BLE001
        pass
    if owner == "nobody":
        # The detail is the sentence a person can act on — "FREE-ISSUE: the customer
        # supplies this" says which correct nothing this is, where the category's own
        # wording only says that it is one.
        return {"class": "nil_by_design", "firmness": NIL, "owner": "nobody",
                "label": (f"{why} — {detail}" if detail else why)}
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


def route_operations_for_part(source: Any, part_number: Any) -> List[str]:
    """The operations the canonical route REQUIRES of this part, read from the route itself.

    WHY THIS EXISTS BESIDE `operations` RATHER THAN REPLACING IT. _operations_from_decisions
    reads decision ids off the priced workbook ROWS, deliberately: its result then names only
    decisions that survived every gate and reached the sheet, which is exactly what you want
    when the question is "what is this part charged for?".

    But it answers a different question from "what does the route require?", and the two were
    being conflated. On every archived 7332-01 summary the canonical route records tubebend on
    7332-01-002 while the costed line publishes `operations: []`, because those rows carry no
    decision ids — so a reader asking whether the route bends the tube got "no" from a record
    whose route says yes. Weakening `operations` to paper over that would destroy the property
    that makes it useful, so the route's own answer is published alongside it instead and each
    keeps its meaning:

        operations        what this part is CHARGED for — survived the gates, reached the sheet
        route_operations  what the route REQUIRES of it — the compiler's decision, status
                          `required` only

    ONLY `required` COUNTS, and a decision with no status does not qualify. "The compiler
    considered tubebend" is not "the route bends the tube", and absence is not a claim.
    """
    want = str(canonical_identity(source, part_number) or part_number or "").strip().upper()
    if not want:
        return []
    out: List[str] = []
    for decision in _decisions_by_id(source).values():
        if str(decision.get("status") or "").strip().lower() != "required":
            continue
        targets = {str(decision.get("target_id") or "").strip().upper(),
                   str(decision.get("subject_id") or "").strip().upper(),
                   str(decision.get("part_number") or "").strip().upper()}
        targets |= {str(p).strip().upper() for p in (decision.get("participants") or [])}
        if want not in (targets - {""}):
            continue
        op = str(decision.get("operation") or "").strip()
        if op and op not in out:
            out.append(op)
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


def _squash(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def stated_rows_not_carried(source: Any) -> List[Dict[str, Any]]:
    """Parts-list rows the pack STATES that the product does not carry: the row's code joins
    no reached node under any alias or spelling, and no ledger ruled it out. 12645 19:17: the
    M8 nut x120 and the tek screw x16 on the body's own parts list (D-324).

    Empty unless the product resolved. A stopped roll-up has its own issue; forcing either of
    12645's offline roots as the product flagged every row under the other."""
    if not isinstance(source, dict):
        return []
    try:
        from invariants import _reached_unaccounted_core as _ruc  # noqa: PLC0415
        _r = _ruc(source)
    except Exception:                                             # noqa: BLE001
        return []
    nodes = _canonical_nodes(source)
    payload = ((source.get("estimate_summary") or {}).get("canonical_route_shadow")
               if isinstance(source.get("estimate_summary"), dict) else None) \
        or source.get("canonical_route_shadow") or {}
    root = str((payload or {}).get("product_root") or "").strip().upper()
    if not root or root not in nodes:
        return []
    reached: Set[str] = set()
    frontier = [root]
    while frontier:
        ident = frontier.pop()
        if ident in reached:
            continue
        reached.add(ident)
        for edge in (nodes.get(ident, {}).get("children") or []):
            child = str((edge or {}).get("part_number") if isinstance(edge, dict) else edge
                        or "").strip().upper()
            if child and child not in reached:
                frontier.append(child)
    reached_sq = {_squash(r) for r in reached}
    for r in list(reached):
        for a in ((nodes.get(r) or {}).get("evidence") or {}).get("raw_aliases") or []:
            reached_sq.add(_squash(a))
    ruled = {_squash(x) for x in removed_identities(source)}
    ruled |= {_squash(e.get("part_number")) for e in (source.get("set_aside_outside_product") or [])
              if isinstance(e, dict)}
    try:
        from part_identity import is_placeholder_identity           # noqa: PLC0415
    except Exception:                                             # noqa: BLE001
        def is_placeholder_identity(_x):                          # type: ignore
            return False
    try:
        from part_identity import strip_code_label                 # noqa: PLC0415
    except Exception:                                             # noqa: BLE001
        def strip_code_label(_x):                                 # type: ignore
            return str(_x or "")
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for row in ((source.get("document_analysis") or {}).get("bom_rows") or []):
        if not isinstance(row, dict):
            continue
        code = str(row.get("part_number") or "").strip()
        qty = _num(row.get("quantity"))
        # THE SPELLING THE RECORD PASS USED, AS WELL AS THE PRINTED ONE. 12173-02's ×16
        # screw was "stated and not carried" beside its own priced line: the record pass had
        # stripped a label the row kept. A row whose code is a known label plus a code joins
        # a reached part under the stripped code, and only where that part is reached.
        spellings = {code, strip_code_label(code)}
        keys = ({_squash(c) for c in spellings}
                | {_squash(canonical_identity(source, c)) for c in spellings})
        keys.discard("")
        if not code or not qty or not keys or keys & seen or is_placeholder_identity(code):
            continue
        if keys & reached_sq or keys & ruled:
            continue
        seen |= keys
        out.append({"part_number": code, "description": str(row.get("description") or ""),
                    "qty": qty, "sheet": str(row.get("bom_sheet") or row.get("source_page")
                                             or row.get("bom_parent") or "")})
    return out


# ── ONE OPERATION ON AN ASSEMBLY AND AGAIN ON SOMETHING IT CONTAINS ─────────────────────
_REPEATED_PER_LEVEL_DEFAULT = ("assembly", "assemble", "handling", "packing")


def _hierarchy_children(source: Any) -> Dict[str, Set[str]]:
    """parent -> children from every hierarchy the job carries: the model's tree and the
    write-up's assembly_children. Unioned, because the question asked of it — is one of these
    the ancestor of another — needs no single source to answer it alone."""
    children: Dict[str, Set[str]] = {}
    if not isinstance(source, Mapping):
        return children
    _sw = ((source.get("solidworks_native") or {}) if isinstance(
        source.get("solidworks_native"), Mapping) else {}).get("hierarchy") or {}
    for parent, kids in (_sw.items() if isinstance(_sw, Mapping) else []):
        for kid in (kids or []):
            code = kid[0] if isinstance(kid, (list, tuple)) and kid else kid
            if str(code or "").strip():
                children.setdefault(str(parent).upper(), set()).add(str(code).upper())
    for part in ((source.get("manufacturing_writeup") or {}).get("parts") or []):
        if not isinstance(part, Mapping):
            continue
        for kid in (part.get("assembly_children") or []):
            if str(kid or "").strip():
                children.setdefault(
                    str(part.get("part_number") or "").upper(), set()).add(str(kid).upper())
    return children


def parent_child_overlaps(source: Any) -> Optional[List[Dict[str, Any]]]:
    """Every operation charged on an assembly and AGAIN on something it contains, as EVENTS.

    None when the job carries no hierarchy (no tree, no opinion). Shared by the invariant
    that reports these and the decision tally that asks them, so the two cannot disagree.

    WHAT 12173-02 TAUGHT (1 Oct 17:34 book), where twenty such rows read "could not be run":
      * ONE EVENT IS NOT TWO CHARGES. A weld decision on 04-201 whose participants are its
        members is the pocket's weld, once — it was reported as "charged on 04-201 and
        separately on 02M, 02M-H, 03M ...". A decision with a target is one event at that
        target; its participants are who it joins, not further charges.
      * NESTED BUILDS ARE LEVELS. An assembly event on 03-GA over 201 and another on 201 over
        its frames are two builds; config OPERATIONS_REPEATED_PER_LEVEL names the operations
        that legitimately recur at every level. A coat or a weld is still asked.
      * THE NEAREST CHARGED ANCESTOR. 06M under 202 under 201, each welded: the question is
        202-and-06M and 201-and-202, never 201-and-06M on top of them.
      * SETTLED BY THE DRAWINGS. Where the compiler read an arc weld drawn on the assembly's
        own sheet and on the member's (field_provenance review
        'joining_on_assembly_and_member_both_drawn'), each charge is its own drawn weld.
      * THE DECISION IDS ARE THE PAIR'S, not the operation's first six.
    A legacy decision with no target (older extracts, test shapes) keeps the old reading:
    each participant is its own charge.

    [{"operation", "assembly", "descendants", "decision_ids", "asked"}], `asked` naming the
    compiler issue that already puts it to a person (joining or powder scope), or ""."""
    if not isinstance(source, Mapping):
        return None
    children = _hierarchy_children(source)
    if not children:
        return None

    def _desc(code: str) -> Set[str]:
        out: Set[str] = set()
        frontier = list(children.get(code, ()))
        while frontier:
            k = frontier.pop()
            if k in out:
                continue
            out.add(k)
            frontier.extend(children.get(k, ()))
        return out

    shadow = ((source.get("estimate_summary") or {}).get("canonical_route_shadow")
              if isinstance(source.get("estimate_summary"), Mapping) else None) \
        or source.get("canonical_route_shadow") or {}
    if not isinstance(shadow, Mapping):
        return []
    _priced = {str(r.get("decision_id") or "") for r in (shadow.get("priced_route_rows") or [])
               if isinstance(r, Mapping)}
    _priced.discard("")
    try:
        import config as _cfg
        _repeat = {str(o).strip().lower() for o in (
            getattr(_cfg, "OPERATIONS_REPEATED_PER_LEVEL", None)
            or _REPEATED_PER_LEVEL_DEFAULT)}
    except Exception:                                                # noqa: BLE001
        _repeat = set(_REPEATED_PER_LEVEL_DEFAULT)
    # op -> [(decision_id, holders, members, targeted, settled)]
    events: Dict[str, List[Tuple[str, Set[str], Set[str], bool, bool]]] = {}
    for n, d in enumerate(shadow.get("decisions") or []):
        if not isinstance(d, Mapping):
            continue
        # A decision that STATES a status other than required is ruled out; one that states
        # none is not (some writers omit it, and requiring it would blind the check).
        _st = str(d.get("status") or "").strip().lower()
        if _st and _st != "required":
            continue
        _id = str(d.get("decision_id") or f"#{n + 1}")
        if _priced and _id not in _priced:
            continue                    # a decision is not a charge until a row joins to it
        op = str(d.get("operation") or "").strip()
        if not op or op.lower() in _repeat:
            continue
        parts_in = {str(p).upper() for p in (d.get("participants") or []) if p}
        tgt = str(d.get("target_id") or "").strip().upper()
        holders = {tgt} if tgt else set(parts_in)
        members = parts_in | ({tgt} if tgt else set())
        _review = str(((d.get("field_provenance") or {}) if isinstance(
            d.get("field_provenance"), Mapping) else {}).get("review") or "")
        events.setdefault(op, []).append(
            (_id, holders, members, bool(tgt),
             _review == "joining_on_assembly_and_member_both_drawn"))
    asked: Dict[Tuple[str, str], str] = {}
    for iss in (shadow.get("issues") or []):
        if not isinstance(iss, Mapping):
            continue
        if iss.get("code") == "joining_charged_on_assembly_and_member":
            asked[(str(iss.get("assembly") or "").upper(),
                   str(iss.get("operation") or "").lower())] = "joining_charged_on_assembly_and_member"
        elif iss.get("code") == "powder_scope_mixed_members":
            asked[(str(iss.get("part_number") or "").upper(), "powder_coating")] = \
                "powder_scope_mixed_members"
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for op, evs in events.items():
        holders_all = {h for (_i, hs, _m, _t, _s) in evs for h in hs}
        for (ic, hc, mc, tc, settled) in evs:
            if settled:
                continue
            for C in hc:
                anc = [P for P in holders_all if P != C and C in _desc(P)]
                # The nearest: no other charged holder sits between P and C.
                near = [P for P in anc if not any(Q != P and Q in _desc(P) and C in _desc(Q)
                                                  for Q in anc)]
                for P in near:
                    for (ip, hp, mp, tp, _sp) in evs:
                        if P not in hp:
                            continue
                        if ip == ic and tp:
                            continue            # one targeted event is not two charges
                        if tc and P in mc:
                            continue            # the child's own event already holds the parent
                        rec = out.setdefault((op, P), {
                            "operation": op, "assembly": P, "descendants": [],
                            "decision_ids": [], "asked": asked.get((P, op.lower()), "")})
                        if C not in rec["descendants"]:
                            rec["descendants"].append(C)
                        for _i in (ip, ic):
                            if _i not in rec["decision_ids"]:
                                rec["decision_ids"].append(_i)
    for rec in out.values():
        rec["descendants"].sort()
    return [out[k] for k in sorted(out)]


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
    # Document-level gauges, once: a line whose gauge is one of them says so on its record.
    try:
        _doc_gauges = document_level_gauges(source)
    except Exception:                                                # noqa: BLE001
        _doc_gauges = {}
    try:
        from source_precedence import source_of as _source_of        # noqa: PLC0415
    except Exception:                                                # noqa: BLE001
        def _source_of(_p, _f):                                      # noqa: ANN001
            return ""
    # Every sheet row a line claims, by object: a row no part claims is still money on the
    # sheet, and is put on the record below (a key-based dict would lose a second row that
    # shares one key, so the claim is the row itself).
    _claimed_rows: Set[int] = set()
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
        for _r in (row, bom):
            if isinstance(_r, dict):
                _claimed_rows.add(id(_r))
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

        # ── "TREAT ANY £0 AS MISSING" IS TRUE ONLY WHILE THE LINE IS £0 ─────────────
        # The SolidWorks connector writes it at ingest, before a wire length or a BOM price
        # arrives. 12173-02: the hook arm's note said it beside £0.31 charged at Estimate!84,
        # and sections 3 and 5 printed it against four lines carrying £0.31–£1.08. Computed
        # here from the money this line holds: where it holds some, the sentence says what
        # that money rests on; where it holds none, the warning stands. Money is not touched.
        flags = _estimator_flags(part.get("review_flags"))
        try:
            from plain_english import NO_GEOMETRY_SENTENCE as _NO_GEO    # noqa: PLC0415
        except Exception:                                            # noqa: BLE001
            _NO_GEO = None
        _money_here = charged_ext if charged_ext is not None else (round(engine_ext, 2) or None)
        if _NO_GEO and _NO_GEO in flags and _money_here:
            flags = [f for f in flags if f != _NO_GEO]
            _cell = ((row or {}).get("charged_cell") or (bom or {}).get("charged_cell")
                     or (f"Estimate!{int(sheet_row)}" if sheet_row else None))
            _where = _cell or "the engine's figure, not yet the sheet's"
            if kind == "bought_in":
                flags.append(f"SolidWorks has no geometry for this part; none is needed for a "
                             f"bought item — the £{_money_here:,.2f} ({_where}) is its "
                             f"purchase price, see the price source")
            else:
                _basis = (f"a length of {length['mm']:,.0f} mm read by "
                          f"{length.get('reader') or 'an unrecorded reader'}"
                          if length and length.get("mm") else
                          (str(origin.get("label") or "") or "the sheet row"))
                flags.append(f"SolidWorks gave this part no usable geometry; the "
                             f"£{_money_here:,.2f} charged ({_where}) rests on {_basis} — the "
                             f"model does not corroborate it; confirm against the drawing")

        # THE GAUGE'S BASIS, ON THE LINE. The Dimensions cell printed a bare "1.0 mm" on
        # 12173-02's meshes — the pack's document-level figure, which won there only because
        # the model's 6 mm was refused — and nothing said where it came from.
        _thk = _num(part.get("normalized_thickness_mm"))
        _hit = next((d for v, d in _doc_gauges.items()
                     if _thk and abs(v - _thk) <= 0.05 and pn in (d.get("kept_on") or [])), None)
        try:
            _thk_src = str(_source_of(dict(part), "normalized_thickness_mm") or "")
        except Exception:                                            # noqa: BLE001
            _thk_src = ""
        thickness_basis = ({"mm": _thk, "source": _thk_src, "document_level": bool(_hit),
                            "also_on": list((_hit or {}).get("refused_on") or [])}
                           if _thk else None)

        lines.append({
            "part_number": pn,
            "identity": identity,
            # Who wrote the code (D-383): a minted or split identity is recognised by its
            # record, so a report never calls the engine's code "the code the drawing printed".
            "identity_source": str(part.get("identity_source") or ""),
            "printed_code": str(part.get("printed_code") or ""),
            "description": str(part.get("description") or ""),
            "kind": kind,
            "qty_per_unit": qty,
            "material_label": _material_label(part, kind),
            "thickness_mm": part.get("normalized_thickness_mm"),
            "thickness_basis": thickness_basis,
            "block": block,
            "sheet_row": sheet_row,
            # The cell the read-back actually read this money from. Recorded at the point the
            # column was located, never inferred from the template's current shape.
            "charged_cell": (str((row or {}).get("charged_cell") or "")
                             or str((bom or {}).get("charged_cell") or "")) or None,
            "cross_reference": cross_ref,
            "charged_unit_gbp": charged_unit,
            "charged_ext_gbp": charged_ext,
            "engine_unit_gbp": round(engine_unit, 4),
            "engine_ext_gbp": round(engine_ext, 4),
            "money_basis": "excel_calculated" if charged_ext is not None else "engine_pre_excel",
            "price_origin": origin,
            "operations": _operations_from_decisions(source, pn),
            # What the ROUTE requires, beside what the part is CHARGED for. The two answer
            # different questions and were being conflated: on every archived 7332-01 summary
            # the route records tubebend on 7332-01-002 while `operations` is empty, because
            # those rows carry no decision ids.
            "route_operations": route_operations_for_part(source, pn),
            "length": length,
            "section_profile": profile,
            "review_flags": flags,
            "plating_members": list(part.get("_plating_members_costed") or []),
            "plating_excluded": list(part.get("_plating_members_deferred") or []),
        })

    # ── EVERY SHEET ROW THAT CARRIES MONEY IS ON THE RECORD ─────────────────────
    # 12173-02, 1 Oct: the hierarchy section ended "a difference of £2.88 on the sheet and on
    # no line here" — exactly the sheet's POWDER row (0.69 kg × £4.00 × 1.04), which the
    # writer mints inside the BOM block with no part record behind it, so no line was ever
    # built for it. The same omission made the summary count 33 money rows against the
    # sheet's 34, section 13 a third figure, and the material breakdown file £2.88 as an
    # unreconciled residual. A row no part claimed — or a second row under a key another row
    # already took — becomes a line of its own, named for the sheet row it is. It is firm
    # (the sheet's own money, at its own cell), never "unpriced" or "market": the open
    # question about powder coverage is the sheet's own outstanding item, not this line's.
    # Only beside a part list: with none, there is no record of lines to complete, and every
    # reader already reads the sheet's rows directly.
    if calculated and lines:
        for r in mat_rows:
            if id(r) in _claimed_rows:
                continue
            gbp = _num(r.get("total_value_gbp"))
            text = str(r.get("description") or "").strip()
            if not gbp or "costed in" in text.lower():
                continue
            _wr = r.get("workbook_row") or r.get("row")
            key = _material_row_key(r) or (f"ROW{int(_wr)}" if _wr else "")
            if not key:
                continue
            _ids = {str(l.get("identity") or "").upper() for l in lines}
            identity = key if key.upper() not in _ids else (
                f"{key} (Estimate row {int(_wr)})" if _wr else f"{key} (second row)")
            cell = (str(r.get("charged_cell") or "")
                    or (f"Estimate!{int(_wr)}" if _wr else "")) or None
            _code = str(r.get("part_code") or key).strip()
            _q = _num(r.get("qty_per_unit")) or _num(r.get("quantity")) or 1.0
            # THE ROW'S OWN TAG IS ITS WITNESS, as for any line: a row the sheet carries at a
            # researched market figure (its supplier cell says so) is a market figure to
            # replace; any other is the sheet's own money, firm at its own cell.
            _supplier = str(r.get("supplier") or "").strip()
            _rtok = " ".join(str(x or "") for x in (_supplier, r.get("source"),
                                                    r.get("price_source"), text)).lower()
            _origin = {"class": "sheet_row", "firmness": FIRM, "owner": None,
                       "label": (f"the sheet's own {_code} row — {text[:80]}"
                                 + (f", {cell}" if cell else ""))}
            if any(t in _rtok for t in _MARKET_AI_TOKENS) or (
                    "ai estimate" in _rtok and "indicative" in _rtok):
                _origin = {"class": "market_ai", "firmness": INDICATIVE_MARKET,
                           "owner": "estimator",
                           "label": (f"researched market price ({_supplier or 'AI/market lookup'})"
                                     f" — not a quotation, replace before quoting"
                                     + (f"; {cell}" if cell else ""))}
            lines.append({
                "part_number": identity, "identity": identity, "description": text,
                "kind": "sheet_row", "qty_per_unit": _q,
                "material_label": _code.title() if _code else str(r.get("block") or "bom"),
                "thickness_mm": None, "thickness_basis": None,
                "block": str(r.get("block") or "bom"), "sheet_row": _wr,
                "charged_cell": cell, "cross_reference": False,
                "charged_unit_gbp": (_num(r.get("unit_price_gbp")) or round(gbp / _q, 4)),
                "charged_ext_gbp": gbp,
                "engine_unit_gbp": 0.0, "engine_ext_gbp": 0.0,
                "money_basis": "excel_calculated",
                "price_origin": _origin,
                "operations": [], "route_operations": [], "length": None,
                "section_profile": None, "review_flags": [],
                "plating_members": [], "plating_excluded": [],
            })

    # ── the gap lists, once ─────────────────────────────────────────────────────
    def _money_of(line: Dict[str, Any]) -> float:
        v = line.get("charged_ext_gbp")
        return _num(v) if v is not None else _num(line.get("engine_ext_gbp"))

    # AN ASSEMBLY OFF THE SHEET IS NOT IN THE UNIT. 12567-01's 17:45 report put £412.09 on
    # market figures to replace, £31 of it the AI's own figures for the two end-header
    # lighting assemblies (02-301, 03-301). Neither is a line on the Estimate sheet — the
    # tapes, diffusers and driver beneath them are — so the unit never contained that £31
    # and nobody needs to replace it. Once the sheet is read back, an assembly with no row
    # on it has nothing in the total to verify (D-306).
    def _in_unit(line: Dict[str, Any]) -> bool:
        return not (calculated and line.get("kind") == "assembly"
                    and line.get("charged_ext_gbp") is None)

    unpriced = [l for l in lines if l["price_origin"]["firmness"] == UNPRICED]
    house = [l for l in lines if l["price_origin"]["firmness"] == INDICATIVE_HOUSE
             and _in_unit(l)]
    market = [l for l in lines if l["price_origin"]["firmness"] == INDICATIVE_MARKET
              and _in_unit(l)]
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
        # A LINE UNPRICED FOR WANT OF A GAUGE SAYS SO. A board whose only thickness readings
        # were the drawing's tolerance text is left without a gauge rather than charged at the
        # table's 3 mm (12173-03-01J); the line is NOT PRICED, and what it needs is the gauge,
        # not a rate — said from the costing pass's own sentence on the line.
        _gauge = next((f for f in (l.get("review_flags") or [])
                       if "confirm the board gauge" in str(f)), "")
        decisions.append({
            "part": l["part_number"], "kind": "missing_price",
            "issue": f"{l['part_number']} carries no price",
            "assumption": "held at £0 — the unit cost is understated by whatever it is worth",
            "action": ("enter the per-unit figure" if l["kind"] == "commercial"
                       else (f"confirm the board gauge from the drawing — {_gauge}"
                             if _gauge else "supply a rate or a supplier quote")),
            "owner": l["price_origin"]["owner"], "gbp_at_stake": None})
    # ── WHAT THE TALLY COULD NOT SEE, FROM THE RESOLVERS THAT ALREADY SEE IT (D-324) ──
    # The tally built its list from priced lines only, so an item with NO line — 12645's
    # shutters, reached and absent — was counted nowhere, and the reached-item check that
    # does see it runs after the banner is written. The same walk now feeds both.
    _named_now = {str(d.get("part") or "").upper() for d in decisions}
    try:
        from invariants import _reached_unaccounted_core as _ruc   # noqa: PLC0415
        _ru = _ruc(source)
    except Exception:                                              # noqa: BLE001
        _ru = {}
    for _ident in _ru.get("unaccounted") or []:
        if str(_ident).upper() in _named_now:
            continue
        _q = _num(((_ru.get("nodes") or {}).get(_ident) or {}).get("qty_per_unit")) or None
        decisions.append({
            "part": _ident, "kind": "missing_price", "qty": _q,
            "issue": (f"{_ident}{f' x{_q:g}' if _q else ''} is on the bill the product reaches "
                      f"and has no line on the sheet"),
            "assumption": "not in the unit cost at all — nothing on the sheet carries it",
            "action": "price it and add the line, or record why SDI does not buy it",
            "owner": "estimator", "gbp_at_stake": None})
    for _r in stated_rows_not_carried(source):
        decisions.append({
            "part": _r["part_number"], "kind": "stated_not_carried", "qty": _r["qty"],
            "issue": (f"{_r['part_number']} ({_r['description']}) x{_r['qty']:g} is stated on "
                      f"{_r['sheet'] or 'a parts list'} and the product does not carry it"),
            "assumption": "not in the unit cost — the row never reached the bill",
            "action": "charge it on the assembly that lists it, or rule it out with a reason",
            "owner": "estimator", "gbp_at_stake": None})
    # LABOUR THE BLOCK HAD NO ROOM FOR (D-340). Not a price the engine lacks — work it
    # timed and could not put on the sheet, so the unit cost is short by exactly it.
    for _d in ((source.get("labour_not_on_sheet") if isinstance(source, Mapping) else None)
               or []):
        if not isinstance(_d, Mapping):
            continue
        _parts = [str(p) for p in (_d.get("parts") or [])]
        decisions.append({
            "part": f"{_d.get('operation') or 'labour'}"
                    + (f" ({', '.join(_parts[:3])}{'…' if len(_parts) > 3 else ''})"
                       if _parts else ""),
            "kind": "labour_not_on_sheet", "qty": None,
            "issue": (f"{_d.get('operation')} on {', '.join(_parts) or 'the job'} is on the "
                      f"route and was timed, but the Labour block was full, so it has no row"),
            "assumption": "not in the unit cost — the row was never written",
            "action": "add rows to the template's Labour block and re-run, or add the row by "
                      "hand from the route",
            "owner": "estimator", "gbp_at_stake": None})
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
        # AND WHERE THE SAME FIGURE STAYED IN FORCE — a question, not a correction: on
        # 12173-02 the meshes kept the 1.0 mm the frames refused, and the decision named
        # only the refusals.
        _kept = list(((_doc_gauges.get(_bv) or {}).get("kept_on")) or [])
        decisions.append({
            "part": ", ".join(_bparts), "kind": "manufacturing_decision",
            "issue": (f"{', '.join(_bparts)} each show {_bv:g} mm from the drawing "
                      f"against their own stronger gauges — one document figure "
                      f"repeated across {len(_bparts)} parts, or {len(_bparts)} real "
                      f"specs"
                      + (f"; and it is the gauge in force on {', '.join(_kept)}, which "
                         f"{'has' if len(_kept) == 1 else 'have'} no measured gauge "
                         f"{'of its own' if len(_kept) == 1 else 'of their own'}"
                         if _kept else "")),
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
    _shadow_issues = ((((source.get("estimate_summary") or {})
                        .get("canonical_route_shadow") if isinstance(
                            source.get("estimate_summary"), Mapping) else None)
                       or source.get("canonical_route_shadow") or {}).get("issues") or [])
    for _iss in _shadow_issues:
        if not isinstance(_iss, Mapping) \
                or str(_iss.get("code")) != "powder_scope_mixed_members":
            continue
        # SAY WHAT THE SHEET CHARGES, NOT WHAT MIGHT. 12312-01-GA: the decision read "both
        # the assembly coat and the coated members' lines stand" while the sheet carried ONE
        # P.Coat row, on 02M, 101 and 14M, and the case leaves had none. The estimator is
        # asked to choose against the scope actually priced.
        _coat_rows = [r for r in (_workbook_rows(source) or [])
                      if "powder_coating" in [str(o) for o in (r.get("engine_operations") or [])]
                      or str(r.get("wb_operation") or "").upper().replace(" ", "") in ("P.COAT", "POWDERCOAT")]
        _charged = sorted({str(pn) for r in _coat_rows for pn in (r.get("part_numbers") or [])})
        _coat_gbp = round(sum(_num(r.get("total_value_gbp")) for r in _coat_rows), 2)
        # THE SCOPE THIS DECISION IS ABOUT, AS THE ROW CHARGES IT. The 17:34 12173 book asked
        # about 04-201 and its members and answered with every part on the job's one P.Coat
        # row — the frame, the rails, the hooks and a rack hand. The decision names what the
        # row charges of THIS assembly and its members, and says the row is shared.
        _members_named = list(_iss.get("coated_members") or []) \
            + list(_iss.get("uncoated_members") or [])
        _scope = {str(_iss.get("part_number") or "").upper()} | {
            str(x).upper() for x in _members_named}
        _in_scope = [pn for pn in _charged if pn.upper() in _scope]
        _others = [pn for pn in _charged if pn.upper() not in _scope]
        _rows_n = [str(r.get("workbook_row")) for r in _coat_rows if r.get("workbook_row")]
        if not _charged:
            _assume = "no P.Coat row is charged on the sheet"
        elif not _members_named or not _others:
            # The issue names no members, or the row holds nothing else: the row IS the scope.
            _assume = (f"the sheet charges one P.Coat scope: {', '.join(_charged)}"
                       f"{f' (£{_coat_gbp:,.2f} a unit)' if _coat_gbp else ''}")
        else:
            _assume = (f"the sheet's P.Coat row{'s' if len(_rows_n) > 1 else ''}"
                       f"{(' ' + ', '.join(_rows_n)) if _rows_n else ''} "
                       f"charge{'' if len(_rows_n) > 1 else 's'} of this scope: "
                       f"{', '.join(_in_scope) or 'none of these parts'}"
                       + (f" (£{_coat_gbp:,.2f} a unit, the row shared with "
                          f"{', '.join(_others)})" if _coat_gbp else
                          f" (the row also carries {', '.join(_others)})"))
        decisions.append({
            "part": str(_iss.get("part_number") or ""),
            "kind": "manufacturing_decision",
            # The operation, as a field: a check's ruling on the same part and operation is
            # the same question and is netted onto this row by these two fields, never by
            # matching words in the issue.
            "operation": "powder_coating",
            "issue": str(_iss.get("message") or "the powder scope is mixed between "
                         "the assembly and its members"),
            "assumption": _assume,
            "action": ("say which parts are coated before assembly and which after: the whole "
                       "case after build (members' RAW notes read as pre-finish), every part "
                       "before, or a mixed route naming each — the P.Coat rows and powder "
                       "area follow the answer"),
            "owner": "estimator", "gbp_at_stake": _coat_gbp or None,
        })
    def _priced_assembly(part: Mapping[str, Any]) -> None:
        # AN ASSEMBLY THAT CARRIES A PRICE OF ITS OWN AND CHARGES NOTHING. 12312-01-08X, the
        # 3.944 m silicone LED diffuser, reached the tree holding four purchased items, so it
        # was an assembly — £0 by design — while the AI had priced the diffuser itself at
        # £32.50. "Nil by design" hid a purchase: the length is something SDI buys.
        _pn_u = str(part.get("part_number") or "").upper()
        _line = _by_pn.get(_pn_u)
        _own_price = _num(((part.get("system_cost") or {}) if isinstance(
            part.get("system_cost"), Mapping) else {}).get("unit_cost_gbp"))
        if not _own_price:
            # The 14:57 rerun: 08X reached the report as a group header, its price only in
            # the flag the pricer leaves ("AI researched price £32.50: priced as ...").
            for _f in (part.get("review_flags") or []):
                _m = re.search(r"AI researched price £([0-9,]+(?:\.[0-9]+)?)", str(_f))
                if _m:
                    _own_price = _num(_m.group(1).replace(",", ""))
                    break
        _is_asm = ((_line is not None and _line.get("kind") == "assembly")
                   or str((nodes.get(_pn_u) or {}).get("kind") or "") == "assembly"
                   or bool(part.get("is_assembly_parent") or part.get("assembly_children")))
        _charged = _money_of(_line) if _line is not None else 0.0
        if _is_asm and not _charged and _own_price > 0 \
                and not any(d.get("part") == str(part.get("part_number") or "")
                            and "carries its own price" in str(d.get("issue"))
                            for d in decisions):
            decisions.append({
                "part": str(part.get("part_number") or ""), "kind": "manufacturing_decision",
                "issue": (f"{part.get('part_number')} ({part.get('description') or 'no description'}) "
                          f"is costed as an assembly at £0, but it carries its own price of "
                          f"£{_own_price:,.2f}"),
                "assumption": "nothing charged for the item itself — only its members",
                "action": ("if SDI buys it (a length, a housing), charge it as a purchased line; "
                           "if its members are the whole of it, confirm £0"),
                "owner": "estimator", "gbp_at_stake": round(_own_price, 2)})

    # A READER'S QUESTION, PRICED BY WHAT RIDES ON IT. A question naming the operations it is
    # about (charged_operations) is a decision only where the sheet charges one of them on the
    # part, and carries those rows' money: an uncharged weld cannot be double-charged, so the
    # flag the reader left on the part stands alone (12173-03-GA, whose members state WELDED,
    # has no weld row). A question naming the lines it is about (gbp_parts — the pieces a DXF
    # reading costed) carries their money. Otherwise the part's own line, as before (D-382).
    _weld_asked: Set[str] = set()

    def _question_decision(part: Mapping[str, Any], mq: Mapping[str, Any]
                           ) -> Optional[Dict[str, Any]]:
        _pn = str(part.get("part_number") or "")
        _ops = {str(o) for o in (mq.get("charged_operations") or []) if o}
        _assume = str(mq.get("assumption") or "")
        if _ops:
            _rows = [r for r in (_workbook_rows(source) or [])
                     if {str(o) for o in (r.get("engine_operations") or [])} & _ops
                     and _pn.upper() in {str(x).upper() for x in (r.get("part_numbers") or [])}]
            if not _rows:
                return None
            _gbp = round(sum(_num(r.get("total_value_gbp")) for r in _rows), 2) or None
            _nums = [str(r.get("workbook_row")) for r in _rows if r.get("workbook_row")]
            if _gbp or _nums:
                _assume += (" (" + (f"£{_gbp:,.2f} a unit" if _gbp else "charged")
                            + (f", Estimate row{'s' if len(_nums) > 1 else ''} "
                               f"{', '.join(_nums)}" if _nums else "") + ")")
        elif "gbp_parts" in mq:           # empty: nothing is costed on the reading — no money
            _gbp = round(sum(_money_of(_by_pn[str(c).upper()]) for c in mq.get("gbp_parts") or []
                             if str(c).upper() in _by_pn), 2) or None
        else:
            _line = _by_pn.get(_pn.upper())
            _gbp = (_money_of(_line) if _line is not None else None) or None
        if str(mq.get("subject") or "") == "welding":
            _weld_asked.add(_pn.upper())
        _qrow: Dict[str, Any] = {"part": _pn, "kind": "manufacturing_decision",
                                 "issue": str(mq.get("issue")), "assumption": _assume,
                                 "action": str(mq.get("action") or ""), "owner": "estimator",
                                 "gbp_at_stake": _gbp}
        # A question that names the operations it asks about carries them as fields: a
        # check's ruling on the same part and operation nets onto this row by them. Where it
        # names only the operations that price it (charged_operations), those are what it asks.
        if mq.get("operation"):
            _qrow["operation"] = str(mq["operation"])
        _asks = mq.get("operations") if isinstance(mq.get("operations"), (list, tuple)) \
            else (sorted(_ops) if _ops else None)
        if _asks:
            _qrow["operations"] = [str(o) for o in _asks if o]
        return _qrow

    def _questions_of(part: Mapping[str, Any]) -> None:
        _seen_q: Set[str] = set()
        for _mq in (part.get("manufacturing_questions") or []):
            if not isinstance(_mq, Mapping) or not _mq.get("issue"):
                continue
            if str(_mq["issue"]) in _seen_q or any(
                    d.get("issue") == _mq["issue"] for d in decisions):
                continue
            _seen_q.add(str(_mq["issue"]))
            _dq = _question_decision(part, _mq)
            if _dq is not None:
                decisions.append(_dq)

    for part in job_parts(source):
        if not isinstance(part, Mapping):
            continue
        _priced_assembly(part)
        _gap = part.get("route_gap")
        if isinstance(_gap, Mapping) and _gap.get("issue"):
            _line = _by_pn.get(str(part.get("part_number") or "").upper())
            decisions.append({
                "part": str(part.get("part_number") or ""), "kind": "manufacturing_decision",
                "issue": str(_gap.get("issue")), "assumption": str(_gap.get("assumption") or ""),
                "action": str(_gap.get("action") or ""), "owner": "estimator",
                "gbp_at_stake": (_money_of(_line) if _line is not None else None) or None})
        # A READER'S OPEN QUESTION IS A DECISION (D-382). A reader that finds evidence it
        # cannot settle — a parent finished one way over members stated welded — leaves the
        # money as the route had it and asks; the question is counted here like any other.
        _questions_of(part)
        _ov = part.get("block_overflow")
        if isinstance(_ov, Mapping) and _ov.get("basis") == "net_part_provisional":
            _line = _by_pn.get(str(part.get("part_number") or "").upper())
            decisions.append({
                "part": str(part.get("part_number") or ""), "kind": "provisional_price",
                "issue": (f"{part.get('part_number')} did not fit the {_ov.get('block')} block "
                          f"and is on the Bill of Materials at the engine's own figure"),
                "assumption": "the engine's sheet and yield, not the block's nest",
                "action": ("nest it by hand and replace the line's price, or widen the block "
                           "in the template"),
                "owner": "estimator",
                "gbp_at_stake": (_money_of(_line) if _line is not None else None) or None})
        _tc = thickness_conflict(part, boilerplate_mm=_boiler)
        if _tc:
            _line = _by_pn.get(str(part.get("part_number") or "").upper())
            if _line is not None:
                _tc["gbp_at_stake"] = _money_of(_line) or None
            decisions.append(_tc)
        # A LINEAR PART WITH NO LENGTH IS A DECISION, NOT A FLAG.
        #
        # On round or section stock the LENGTH IS THE MONEY: it multiplies the rate directly,
        # so an absent one and a zero look identical in a total. The estimator already assumes
        # a developed length by form band and marks the line INDICATIVE — which is the right
        # costing behaviour and the wrong REPORTING behaviour, because a review flag is not a
        # decision and nothing made an estimator answer it. MBY432 on 0359342 is Ø8 x 219.6
        # printed on its own detail sheet, against an assumed 900 mm band: four times the mass,
        # 56 off. The assumption is defensible; leaving it unasked is not.
        _mat_est = part.get("material_estimate") or {}
        _cost_method = str(_mat_est.get("cost_method") or "")
        if "assumed_length" in _cost_method:
            _line = _by_pn.get(str(part.get("part_number") or "").upper())
            _gauge = _mat_est.get("wire_gauge_mm") or part.get("wire_gauge_mm")
            decisions.append({
                "part": str(part.get("part_number") or ""),
                "kind": "manufacturing_decision",
                "issue": (f"Cut length of {part.get('part_number')} is not known — it is "
                          f"round/section stock priced per metre, so the length is the money"),
                "assumption": (f"an assumed developed length of "
                               f"{_mat_est.get('blank_length_mm') or '?'} mm"
                               + (f" on Ø{_gauge:g}" if isinstance(_gauge, (int, float))
                                  else "")
                               + " — a band by form, not a reading. No length is inferred "
                                 "from a drawing outline"),
                "action": ("state the cut length from the part's own detail sheet, or "
                           "confirm the assumed band"),
                "owner": "estimator",
                "gbp_at_stake": (_money_of(_line) if _line is not None else None) or None,
            })

        for _bc in (part.get("_bom_numeric_conflicts") or []):
            if not isinstance(_bc, Mapping):
                continue
            # A CONFLICT A PERSON HAS SETTLED IS NOT A DECISION TO RE-ASK. The tape's two
            # BOM statements read LENGTH: 200.00 and 220.00; Howard picked 200 and the
            # answers file stamped it. When the confirmed length matches the KEPT reading,
            # the pick has been made — asking again on every run is how the list dies.
            _conf = part.get("confirmed_piece_length_mm")
            if _conf is not None:
                _mk = re.search(r"LENGTH:\s*([0-9.]+)", str(_bc.get("kept") or ""))
                try:
                    if _mk and abs(float(_mk.group(1)) - float(_conf)) <= 0.5:
                        continue
                except (TypeError, ValueError):
                    pass
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
    # The sheet's list drops an assembly that has no line of its own — which is exactly the
    # case being looked for — so the write-up's own records are checked as well.
    _seen_parts = {str(p.get("part_number") or "").upper() for p in job_parts(source)
                   if isinstance(p, Mapping)}
    for part in (((source.get("manufacturing_writeup") or {}).get("parts") or [])
                 if isinstance(source, Mapping) else []):
        if isinstance(part, Mapping) and str(part.get("part_number") or "").upper() \
                not in _seen_parts:
            _priced_assembly(part)
            # An assembly with no line of its own still carries the questions its readers left.
            _questions_of(part)
    # ── HOW A PLASTIC ASSEMBLY IS JOINED IS A PERSON'S CALL ──────────────────────
    # 12633-00-GA review: "three glue charges should not be added merely because there are
    # three GAs. Confirm the joining method for each assembly." The engine costs one bonding
    # event (glue + flame polish) wherever a plastic assembly is welded or holds loose panels
    # and no fixings; that is a working assumption, so it is one decision naming every
    # assembly it was made for, not a flag per record.
    _bonded: List[str] = []
    _seen_b: set = set()
    for _bp in list(job_parts(source)) + list(
            ((source.get("manufacturing_writeup") or {}).get("parts") or [])
            if isinstance(source, Mapping) else []):
        if isinstance(_bp, Mapping) and _bp.get("acrylic_bonded"):
            _k = str(_bp.get("bonded_for_assembly") or _bp.get("part_number") or "")
            if _k and _k.upper() not in _seen_b:
                _seen_b.add(_k.upper())
                _bonded.append(_k)
    if _bonded:
        decisions.append({
            "part": ", ".join(_bonded), "kind": "manufacturing_decision",
            "issue": (f"How {', '.join(_bonded)} {'is' if len(_bonded) == 1 else 'are'} "
                      f"joined"),
            "assumption": ("one bonding event each (Glue, with the flame-polish that goes with "
                           "it) — no drawing states the joint"),
            "action": ("confirm per assembly: solvent cement, adhesive, or a push/tab fit "
                       "with no glue; drop the glue rows where it is not bonded"),
            "owner": "estimator", "gbp_at_stake": None})

    # ── A WELD THE ENGINE INFERRED IS PRICED, AND PUT TO A PERSON ────────────────
    # 12614-01-GA (26 Sep): the header case was welded and dressed on the extract's own
    # inference ("case shown as single fabricated unit") with no weld note or symbol — £48.98
    # a unit. James Gray: "we've said it's inferred so it should be priced. We always aim to
    # price everything. Our inference is always based on logic." So it stays on the sheet, and
    # the estimator is asked, with the money it carries, rather than finding it in a column
    # (D-258).
    _shadow_d = (((source.get("estimate_summary") or {}).get("canonical_route_shadow") or {})
                 .get("decisions") or []) if isinstance(source, Mapping) else []
    _guessed: Dict[str, Mapping[str, Any]] = {}
    for _d in _shadow_d:
        if (isinstance(_d, Mapping) and _d.get("status") == "required"
                and str(_d.get("operation") or "") in ("welding", "spot_welding")
                and str(_d.get("source") or "").strip().lower() == "inference"
                and not str(_d.get("evidence") or "").strip()):
            _guessed.setdefault(str(_d.get("target_id") or ""), _d)
    # THE SENTENCE IS COMPUTED FROM THE RECORD. "no weld note or symbol on the drawing" was a
    # literal: on the 1 Oct 12173 book it sat beside the extract's own "weld symbols and frame
    # weld assembly views on pages 6-8" for three parts whose sheets draw fillet callouts. The
    # note half is what empty evidence means — the inference quotes no note; the symbol half
    # is what the reader found on the target's own sheet (weld_symbols.describe_weld_symbols),
    # with "not read" kept apart from "named none".
    try:
        from weld_symbols import describe_weld_symbols as _describe_ws
    except Exception:                                                # pragma: no cover
        _describe_ws = None
    _ws_recs: Dict[str, Mapping[str, Any]] = {}
    for _wp in list(job_parts(source)) + list(
            ((source.get("manufacturing_writeup") or {}).get("parts") or [])
            if isinstance(source, Mapping) else []):
        if isinstance(_wp, Mapping) and _wp.get("part_number"):
            _k = str(_wp.get("part_number")).upper()
            if _k not in _ws_recs or (_ws_recs[_k].get("weld_symbols") is None
                                      and _wp.get("weld_symbols") is not None):
                _ws_recs[_k] = _wp
    for _tgt, _d in _guessed.items():
        if _tgt.upper() in _weld_asked:
            continue                      # its reader already asked, with the rows' money
        _wrec = _ws_recs.get(_tgt.upper()) or {}
        _wsc = _wrec.get("weld_symbols")
        _drawn = (_describe_ws(_wsc if isinstance(_wsc, Mapping) else None,
                               _wrec.get("weld_symbol_pages") or [])
                  if _describe_ws is not None else "its own sheet was not read for weld symbols")
        _wrows = [r for r in (_workbook_rows(source) or [])
                  if {str(o) for o in (r.get("engine_operations") or [])}
                  & {"welding", "spot_welding", "dress_welds"}
                  and _tgt.upper() in {str(pn).upper() for pn in (r.get("part_numbers") or [])}]
        _w_gbp = round(sum(_num(r.get("total_value_gbp")) for r in _wrows), 2)
        _why = str(_d.get("reason") or "").strip()
        decisions.append({
            "part": _tgt, "kind": "manufacturing_decision",
            # Charged as welded AND dressed: both operations are this row's question.
            "operation": str(_d.get("operation") or "welding"),
            "operations": [str(_d.get("operation") or "welding"), "dress_welds"],
            "issue": f"Welding on {_tgt} is inferred, not drawn",
            "assumption": (f"charged as welded and dressed"
                           f"{f' (£{_w_gbp:,.2f} a unit)' if _w_gbp else ''}"
                           f"{f' — {_why}' if _why else ''}; the inference quotes no weld "
                           f"note from the drawing, and {_drawn}"),
            "action": ("confirm it is welded; if it is assembled mechanically (studs, "
                       "nutserts, screws), replace the Weld and Dress rows with the "
                       "mechanical joining labour, rather than only removing them"),
            "owner": "estimator", "gbp_at_stake": _w_gbp or None})

    # ── A LEAF WELD WITHHELD FOR WANT OF EVIDENCE IS ASKED, WITH NOTHING CHARGED (D-385) ──
    # The route compiler leaves such a decision on the record as not applicable with the
    # reason; the question is a person's — put the weld back if the leaf is welded itself.
    _withheld: Dict[str, List[str]] = {}
    for _d in _shadow_d:
        if (isinstance(_d, Mapping) and str(_d.get("status") or "") == "not_applicable"
                and str((_d.get("field_provenance") or {}).get("status") or "")
                == "evidenceless_leaf_weld_withheld"):
            _withheld.setdefault(str(_d.get("target_id") or ""), []).append(
                str(_d.get("operation") or ""))
    for _tgt, _ops_w in sorted(_withheld.items()):
        if not _tgt or _tgt.upper() in _weld_asked or _tgt.upper() in _guessed:
            continue
        decisions.append({
            "part": _tgt, "kind": "manufacturing_decision",
            "operation": "welding", "operations": sorted(set(_ops_w)),
            "issue": f"Is {_tgt} welded itself? Nothing on its own sheet says so",
            "assumption": (f"{' and '.join(sorted(set(_ops_w)))} NOT charged on {_tgt}: its own "
                           f"sheet shows no weld symbol, no FINISH: WELDED and no weld note, "
                           f"and the pack's weld specification says how welds are made, not "
                           f"that this part is welded; any joint is charged on the assembly "
                           f"it belongs to"),
            "action": ("if this part carries a weld of its own, say so and the Weld and Dress "
                       "rows return; if it is joined within its assembly, nothing is needed"),
            "owner": "estimator", "gbp_at_stake": None})

    # ── A MEMBER'S FINISH: WELDED UNDER A WELDED ASSEMBLY IS ONE JOINT, ASKED ONCE (D-387) ──
    # The compiler charges the joint on the assembly and leaves the member's welding and
    # dressing not applicable with the owner named; a seam weld the member carries in itself
    # is a person's to put back, with nothing charged until then.
    _moved: Dict[str, Dict[str, Any]] = {}
    for _d in _shadow_d:
        if (isinstance(_d, Mapping) and str(_d.get("status") or "") == "not_applicable"
                and str((_d.get("field_provenance") or {}).get("status") or "")
                == "member_weld_is_the_assemblys"):
            _slot = _moved.setdefault(str(_d.get("target_id") or ""), {
                "ops": [], "owner": str((_d.get("field_provenance") or {}).get("weld_owner")
                                        or "its assembly")})
            _slot["ops"].append(str(_d.get("operation") or ""))
    for _tgt, _m in sorted(_moved.items()):
        if not _tgt or _tgt.upper() in _weld_asked:
            continue
        _ops_m = sorted(set(_m["ops"]))
        decisions.append({
            "part": _tgt, "kind": "manufacturing_decision",
            "operation": "welding", "operations": _ops_m,
            "issue": (f"Is {_tgt} welded within itself, beyond its joint to {_m['owner']}? "
                      f"Its sheet states FINISH: WELDED and draws no weld"),
            "assumption": (f"{' and '.join(_ops_m)} NOT charged on {_tgt}: the one joint is "
                           f"charged on {_m['owner']}, which is welded on its own evidence; "
                           f"the member's FINISH: WELDED says how it leaves the shop, not that "
                           f"it is a weldment in itself"),
            "action": ("if this part carries a seam or tab weld of its own, say so and its "
                       "Weld and Dress rows return; if it is only welded into the assembly, "
                       "nothing is needed"),
            "owner": "estimator", "gbp_at_stake": None})

    # ── A JOINT CHARGED ON AN ASSEMBLY AND AGAIN ON ITS MEMBER IS ASKED, ONCE ─────────────
    # The compiler's joining_charged_on_assembly_and_member issue ("BOTH ARE CHARGED — strike
    # whichever is not real") reached a person only by riding inside the inferred-weld
    # decision's reason, so a STATED weld charged on 12173-03-202 and again on its tab 06M
    # was asked of nobody, while the consistency check printed it as "could not be run". It
    # is a decision here, priced by the member's weld and dress rows. One per member and
    # assembly whatever operations the issue names; none where the member's inferred-weld
    # decision already carries it, or its reader already asked about its weld.
    _inferred_asked = {str(d.get("part") or "").upper() for d in decisions
                       if str(d.get("issue") or "").startswith("Welding on ")
                       and str(d.get("issue") or "").endswith("is inferred, not drawn")}
    _joints: Dict[Tuple[str, str], Set[str]] = {}
    for _iss in _shadow_issues:
        if isinstance(_iss, Mapping) \
                and str(_iss.get("code")) == "joining_charged_on_assembly_and_member":
            _joints.setdefault((str(_iss.get("assembly") or ""), str(_iss.get("member") or "")),
                               set()).add(str(_iss.get("operation") or ""))
    _joint_asked: Set[Tuple[str, str]] = set()
    for (_asm, _mem), _ops_j in sorted(_joints.items()):
        if not _asm or not _mem:
            continue
        _joint_asked.add((_asm.upper(), _mem.upper()))
        if _mem.upper() in _inferred_asked or _mem.upper() in _weld_asked:
            continue
        _jrows = [r for r in (_workbook_rows(source) or [])
                  if {str(o) for o in (r.get("engine_operations") or [])}
                  & {"welding", "spot_welding", "dress_welds"}
                  and _mem.upper() in {str(pn).upper() for pn in (r.get("part_numbers") or [])}]
        _j_gbp = round(sum(_num(r.get("total_value_gbp")) for r in _jrows), 2)
        _j_nums = [str(r.get("workbook_row")) for r in _jrows if r.get("workbook_row")]
        decisions.append({
            "part": _mem, "kind": "manufacturing_decision",
            # The pair and the operations, as fields: the overlap check's ruling on this
            # assembly and operation is this question, netted onto it (below).
            "assembly": _asm, "operations": sorted(o for o in _ops_j if o),
            "issue": (f"{' and '.join(sorted(o.replace('_', ' ') for o in _ops_j if o))} "
                      f"charged on {_asm} and again on its member {_mem}"),
            "assumption": (f"both charged"
                           + (f" (£{_j_gbp:,.2f} a unit on {_mem}"
                              + (f", Estimate row{'s' if len(_j_nums) > 1 else ''} "
                                 f"{', '.join(_j_nums)}" if _j_nums else "") + ")"
                              if _j_gbp else "")
                           + " — one joint charged twice, or the assembly's joint plus the "
                             "member's own weld; the drawings read do not tell them apart"),
            "action": (f"read the joint on {_asm}'s sheet: if it is the weld that joins {_mem} "
                       f"to its siblings, strike one charge; if {_mem} has a weld of its own, "
                       f"confirm both"),
            "owner": "estimator", "gbp_at_stake": _j_gbp or None})

    # ── AN OPERATION ON AN ASSEMBLY AND AGAIN ON SOMETHING IT CONTAINS ────────────────
    # The same overlaps the consistency check reports (one helper), asked here unless the
    # compiler's own question already puts that pair to a person: a coat before AND after
    # assembly is real, so is one item twice, and only a person can tell.
    try:
        _overlaps = parent_child_overlaps(source) or []
    except Exception:                                                # noqa: BLE001
        _overlaps = []
    for _ov in _overlaps:
        if _ov.get("asked"):
            continue
        _asm = str(_ov.get("assembly") or "")
        _kids = [str(k) for k in (_ov.get("descendants") or [])
                 if (_asm.upper(), str(k).upper()) not in _joint_asked]
        if not _asm or not _kids:
            continue
        _op_o = str(_ov.get("operation") or "")
        _orows = [r for r in (_workbook_rows(source) or [])
                  if _op_o in {str(o) for o in _row_engine_ops(r)}
                  and {str(pn).upper() for pn in (r.get("part_numbers") or [])}
                  & {k.upper() for k in _kids}]
        _o_gbp = round(sum(_num(r.get("total_value_gbp")) for r in _orows), 2)
        _o_issue = (f"{_op_o.replace('_', ' ')} is charged on {_asm} and again on "
                    f"{', '.join(_kids)}, which {_asm} contains")
        if any(d.get("issue") == _o_issue for d in decisions):
            continue
        decisions.append({
            "part": _asm, "kind": "manufacturing_decision", "issue": _o_issue,
            # The operation, as a field: the overlap check's ruling nets onto this row by it.
            "operation": _op_o,
            "assumption": ("both charged"
                           + (f" (£{_o_gbp:,.2f} a unit on the rows that carry "
                              f"{', '.join(_kids)})" if _o_gbp else "")
                           + f" — decisions {', '.join(_ov.get('decision_ids') or [])}"),
            "action": ("say whether this is done before AND after assembly (two real events) "
                       "or once — strike the charge that is not real"),
            "owner": "estimator", "gbp_at_stake": _o_gbp or None})

    # ── A LINE COSTED AT A QUANTITY ITS OWN BOM ROW DOES NOT STATE ────────────────
    # 12312-01-GA: the driver, LED tape, power cord and Y-splitter each stated 1 and were
    # costed at 2, reached once through the lighting assembly and once from the GA's table.
    # Comparing a row's stated count with its costed count is mechanical, so it is asked here
    # rather than left in a column. A count multiplied down ONE route (2 per sub-assembly, 3
    # sub-assemblies) is the cascade doing its job and is not asked; two routes, or none that
    # explains it, is.
    for _ident, _node in sorted(nodes.items()):
        _line = _by_pn.get(_ident)
        if _line is None:
            continue
        try:
            _own = float(_node.get("qty_own"))
            _eff = float(_node.get("qty_per_unit"))
        except (TypeError, ValueError):
            continue
        _trails = [str(t) for t in (_node.get("qty_trail") or []) if t]
        if abs(_own - _eff) < 1e-9:
            # COUNTED ONCE IS A JUDGEMENT, SO IT IS ASKED. route_compiler drops a table's row
            # for a part its listed sub-assembly already holds at the same count — right for a
            # repeated description, wrong for a genuine spare the table adds. Equal counts
            # cannot tell the two apart; a person can.
            _qn = str(_node.get("qty_note") or "")
            if "counted once" in _qn:
                # £ WHERE KNOWN: the model's whole-product count is on the record (the TWO
                # ROADS check reads the same field). 12645: 120 bolts costed, the model 136.
                _prec = next((p for p in job_parts(source)
                              if str(p.get("part_number") or "").upper() == _ident), {})
                _tot = _num(_prec.get("quantity_total_per_unit"))
                _each_q = _money_of(_line) / _eff if _eff else 0.0
                decisions.append({
                    "part": _line["part_number"], "kind": "quantity_check",
                    "issue": (f"{_line['part_number']}: listed twice (a table and a "
                              f"sub-assembly) and costed once, at {_eff:g}"),
                    "assumption": _qn,
                    "action": ("confirm it is one item described twice — or, if the table "
                               "adds a spare or second item, raise the line"),
                    "owner": "estimator",
                    "gbp_at_stake": (round(abs(_tot - _eff) * _each_q, 2)
                                     if _tot and _each_q and abs(_tot - _eff) > 1e-9 else None)})
            continue
        if len(_trails) == 1 and not str(_node.get("qty_note") or ""):
            continue
        _each = _money_of(_line) / _eff if _eff else 0.0
        decisions.append({
            "part": _line["part_number"], "kind": "quantity_check",
            "issue": (f"{_line['part_number']}: its BOM row states {_own:g}, the sheet costs "
                      f"{_eff:g}"),
            "assumption": ("; ".join(_trails) if _trails else "no route recorded")
                          + (f" — {_node.get('qty_note')}" if _node.get("qty_note") else ""),
            "action": (f"confirm {_eff:g} per unit, or correct the line to {_own:g}"
                       + (f" (£{abs(_eff - _own) * _each:,.2f} a unit at the sheet's price)"
                          if _each else "")),
            "owner": "estimator", "gbp_at_stake": round(abs(_eff - _own) * _each, 2) or None})
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
            "issue": f"{l['part_number']} rests on a researched market price",
            "assumption": l["price_origin"]["label"],
            "action": "replace it with a catalogue or supplier price — it moves between runs",
            "owner": "estimator", "gbp_at_stake": _money_of(l)})

    # ── WHAT THE CHECKS FOUND, AS ROWS OF THE ONE RECORD ──────────────────────────
    # 12173-02, 1 Oct 2026: "25 to settle: 2 + 1 + 7 + 10 + 5 + 11" — a headline of 25 rows
    # over a phrase adding to 36, because eleven failing checks and the render's assumed
    # sizes were counts kept beside the list, not rows of it; and when nothing else was
    # open the banner read "0 to settle: 1 consistency check failing" over a table saying
    # "not itemised here". Every counted item is now a row, so the headline, the phrase and
    # the table are one count by construction.
    inv = source.get("invariants") if isinstance(source.get("invariants"), dict) else None
    _viol = [v for v in ((inv or {}).get("violations") or []) if isinstance(v, Mapping)]
    _blocking_v = [v for v in _viol if v.get("severity") == "blocking"]
    _unverified_v = [v for v in _viol if v.get("severity") == "unverified"]
    # A RULING BY ITS MARKER, AT WHATEVER SEVERITY THE CHECK GAVE IT (invariants.check_job
    # splits them the same way): the parent-and-child overlap is a WARNING that needs one.
    _ruling_v = [v for v in _viol if v.get("severity") in ("unverified", "warning")
                 and isinstance(v.get("detail"), Mapping) and v["detail"].get("needs_ruling")]
    try:
        import config as _cfg_owner                                  # noqa: PLC0415
        _owner_of = dict(getattr(_cfg_owner, "CONSISTENCY_CHECK_OWNER", {}) or {})
        _owner_default = str(getattr(_cfg_owner, "CONSISTENCY_CHECK_OWNER_DEFAULT", "")
                             or "estimator")
    except Exception:                                                # noqa: BLE001
        _owner_of, _owner_default = {}, "estimator"

    def _first_sentence(v: Mapping[str, Any]) -> str:
        msg = str(v.get("message") or v.get("code") or "").strip()
        return re.split(r"(?<=\.)\s", msg, 1)[0]

    # A BLOCKING CHECK IS NETTED ONLY WHERE IT ASKS THE SAME QUESTION AS A ROW (D-324). The
    # reached-item check and the missing-price row are one walk, so the check adds nothing.
    # Netting by identity alone dropped ANY check whose parts were named by ANY row — an
    # engine fault naming a market-figure part would have vanished from the tally.
    _CHECK_ITEMISED_AS = {"reached_bom_item_unaccounted": frozenset({"missing_price"})}

    def _already_itemised(v: Mapping[str, Any]) -> bool:
        kinds = _CHECK_ITEMISED_AS.get(str(v.get("code") or ""))
        det = v.get("detail") if isinstance(v.get("detail"), Mapping) else {}
        ids = {str(i).strip().upper() for i in (v.get("identities") or det.get("identities")
                                                 or []) if str(i).strip()}
        if not kinds or not ids:
            return False
        rows = [d for d in decisions if d.get("kind") in kinds
                and str(d.get("part") or "").strip().upper() in ids]
        if {str(d.get("part") or "").strip().upper() for d in rows} < ids:
            return False
        for d in rows:
            d["also_failing_check"] = str(v.get("code") or "")
        return True

    for v in _blocking_v:
        if _already_itemised(v):
            continue
        det = v.get("detail") if isinstance(v.get("detail"), Mapping) else {}
        code = str(v.get("code") or "")
        decisions.append({
            "part": str(det.get("target_id") or det.get("assembly") or det.get("part_number")
                        or ", ".join(str(i) for i in (det.get("identities") or [])[:6])
                        or code),
            "kind": "consistency_check", "check_code": code,
            "issue": _first_sentence(v),
            "assumption": "the sheet stands as built; the figure this check guards is "
                          "unconfirmed",
            "action": f"resolve it, or record why it does not apply (Consistency checks: {code})",
            "owner": str(_owner_of.get(code) or _owner_default), "gbp_at_stake": None})

    # A FINDING THAT NEEDS A RULING IS A QUESTION, AND A ROW (12173-02: twenty of them sat in
    # no tally, labelled "could not be run"). Where a manufacturing decision already asks the
    # same question — the same part, the same operation, as FIELDS — the ruling is that row's
    # and is marked on it; otherwise it is a row of its own. No money is added or removed.
    #
    # THE PAIR, NOT ONLY THE PARENT. A parent-and-child overlap is asked on the assembly by
    # the overlap decision (or the powder-scope one), but a JOINT charged on both levels is
    # asked on the member — the joining decision, or the member's own inferred-weld or weld
    # question that stands in for it (12173-03-202 and its tab 06M). A row on a member the
    # ruling names, carrying the operation, and naming this assembly or none, asks the same
    # pair. The assembly's own row is preferred where both exist.
    def _row_covers(d: Mapping[str, Any], part: str, op: str,
                    kids: frozenset = frozenset()) -> bool:
        if d.get("kind") != "manufacturing_decision" or not op:
            return False
        if not (op == str(d.get("operation") or "")
                or op in [str(o) for o in (d.get("operations") or [])]):
            return False
        _p = str(d.get("part") or "").strip().upper()
        if _p == part:
            return True
        return (_p in kids
                and str(d.get("assembly") or "").strip().upper() in ("", part))

    _ruling_netted = 0
    for v in _ruling_v:
        det = v["detail"]
        _asm = str(det.get("assembly") or "").strip()
        _op = str(det.get("operation") or "").strip()
        _kids = frozenset(str(k).strip().upper() for k in (det.get("descendants") or [])
                          if str(k).strip())
        _hit = (next((d for d in decisions if _row_covers(d, _asm.upper(), _op)), None)
                or next((d for d in decisions
                         if _row_covers(d, _asm.upper(), _op, _kids)), None))
        if _hit is not None:
            _hit["also_ruled_by_check"] = str(v.get("code") or "")
            _ruling_netted += 1
            continue
        decisions.append({
            "part": _asm or str(v.get("code") or ""), "kind": "ruling",
            "operation": _op, "check_code": str(v.get("code") or ""),
            "issue": _first_sentence(v),
            "assumption": "both levels stay charged as the route has them",
            "action": "rule: two real events, or strike one of the charges",
            "owner": "estimator", "gbp_at_stake": None})

    # A SIZE READ OFF A PICTURE IS A ROW (D-356 counted it beside the list, never in it).
    for _pn, _flag in _parts_sized_from_a_render_with_flags(source):
        decisions.append({
            "part": _pn, "kind": "size_assumed",
            "issue": f"{_pn}: size assumed from a render, not measured",
            "assumption": _flag or "the size sighted on the render is the size costed",
            "action": "confirm the size from a drawing or a model",
            "owner": "estimator", "gbp_at_stake": None})

    # WORST FIRST, ONCE, HERE. Every surface lists the record in this order.
    decisions.sort(key=lambda d: (decision_kind(d.get("kind"))[2],
                                  -_num(d.get("gbp_at_stake"))))

    # ── A RUN THAT PRODUCED NOTHING TO COST IS THE FIRST ROW AND THE WHOLE HEADLINE (D-409) ──
    # 12675-01, 8 Oct 2026: the scan stopped the run (design-intent sheets, no part) and this
    # record went on to list two market figures to replace and a failing BOM check — true rows
    # about an empty book, with the one fact that explained them written nowhere. The stop is a
    # row of the one tally, so the banner, the Decisions table, the verdict and the quote's
    # blocking list all say it, in the same words, first.
    try:
        from run_stop import (nothing_to_cost as _nothing_to_cost, sentence as _stop_sentence,
                              doors as _stop_doors)
        _stop = _nothing_to_cost(source)
    except Exception:                                                # noqa: BLE001
        _stop = None
    if _stop:
        _why_doors = _stop_doors(_stop)
        decisions.insert(0, {
            "part": "—", "kind": "nothing_to_cost",
            "issue": f"Nothing to cost: {_stop.get('short') or _stop.get('kind')}",
            "assumption": (f"no part was costed — {_why_doors}" if _why_doors else
                           "no part was costed, so no figure on the sheet is a price"),
            "action": (_stop.get("next_step")
                       or "answer the pack with the method the stop names, then re-run"),
            "owner": "estimator / Design", "gbp_at_stake": None})
    # ── release status ──────────────────────────────────────────────────────────
    _checks = [d for d in decisions if d["kind"] == "consistency_check"]
    _rulings = [d for d in decisions if d["kind"] == "ruling"]
    _assumed = [d for d in decisions if d["kind"] == "size_assumed"]
    _ruling_ids = {id(v) for v in _ruling_v}
    _not_run_v = [v for v in _unverified_v if id(v) not in _ruling_ids]
    try:
        _unverified_n = int((inv or {}).get("unverified"))
    except (TypeError, ValueError):
        _unverified_n = len(_unverified_v)
    _not_run_n = max(len(_not_run_v), _unverified_n - sum(
        1 for v in _ruling_v if v.get("severity") == "unverified"), 0)
    _checks_rec = {
        "checks_ran": inv is not None,
        "checks_run": len((inv or {}).get("checks_run") or []),
        "checks_failing_total": len(_blocking_v),
        "rulings_total": len(_ruling_v),
        "rulings_netted": _ruling_netted,
        "not_run": _not_run_n,
        "checks_with_findings": len({str(v.get("check") or v.get("code") or "")
                                     for v in _blocking_v + _ruling_v + _not_run_v}),
    }
    reasons: List[str] = []
    if _stop:
        reasons.append(_stop_sentence(_stop))
    if unpriced:
        reasons.append(f"{len(unpriced)} line(s) carry no price: {', '.join(gaps['unpriced'])}")
    _no_line = [d for d in decisions if d["kind"] == "missing_price"
                and "has no line on the sheet" in str(d.get("issue") or "")]
    if _no_line:
        reasons.append(f"{len(_no_line)} reached item(s) have no line at all: "
                       f"{', '.join(str(d['part']) for d in _no_line)}")
    if market:
        reasons.append(f"{len(market)} line(s) rest on a researched market price")
    if inv is not None:
        # ONE SENTENCE, WITH THE NETTING SAID (12173-02: the bullet read 12, the banner 11).
        _fc = _failing_checks_words(decisions, _checks_rec)
        if _fc["blocking_words"]:
            reasons.append(_fc["blocking_words"])
        if _fc["ruling_words"]:
            reasons.append(_fc["ruling_words"])
        if _fc["not_run_words"]:
            reasons.append(_fc["not_run_words"])
    else:
        reasons.append("the consistency checks have not run")
    if not calculated:
        reasons.append("the calculated sheet was not read back")
    manufacturing = [d for d in decisions if d["kind"] == "manufacturing_decision"]
    if manufacturing:
        reasons.append(f"{len(manufacturing)} manufacturing decision(s) open")
    _qty_checks = [d for d in decisions if d["kind"] == "quantity_check"]
    if _qty_checks:
        reasons.append(f"{len(_qty_checks)} quantity check(s) open")
    _provisional = [d for d in decisions if d["kind"] == "provisional_price"]
    if _provisional:
        reasons.append(f"{len(_provisional)} line(s) spilled from a full block at a "
                       f"provisional price")
    _stated = [d for d in decisions if d["kind"] == "stated_not_carried"]
    if _stated:
        reasons.append(f"{len(_stated)} parts-list row(s) stated and not carried")
    _off_sheet = [d for d in decisions if d["kind"] == "labour_not_on_sheet"]
    if _off_sheet:
        reasons.append(f"{len(_off_sheet)} timed operation(s) not on the sheet — the Labour "
                       f"block was full")
    if _assumed:
        reasons.append(f"{len(_assumed)} size(s) assumed from a render: "
                       f"{', '.join(str(d['part']) for d in _assumed)}")
    unpriced_all = [d for d in decisions if d["kind"] == "missing_price"]
    status = ("provisional" if (unpriced_all or _stated or _off_sheet or market or _provisional
                                or not calculated or _checks or _assumed or inv is None)
              else ("reviewable" if (house or manufacturing or _qty_checks or _rulings)
                    else "firm"))
    # DRAFT is narrower than PROVISIONAL. A quote is a draft while a person still owes it
    # something — a price, a replacement for a market guess, a manufacturing decision, a
    # blocking check to clear, a ruling, a size to confirm. "The checks have not run yet"
    # and "the sheet was not read back" keep the estimate provisional but say nothing about
    # the quote's scope; the LLM-only path already marks those runs in its own words.
    _draft_rows = [d for d in decisions if d["kind"] in _DRAFT_KINDS]
    draft = bool(_draft_rows)
    if _stop:
        status = "provisional"

    return {
        "schema": COSTED_JOB_SCHEMA,
        # The stop travels on the record, so a reader given the record alone (the HTML
        # regeneration path, the quote's blocking list) still knows the book is empty by mode.
        "run_stop": _stop or None,
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
                    # The rows a person owes before the quote is more than a draft.
                    "outstanding": len(_draft_rows),
                    # WHAT THE BANNER LEFT OUT (D-356), NOW ROWS (v2). Both values are
                    # counts OF the rows above, kept for the readers that print them.
                    "blocking_checks": len(_checks),
                    "sizes_assumed": len(_assumed),
                    "rulings": len(_rulings),
                    **_checks_rec,
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



def _parts_sized_from_a_render_with_flags(source: Any) -> List[Tuple[str, str]]:
    """(part number, the flag that says so) for every part whose size the engine took from
    a render rather than a drawing or a model — once per part, in part-number order."""
    if not isinstance(source, Mapping):
        return []
    _es = source.get("estimate_summary") if isinstance(source.get("estimate_summary"), Mapping) else {}
    _seen: Dict[str, Tuple[str, str]] = {}
    for _p in list(_es.get("part_estimates") or []) + list(source.get("parts") or []):
        if not isinstance(_p, Mapping):
            continue
        _pn = str(_p.get("part_number") or "").strip()
        if not _pn or _pn.upper() in _seen:
            continue
        _flag = next((str(f) for f in (_p.get("review_flags") or [])
                      if "size assumed from the render" in str(f).lower()), None)
        if _flag is not None:
            _seen[_pn.upper()] = (_pn, _flag.strip())
    return [_seen[k] for k in sorted(_seen)]


def _parts_sized_from_a_render(source: Any) -> List[str]:
    """The parts, sorted, whose size was assumed from a render."""
    return [pn for pn, _f in _parts_sized_from_a_render_with_flags(source)]


def _sizes_assumed_from_a_render(source: Any) -> int:
    """How many parts had their size taken from a render (a count of the set above)."""
    return len(_parts_sized_from_a_render(source))


def _failing_checks_words(decisions: List[Mapping[str, Any]],
                          rel: Mapping[str, Any]) -> Dict[str, Any]:
    """The checks' findings in their own units, with the netting said — from the record.

    12173-02 stated failing checks as 12 (the bullet, section 2, the verdict, section 13)
    and 11 (the banner, the verdict's tally, section 14) and nothing said why: one failure
    was already Decisions row 2. And "12 check(s) failed and 20 could not be run, out of 45"
    counted findings against check functions, and called twenty rulings unrun. Every one of
    those sentences is now this one, computed from the rows and the release block."""
    def _i(key: str) -> int:
        try:
            return int(rel.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    total, rulings, not_run = _i("checks_failing_total"), _i("rulings_total"), _i("not_run")
    ran, with_findings = _i("checks_run"), _i("checks_with_findings")
    added = sum(1 for d in decisions if d.get("kind") == "consistency_check")
    netted = [d for d in decisions if d.get("also_failing_check")]
    r_added = sum(1 for d in decisions if d.get("kind") == "ruling")
    r_netted = [d for d in decisions if d.get("also_ruled_by_check")]
    itemised = max(total - added, 0)
    r_itemised = max(rulings - r_added, 0)

    def _as(rows: List[Mapping[str, Any]]) -> str:
        labels = []
        for d in rows:
            lab = decision_kind(d.get("kind"))[1].lower()
            if lab not in labels:
                labels.append(lab)
        return " or ".join(f"a {x}" for x in labels) or "a decision"

    blocking_words = ""
    if total:
        blocking_words = f"{total} consistency finding(s) failed"
        if itemised:
            names = ", ".join(dict.fromkeys(str(d.get("part") or "") for d in netted)) or "—"
            blocking_words += (f" ({itemised} of them, {names}, already listed as "
                               f"{_as(netted)}, so {added} {'are' if added != 1 else 'is'} "
                               f"added to the decisions)")
    ruling_words = ""
    if rulings:
        ruling_words = f"{rulings} finding(s) need a ruling"
        if r_itemised:
            ruling_words += (f" ({r_itemised} already listed as {_as(r_netted)}, so "
                             f"{r_added} {'are' if r_added != 1 else 'is'} added)")
    not_run_words = f"{not_run} could not be run" if not_run else ""
    tail = " and ".join(w for w in (ruling_words, not_run_words) if w)
    sentence = "; ".join(w for w in (blocking_words, tail) if w)
    if sentence and ran:
        sentence += f" (from {with_findings} of the {ran} checks)"
    return {"total": total, "itemised": itemised, "added": added,
            "rulings": rulings, "rulings_itemised": r_itemised, "rulings_added": r_added,
            "not_run": not_run, "checks_run": ran, "checks_with_findings": with_findings,
            "blocking_words": blocking_words, "ruling_words": ruling_words,
            "not_run_words": not_run_words, "sentence": sentence}


def failing_checks_summary(source: Any) -> Dict[str, Any]:
    """THE ONE STATEMENT OF WHAT THE CHECKS FOUND, for every surface that prints it.

    Accepts a run summary or a built record, like outstanding_summary. On a record made
    before v2 (no rows for the checks) it falls back to the release block's own counts."""
    job = source if (isinstance(source, Mapping) and "decisions_required" in source
                     and "release" in source) else costed_job(source)
    rel = job.get("release") if isinstance(job.get("release"), Mapping) else {}
    ds = [d for d in (job.get("decisions_required") or []) if isinstance(d, Mapping)]
    if str(job.get("schema") or "") in _COUNTS_BESIDE_ROWS and "checks_failing_total" not in rel:
        rel = dict(rel, checks_failing_total=rel.get("blocking_checks") or 0)
    out = _failing_checks_words(ds, rel)
    out["checks_ran"] = bool(rel.get("checks_ran", True))
    return out


_PURCHASED_KINDS = ("bought_in", "commercial")


def _desc_key(text: Any) -> str:
    return " ".join(re.findall(r"[A-Z0-9.]+", str(text or "").upper()))


def double_count_status(source: Any, record: Optional[Mapping[str, Any]] = None
                        ) -> Dict[str, Any]:
    """WHETHER ANYTHING IS COUNTED TWICE — one answer for section 2 and the verdict.

    12173-02's section 2 said "Sound | No double-counting found ... one item under two
    invented names is caught upstream by the identity fold" while the same page carried the
    ×12 screw twice (BI-SCREW ×16 and FIXING-3.5-X12MM-PAN-HEAD ×16, same words, same
    parent) and twenty unsettled "the same item is being charged twice" findings; and the
    verdict said "nothing is counted twice". Three things are looked at:

      cross_stream     one part number costed as fabricated AND as a purchase
      same_item_pairs  two PURCHASED lines under one real parent with the same words and
                       the same count — opposite hands and settled same-article lines are
                       never a pair; lines with no parent are not grouped
      the checks       a double-count finding at BLOCKING or WARNING was FOUND; one at
                       UNVERIFIED (or a crash of a double-count check) is not established

    state: "found" | "not_established" (no checks, or one could not settle it) | "clear".
    A pair is a question for a person — nothing is ever removed on it."""
    if not isinstance(source, dict):
        return {"state": "not_established", "cross_stream": [], "same_item_pairs": [],
                "found_by_checks": [], "unrun": 0}
    try:
        from bought_in_policy import is_bought_in                    # noqa: PLC0415
    except Exception:                                                 # noqa: BLE001
        def is_bought_in(p):                                          # type: ignore
            return str(p.get("part_number") or "").upper().startswith("BI-")
    try:
        from part_code_conventions import is_mirror_code              # noqa: PLC0415
    except Exception:                                                 # noqa: BLE001
        def is_mirror_code(_c):                                       # type: ignore
            return False
    try:
        from invariants import DOUBLE_COUNT_CODES, DOUBLE_COUNT_CHECKS  # noqa: PLC0415
    except Exception:                                                 # noqa: BLE001
        DOUBLE_COUNT_CODES, DOUBLE_COUNT_CHECKS = frozenset(), frozenset()
    rec = record if isinstance(record, Mapping) and "lines" in record else costed_job(source)
    nodes = _canonical_nodes(source)
    # CROSS-STREAM: the population every surface costs, asked of the make/buy authority.
    parts = [p for p in job_parts(source) if isinstance(p, Mapping)]
    _fab = {str(p.get("part_number") or "").strip().upper()
            for p in parts if not is_bought_in(dict(p))} - {""}
    _bi = {str(p.get("part_number") or "").strip().upper()
           for p in parts if is_bought_in(dict(p))} - {""}
    cross = sorted(_fab & _bi)
    # SAME ITEM, TWO LINES: purchased lines only, grouped under a real parent.
    groups: Dict[Tuple[str, str, Any], Dict[str, Mapping[str, Any]]] = {}
    for l in rec.get("lines") or []:
        if not isinstance(l, Mapping) or l.get("kind") not in _PURCHASED_KINDS:
            continue
        if str((l.get("price_origin") or {}).get("class") or "") == "same_article":
            continue
        _ident = str(l.get("identity") or l.get("part_number") or "").strip().upper()
        _dk = _desc_key(l.get("description"))
        if not _ident or not _dk or is_mirror_code(_ident):
            continue
        _parents = (nodes.get(_ident) or {}).get("parents") or []
        if isinstance(_parents, Mapping):
            _parents = list(_parents)
        for _par in _parents:
            if str(_par or "").strip():
                groups.setdefault((str(_par).strip().upper(), _dk, l.get("qty_per_unit")),
                                  {})[_ident] = l
    pairs = [{"parent": par, "identities": sorted(ls), "qty_per_unit": q,
              "description": str(next(iter(ls.values())).get("description") or "")}
             for (par, _d, q), ls in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1],
                                                                           str(kv[0][2])))
             if len(ls) > 1]
    # THE CHECKS, by the vocabulary invariants.py owns.
    inv = source.get("invariants") if isinstance(source.get("invariants"), dict) else None
    viol = [v for v in ((inv or {}).get("violations") or []) if isinstance(v, Mapping)]

    def _check_of(v: Mapping[str, Any]) -> str:
        return str(v.get("check") or (v.get("detail") or {}).get("check") or "")
    ours = [v for v in viol if str(v.get("code") or "") in DOUBLE_COUNT_CODES
            or (v.get("code") == "check_failed" and _check_of(v) in DOUBLE_COUNT_CHECKS)]
    found_by_checks = sorted({str(v.get("code")) for v in ours
                              if str(v.get("severity") or "") in ("blocking", "warning")})
    unrun = [v for v in ours if str(v.get("severity") or "") == "unverified"]
    state = ("found" if (cross or pairs or found_by_checks)
             else "not_established" if (inv is None or unrun) else "clear")
    return {"state": state, "cross_stream": cross, "same_item_pairs": pairs,
            "found_by_checks": found_by_checks, "unrun": len(unrun)}


def bought_in_tally(source: Any, record: Optional[Mapping[str, Any]] = None
                    ) -> Dict[str, List[str]]:
    """THE BOUGHT-IN POPULATION, COUNTED ONCE, from the record's own kinds and firmness.

    12173-02's page counted one population three ways — 7 (the stream table), 12 (section 2)
    and 10 (the BOM table) — and section 2's "1 priced by an AI market estimate" sat beside a
    banner naming five bought-ins on researched market prices. Every one of those now reads
    these lists: the kind the record gives the line, and the firmness the banner reads."""
    rec = record if isinstance(record, Mapping) and "lines" in record else costed_job(source)
    lines = [l for l in (rec.get("lines") or []) if isinstance(l, Mapping)]

    def _pns(kind: str, firm: Optional[str] = None) -> List[str]:
        return [str(l.get("part_number") or "") for l in lines if l.get("kind") == kind
                and (firm is None or (l.get("price_origin") or {}).get("firmness") == firm)]
    return {"bought_in": _pns("bought_in"), "commercial": _pns("commercial"),
            "bought_in_market": _pns("bought_in", INDICATIVE_MARKET),
            "commercial_market": _pns("commercial", INDICATIVE_MARKET),
            "bought_in_unpriced": _pns("bought_in", UNPRICED)}

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
    qty = _n("quantity_check")
    prov = _n("provisional_price")
    stated = _n("stated_not_carried")
    off_sheet = _n("labour_not_on_sheet")
    rulings = _n("ruling")
    stopped = _n("nothing_to_cost")
    # FAILING CHECKS AND ASSUMED SIZES ARE ROWS (v2, 12173-02). A record saved before that
    # kept them as two counts in its release block; those are still printed AND added to
    # the headline, so even an old record's "N to settle" is the sum of its phrase.
    _rel = job.get("release") if isinstance(job.get("release"), Mapping) else {}
    legacy = 0
    if str(job.get("schema") or "") in _COUNTS_BESIDE_ROWS:
        legacy = (int(_num(_rel.get("blocking_checks")) or 0)
                  + int(_num(_rel.get("sizes_assumed")) or 0))
        _checks = int(_num(_rel.get("blocking_checks")) or 0) + _n("consistency_check")
        _assumed = int(_num(_rel.get("sizes_assumed")) or 0) + _n("size_assumed")
    else:
        _checks, _assumed = _n("consistency_check"), _n("size_assumed")
    # A kind none of the buckets recognises must still be SEEN: on the 12:28 run of
    # 7332-01 an "advisory" entry sat in the list, the headline said "7 to settle" and
    # the phrase added to 6, because total counted every row and the phrase counted four
    # kinds. The headline and the phrase are one tally or they are two lies — so every
    # row lands in a named bucket, and an unclassified kind is counted as blocking, not
    # quietly dropped: an open item nobody classified is not thereby advisory.
    other = len(ds) + legacy - (prices + market + mfg + house + qty + prov + stated
                                + off_sheet + rulings + _checks + _assumed + stopped)

    def _gbp(kind: str) -> str:
        v = sum(_num(d.get("gbp_at_stake")) for d in ds if d.get("kind") == kind)
        return f" (£{v:,.2f})" if v else ""
    bits: List[str] = []
    if stopped:
        # FIRST, because it is the fact the other bits are about (D-409).
        bits.append("nothing to cost — the run stopped before pricing")
    if prices:
        bits.append(f"{prices} price{'s' if prices != 1 else ''} missing")
    if stated:
        bits.append(f"{stated} stated row{'s' if stated != 1 else ''} not carried")
    if off_sheet:
        bits.append(f"{off_sheet} operation{'s' if off_sheet != 1 else ''} not on the sheet "
                    f"(Labour block full)")
    if market:
        bits.append(f"{market} market figure{'s' if market != 1 else ''} to replace"
                    f"{_gbp('market_figure')}")
    if mfg:
        bits.append(f"{mfg} manufacturing decision{'s' if mfg != 1 else ''}")
    if qty:
        bits.append(f"{qty} quantity check{'s' if qty != 1 else ''}")
    if prov:
        bits.append(f"{prov} provisional line{'s' if prov != 1 else ''} to nest by hand"
                    f"{_gbp('provisional_price')}")
    if house:
        bits.append(f"{house} indicative rate{'s' if house != 1 else ''} to verify")
    if rulings:
        bits.append(f"{rulings} finding{'s' if rulings != 1 else ''} to rule on")
    if _assumed:
        bits.append(f"{_assumed} size{'s' if _assumed != 1 else ''} assumed from a render")
    if _checks:
        bits.append(f"{_checks} consistency finding{'s' if _checks != 1 else ''} failed")
    if other:
        bits.append(f"{other} other open item{'s' if other != 1 else ''}")
    # A TALLY THAT COULD NOT SEE THE CHECKS SAYS SO (12173-02). The workbook banner and its
    # AI Explanation tab are written before the checks run, and printed "25 to settle" with
    # no word of the eleven failing checks the report then added. Said, not counted: the
    # headline stays the sum of the phrase.
    _unseen = ("; the consistency checks had not run when this was counted"
               if _rel.get("checks_ran") is False and bits else "")
    # AND WHAT THEY ARE, NOT ONLY HOW MANY. "4 prices missing + 1 market figure to replace +
    # 2 manufacturing decisions" is a number an estimator cannot act on: he has to open the
    # workbook and hunt for which four. Every one of those rows already knows its own part,
    # so the names are free — and a banner that says "pack & delivery, M4 screw, wood screw"
    # is a list somebody can answer in a minute, which is the whole point of sending it.
    #
    # The counts stay exactly as they were. Nothing that reads `phrase` changes; this adds a
    # second sentence for the surfaces that have room for it.
    _named: List[str] = []
    for _d in ds:
        if str(_d.get("kind") or "") == "indicative_rate":
            continue                      # advisory: named in its own line, not the blocker
        _what = str(_d.get("part") or "").strip()
        if _what and _what.upper() not in {w.upper() for w in _named}:
            _named.append(_what)
    return {
        "prices_missing": prices, "market_figures": market,
        "manufacturing": mfg, "indicative": house, "other": other,
        "provisional": prov, "stated_not_carried": stated,
        "labour_not_on_sheet": off_sheet,
        "consistency_checks": _checks, "sizes_assumed": _assumed, "rulings": rulings,
        "nothing_to_cost": stopped,
        "blocking": (prices + market + mfg + prov + stated + off_sheet + rulings + _checks
                     + _assumed + stopped + other),
        "advisory": house,
        # THE HEADLINE IS THE SUM OF THE PHRASE: every row, plus the counts an old record
        # kept beside its rows. `in_table` is how many of them the Decisions table lists.
        "total": len(ds) + legacy,
        "in_table": len(ds),
        "legacy": legacy,
        "phrase": (" + ".join(bits) + _unseen) if bits else "nothing outstanding",
        # The blocking items by name, worst first — the order `decisions_required` is
        # already sorted in.
        "open_items": _named,
        "named_phrase": (" + ".join(bits) + ": " + ", ".join(_named[:6])
                         + (f" and {len(_named) - 6} more" if len(_named) > 6 else "")
                         + _unseen
                         if bits and _named else
                         ((" + ".join(bits) + _unseen) if bits else "nothing outstanding")),
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
__all__ += ["route_operations_for_part"]
__all__ += ["costed_job", "costed_line", "record_lines", "charged_breakdown_by_material",
            "charged_material_rows_present", "packaging_is_charged", "packaging_status",
            "RESIDUAL_LABEL",
            "PRICE_ORIGIN_LABELS", "FIRM", "INDICATIVE_HOUSE", "INDICATIVE_MARKET",
            "UNPRICED", "NIL", "COSTED_JOB_SCHEMA"]
