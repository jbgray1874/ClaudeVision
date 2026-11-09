"""Each reader finding, through the build, the costing and the calculated workbook (SCRUM-194
requirement 2; the reviewer, 9 Nov 2026: "original reader findings -> built part records ->
costing -> calculated workbook cells; retain the findings before merging and filtering, including
findings that could not be assigned to a part, then audit each transition").

The findings are `summary["reader_findings"]` (reader_findings.capture, taken at scan before the
build). This module never reconstructs them from the parts: a record without them is NOT
APPLICABLE, said so, because nothing can be shown about what the reader found before the build.

Each finding gets a row with three transitions and a verdict:

    record      in_record | changed (the record holds another value, with its source) | dropped
                | held_as_operation (a hole, thread or countersink the record carries as work)
    costing     costed | changed | not_costed | n/a (work and finishes are charged, not costed)
    workbook    the drawing ledger's disposition for the matching item (charged, covered,
                excluded, unresolved, carried, corrected) | no_item | not_read_back
    verdict     PASS | CORRECTED (changed by a named source and charged) | FAIL | UNASSIGNED
                | REFERENCE (read, and not a datum to cost: a weldment's extents) | NOT TESTED

A finding with no part is UNASSIGNED and stays in the list with its page and words: the GA's
overall extents, a countersink cue on the parts list. Pure; nothing is changed.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Optional

TOL = 1.0


def _pn(v: Any) -> str:
    return " ".join(str(v or "").split()).upper()


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _same(a: Any, b: Any) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= TOL
    return bool(a) and _letters(a) == _letters(b)


def _letters(v: Any) -> str:
    return re.sub(r"[^A-Z]", "", str(v or "").upper())


def _ops(rec: Mapping[str, Any]) -> set:
    return {str(o).strip().lower() for k in ("textual_operations", "inferred_operations", "operations")
            for o in (rec.get(k) or []) if str(o).strip()}


def _record_stage(f: Mapping[str, Any], rec: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    kind, val = f.get("kind"), f.get("value")
    if rec is None:
        return {"state": "dropped", "note": "no built part record for this part"}
    ss = rec.get("section_stock") if isinstance(rec.get("section_stock"), Mapping) else {}
    ops = _ops(rec)
    if kind == "identity":
        return {"state": "in_record", "note": f"pages {rec.get('pages')}"}
    if kind == "material":
        got = (rec.get("materials") or [None])[0]
        if got and _same(val, got):
            return {"state": "in_record", "value": got}
        return {"state": "changed" if got else "dropped", "value": got,
                "note": f"source {rec.get('material_source') or rec.get('materials_source') or '?'}" if got else ""}
    if kind == "thickness":
        got = _num(rec.get("normalized_thickness_mm"))
        if got is not None and _same(val, got):
            return {"state": "in_record", "value": got}
        return {"state": "changed" if got is not None else "dropped", "value": got,
                "note": f"source {rec.get('normalized_thickness_mm_source') or rec.get('thickness_source') or '?'}" if got is not None else ""}
    if kind == "section_profile":
        got = [ss.get("a"), ss.get("b"), ss.get("t")] if ss.get("a") else None
        if got and all(_same(x, y) for x, y in zip(val or [], got)):
            return {"state": "in_record", "value": got}
        return {"state": "changed" if got else "dropped", "value": got}
    if kind == "section_callout":
        if not ss.get("a"):
            return {"state": "dropped", "note": "the record holds no section"}
        want_len = _num((val or {}).get("length_mm"))
        got_len = _num(ss.get("length_mm"))
        prof_ok = all(_same((val or {}).get(k), ss.get(k)) for k in ("a", "b", "t"))
        if not prof_ok:
            return {"state": "changed", "value": {k: ss.get(k) for k in ("a", "b", "t")},
                    "note": "another profile on the record"}
        if want_len is not None and got_len is not None and not _same(want_len, got_len):
            return {"state": "changed", "value": got_len,
                    "note": f"length {got_len:g} by {ss.get('length_source') or '?'} ({ss.get('length_printed') or ''})".strip()}
        return {"state": "in_record", "value": {k: ss.get(k) for k in ("a", "b", "t", "length_mm", "cut_lengths_mm") if ss.get(k) is not None}}
    if kind == "overall":
        vals = sorted((_num(v) for v in (val or [])), key=lambda x: -(x or 0))
        vals = [v for v in vals if v is not None]
        if ss.get("a"):
            pieces = ss.get("cut_lengths_mm") or []
            if isinstance(pieces, list) and len(pieces) > 1:
                return {"state": "reference", "value": pieces,
                        "note": "a weldment's overall extents; its stock is the cut list"}
            got = _num(ss.get("length_mm"))
            if got is not None and vals and _same(vals[0], got):
                return {"state": "in_record", "value": got, "note": f"as the section's length ({ss.get('length_source') or '?'})"}
            return {"state": "changed" if got is not None else "dropped", "value": got,
                    "note": f"length by {ss.get('length_source') or '?'}" if got is not None else ""}
        bl, bw = _num(rec.get("blank_length_mm")), _num(rec.get("blank_width_mm"))
        if len(vals) == 2 and bl is not None and bw is not None and _same(vals[0], bl) and _same(vals[1], bw):
            return {"state": "in_record", "value": [bl, bw], "note": f"blank by {rec.get('blank_length_mm_source') or '?'}"}
        if bl is None and bw is None:
            return {"state": "dropped", "note": "no blank on the record" + (
                "; three or more overall figures are not a flat blank" if len(vals) >= 3 else "")}
        return {"state": "changed", "value": [bl, bw], "note": f"blank by {rec.get('blank_length_mm_source') or '?'}"}
    if kind == "hole":
        held = ops & {"hole_machining", "drilling", "punching", "laser_cutting", "holes"}
        return ({"state": "held_as_operation", "value": sorted(held)} if held else
                {"state": "dropped", "note": "no operation on the record carries its holes"})
    if kind == "countersink":
        return ({"state": "held_as_operation", "value": ["countersinking"]} if "countersinking" in ops else
                {"state": "dropped", "note": "countersinking is not on the record"})
    if kind == "thread":
        if "tapping" in ops:
            ev = (rec.get("operation_evidence") or {}).get("tapping") if isinstance(rec.get("operation_evidence"), Mapping) else None
            return {"state": "held_as_operation", "value": ["tapping"], "note": f"words {ev!r}" if ev else "no words kept"}
        return {"state": "dropped", "note": "tapping is not on the record"}
    if kind == "operation":
        return ({"state": "in_record", "value": val} if str(val).lower() in ops else
                {"state": "dropped", "note": f"{val} is not on the record"})
    if kind == "finish":
        try:
            import finish_rules as fr
            fams = fr.finish_families(fr.stated_finish(rec))
        except Exception:                                            # noqa: BLE001
            fams = set()
        if val in fams:
            return {"state": "in_record", "value": sorted(fams)}
        return {"state": "changed" if fams else "dropped", "value": sorted(fams),
                "note": f"source {rec.get('finish_source') or '?'}" if fams else ""}
    if kind == "bom_row":
        q = _num((val or {}).get("quantity"))
        got = _num(rec.get("quantity"))
        if q is not None and got is not None and not _same(q, got):
            return {"state": "changed", "value": got, "note": f"quantity by {rec.get('quantity_source') or '?'}"}
        return {"state": "in_record", "value": got}
    return {"state": "in_record", "note": "recorded as read"}


def _costing_stage(f: Mapping[str, Any], cost: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    kind, val = f.get("kind"), f.get("value")
    if kind in ("hole", "countersink", "thread", "operation", "finish", "identity"):
        return {"state": "n/a", "note": "charged as work, not costed as a datum"}
    if cost is None:
        return {"state": "not_costed", "note": "no costed record"}
    ss = cost.get("section_stock") if isinstance(cost.get("section_stock"), Mapping) else {}
    if kind == "material":
        got = cost.get("normalized_material") or cost.get("material_priced_as")
        return {"state": "costed" if got and _same(val, got) else ("changed" if got else "not_costed"),
                "value": got, "note": f"source {cost.get('material_source') or '?'}"}
    if kind == "thickness":
        got = _num(cost.get("normalized_thickness_mm"))
        return {"state": "costed" if got is not None and _same(val, got) else ("changed" if got is not None else "not_costed"),
                "value": got}
    if kind in ("section_profile", "section_callout"):
        if not ss.get("a"):
            return {"state": "not_costed", "note": "no section on the costed record"}
        prof = val if kind == "section_profile" else [(val or {}).get("a"), (val or {}).get("b"), (val or {}).get("t")]
        ok = all(_same(x, ss.get(k)) for x, k in zip(prof or [], ("a", "b", "t")))
        return {"state": "costed" if ok else "changed",
                "value": {k: ss.get(k) for k in ("a", "b", "t", "length_mm") if ss.get(k) is not None}}
    if kind == "overall":
        vals = [v for v in sorted((_num(v) for v in (val or [])), key=lambda x: -(x or 0)) if v is not None]
        if ss.get("a"):
            if isinstance(ss.get("cut_lengths_mm"), list) and len(ss.get("cut_lengths_mm") or []) > 1:
                return {"state": "n/a", "note": "a weldment's extents; the cut list is costed"}
            got = _num(ss.get("length_mm"))
            return {"state": "costed" if got is not None and vals and _same(vals[0], got) else ("changed" if got is not None else "not_costed"), "value": got}
        bl, bw = _num(cost.get("blank_length_mm")), _num(cost.get("blank_width_mm"))
        if bl is None and bw is None:
            return {"state": "not_costed", "note": "no blank on the costed record"}
        ok = len(vals) == 2 and bl is not None and bw is not None and _same(vals[0], bl) and _same(vals[1], bw)
        return {"state": "costed" if ok else "changed", "value": [bl, bw]}
    if kind == "bom_row":
        q, got = _num((val or {}).get("quantity")), _num(cost.get("quantity"))
        return {"state": "costed" if q is not None and got is not None and _same(q, got) else ("changed" if got is not None else "not_costed"),
                "value": got}
    return {"state": "n/a"}


_LEDGER_SUFFIX = {"material": ".material", "thickness": ".size", "bom_row": ".quantity",
                  "section_profile": ".section", "section_callout": ".section", "finish": ".finish",
                  "thread": ".op.tapping", "countersink": ".op.countersinking"}


def _workbook_stage(f: Mapping[str, Any], rec: Optional[Mapping[str, Any]],
                    items: Mapping[str, Mapping[str, Any]], read_back: bool) -> Dict[str, Any]:
    if not read_back:
        return {"state": "not_read_back"}
    pn = _pn(f.get("part"))
    kind = f.get("kind")
    part_items = {k: v for k, v in items.items() if _pn(v.get("record")) == pn}
    if not part_items:
        return {"state": "no_item", "note": "the drawing ledger holds nothing for this part"}
    if kind == "identity":
        it = next((v for k, v in part_items.items() if v.get("kind") == "part"), None)
    elif kind == "overall":
        ss = (rec or {}).get("section_stock") if isinstance((rec or {}).get("section_stock"), Mapping) else {}
        suf = ".section" if ss.get("a") else ".size"
        it = next((v for k, v in part_items.items() if k.endswith(suf)), None)
    elif kind == "operation":
        it = next((v for k, v in part_items.items() if k.endswith(f".op.{str(f.get('value')).lower()}")), None)
    elif kind == "hole":
        it = next((v for k, v in part_items.items() if k.endswith((".op.hole_machining", ".op.drilling"))), None)
    else:
        suf = _LEDGER_SUFFIX.get(str(kind))
        it = next((v for k, v in part_items.items() if suf and k.endswith(suf)), None)
    if it is None:
        return {"state": "no_item", "note": "no ledger item of this kind for the part"}
    return {"state": it.get("state"), "how": it.get("how"), "cells": it.get("cells") or [], "item": it.get("id")}


def _verdict(rec_s: str, cost_s: str, wb_s: str, part: Any) -> str:
    if not part:
        return "UNASSIGNED"
    if wb_s == "not_read_back":
        return "NOT TESTED"
    if rec_s == "reference":
        return "REFERENCE"
    if rec_s == "dropped" or cost_s == "not_costed":
        return "FAIL"
    if wb_s in ("unresolved", "no_item"):
        return "FAIL"
    if rec_s == "changed" or cost_s == "changed" or wb_s == "corrected":
        return "CORRECTED"
    return "PASS"


def audit(summary: Mapping[str, Any], charge_result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    findings = summary.get("reader_findings") if isinstance(summary.get("reader_findings"), Mapping) else None
    if not findings or not findings.get("items"):
        return {"applicable": False, "items": [],
                "why": ("no reader findings on this record: the scan predates their capture, so "
                        "nothing can be shown about what the reader found before the build" if not findings
                        else "the reader made no finding")}
    recs = {_pn(p.get("part_number")): p for p in ((summary.get("manufacturing_writeup") or {}).get("parts") or [])
            if isinstance(p, Mapping)}
    es = summary.get("estimate_summary") if isinstance(summary.get("estimate_summary"), Mapping) else {}
    costs = {_pn(p.get("part_number")): p for p in (es.get("part_estimates") or []) if isinstance(p, Mapping)}
    final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), Mapping) else {}
    read_back = final.get("source") == "excel_calculated"
    cr = charge_result if charge_result is not None else (
        summary.get("drawing_charge_result") if isinstance(summary.get("drawing_charge_result"), Mapping) else {})
    items = {str(i.get("id")): i for i in (cr.get("items") or []) if isinstance(i, Mapping)}
    rows: List[Dict[str, Any]] = []
    for f in findings["items"]:
        pn = _pn(f.get("part"))
        rec = recs.get(pn) if pn else None
        cost = costs.get(pn) if pn else None
        r = _record_stage(f, rec) if pn else {"state": "unassigned", "note": "no part named on the page"}
        c = _costing_stage(f, cost) if pn else {"state": "unassigned"}
        w = _workbook_stage(f, rec, items, read_back) if pn else {"state": "unassigned"}
        rows.append({"id": f.get("id"), "page": f.get("page"), "part": f.get("part"), "kind": f.get("kind"),
                     "value": f.get("value"), "units": f.get("units"), "words": f.get("words"),
                     "source": f.get("source"), "record": r, "costing": c, "workbook": w,
                     "verdict": _verdict(r["state"], c["state"], w["state"], pn)})
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"applicable": True, "captured": findings.get("captured"), "items": rows, "counts": counts,
            "read_back": read_back, "unassigned": [r for r in rows if r["verdict"] == "UNASSIGNED"]}
