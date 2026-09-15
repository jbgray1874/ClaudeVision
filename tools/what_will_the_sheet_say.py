"""What the next run will put on the sheet — in seconds, from the JSON you already have.

    "if I re run now, nothing will change, so what do we do from here?"
                                                    — James Gray, SDI, 15 Sep 2026

He was right to ask. Four fixes were predicted to move a number on 7332-01 and two of them
did. Each time the evidence arrived as a whole job run — twenty minutes of extraction,
costing and Excel — to answer a question about one cell.

That is the actual defect. The weld time had THREE rules stacked in front of it, each
individually defensible, and the loop that could have found all three in one sitting was
being run once per rule at twenty minutes a turn:

    assembly scope skips the grouping        no hours reach the group
    the floor guard replaces outliers        a stated time looks like garbage
    one-row-per-job ops take the default     the derived value is never read

This runs the LABOUR GROUPING AND THE THROUGHPUT DECISION ONLY, against the job record the
last run already saved, and prints what each row would get and on what basis. No Excel, no
extraction, no LLM. It is not a substitute for the run — the workbook's own formulas turn a
throughput into money and nothing here does that — it answers the one question a run was
being spent on: WHICH RULE DECIDES THIS ROW.

    python tools/what_will_the_sheet_say.py output/json/7332-01.json
    python tools/what_will_the_sheet_say.py output/json/7332-01.json --prices

`--prices` does the same for the price-origin classifier: which bucket each priced line
lands in, which is the other place a fix has silently failed to land.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _order_qty(summary: dict) -> int:
    for key in ("assumed_job_quantity", "quantity"):
        try:
            n = int(summary.get(key) or 0)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    es = summary.get("estimate_summary") or {}
    try:
        return max(1, int(es.get("assumed_job_quantity") or 1))
    except (TypeError, ValueError):
        return 1


def labour_rows(summary: dict) -> None:
    """Every labour group, its hours, and WHICH RULE would set its throughput."""
    import wb_populate as wb                                            # noqa: PLC0415
    import costed_facts as cf                                           # noqa: PLC0415

    pes = cf.job_parts(summary) or []
    oq = _order_qty(summary)
    groups = wb.canonical_labour_groups(summary, list(pes), oq)
    if not groups:
        print("  no canonical labour groups — this job did not route through the compiler")
        return

    print(f"  order quantity {oq}, {len(groups)} labour group(s)\n")
    hdr = f"  {'operation':24} {'parts':34} {'rhpu':>9} {'bh':>8}  basis / rule"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for g in sorted(groups.values(), key=lambda x: str(x.get("wb_op") or "")):
        op = str(g.get("wb_op") or "?")
        parts = ", ".join(str(p) for p in (g.get("parts") or []))[:33]
        rhpu = g.get("run_hours_per_unit")
        bh = g.get("bh")
        stated = wb._group_carries_a_stated_shop_time(g, {})
        # The branch chain the emit loop walks, in its own order.
        if op == "Laser (Metal)":
            rule = "template_calculated — the sheet's own laser calculator"
        elif (op in wb_one_row_per_job() and not stated):
            rule = "DEPARTMENT DEFAULT (one-row-per-job) — a derived time is not read"
        elif op in wb_one_row_per_job() and stated:
            tp = (float(g.get("qty") or 1) / float(rhpu)) if rhpu else None
            rule = (f"STATED SHOP TIME -> {tp:.2f}/hr" if tp
                    else "stated, but no hours arrived — default stands")
        elif rhpu:
            rule = f"engine_derived -> {float(g.get('qty') or 1) / float(rhpu):.2f}/hr"
        elif bh:
            rule = "derived from BATCH hours (moves with the order — a known weakness)"
        else:
            rule = "no hours at all — department default"
        print(f"  {op:24} {parts:34} "
              f"{(f'{rhpu:.4f}' if rhpu else '—'):>9} {(f'{bh:.3f}' if bh else '—'):>8}  {rule}")
    print("\n  A row reading DEPARTMENT DEFAULT will not move however the estimator's time "
          "changes.\n  That is the sentence four runs were spent discovering.")


def wb_one_row_per_job() -> set:
    """The set the emit loop uses, read from the source rather than copied.

    A second copy of this set here would be the exact defect this whole session has been
    about: two readers of one fact, agreeing until the day they do not."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    try:
        block = src.split("_ONE_ROW_PER_JOB = {")[1].split("}")[0]
    except IndexError:
        return set()
    import re
    return set(re.findall(r'"([^"]+)"', block))


def price_rows(summary: dict) -> None:
    """Which bucket each priced line lands in — the other place a fix fails silently."""
    import costed_facts as cf                                           # noqa: PLC0415
    job = cf.costed_job(summary)
    lines = job.get("lines") or []
    print(f"  {len(lines)} costed line(s)\n")
    hdr = f"  {'part':26} {'£/unit':>9}  {'firmness':18} class / label"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for l in lines:
        po = l.get("price_origin") or {}
        money = l.get("charged_unit_gbp")
        if money is None:
            money = l.get("engine_unit_gbp")
        print(f"  {str(l.get('part_number') or '')[:25]:26} "
              f"{(f'{float(money):.2f}' if money not in (None, '') else '—'):>9}  "
              f"{str(po.get('firmness') or '?'):18} "
              f"{po.get('class') or '?'} — {str(po.get('label') or '')[:60]}")
    out = cf.outstanding_summary(job)
    print(f"\n  headline: {out['phrase']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job_json", help="output/json/<job>.json from the last run")
    ap.add_argument("--prices", action="store_true",
                    help="show the price-origin bucket for every costed line instead")
    args = ap.parse_args()

    path = Path(args.job_json)
    if not path.is_file():
        print(f"no such file: {path}")
        return 2
    summary = _load(path)
    print(f"\n{path.name} — what the next run would put on the sheet")
    print("=" * 78)
    try:
        if args.prices:
            price_rows(summary)
        else:
            labour_rows(summary)
    except Exception as exc:                                            # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"\n  could not answer from this record: {type(exc).__name__}: {exc}")
        return 1
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
