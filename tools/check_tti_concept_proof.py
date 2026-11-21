"""Check a concept proof before the full batch may start. Reads only; exit 0 only when every check holds.

    python -B tools/check_tti_concept_proof.py --sheet <tracker> --shared-root <UNC root> --rows 6,12

For each proof row, on BOTH archives (local and shared):
  * the durable state says the row is done, with a run and a unit price;
  * every picture the plan found for the row was archived and was named in the request sent;
  * the request's units are the row's effective quantity;
  * a workbook, exactly one engine record and the price audit are there;
and in the tracker itself the row's AiCost cell now holds that unit price.
A proof row that had pictures but sent none, or a price that reached the sheet without both
archives, fails here, and the full batch must not start.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_concept_batch as batch  # noqa: E402
from tti_concept_inputs import read_plan  # noqa: E402

INPUT_NAMES = {"source-row.json", "ENQUIRY_BRIEF.txt", "request.json"}


def check(sheet, local_root, shared_root, rows, sheet_name="Milwaukee", out=print):
    key = batch.sha(str(Path(sheet).resolve()).casefold().encode())[:20]
    roots = [Path(local_root) / key, Path(shared_root) / key]
    ok = True

    def say(good, text):
        nonlocal ok
        ok = ok and bool(good)
        out(("OK    " if good else "FAIL  ") + text)

    states = [batch.read_json(r / "state.json") if (r / "state.json").is_file() else None for r in roots]
    say(all(states) and states[0] == states[1], "the local and shared ledgers exist and agree")
    if not ok:
        return False
    plan = batch.read_json(roots[0] / "plan.json")
    now_plan, _ = read_plan(sheet, sheet_name, assume_missing_quantity_one=bool(plan.get("assume_missing_quantity_one")))
    live = {r["row"]: r for r in now_plan["rows"]}
    for row in rows:
        item = next((r for r in plan["rows"] if r["row"] == row), None)
        if item is None:
            say(False, f"row {row}: not in the plan")
            continue
        entry = states[0]["entries"].get(item["reference"], {})
        say(entry.get("phase") == "done" and entry.get("run_id") and entry.get("unit_gbp"),
            f"row {row}: done, run {entry.get('run_id')}, unit GBP {entry.get('unit_gbp')} (phase {entry.get('phase')})")
        for root in roots:
            where = "local" if root == roots[0] else "shared"
            base = root / item["reference"]
            pics = [f for f in (base / "inputs").iterdir() if f.name not in INPUT_NAMES] if (base / "inputs").is_dir() else []
            req = batch.read_json(base / "inputs" / "request.json") if (base / "inputs" / "request.json").is_file() else {}
            say(len(pics) == len(item["images"]) == len(req.get("files") or []),
                f"row {row} ({where}): {len(item['images'])} picture(s) in the plan, {len(pics)} archived, "
                f"{len(req.get('files') or [])} sent")
            say(req.get("units") == item["quantity"],
                f"row {row} ({where}): priced at quantity {req.get('units')}"
                + (" (assumed one)" if item.get("quantity_assumed") else ""))
            res = base / "results"
            names = [f.name for f in res.iterdir()] if res.is_dir() else []
            say(any(n.lower().endswith(".xlsx") for n in names)
                and sum(n.lower().endswith("_record.json") for n in names) == 1
                and "price-for-writeback.json" in names,
                f"row {row} ({where}): workbook, engine record and price audit archived ({len(names)} file(s))")
        cell = live.get(row, {}).get("cost_before")
        try:
            same = abs(float(cell) - float(entry.get("unit_gbp"))) < 0.005
        except (TypeError, ValueError):
            same = False
        say(same, f"row {row}: AiCost {item.get('cost_cell')} holds {cell!r}")
    out("PROOF CHECK OK" if ok else "PROOF CHECK FAILED")
    return ok


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sheet", required=True)
    p.add_argument("--sheet-name", default="Milwaukee")
    p.add_argument("--local-root", default=str(ROOT / "output" / "tti_concepts"))
    p.add_argument("--shared-root", required=True)
    p.add_argument("--rows", required=True)
    a = p.parse_args(argv)
    return 0 if check(a.sheet, a.local_root, a.shared_root, [int(v) for v in a.rows.split(",")], a.sheet_name) else 1


if __name__ == "__main__":
    sys.exit(main())
