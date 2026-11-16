"""Why does a saved record's money differ from the accepted figures? Arithmetic, not narrative.

    python tools\\explain_money_gap.py output\\archive\\json\\7332-01_v0013_2026-09-07_14-06-13.json ^
        --material 40.89 --labour 33.59 --unit 80.09

THE QUESTION THIS ANSWERS. v0013 of 7332-01 carries material GBP 34.96 and labour GBP 50.09,
while the accepted 14:17 workbook and its covering email say GBP 40.89 and GBP 33.59. The timing
says v0013 is the run behind that workbook; the money says it is not. One of those has to give,
and which one matters: if the record simply predates two corrections then it is a pre-fix run
and not the accepted baseline at all, and no amount of hashing makes it one.

So this reports, per block and per line, where the record's money actually sits, and then tests
two specific hypotheses by arithmetic rather than by assertion:

    LABOUR IS TOO HIGH   because operations the accepted workbook excluded are charged here.
                         Powder is the candidate: review found 7332-01's plated and Harrods-1
                         finishes read as powder, and that fix landed after 7 September.
    MATERIAL IS TOO LOW  because a part is on NO priced workbook row, so its stock never
                         reaches the material total. diagnose_operations_gap.py showed exactly
                         that for 7332-01-002: the route requires tubebend and the part is
                         charged on nothing.

If removing the first and adding the second closes the gap, the record is a pre-fix run and the
two known defects explain it. If it does not close, something else moved and the remainder is
named rather than rounded away. A residual this tool cannot account for is the interesting
output, not a failure of the tool.

It changes nothing and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Operations whose presence in a record but absence from an accepted workbook would raise
# labour. Named, not guessed: each is a finish SDI charges in the labour block.
FINISH_OPS = ("powder_coating", "powder", "wet_spray", "anodising", "plating")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(line: Dict[str, Any]) -> float:
    charged = line.get("charged_ext_gbp")
    return _num(charged if charged is not None else line.get("engine_ext_gbp"))


def explain(path: Path, want: Dict[str, Optional[float]], divisor: float) -> int:
    import costed_facts as cf
    record = json.loads(path.read_text(encoding="utf-8"))
    costed = cf.costed_job(record) or {}
    run = costed.get("run") or {}
    lines = [l for l in (costed.get("lines") or []) if isinstance(l, dict)]

    print(f"== {path.name} ==")
    print(f"   processed_at {record.get('processed_at') or '(none)'}")
    print(f"   order_qty    {run.get('order_qty')}")
    print()

    print("1 · what this record says the money is")
    engine_material = run.get("material_gbp")
    engine_labour = run.get("labour_gbp")
    print(f"      material {engine_material if engine_material is not None else '(no total)'}")
    print(f"      labour   {engine_labour if engine_labour is not None else '(no total)'}")
    print(f"      source   {run.get('totals_source')}")
    if engine_material is None:
        print("      !! this record carries no final_estimate.totals, so the figures below come")
        print("         from the engine's own line sums and are NOT the workbook's arithmetic")
    print()

    # ── every line, with its money and its operations ──────────────────────────
    print("2 · lines, money and operations")
    total_charged = 0.0
    finish_money = 0.0
    finish_lines: List[str] = []
    unpriced_parts: List[str] = []
    for line in sorted(lines, key=lambda l: -_money(l)):
        pn = str(line.get("part_number") or "?")
        money = _money(line)
        total_charged += money
        ops = [str(o).lower() for o in (line.get("operations") or [])]
        routed = [str(o).lower() for o in (line.get("route_operations") or [])]
        hit = sorted({o for o in ops + routed if any(f in o for f in FINISH_OPS)})
        if hit:
            finish_money += money
            finish_lines.append(f"{pn} ({', '.join(hit)}) {money:.2f}")
        rows = cf.priced_rows_for_part(record, pn) or []
        flag = ""
        if not rows:
            unpriced_parts.append(pn)
            flag = "   <- on NO priced workbook row"
        print(f"      {pn:22s} {money:9.2f}  kind={str(line.get('kind') or '-'):12s} "
              f"charged={ops or '[]'}")
        if routed and routed != ops:
            print(f"      {'':22s} {'':9s}  route requires={routed}{flag}")
        elif flag:
            print(f"      {'':22s} {'':9s} {flag}")
    print(f"      {'TOTAL':22s} {total_charged:9.2f}")
    print()

    # ── hypothesis 1: a finish is charged that the accepted workbook excluded ───
    print("3 · finish operations charged in this record")
    if finish_lines:
        for item in finish_lines:
            print(f"      {item}")
        print(f"      total on lines carrying a finish: {finish_money:.2f}")
        print("      (the whole line's money, not the finish's share — a line can carry other")
        print("       work too, so treat this as an upper bound on what removing it would save)")
    else:
        print("      none")
    print()

    # ── hypothesis 2: a part charged on nothing ────────────────────────────────
    print("4 · parts the route requires work on, charged on no priced row")
    stranded: List[str] = []
    for line in lines:
        pn = str(line.get("part_number") or "")
        routed = [str(o).lower() for o in (line.get("route_operations") or [])]
        if pn in unpriced_parts and routed:
            stranded.append(f"{pn}  route requires {routed}  money on the line {_money(line):.2f}")
    if stranded:
        for item in stranded:
            print(f"      {item}")
        print("      A part on no priced row contributes no stock to the material total, which")
        print("      is the shape of a material figure that is too LOW.")
    else:
        print("      none")
    print()

    # ── the gap, and whether the two hypotheses close it ───────────────────────
    print("5 · against the accepted figures")
    have = {"material_gbp": engine_material, "labour_gbp": engine_labour,
            "unit_gbp": run.get("unit_gbp")}
    for key, label in (("material_gbp", "material"), ("labour_gbp", "labour"),
                       ("unit_gbp", "unit")):
        target = want.get(key)
        got = have.get(key)
        if target is None:
            continue
        if got is None:
            print(f"      {label:9s} accepted {target:8.2f}   record has no total to compare")
            continue
        print(f"      {label:9s} accepted {target:8.2f}   record {got:8.2f}   "
              f"difference {got - float(target):+8.2f}")

    if want.get("material_gbp") is not None and want.get("labour_gbp") is not None:
        accepted_sum = float(want["material_gbp"]) + float(want["labour_gbp"])
        print()
        print(f"      accepted material + labour = {accepted_sum:.2f}")
        if divisor:
            print(f"      / {divisor} absorption divisor = {accepted_sum / divisor:.2f}"
                  f"   (accepted unit {want.get('unit_gbp')})")
        if engine_labour is not None and finish_money:
            print(f"      record labour {engine_labour:.2f} less finish-bearing lines "
                  f"{finish_money:.2f} = {engine_labour - finish_money:.2f}")
            residual = (engine_labour - finish_money) - float(want["labour_gbp"])
            print(f"      vs accepted labour {float(want['labour_gbp']):.2f} -> residual "
                  f"{residual:+.2f}")
            if abs(residual) > 0.5:
                print(f"      THE RESIDUAL IS THE INTERESTING NUMBER. Removing the finish does "
                      f"not account")
                print(f"      for the difference on its own, so something else moved between "
                      f"this record")
                print(f"      and the accepted workbook. Do not treat the two as the same run.")
    print()
    print("   Nothing has been changed or written. These are the record's own figures; the")
    print("   accepted ones are whatever was passed in.")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("record", help="path to a saved run's JSON")
    ap.add_argument("--material", type=float, default=None, help="accepted material total")
    ap.add_argument("--labour", type=float, default=None, help="accepted labour total")
    ap.add_argument("--unit", type=float, default=None, help="accepted unit price")
    ap.add_argument("--divisor", type=float, default=0.93,
                    help="absorption divisor used to get unit from material+labour")
    args = ap.parse_args(argv[1:])
    path = Path(args.record)
    if not path.is_file():
        print(f"!! {path} not found")
        return 2
    return explain(path, {"material_gbp": args.material, "labour_gbp": args.labour,
                          "unit_gbp": args.unit}, args.divisor)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
