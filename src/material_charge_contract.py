"""A sheet blank and a bought item reach the charged cells, or the book says which did not (D-582).

The third accuracy contract, beside the section contract (D-576…578) and the final-charge
contract on which it leans. It reads the canonical nodes, the canonical price records and
the calculated workbook's read-back, and asks of every manufactured blank and every bought
item: is there one material row for it, at this quantity, in the right block, with the blank
and gauge the engine holds, a positive charge whose arithmetic holds, and does the saved file's
own cached cell say the same. It is not a second pricing engine: it invents no nesting, no
purchase unit, no pack conversion, no rate and no scope exclusion.

TWO KINDS OF FINDING, KEPT APART. A MISMATCH is a demonstrated disagreement — the row is
missing, the gauge differs, the arithmetic does not hold. UNVERIFIED is evidence the record
does not carry — no sheet price on the row, no stated purchase basis on the record, no saved
workbook to read. The second is never dressed as the first and never filled in: a missing
sheet price is NOT recovered by dividing the charge backwards, which would compare the answer
with itself. Where the writer carries those facts forward (sheet_price_gbp, sheet dimensions,
a stated sheet_charge_policy, a purchase_basis on the bought record) the gaps close one by one.

ROLLOUT. `mode()` is config.ACCURACY_CONTRACT["mode"], overridden by
SDI_ACCURACY_CONTRACT_MODE on one machine. In `shadow` the result is recorded and counted on
the console and the release is untouched; in `enforce` mismatches AND unverified evidence
reach the BLOCKING invariant and the existing release gate holds the quote. A misspelt mode
is enforce with a finding, never shadow by accident. Enforcement is for after replay review:
on a legacy record it would hold release for missing sheet and purchase evidence.

Contract and proofs as proposed in the Codex review package of 22 Oct 2026 (accuracy
contracts), merged on the engine's terms: the commercial exclusion reads the engine's own
`commercial_line` flag, the mode lives in config, and the findings reach one invariant.
"""
from __future__ import annotations

import os
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from math import isclose
from typing import Any, Dict, List, Optional

from quantity_flow_contract import (numeric, identity, unit, convert, is_commercial,
                                    audit as quantity_audit, _canonical_parts, _graph)

SCHEMA = "material_charge_contract.v1"
MODES = ("shadow", "enforce")
SECTION_FORMS = {"tube", "wire", "bar", "section"}
SHEET_BLOCKS = {"steel", "other_sheet"}


def mode() -> str:
    """The rollout mode: the config table's word, overridden by the environment. Anything
    that is not a known mode is returned as written, for the caller to fail closed on."""
    env = os.environ.get("SDI_ACCURACY_CONTRACT_MODE", "").strip().lower()
    if env:
        return env
    try:
        from config import ACCURACY_CONTRACT
        return str(ACCURACY_CONTRACT.get("mode") or "shadow").strip().lower()
    except Exception:                                                # noqa: BLE001
        return "shadow"


def audit(summary: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The findings — mismatches and unverified evidence apart — and a trace row per part.
    Mutates nothing; never returns a kept verdict."""
    nodes = [n for n in (_graph(summary).get("nodes") or []) if isinstance(n, dict)]
    parts = _canonical_parts(summary)
    final = summary.get("final_estimate") or {}
    issues: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    traces: List[Dict[str, Any]] = []

    def fail(code: str, part: str = "", **detail: Any) -> None:
        issues.append({"code": code, "part": part, **detail})

    def unverified(code: str, part: str = "", **detail: Any) -> None:
        unknown.append({"code": code, "part": part, **detail})

    counts = Counter(identity(p.get("part_number")) for p in parts)
    ps = {identity(p.get("part_number")): p for p in parts
          if counts[identity(p.get("part_number"))] == 1}
    rows = [r for r in (final.get("material_rows") or []) if isinstance(r, dict)]
    known = set(ps)

    def row_id(row: Dict[str, Any]) -> str:
        explicit = identity(row.get("part_code"))
        if explicit:
            return explicit
        desc = identity(row.get("description"))
        hits = [pn for pn in known if pn and (desc == pn or desc.startswith(pn + " "))]
        return hits[0] if len(hits) == 1 else ""

    if final.get("source") != "excel_calculated":
        unverified("calculated_material_readback_missing")
    if final.get("adapter_problems"):
        fail("material_readback_incomplete", problems=final["adapter_problems"])
    addresses = Counter(r.get("charged_cell") for r in rows)
    for address, n in addresses.items():
        if not address or n != 1:
            fail("material_cell_missing_or_duplicate", cell=address, count=n)
    amounts = [numeric(r.get("total_value_gbp")) for r in rows]
    total = numeric((final.get("totals") or {}).get("material_gbp"))
    if total is None or any(v is None for v in amounts):
        unverified("material_total_unverified")
    elif not isclose(sum(amounts), total, abs_tol=.02, rel_tol=0):
        fail("material_total_mismatch", expected=sum(amounts), actual=total)

    # THE SAVED FILE'S OWN CELLS: the charge, and every input cell the read-back located.
    if snapshot is None:
        unverified("saved_workbook_not_verified")
    else:
        cells = snapshot.get("cells") or {}
        for row in rows:
            cell = row.get("charged_cell")
            actual, value = numeric(cells.get(cell)), numeric(row.get("total_value_gbp"))
            if actual is None or value is None or not isclose(actual, value, abs_tol=.0001, rel_tol=0):
                fail("saved_material_charge_mismatch", row_id(row), cell=cell)
            evidence = row.get("evidence_cells") or {}
            if not evidence:
                unverified("material_input_cells_not_recorded", row_id(row))
            for field, address in evidence.items():
                a, b = cells.get(address), row.get(field)
                if isinstance(b, str):
                    # The read-back collapses a cell's whitespace; compare on the same terms.
                    equal = " ".join(str(a or "").split()).upper() == " ".join(b.split()).upper()
                elif b is None:
                    equal = a is None
                else:
                    x, y = numeric(a), numeric(b)
                    equal = x is not None and y is not None and isclose(x, y, abs_tol=1e-8, rel_tol=0)
                if not equal:
                    fail("saved_material_input_mismatch", row_id(row), field=field, cell=address)

    for node in nodes:
        pn = identity(node.get("part_number"))
        p = ps.get(pn)
        if p is None:
            continue            # the quantity contract reports the missing price record
        if is_commercial(p) or node.get("kind") in {"commercial", "consumable"}:
            continue
        mat = p.get("material_estimate") or {}
        stock = mat.get("stock_form")
        bought = node.get("kind") == "bought_in" or p.get("is_bought_in") is True
        length, width = numeric(mat.get("blank_length_mm")), numeric(mat.get("blank_width_mm"))
        sheet = (node.get("kind") in {"leaf", "part"} and not bought
                 and stock not in SECTION_FORMS
                 and length is not None and width is not None and length > 0 and width > 0)
        if not bought and not sheet:
            continue
        category = "bought" if bought else "sheet"
        hits = [r for r in rows if row_id(r) == pn]
        traces.append({"part": pn, "category": category, "quantity": p.get("quantity"),
                       "material_cells": [r.get("charged_cell") for r in hits]})
        if p.get("set_aside"):
            fail("required_material_set_aside", pn)
        if len(hits) != 1:
            fail("material_row_missing_or_duplicate", pn, category=category, count=len(hits))
            continue
        row = hits[0]
        q, rq = numeric(p.get("quantity")), numeric(row.get("qty_per_unit"))
        if q is None or rq is None or not isclose(q, rq, abs_tol=1e-8, rel_tol=0):
            fail("material_quantity_mismatch", pn, expected=q, actual=rq)
        money, scrap = numeric(row.get("total_value_gbp")), numeric(row.get("scrap_pct"))
        if money is None or money <= 0:
            fail("material_not_charged", pn)
        if scrap is None:
            # A blank allowance is not read as nought: the template's allowance is evidence.
            unverified("material_allowance_basis_missing", pn)
        elif scrap < 0:
            fail("negative_material_allowance", pn)
        if bought:
            _audit_bought(p, pn, row, rq, scrap, money, fail, unverified)
        else:
            _audit_sheet(p, pn, row, length, width, rq, scrap, money, fail, unverified)

    quantities = quantity_audit(summary)
    issues.extend(quantities["issues"])
    return {"schema": SCHEMA, "passed": not issues and not unknown,
            "issues": issues, "unverified": unknown, "trace": traces,
            "quantity_trace": quantities["trace"],
            "workbook_sha256": (snapshot or {}).get("sha256"),
            "scope": "canonical sheet blanks and bought items; not requirements no reader captured"}


def _audit_bought(p, pn, row, rq, scrap, money, fail, unverified) -> None:
    """A bought item needs no cutting row. Its charge is rate × quantity × allowance, and
    where the record states how it is bought (a pack of a hundred at £20 is 20p each, not
    £20 each) the row's rate must be that conversion. A missing basis stays unverified; it is
    never read off the description and never assumed to be `each`."""
    rate = numeric(row.get("unit_price_gbp"))
    if rate is not None and rq is not None and scrap is not None and money is not None:
        expected = rate * rq * (1 + scrap)
        if not isclose(expected, money, abs_tol=.005, rel_tol=0):
            fail("bought_charge_arithmetic_mismatch", pn, expected=expected, actual=money)
    else:
        unverified("bought_charge_basis_missing", pn)
    basis = p.get("purchase_basis") or {}
    if not basis:
        unverified("purchase_unit_basis_missing", pn)
        return
    try:
        per_item = convert(1, basis.get("required_unit"), basis.get("price_unit"),
                           basis.get("units_per_purchase"))
        source_rate = numeric(basis.get("price_gbp"))
        if source_rate is None or source_rate <= 0 or rate is None:
            raise ValueError("Purchase price missing")
        if basis.get("rounding") not in {None, "proportional"}:
            raise ValueError("Whole-pack allocation requires batch purchasing evidence")
        if not isclose(source_rate * per_item, rate, abs_tol=.0001, rel_tol=0):
            fail("purchase_rate_conversion_mismatch", pn, expected=source_rate * per_item, actual=rate)
        required = unit(p.get("unit_of_measure") or p.get("unit"))
        if required is None or required != unit(basis.get("required_unit")):
            unverified("required_purchase_unit_unverified", pn)
    except ValueError as exc:
        unverified("purchase_conversion_unverified", pn, detail=str(exc))


def _audit_sheet(p, pn, row, length, width, rq, scrap, money, fail, unverified) -> None:
    """A manufactured blank: one row in a sheet block carrying this blank (rotation allowed)
    and gauge, a whole positive yield that fits the stock area, and — only where the row
    states a sheet price, stock size and charge policy — the arithmetic. The area bound is
    necessary, not sufficient: it does not prove an exact nest."""
    mat = p.get("material_estimate") or {}
    if row.get("block") not in SHEET_BLOCKS:
        fail("sheet_written_to_wrong_block", pn, block=row.get("block"))
    gauge = numeric(mat.get("thickness_mm")) or numeric(p.get("normalized_thickness_mm"))
    rg = numeric(row.get("gauge")) or numeric(row.get("thickness_mm"))
    dims = [numeric(row.get("length_mm")), numeric(row.get("width_mm"))]
    if None in dims or not all(isclose(a, b, abs_tol=.01, rel_tol=0)
                               for a, b in zip(sorted([length, width]), sorted(dims))):
        fail("sheet_blank_mismatch", pn)
    if gauge is None or rg is None:
        unverified("sheet_gauge_unverified", pn)
    elif not isclose(gauge, rg, abs_tol=.001, rel_tol=0):
        fail("sheet_gauge_mismatch", pn, expected=gauge, actual=rg)
    yield_ = numeric(row.get("qty_per_sheet"))
    if yield_ is None or yield_ <= 0 or not yield_.is_integer():
        fail("sheet_yield_invalid", pn)
    sheet_price = numeric(row.get("sheet_price_gbp"))
    sl, sw = numeric(row.get("sheet_length_mm")), numeric(row.get("sheet_width_mm"))
    if sl is None or sw is None:
        unverified("sheet_stock_dimensions_missing", pn)
    elif yield_ is not None and (length * width * yield_ > sl * sw + .01 or
                                 not ((length <= sl and width <= sw) or (length <= sw and width <= sl))):
        fail("sheet_yield_exceeds_geometric_capacity", pn)
    if sheet_price is None or sheet_price <= 0 or not yield_ or rq is None or scrap is None:
        unverified("sheet_price_basis_missing", pn)
        return
    policy = row.get("sheet_charge_policy")
    base = sheet_price / yield_
    if policy == "rounded_piece_2dp":
        base = float(Decimal(str(base)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    elif policy != "fractional_sheet":
        unverified("sheet_charge_policy_missing", pn)
        return
    expected = base * rq * (1 + scrap)
    if money is None or not isclose(expected, money, abs_tol=.005, rel_tol=0):
        fail("sheet_charge_arithmetic_mismatch", pn, expected=expected, actual=money)


def record(summary: Dict[str, Any], workbook_path: Any = None) -> Dict[str, Any]:
    """Run the audit against the record and, where given, the saved workbook, and keep the
    result on the record as `material_charge_result`. A failure of the checker is a finding;
    an unknown mode is enforce with a finding. Prices are never changed here."""
    requested = mode()
    try:
        from final_charge_contract import snapshot_xlsx
        result = audit(summary, snapshot_xlsx(workbook_path) if workbook_path else None)
    except Exception as exc:                                         # noqa: BLE001
        result = {"schema": SCHEMA, "passed": False, "unverified": [], "trace": [],
                  "issues": [{"code": "material_contract_failed", "part": "", "detail": str(exc)}]}
    if requested not in MODES:
        result["issues"].append({"code": "invalid_accuracy_contract_mode", "part": "", "mode": requested})
        result["passed"] = False
        requested = "enforce"
    result["mode"] = requested
    summary["material_charge_result"] = result
    print(f"   [accuracy-contract:{requested}] {len(result['issues'])} mismatch(es), "
          f"{len(result['unverified'])} unverified evidence item(s)", flush=True)
    return result
