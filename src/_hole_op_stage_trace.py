"""READ-ONLY. Pinpoints WHERE hole_machining survives for 1298-01 after the full run,
by dumping the exact op fields from the persisted JSON (the end-state of the whole
pipeline). No patching, no edits — just reads the JSON the last run wrote.

Three fixes to document_builder haven't stuck, so hole_machining is either (a) set in a
field we're not stripping, or (b) written AFTER document_builder (estimator/reconcile).
This shows every op-bearing field so we can see exactly which one still has it.

Run from C:\ClaudeVision\src (after a fresh 1298 run):
  C:\ClaudeVision\.venv\Scripts\python.exe _hole_op_stage_trace.py
"""
import json
from pathlib import Path

JSON_OUT = Path(r"C:\ClaudeVision\output\json\1298DrillHolder.json")

print("=" * 72)
print("1298-01 op fields in the persisted JSON (pipeline end-state)")
print("=" * 72)

data = json.loads(JSON_OUT.read_text(encoding="utf-8"))

FOUND = []
def walk(o, path=""):
    if isinstance(o, dict):
        pn = o.get("part_number") or o.get("description")
        if pn and ("1298" in str(pn) or "DRILL" in str(pn).upper()):
            FOUND.append((path, o))
        for k, v in o.items():
            walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{path}[{i}]")

walk(data)

if not FOUND:
    print("  No 1298-01 part dict found in JSON — check the JSON path/structure.")
else:
    for path, part in FOUND:
        pn = part.get("part_number") or part.get("description")
        print(f"\n  PART: {pn}   (at {path})")
        # every field that might carry ops
        for field in ("operations", "textual_operations", "operations_from_notes",
                      "inferred_operations", "routing"):
            val = part.get(field)
            if val is not None:
                has = "hole_machining" in json.dumps(val)
                flag = "  <<< HAS hole_machining" if has else ""
                print(f"    {field:22} = {val}{flag}")
        mi = part.get("manufacturing_interpretation") or {}
        if mi:
            rt = [s.get("operation") for s in (mi.get("routing") or [])]
            has = "hole_machining" in rt
            print(f"    mfg_interp.routing     = {rt}{'  <<< HAS hole_machining' if has else ''}")
        # also show labour/priced ops if present
        for field in ("priced_operations", "labour_lines", "operation_costs"):
            val = part.get(field)
            if val is not None:
                has = "hole_machining" in json.dumps(val)
                if has:
                    print(f"    {field:22} <<< HAS hole_machining")

print("\n" + "=" * 72)
print("READ: whichever field above shows '<<< HAS hole_machining' is the surviving")
print("source. If it's ONLY in a labour/priced/routing field (not textual/operations),")
print("then it's re-derived during ESTIMATION from the hole geometry (hole_sizes 4.0/8.0,")
print("estimated_hole_count 3) — the fix belongs in the estimator's op-routing, not")
print("document_builder. That would explain why 3 document_builder edits didn't stick.")
