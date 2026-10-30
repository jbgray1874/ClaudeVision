#!/usr/bin/env python3
r"""parity_workbooks.py — the engine's workbook against the estimator's, week after week.

WHY THIS EXISTS SEPARATELY FROM parity_run.py.

parity_run.py compares the engine's own JSON reading of a job against the manual sheet, which
is the richer comparison and needs the run's summary.json. That file lives wherever the engine
ran. What travels — what an estimator e-mails back, what sits on the share — is the WORKBOOK.
Two workbooks on the same house template can be compared on their own, and that is what the
weekly parity number should be built from, because it needs nothing but the two files.

THE THING THIS GETS RIGHT THAT A NAIVE COMPARISON DOES NOT.

**A parity number across two different quantities is worse than no number.** On 11908-21 the
manual sheet is priced at 50 off and the engine run was at 1: set-up amortises over fifty on
one side and over one on the other, so the labour lines are not measuring the same thing and
the "variance" is arithmetic about nothing. Published as a KPI it would read as a 35% engine
error and destroy the trust the parallel run exists to build.

So every pair states the quantity it is compared AT, and where the two differ the engine side
is read from its own **Quantity Breaks** tab -- the column that recalculates the whole estimate
at the manual's quantity. Where no such column exists the pair is reported as NOT COMPARABLE
with the reason, and it is left out of the averages rather than quietly included.

**And the sheets have to be the same article.** 10975-02 has two manual revisions: an L-Stand
at 1 off and the A4 table-top holder at 10 off. Comparing the engine's table-top run against
the L-Stand sheet produces a 789% material variance and means nothing at all.

WHAT IT WILL NOT PRINT. No figure from a manual estimate is written into the output, per the
pricing policy: a number off an estimator's sheet is not retained in our reports. Parity is
reported as the engine's own figure and a VARIANCE with a direction, which measures us without
retaining them, and cannot be used as a price by anybody downstream.

    python tools/parity_workbooks.py \
        --pair 7332-01  engine.xlsx manual.xls \
        --pair 11908-21 engine.xlsx manual.xls \
        --out parity.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import parity_check as pc                                    # noqa: E402

# The Quantity Breaks tab's own summary block, by the labels it writes.
_QB_SHEET = "Quantity Breaks"
_QB_ROWS = {"quantity": "quantity", "material": "material £/unit",
            "labour": "labour £/unit", "unit": "unit cost £"}


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f                              # NaN is not a number here either


def quantity_break_columns(path: Path) -> Dict[float, Dict[str, float]]:
    """{quantity: {material, labour, unit}} from the engine workbook's own breaks tab.

    Empty when the tab is absent, blank or carries an error -- which is a fact about that run,
    not a failure here. 12349-02's 14 Sep book has the tab and it reads #REF!, from the
    template-formula defect fixed on 16 September; that book simply has no usable column and
    is compared at its own quantity instead.
    """
    try:
        import openpyxl                                       # noqa: PLC0415
    except ImportError:
        return {}
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:                                         # noqa: BLE001
        return {}
    try:
        if _QB_SHEET not in wb.sheetnames:
            return {}
        ws = wb[_QB_SHEET]
        found: Dict[str, List[Any]] = {}
        for row in ws.iter_rows(values_only=True):
            head = str(row[0] or "").strip().lower()
            for key, label in _QB_ROWS.items():
                if head == label:
                    found[key] = list(row[1:9])
        if "quantity" not in found:
            return {}
        out: Dict[float, Dict[str, float]] = {}
        for i, q in enumerate(found["quantity"]):
            qty = _f(q)
            if qty is None:
                continue
            cols = {k: _f(found.get(k, [None] * 9)[i]) for k in ("material", "labour", "unit")}
            if cols["material"] is None and cols["labour"] is None:
                continue
            out[qty] = {k: v for k, v in cols.items() if v is not None}
        return out
    finally:
        wb.close()


def _variance(engine: Optional[float], manual: Optional[float]) -> Optional[float]:
    """Engine against manual, as a percentage of the manual. Positive = the engine is higher."""
    if engine is None or manual in (None, 0):
        return None
    return round((engine - manual) / manual * 100.0, 1)


def compare(job: str, engine_path: Path, manual_path: Path) -> Dict[str, Any]:
    eng = pc.read_house_workbook(engine_path)
    man = pc.read_house_workbook(manual_path)

    eq = _f(eng["headline"].get("quantity"))
    mq = _f(man["headline"].get("quantity"))
    e_mat, e_lab = _f(eng["totals"].get("material")), _f(eng["totals"].get("labour"))
    m_mat, m_lab = _f(man["totals"].get("material")), _f(man["totals"].get("labour"))

    row: Dict[str, Any] = {
        "job": job,
        "engine_file": engine_path.name, "manual_file": manual_path.name,
        "engine_qty": eq, "manual_qty": mq,
        "engine_reconciles": pc.reconcile(eng).get("balances"),
        "manual_reconciles": pc.reconcile(man).get("balances"),
        "source": "estimate sheet",
        "comparable": True, "note": "",
    }

    if eq is not None and mq is not None and eq != mq:
        # The engine recalculates the whole estimate at each quantity on its own breaks tab.
        # If it carries the manual's quantity, that column IS the like-for-like answer.
        cols = quantity_break_columns(engine_path)
        if mq in cols:
            e_mat = cols[mq].get("material", e_mat)
            e_lab = cols[mq].get("labour", e_lab)
            row.update(source=f"engine Quantity Breaks column at {mq:g} off", engine_qty=mq,
                       note=(f"The engine run was at {eq:g} off and the manual sheet is at "
                             f"{mq:g}. Compared at {mq:g} from the engine's own Quantity Breaks "
                             f"tab, so set-up amortises over the same number on both sides."))
        else:
            row.update(comparable=False,
                       note=(f"NOT COMPARABLE: the engine ran at {eq:g} off, the manual sheet is "
                             f"at {mq:g}, and the run carries no Quantity Breaks column at "
                             f"{mq:g}. Set-up spreads over different numbers, so any variance "
                             f"would be arithmetic about nothing. Re-run at {mq:g} off."))

    row["qty_compared"] = row["engine_qty"]
    row["engine_material"] = e_mat
    row["engine_labour"] = e_lab
    row["engine_subtotal"] = round((e_mat or 0) + (e_lab or 0), 2) if row["comparable"] else None
    # The manual side is measured and NOT retained: only the variance leaves this function.
    row["material_variance_pct"] = _variance(e_mat, m_mat) if row["comparable"] else None
    row["labour_variance_pct"] = _variance(e_lab, m_lab) if row["comparable"] else None
    row["subtotal_variance_pct"] = (
        _variance((e_mat or 0) + (e_lab or 0), (m_mat or 0) + (m_lab or 0))
        if row["comparable"] else None)
    row["manual_lines"] = sum(len(man["blocks"].get(b, [])) for b in pc.BLOCK_ORDER)
    row["engine_lines"] = sum(len(eng["blocks"].get(b, [])) for b in pc.BLOCK_ORDER)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", nargs=3, action="append", metavar=("JOB", "ENGINE", "MANUAL"),
                    required=True, help="job number, the engine workbook, the manual workbook")
    ap.add_argument("--out", type=Path, default=None, help="write the result as JSON")
    args = ap.parse_args()

    rows = []
    for job, e, m in args.pair:
        try:
            rows.append(compare(job, Path(e), Path(m)))
            r = rows[-1]
            state = "comparable" if r["comparable"] else "NOT COMPARABLE"
            print(f"{job:<10} {state:<15} at {r['qty_compared'] or '?':>5} off   "
                  f"material {r['material_variance_pct']!s:>7}%   "
                  f"labour {r['labour_variance_pct']!s:>7}%   "
                  f"subtotal {r['subtotal_variance_pct']!s:>7}%")
            if r["note"]:
                print(f"           {r['note']}")
        except Exception as exc:                              # noqa: BLE001
            print(f"{job:<10} FAILED: {exc}", file=sys.stderr)

    ok = [r for r in rows if r["comparable"]]
    if ok:
        avg = round(sum(abs(r["subtotal_variance_pct"] or 0) for r in ok) / len(ok), 1)
        print(f"\n{len(ok)} of {len(rows)} pairs comparable; "
              f"mean absolute subtotal variance {avg}%")
    if args.out:
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
