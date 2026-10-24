"""Hold a saved run's LLM read to its calculated workbook, with no run (D-596).

    python tools/read_ledger_audit.py --record output/json/<job>.json --xlsx <book.xlsx>
        [--read cache/vision_concept/<key>.json] [--brief <job folder>/ENQUIRY_BRIEF.txt]
        [--breaks 1000]

read_charge_contract runs in main after Excel on every run that took an LLM read. This runs
the same contract over a run already saved, one taken before the ledger existed included:
the read comes from --read (the concept cache entry that run used, named by the read_key in
<job>_concept_bill.json) or from the record's own kept answer; the brief from --brief; and
the ledger is captured from that answer against the record's parts. The saved workbook's own
cached cells are read with --xlsx; without it nothing is verified against the file.

Read-only. Prints every item's state, the engine's allowances and the verdict, and writes the
result to output/replay/<job>_read_ledger.json. Nothing in the record, the workbook or the
cache is changed, and no model is called.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", required=True, help="the saved run record (output/json/<job>.json)")
    ap.add_argument("--xlsx", help="the calculated workbook that run wrote")
    ap.add_argument("--read", help="the concept cache entry the run used, if the record kept no read")
    ap.add_argument("--brief", help="the enquiry brief the run read, if any")
    ap.add_argument("--breaks", help="quantity breaks for the allowance hours, e.g. 1000")
    ap.add_argument("--out", help="folder for the result (default output/replay)")
    args = ap.parse_args(argv)
    # A FILE NOT THERE IS SAID, NOT A TRACEBACK: the first laptop run stopped on a workbook
    # that had not been copied into the evidence folder.
    for what, given in (("record", args.record), ("workbook", args.xlsx),
                        ("saved read", args.read), ("brief", args.brief)):
        if given and not Path(given).is_file():
            print(f"The {what} is not there: {given} — copy it in and run again. Nothing was "
                  f"audited.")
            return 2

    os.environ.setdefault("SDI_OFFLINE", "1")
    if args.breaks:
        os.environ["SDI_QUANTITY_BREAKS"] = args.breaks
    import concept_scan as cs
    import final_charge_contract as fcc
    import read_charge_contract as rcc

    record_path = Path(args.record)
    summary = json.loads(record_path.read_text(encoding="utf-8"))
    ledger = summary.get("read_ledger") if isinstance(summary.get("read_ledger"), dict) else {}
    if args.read or not ledger.get("items"):
        kept = summary.get("concept_read") if isinstance(summary.get("concept_read"), dict) else {}
        raw, key = str(kept.get("raw_response") or ""), str(kept.get("read_key") or "")
        if args.read:
            entry = json.loads(Path(args.read).read_text(encoding="utf-8"))
            raw, key = str(entry.get("raw_response") or ""), Path(args.read).stem
        answer = cs.parse_concept_response(raw)
        if answer is None:
            print("No read to audit: the record kept no answer and --read gave none that parses.")
            return 2
        brief = Path(args.brief).read_text(encoding="utf-8") if args.brief else ""
        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
        summary["read_ledger"] = rcc.capture(
            answer, records=parts, raw_response=raw, read_key=key, brief=brief,
            set_aside=kept.get("set_aside_undrawn") or [])
        print(f"Ledger captured from the saved answer ({len(raw)} chars, key {key or 'unknown'})")
    snapshot = fcc.snapshot_xlsx(args.xlsx) if args.xlsx else None
    result = rcc.audit(summary, snapshot)

    print(f"\n{'item':24} {'state':11} how")
    for e in result.get("items") or []:
        print(f"{e['id']:24} {e['state']:11} {e['how']}")
        # WHAT THE ITEM IS, as the read put it — so a pasted table can be judged on its own.
        if e.get("label"):
            print(f"{'':36} read as: {str(e['label'])[:110]}")
        if e.get("link"):
            # HOW THE LINE WAS LINKED TO ITS RECORD (D-596e): read_id, fingerprint, name, or
            # ambiguous — so a link by name on an old record is never mistaken for an exact one.
            print(f"{'':36} linked by: {e['link']}")
        if e.get("cells"):
            print(f"{'':36} cells: {', '.join(e['cells'])}")
    print("\nEngine allowances (charges no read item explains):")
    for a in result.get("allowances") or []:
        hours = ", ".join(f"{h:g} h at {q} off" for q, h in (a.get("hours_at") or {}).items())
        print(f"  {a['operation']:20} {a['part']:22} {a['class']:21} "
              f"{a.get('minutes_per_product')} min a unit  {hours}  "
              f"{'HOLDS' if a.get('holds') else 'disclosed'}")
    for line in result.get("engine_lines") or []:
        print(f"  line {line['record']:28} {line['class']:21} "
              f"{'HOLDS' if line.get('holds') else 'disclosed'}  {line['basis']}")
    c = result.get("counts") or {}
    print(f"\n{c.get('charged', 0)} charged, {c.get('covered', 0)} covered, "
          f"{c.get('excluded', 0)} excluded, {c.get('unresolved', 0)} unresolved; facts "
          f"{c.get('carried', 0)} carried, {c.get('corrected', 0)} corrected. "
          f"{'PASSES' if result.get('passed') else 'HOLDS THE RELEASE'} "
          f"({len(result.get('issues') or [])} finding(s)); "
          f"saved workbook {'read' if snapshot else 'NOT read'}.")
    out_dir = Path(args.out) if args.out else ROOT / "output" / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{record_path.stem}_read_ledger.json"
    out.write_text(json.dumps({"ledger": summary["read_ledger"], "result": result}, indent=1,
                              default=str), encoding="utf-8")
    print(f"Written: {out}")
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
