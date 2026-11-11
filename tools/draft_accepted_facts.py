"""Draft accepted_facts.json from an accepted run, for an estimator to review (SCRUM-134).

RUN THIS ON THE BOX, against the archived record of a run an estimator has accepted:

    python tools\\draft_accepted_facts.py 11908-22-GA --source output\\archive\\11908-22-GA_accepted.json

It writes tests\\replay\\11908-22-GA\\accepted_facts.draft.json and prints it. Nothing is
accepted by this tool: the freeze tool refuses to run without accepted_facts.json, and that
file exists only when a person has read the draft, struck or kept each pin, and renamed it.
That is the rule the harness was built on ("an estimator-reviewed file, and this tool will not
invent one"); the draft only saves the typing, and every pin it proposes is read from the
record by the same readers the replay gate runs (costed_facts.costed_job, the canonical route,
outstanding_summary), so a draft can never disagree with what the gate will check.

What it proposes, all STRUCTURE and never money (rates move; identities and routes must not):
  bom_identities         every line on the record, exactly
  quantities             every line's quantity per unit
  required_operations    each line's REQUIRED route operations
  forbidden_operations_anywhere
                         the usual wrong-turn operations that NO line charges on this run
                         (welding, folding, powder coating, ...): review each one, because a
                         pin here says "this job must never be charged this"
  material_charged       made lines whose material money reaches the line
  materials              each made line's material as the accepted run printed it: trim each
                         to the words that matter ("STAINLESS 304"), since a pin holds when
                         every one of its words is on the line
  no_duplicate_operations
                         true: no operation charged on two rows of one part, except the
  allowed_repeats        repeats the accepted run carries, listed for the estimator to confirm
  decisions_expected     the open manufacturing decisions on the accepted run

Review notes go under "_review", which the gate ignores.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "replay"))
REPLAY = ROOT / "tests" / "replay"

# Operations whose wrong appearance has cost money on reviewed jobs; proposed as forbidden
# anywhere only where the accepted run charges none of them.
WRONG_TURN_OPERATIONS = ("welding", "dress_welds", "spot_welding", "folding", "laser_cutting",
                         "powder_coating", "wet_spray", "plating", "hole_machining",
                         "tube_bending", "deburring")


# Lines that are not made here, so carry no material of their own to pin.
NOT_MADE = ("assembly", "commercial", "bought_in", "service", "sheet_row")


def draft(summary: Dict[str, Any]) -> Dict[str, Any]:
    import costed_facts as cf
    from test_frozen_replays import required_ops_for
    record = cf.costed_job(summary)
    lines = [l for l in (record.get("lines") or []) if isinstance(l, dict)]
    ids = sorted({str(l.get("part_number") or "").strip() for l in lines} - {""})
    quantities: Dict[str, float] = {}
    required: Dict[str, List[str]] = {}
    material: List[str] = []
    materials: Dict[str, str] = {}
    repeats: Dict[str, List[str]] = {}
    charged_anywhere: set = set()
    for l in lines:
        pn = str(l.get("part_number") or "").strip()
        if not pn:
            continue
        q = l.get("qty_per_unit")
        if q is not None:
            try:
                quantities[pn] = round(float(q), 4)
            except (TypeError, ValueError):
                pass
        charged_anywhere |= {str(o).lower() for o in (l.get("operations") or [])}
        routed = {str(o).lower() for o in (l.get("route_operations") or [])} \
            or required_ops_for(summary, pn)
        if routed:
            required[pn] = sorted(routed)
        twice = sorted(str(op) for op, n in (l.get("operation_charges") or {}).items()
                       if int(n or 0) > 1)
        if twice:
            repeats[pn] = twice
        if str(l.get("kind") or "") in NOT_MADE:
            continue
        label = " ".join(str(l.get("material_label") or "").split())
        if label:
            materials[pn] = label
        money = l.get("charged_unit_gbp")
        money = money if money is not None else l.get("engine_unit_gbp")
        try:
            if money is not None and float(money) > 0:
                material.append(pn)
        except (TypeError, ValueError):
            pass
    tally = cf.outstanding_summary(summary) or {}
    return {
        "_reviewed": "DRAFT, not reviewed. Strike or keep each pin, add who accepted the run "
                     "and when, then rename this file accepted_facts.json",
        "_review": {
            "record_processed_at": str(summary.get("processed_at") or ""),
            "forbidden_anywhere_why": "proposed because the accepted run charges none of "
                                      "them; keep only those that must never appear on this job",
            "materials_why": "copied from the accepted run's material column; trim each to "
                             "the words that would show a swap",
            "allowed_repeats_why": "operations the accepted run charges on more than one row "
                                   "of one part; keep a repeat only if it is right, otherwise "
                                   "the run was not acceptable",
        },
        "bom_identities": ids,
        "quantities": quantities,
        "required_operations": required,
        "forbidden_operations_anywhere": [op for op in WRONG_TURN_OPERATIONS
                                          if op not in charged_anywhere],
        "material_charged": sorted(material),
        "materials": materials,
        "no_duplicate_operations": True,
        "allowed_repeats": repeats,
        "decisions_expected": int(tally.get("manufacturing") or 0),
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", help="the job's folder name under tests/replay, e.g. 11908-22-GA")
    ap.add_argument("--source", required=True, help="the ACCEPTED run's archived record (.json)")
    a = ap.parse_args(argv)
    src = Path(a.source)
    if not src.is_file():
        print(f"!! {src} is not a file")
        return 2
    summary = json.loads(src.read_text(encoding="utf-8"))
    out_dir = REPLAY / a.job
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / "accepted_facts.json").is_file():
        print(f"!! {out_dir / 'accepted_facts.json'} already exists; a draft would not replace "
              f"it. Edit that file under review instead.")
        return 2
    facts = draft(summary)
    target = out_dir / "accepted_facts.draft.json"
    target.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2, ensure_ascii=False))
    print(f"\nDRAFT written: {target}\nReview every pin, then rename it accepted_facts.json "
          f"and freeze the run with tools\\freeze_replay_fixture.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
