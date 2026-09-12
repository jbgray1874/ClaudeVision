"""Thirty seconds on a finished workbook, before it goes to anybody.

WHY THIS EXISTS. A pack went out whose quantities were finally right and whose money was
gone — "not readable from the sheet", "Labour is 0 sheet rows", Subtotal GBP 0.00. The engine
had already printed the reason ("labour op '…' has no batch_hours and no default throughput —
WB hours/cost will be #DIV/0! for this row") and produced the pack anyway. Five thousand tests
exercise the engine and not one of them evaluates a workbook formula, so that whole class is
invisible to them: the arithmetic is Excel's, not Python's.

This asks the finished file the questions the suite structurally cannot.

    python tools\\preflight_before_you_send_it.py C:\\ClaudeVision\\output\\12349-02_20260912_144540.xlsx

Exit code 0 = safe to send, 1 = do not send. Add the BOMs & Routes workbook as a second
argument to check the quantity columns too.

THE CHECK THAT MATTERS MOST, and the one that caught the run above: a labour row that names an
operation and has an EMPTY throughput cell. `Total Hours` is 60/throughput, so an empty cell is
a division by nothing; one such row poisons the labour SUM, the unit cost, and every figure the
covering email tries to read. A formula in that cell is fine — the laser rate is written as one
— so the test is emptiness, not blankness on screen.

Reads only. Changes nothing, needs no re-run.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:                                       # pragma: no cover
    print("openpyxl is needed: py -m pip install openpyxl")
    raise SystemExit(2)

_ERRORS = ("#DIV/0!", "#VALUE!", "#REF!", "#N/A", "#NAME?", "#NULL!", "#NUM!")


def _find_header(ws, *wanted):
    """Row and columns of a header row carrying all of `wanted`, by TEXT not coordinate, so a
    template that shifts a row down does not silently stop being checked."""
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 400)):
        vals = {str(c.value).strip().lower(): c.column for c in row if c.value is not None}
        if all(any(w.lower() == k for k in vals) for w in wanted):
            return row[0].row, {w: vals[next(k for k in vals if k == w.lower())] for w in wanted}
    return None, {}


def check(path: Path) -> list:
    fails, warns = [], []
    wf = openpyxl.load_workbook(path, data_only=False)
    wv = openpyxl.load_workbook(path, data_only=True)

    # 1. Any cell that has already evaluated to an error.
    for name in wv.sheetnames:
        for row in wv[name].iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.strip() in _ERRORS:
                    fails.append(f"{name}!{c.coordinate} is {c.value.strip()}")

    if "Estimate" not in wf.sheetnames:
        fails.append("no Estimate sheet in this workbook")
        return fails, warns

    ws, wsv = wf["Estimate"], wv["Estimate"]

    # 2. THE ONE THAT CAUGHT THE BROKEN PACK.
    hdr_row, cols = _find_header(ws, "Operation", "Rate Per Hour")
    if hdr_row is None:
        warns.append("could not find the labour header row — throughput not checked")
    else:
        _op, _thr = cols["Operation"], cols["Rate Per Hour"]
        blanks = []
        # STOP AT THE BLOCK'S OWN END. "Total Labour Cost" closes the labour rows; past it the
        # same column carries the departments table and the outstanding-inputs list, and scanning
        # on reported the estimator's own to-do notes as broken labour rows. A checker that cries
        # wolf on a good pack is worse than no checker — the next person turns it off.
        for r in range(hdr_row + 1, min(ws.max_row, hdr_row + 200)):
            op = ws.cell(row=r, column=_op).value
            if op and str(op).strip().lower().startswith("total"):
                break
            if not op:
                continue
            if ws.cell(row=r, column=_thr).value is None:
                blanks.append(f"row {r} '{op}'")
        for b in blanks:
            fails.append(f"labour {b} names an operation with an EMPTY throughput — "
                         f"Total Hours is 60/blank, so this row and the labour total "
                         f"will be #DIV/0!")

    # 3. The totals exist and are live formulas.
    for label in ("Total Material Cost", "Total Labour Cost", "Total Unit Cost Price"):
        found = False
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 400)):
            for c in row:
                if isinstance(c.value, str) and c.value.strip().lower().startswith(label.lower()):
                    found = True
                    if not any(isinstance(x.value, str) and str(x.value).startswith("=")
                               for x in row):
                        fails.append(f"'{label}' row carries no formula — the total is a "
                                     f"literal or is missing")
                    break
            if found:
                break
        if not found:
            warns.append(f"'{label}' not found on the Estimate sheet")

    # 4. Costed rows with no quantity.
    bom_row, bcols = _find_header(ws, "Part code", "Qty Per Unit")
    if bom_row is not None:
        # STOP AT THE END OF THE BLOCK. The bill of materials is contiguous; past it the same
        # column carries a gauge on the nested blocks, and scanning on reported every steel row
        # as a part with no quantity. A checker that cries wolf on a good pack is worse than no
        # checker, because the next person turns it off.
        for r in range(bom_row + 1, min(ws.max_row, bom_row + 60)):
            code = ws.cell(row=r, column=bcols["Part code"]).value
            if not code:
                break
            q = wsv.cell(row=r, column=bcols["Qty Per Unit"]).value
            if q is None or (isinstance(q, (int, float)) and q <= 0):
                fails.append(f"BOM row {r} '{code}' has quantity {q!r} — a costed line with no "
                             f"quantity prices as nothing")

    # 5. Lines the estimator still has to price. Expected on a provisional sheet, so a warning.
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 400)):
        for c in row:
            if isinstance(c.value, str) and (
                    "NOT YET PRICED" in c.value or "MATERIAL UNPRICED" in c.value):
                warns.append(f"unpriced: {str(c.value)[:78]}")
                break
    return fails, warns


def check_boms_and_routes(path: Path) -> list:
    """qty own against qty effective, where the extract publishes both."""
    warns = []
    wb = openpyxl.load_workbook(path, data_only=True)
    for name in wb.sheetnames:
        ws = wb[name]
        hdr, cols = _find_header(ws, "part number", "qty own", "qty effective")
        if hdr is None:
            continue
        for r in range(hdr + 1, ws.max_row + 1):
            pn = ws.cell(row=r, column=cols["part number"]).value
            own = ws.cell(row=r, column=cols["qty own"]).value
            eff = ws.cell(row=r, column=cols["qty effective"]).value
            if not pn or own is None or eff is None:
                continue
            try:
                if abs(float(own) - float(eff)) > 1e-9:
                    warns.append(f"{pn}: states {own}, costed at {eff} — check the reason column")
            except (TypeError, ValueError):
                continue
    return warns


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    book = Path(sys.argv[1])
    if not book.is_file():
        print(f"not a file: {book}")
        return 2
    print(f"\n=== pre-flight: {book.name}\n")
    fails, warns = check(book)

    if len(sys.argv) > 2 and Path(sys.argv[2]).is_file():
        warns += check_boms_and_routes(Path(sys.argv[2]))

    for f in fails:
        print(f"   FAIL  {f}")
    for w in warns[:25]:
        print(f"   note  {w}")
    if len(warns) > 25:
        print(f"   note  ... and {len(warns) - 25} more")

    print()
    if fails:
        print(f"   DO NOT SEND — {len(fails)} blocking problem(s). The money on this sheet "
              f"will not read.")
        return 1
    print(f"   SAFE TO SEND — nothing blocking. {len(warns)} note(s) above are things the "
          f"estimator still has to settle, not faults.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
