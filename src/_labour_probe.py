"""
Read-only. Find where labour operations + hours actually live in the JSON, by
dumping labour_estimate for a few parts. The old xlsx_output.py read ops from
labour_estimate.costs_gbp.keys() — confirm that's where they are.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _labour_probe.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

TARGETS = {"1449-01C", "1455-C-001", "3886-02", "1448-02"}
for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in TARGETS:
        continue
    le = pe.get("labour_estimate") or {}
    pe_proc = pe.get("process_estimate") or {}
    print("="*66)
    print(f"{pn} — {pe.get('description')}")
    print(f"  process_estimate.operations : {pe_proc.get('operations')}")
    print(f"  labour_estimate present?    : {bool(le)}")
    print(f"  labour_estimate keys        : {list(le.keys())}")
    print(f"  costs_gbp                   : {le.get('costs_gbp')}")
    print(f"  hours (any key with 'hour') : { {k:v for k,v in le.items() if 'hour' in k.lower() or 'time' in k.lower()} }")
    print(f"  setup_times_min             : {le.get('setup_times_min')}")
    print(f"  rates (any 'rate' key)      : { {k:v for k,v in le.items() if 'rate' in k.lower()} }")
    # what does a costs_gbp entry look like — op name -> cost?
    cg = le.get("costs_gbp") or {}
    if cg:
        print(f"  >>> operation names (costs_gbp keys): {list(cg.keys())}")
