"""A section requirement reaches the charged cells of the calculated workbook, or the book
says which did not (D-578).

THE LAST STAGE OF THE CONTRACT. section_coverage_contract captures a cut list from the
sheet's own words, carries it to the record, and checks it at the hand-off to the workbook
(D-576) and in the rows read back (D-577). The 18:09 book of 21 Oct 2026 showed the gap that
leaves: the hand-off passed, the record held 1011 mm and a price, and the writer left the
line off the sheet. This stage reads what the calculated workbook actually charges:

    drawing requirement -> part and quantity -> route and price -> workbook charge

For every captured requirement, the owner or its cut-list members must have exactly one
material row on the read-back at the record's own quantity, a positive calculated charge
whose arithmetic holds (rate x quantity x (1 + scrap)), and a cutting row with hours on it
that names the piece. The read-back itself must be whole: every row with a cell address,
no address twice, every amount numeric, the rows summing to the sheet's total. And where
the saved file is to hand, its own cached values are read — never a formula, never text
that looks like a number — and must agree with the read-back on each charged cell, the
block total, the row's identity and its quantity. A stale read-back cannot pass.

WHAT A FAILURE DOES. Findings are written on the record (`final_charge_result`) and raised
by invariants.check_a_section_schedule_reaches_the_sheet, BLOCKING, beside the earlier
stages: the book is made, the release held, the first decision names the sheet and the
piece. The check is recomputed in main after Excel on every run; a verdict kept from an
earlier workbook is not this one's. A checker that fails is itself a finding, never a pass.

Read-only. Nothing here prices, edits a workbook, calls a model or infers a joint. Method
and proofs as proposed in the Codex review package of 21 Oct 2026, merged into the engine's
own structure: the same BLOCKING invariant, the probe under tools/diagnose. Scope: section
schedules at the workbook's priced quantity; the other requirement classes follow the same
shape.
"""
from __future__ import annotations

import hashlib
import math
import posixpath
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile

SCHEMA = "final_charge_contract.v1"
CUT_OPERATIONS = {"saw", "tube_cut", "tube_laser", "laser_cutting"}


def number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def key(value: Any) -> str:
    return str(value or "").strip().upper()


def cached_number(value: Any) -> Optional[float]:
    """A calculated Excel number. Text that looks numeric is not one: SUM ignores it."""
    return number(value) if isinstance(value, (int, float)) else None


def tokens(value: Any) -> set:
    return {key(x) for x in (value if isinstance(value, list) else
                            re.split(r"[,;]", str(value or ""))) if key(x)}


def row_cells(cells: Dict[str, Any], address: str) -> Dict[str, Any]:
    """Every cached cell on the row of `address`, on its sheet."""
    sheet, cell = address.rsplit("!", 1)
    row = re.search(r"\d+$", cell).group()
    return {a: v for a, v in cells.items() if a.startswith(sheet + "!") and
            re.search(r"\d+$", a).group() == row}


def quantity_cell(cells: Dict[str, Any], address: str) -> Optional[str]:
    """The quantity cell on this row: under the nearest preceding "Qty Per Unit" header on
    the sheet, not a fixed column — the blocks name their columns, the template may move."""
    sheet, cell = address.rsplit("!", 1)
    row = int(re.search(r"\d+$", cell).group())
    headers = []
    for a, v in cells.items():
        if a.startswith(sheet + "!") and key(v) == "QTY PER UNIT":
            r = int(re.search(r"\d+$", a).group())
            if r < row:
                headers.append((r, re.sub(r"\d+$", str(row), a)))
    if not headers:
        return None
    closest = max(r for r, _ in headers)
    hits = [a for r, a in headers if r == closest]
    return hits[0] if len(hits) == 1 else None


def snapshot_xlsx(path: Any) -> Dict[str, Any]:
    """The saved file's cached values, cell by cell. A formula with no cached value is None;
    formula text is never evaluated and never taken as money."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    cells: Dict[str, Any] = {}
    with ZipFile(path) as z:
        strings: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = ["".join(e.itertext()) for e in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        rels = {e.attrib["Id"]: e.attrib["Target"] for e in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).findall("s:sheets/s:sheet", ns):
            target = rels[sheet.attrib[f"{{{relns}}}id"]]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            for c in ET.fromstring(z.read(target)).findall(".//s:sheetData/s:row/s:c", ns):
                v = c.find("s:v", ns)
                raw = v.text if v is not None else None
                typ = c.get("t")
                if typ == "s" and raw is not None:
                    value: Any = strings[int(raw)]
                elif typ == "inlineStr":
                    value = "".join(c.find("s:is", ns).itertext())
                elif typ == "b":
                    value = raw == "1"
                elif typ in ("str", "e"):
                    value = raw
                else:
                    value = number(raw)
                cells[f"{sheet.attrib['name']}!{c.attrib['r']}"] = value
    return {"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "cells": cells}


def audit(summary: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The findings and a trace row per piece. Mutates nothing; never returns a kept verdict.

    The requirement's geometry and quantity are the section contract's to validate; here the
    record's own quantity and a positive charge must have survived Excel. A grouped cutting
    row serves several pieces and is not charged again per member."""
    contract = summary.get("section_coverage_contract") or {}
    requirements = contract.get("requirements") or []
    result: Dict[str, Any] = {"schema": SCHEMA, "applicable": bool(requirements), "issues": [], "trace": []}
    issues = result["issues"]

    def fail(code: str, part: str = "", **detail: Any) -> None:
        issues.append({"code": code, "part": part, **detail})

    if not requirements:
        result.update(passed=True, scope="no captured section requirements")
        return result
    final = summary.get("final_estimate") or {}
    if final.get("source") != "excel_calculated":
        fail("calculated_workbook_missing")
        result["passed"] = False
        return result
    if final.get("adapter_problems"):
        fail("workbook_readback_incomplete", problems=final["adapter_problems"])
    es = summary.get("estimate_summary") or {}
    # An empty canonical population is evidence of loss, not permission to revive
    # a pre-canonical population. Duplicate identities must never overwrite silently.
    estimates = (es.get("canonical_part_estimates") if "canonical_part_estimates" in es
                 else es.get("part_estimates")) or []
    for pn, count in Counter(key(p.get("part_number")) for p in estimates if isinstance(p, dict)).items():
        if not pn or count != 1:
            fail("canonical_part_identity_missing_or_duplicate", pn, count=count)
    costs = {key(p.get("part_number")): p for p in estimates if isinstance(p, dict)}
    raw = {key(p.get("part_number")): p for p in
           (summary.get("manufacturing_writeup") or {}).get("parts", []) if isinstance(p, dict)}
    material = [r for r in (final.get("material_rows") or []) if isinstance(r, dict)]
    labour = [r for r in (final.get("labour_rows") or []) if isinstance(r, dict)]

    # THE READ-BACK IS WHOLE: every row at a cell, no cell twice, every amount a number, the
    # rows summing to the sheet's own total; and the saved file agrees, cell by cell.
    for label, rows, total_key in (("material", material, "material_gbp"),
                                   ("labour", labour, "labour_gbp")):
        addresses = [r.get("charged_cell") for r in rows]
        for address, count in Counter(addresses).items():
            if not address or count != 1:
                fail("charged_cell_missing_or_repeated", cell=address, block=label)
        amounts = [cached_number(r.get("total_value_gbp")) for r in rows]
        total = cached_number((final.get("totals") or {}).get(total_key))
        if any(a is None for a in amounts) or total is None:
            fail("calculated_value_missing", block=label)
        elif not math.isclose(sum(amounts), total, rel_tol=0, abs_tol=0.02):
            fail("charged_rows_do_not_reconcile", block=label, rows_gbp=sum(amounts), total_gbp=total)
        if snapshot is not None:
            for row in rows:
                cell = row.get("charged_cell")
                actual = cached_number(snapshot["cells"].get(cell))
                recorded = cached_number(row.get("total_value_gbp"))
                if actual is None or recorded is None or not math.isclose(actual, recorded, rel_tol=0, abs_tol=0.0001):
                    fail("saved_cell_differs_from_readback", cell=cell, actual=actual, recorded=recorded)
            total_label = "TOTAL MATERIAL COST" if label == "material" else "TOTAL LABOUR COST"
            labels = [a for a, v in snapshot["cells"].items()
                      if key(v) == total_label or key(v).startswith(total_label + " (")]
            totals = [cached_number(v) for a in labels for v in row_cells(snapshot["cells"], a).values()
                      if cached_number(v) is not None]
            if len(totals) != 1 or total is None or not math.isclose(totals[0], total, rel_tol=0, abs_tol=0.02):
                fail("saved_total_not_verified", block=label, actual=totals, recorded=total)
    known = set(costs) | set(raw)

    def material_id(row: Dict[str, Any]) -> str:
        explicit = key(row.get("part_code"))
        if explicit:
            return explicit
        # The sheet blocks have no code column: the description leads with the code, whole.
        desc = key(row.get("description"))
        matches = [pn for pn in known if desc == pn or desc.startswith(pn + " ")]
        return matches[0] if len(matches) == 1 else ""

    for req in requirements:
        owner = key(req["part"])
        candidates = [pn for pn, p in raw.items() if key(p.get("cut_list_member_of")) == owner] or [owner]
        for pn in candidates:
            cost = costs.get(pn) or {}
            if cost.get("set_aside"):
                fail("required_section_set_aside", pn, source=req.get("source"))
                continue
            qty = number(cost.get("quantity"))
            mat = cost.get("material_estimate") or {}
            price = number(mat.get("unit_material_cost_gbp"))
            if price is None:
                price = number(mat.get("cost_per_part_gbp"))
            hits = [r for r in material if material_id(r) == pn]
            trace: Dict[str, Any] = {"part": pn, "owner": owner, "source": req.get("source"),
                                     "expected_quantity": qty, "engine_unit_material_gbp": price,
                                     "material_cells": [r.get("charged_cell") for r in hits]}
            result["trace"].append(trace)
            if len(hits) != 1:
                fail("section_material_row_missing_or_duplicate", pn, matches=len(hits), source=req.get("source"))
            else:
                row = hits[0]
                count = cached_number(row.get("qty_per_unit"))
                money = cached_number(row.get("total_value_gbp"))
                trace.update(charged_quantity=count, charged_gbp=money)
                if snapshot is not None:
                    cells = snapshot["cells"]
                    address = row.get("charged_cell") or ""
                    try:
                        qcell = quantity_cell(cells, address)
                        actual_qty = cached_number(cells.get(qcell))
                        identity_found = any(key(v) == pn or key(v).startswith(pn + " ")
                                             for v in row_cells(cells, address).values())
                    except (ValueError, AttributeError):
                        actual_qty, identity_found, qcell = None, False, None
                    trace["quantity_cell"] = qcell
                    if not identity_found:
                        fail("saved_material_identity_not_verified", pn, cell=address)
                    if actual_qty is None or count is None or not math.isclose(actual_qty, count, rel_tol=0, abs_tol=1e-8):
                        fail("saved_quantity_differs_from_readback", pn, actual=actual_qty, recorded=count)
                if qty is None or qty <= 0 or count is None or not math.isclose(qty, count, rel_tol=0, abs_tol=1e-8):
                    fail("section_charged_quantity_mismatch", pn, expected=qty, charged=count)
                if money is None or money <= 0:
                    fail("section_material_not_charged", pn, cell=row.get("charged_cell"))
                # The sheet's own rate at this quantity, not another break's engine rate.
                rate = cached_number(row.get("unit_price_gbp"))
                scrap = 0 if row.get("scrap_pct") is None else cached_number(row.get("scrap_pct"))
                if rate is None or count is None or scrap is None or rate <= 0 or scrap < 0:
                    fail("section_rate_basis_missing", pn)
                elif money is None or not math.isclose(rate * count * (1 + scrap), money, rel_tol=0, abs_tol=0.02):
                    fail("section_charge_arithmetic_mismatch", pn, expected=rate * count * (1 + scrap), charged=money)
            # THE CUT SURVIVED TO A CHARGED ROW WITH HOURS ON IT. The engine's labour groups
            # say which workbook row carries which operation for which pieces.
            groups = (summary.get("workbook_labour") or {}).get("rows") or []
            cut_row_numbers = {g.get("workbook_row") for g in groups if isinstance(g, dict)
                               and set(g.get("engine_operations") or []) & CUT_OPERATIONS
                               and pn in tokens(g.get("part_numbers"))}
            saws = [r for r in labour if pn in tokens(r.get("part_numbers"))
                    and r.get("workbook_row") in cut_row_numbers]
            trace["cut_cells"] = [r.get("charged_cell") for r in saws]
            if not saws or not any((cached_number(r.get("total_value_gbp")) or 0) > 0 and
                                   (cached_number(r.get("batch_hours")) or 0) > 0 for r in saws):
                fail("section_cut_not_charged", pn, source=req.get("source"))
            elif snapshot is not None:
                for cut in saws:
                    if not any(pn in tokens(v) for v in row_cells(snapshot["cells"], cut["charged_cell"]).values()):
                        fail("saved_cut_identity_not_verified", pn, cell=cut["charged_cell"])
    result.update(passed=not issues, workbook_sha256=(snapshot or {}).get("sha256"))
    return result


def record(summary: Dict[str, Any], workbook_path: Any = None) -> Dict[str, Any]:
    """Audit against the saved workbook and write the result on the record. A failure of the
    checker is a finding; a workbook not to hand is a finding; neither is a pass."""
    try:
        snapshot = snapshot_xlsx(workbook_path) if workbook_path else None
        result = audit(summary, snapshot)
        if result["applicable"] and not workbook_path:
            result["issues"].append({"code": "final_workbook_not_verified", "part": ""})
            result["passed"] = False
    except Exception as exc:                                         # noqa: BLE001
        result = {"schema": SCHEMA, "applicable": True, "passed": False, "trace": [],
                  "issues": [{"code": "final_charge_audit_failed", "part": "", "text": str(exc)}]}
    summary["final_charge_result"] = result
    if result.get("applicable") and not result.get("passed"):
        print("   [final-charge] " + "; ".join(
            f"{i.get('part') or 'the workbook'}: {i.get('code')}" for i in result.get("issues") or []),
              flush=True)
    return result
