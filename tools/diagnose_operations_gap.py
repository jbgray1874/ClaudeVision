"""Where does a part's operation list lose its operations between the route and the record?

    python tools\\diagnose_operations_gap.py output\\archive\\json\\7332-01_v0013_2026-09-07_14-06-13.json 7332-01-002

WHY THIS EXISTS AS A TOOL AND NOT AS A GUESS. The canonical route records tubebend on
7332-01-002 and costed_job() publishes `operations: []` for the same part. There are four
places that can happen and they need four different repairs, so naming the stage matters more
than having a theory:

    1  the route never recorded it             -> a compiler problem
    2  the decision is recorded but not
       `required`                              -> a status problem, and an unverified decision
                                                  SHOULD NOT satisfy a required-operation pin
    3  no workbook row carries the part        -> the part never reached the sheet
    4  rows carry the part but no decision_ids -> the join that costed_facts depends on is
                                                  missing, which is the likeliest one: its
                                                  docstring says it reads decisions "taken from
                                                  the workbook rows rather than the decision
                                                  list directly, so it names only decisions that
                                                  survived every gate and reached the sheet"

This walks the same functions costed_facts uses, in order, and prints what each one returns. It
changes nothing. Run it on the accepted record and the answer is the stage whose output is empty
while the stage before it was not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _decisions(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every canonical decision, under either spelling and either nesting."""
    out: List[Dict[str, Any]] = []
    for holder in (record, record.get("estimate_summary") or {}):
        if not isinstance(holder, dict):
            continue
        for key in ("canonical_route_shadow", "canonical_route"):
            payload = holder.get(key)
            if isinstance(payload, dict):
                for decision in (payload.get("decisions") or []):
                    if isinstance(decision, dict) and decision not in out:
                        out.append(decision)
    return out


def diagnose(path: Path, part_number: str) -> int:
    record = json.loads(path.read_text(encoding="utf-8"))
    want = str(part_number).strip().upper()
    print(f"== {path.name} / {part_number} ==")
    print(f"   processed_at {record.get('processed_at') or '(none)'}")
    print()

    # ── STAGE 0: did the workbook stage write anything back into this record? ───
    # This is upstream of everything below and explains three symptoms at once, so it runs
    # first. priced_rows_for_part reads `final_estimate.labour_rows` joined to
    # `workbook_labour.rows` — the latter is where part_numbers and decision_ids live. If
    # neither is present then the record is a PRE-WORKBOOK artefact: it holds what the engine
    # handed TO Excel, not what Excel produced. Then, necessarily and all from one cause:
    #
    #   · no final_estimate.totals  -> no unit/material/labour, so the accepted figures are
    #                                  not in the record and cannot be checked against it
    #   · no priced rows            -> no decision ids to read, so every part's `operations`
    #                                  is empty however good the route is
    #   · no link to the workbook   -> the engine's own line sums are a DIFFERENT calculator
    #                                  from the sheet's, so a difference between them is not a
    #                                  defect in either; they measure different things
    print("0 · did the workbook stage write back into this record?")
    fe = record.get("final_estimate")
    if not isinstance(fe, dict) and isinstance(record.get("estimate_summary"), dict):
        fe = record["estimate_summary"].get("final_estimate")
    fe = fe if isinstance(fe, dict) else {}
    wl = record.get("workbook_labour")
    if not isinstance(wl, dict) and isinstance(record.get("estimate_summary"), dict):
        wl = record["estimate_summary"].get("workbook_labour")
    wl = wl if isinstance(wl, dict) else {}
    labour_rows = fe.get("labour_rows") if isinstance(fe.get("labour_rows"), list) else None
    accepted_rows = wl.get("rows") if isinstance(wl.get("rows"), list) else None
    totals = fe.get("totals") if isinstance(fe.get("totals"), dict) else None
    totals_note = ("present: " + ", ".join(sorted(totals))) if totals else "ABSENT"
    labour_note = f"{len(labour_rows)} row(s)" if labour_rows is not None else "ABSENT"
    accepted_note = f"{len(accepted_rows)} row(s)" if accepted_rows is not None else "ABSENT"
    print(f"      final_estimate.totals      {totals_note}")
    print(f"      final_estimate.labour_rows {labour_note}")
    print(f"      workbook_labour.rows       {accepted_note}")
    if not labour_rows and not accepted_rows:
        print()
        print("      -> STAGE 0. Neither is present, so this record is a PRE-WORKBOOK artefact:")
        print("         it holds what the engine handed TO Excel, not what Excel produced. That")
        print("         one fact explains three symptoms at once — no accepted totals to check")
        print("         against, no priced rows so every part's operations is empty, and no link")
        print("         between the saved JSON and the accepted workbook. The engine's line sums")
        print("         and the sheet's arithmetic are DIFFERENT CALCULATORS, so a difference")
        print("         between them is not a defect in either figure.")
        print("         Everything below is reported for completeness, but the repair is here:")
        print("         the read-back has to write its totals and row grouping into the record.")
        print()

    # ── which route payloads exist at all ──────────────────────────────────────
    print("1 · route payloads present")
    for holder_name, holder in (("(top level)", record),
                                ("estimate_summary", record.get("estimate_summary") or {})):
        if not isinstance(holder, dict):
            continue
        for key in ("canonical_route_shadow", "canonical_route"):
            payload = holder.get(key)
            if isinstance(payload, dict):
                n = len(payload.get("decisions") or [])
                err = payload.get("compiler_error")
                print(f"      {holder_name}.{key}: {n} decision(s)"
                      + (f"  COMPILER ERROR: {err}" if err else ""))
            elif key in holder:
                print(f"      {holder_name}.{key}: present but not an object")
    if not _decisions(record):
        print("      -> NO decisions anywhere. Stage 1: the route was never recorded in this")
        print("         record, so nothing downstream can carry an operation.")
        return 0

    # ── this part's decisions, and their statuses ──────────────────────────────
    print()
    print(f"2 · decisions naming {part_number}")
    mine: List[Dict[str, Any]] = []
    for decision in _decisions(record):
        targets = {str(decision.get("part_number") or "").strip().upper(),
                   str(decision.get("target_id") or "").strip().upper()}
        targets |= {str(p).strip().upper() for p in (decision.get("participants") or [])}
        if want in targets - {""}:
            mine.append(decision)
            print(f"      {str(decision.get('operation') or '?'):20s} "
                  f"status={str(decision.get('status') or '(none)'):16s} "
                  f"scope={str(decision.get('scope') or '-'):10s} "
                  f"id={str(decision.get('decision_id') or '(none)')[:24]}")
    if not mine:
        print(f"      -> none. Stage 1: the route records nothing for this part.")
        return 0
    required = [d for d in mine if str(d.get("status") or "").strip().lower() == "required"]
    if not required:
        print(f"      -> {len(mine)} decision(s) but NONE with status 'required'. Stage 2: an")
        print(f"         unverified decision must not satisfy a required-operation pin, so this")
        print(f"         is a status problem, not a plumbing one.")

    # ── the rows costed_facts reads from ───────────────────────────────────────
    print()
    print("3 · priced workbook rows for this part")
    try:
        import costed_facts as cf
        rows = cf.priced_rows_for_part(record, part_number) or []
    except Exception as err:                                             # noqa: BLE001
        print(f"      could not read rows: {type(err).__name__}: {err}")
        return 1
    print(f"      {len(rows)} row(s)")
    if not rows:
        print("      -> Stage 3: the part is on no priced row, so costed_facts has nothing to")
        print("         read decision ids FROM. Its operations will be empty however good the")
        print("         route is.")
    with_ids = 0
    for row in rows:
        ids = [str(d) for d in (row.get("decision_ids") or []) if d]
        if not ids and row.get("decision_id"):
            ids = [str(row["decision_id"])]
        if ids:
            with_ids += 1
        print(f"      row {str(row.get('row_label') or row.get('block') or '?')[:28]:30s} "
              f"decision_ids={ids or '[]'}")
    if rows and not with_ids:
        print("      -> Stage 4: rows exist but carry NO decision_ids. This is the join")
        print("         costed_facts depends on, and it is missing. The route is fine; the")
        print("         workbook rows were written without the ids that tie them to it.")

    # ── what the two readers actually return ───────────────────────────────────
    print()
    print("4 · what the readers return")
    try:
        ids = cf.decision_ids_for_part(record, part_number) or []
        print(f"      decision_ids_for_part     -> {ids or '[]'}")
    except Exception as err:                                             # noqa: BLE001
        print(f"      decision_ids_for_part     -> ERROR {type(err).__name__}: {err}")
    try:
        ops = cf._operations_from_decisions(record, part_number) or []
        print(f"      _operations_from_decisions -> {ops or '[]'}")
    except Exception as err:                                             # noqa: BLE001
        print(f"      _operations_from_decisions -> ERROR {type(err).__name__}: {err}")
    try:
        costed = cf.costed_job(record) or {}
        line = next((l for l in (costed.get("lines") or [])
                     if str(l.get("part_number") or "").upper() == want), None)
        print(f"      costed line operations     -> "
              f"{(line or {}).get('operations') if line else 'NO LINE FOR THIS PART'}")
    except Exception as err:                                             # noqa: BLE001
        print(f"      costed_job                 -> ERROR {type(err).__name__}: {err}")

    print()
    print("   The stage to repair is the first one above whose output is empty while the stage")
    print("   before it was not. Nothing here has been changed or written.")
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print(__doc__.strip().splitlines()[0])
        print()
        print("   usage: python tools/diagnose_operations_gap.py RECORD.json PART-NUMBER")
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"!! {path} not found")
        return 2
    return diagnose(path, argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
