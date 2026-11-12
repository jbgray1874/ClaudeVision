"""
Diagnostic: show part materials from the scan JSON (not priced estimate_summary only).

Usage:
  python src/diag_parts.py
  python src/diag_parts.py "output/json/your_scan.json"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

json_path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(r"output/json/11367-09-GA - Shelf Lightbox_revD.json")
)
data = json.load(json_path.open(encoding="utf-8"))

mfg_parts = (data.get("manufacturing_writeup") or {}).get("parts") or []
raw_parts = data.get("parts") or []

print(f"JSON: {json_path}")
print(f"manufacturing_writeup[parts]: {len(mfg_parts)}")
print(f"data[parts]: {len(raw_parts)}")

# Priced layer (often flat — no pages/materials)
est_parts = (data.get("estimate_summary") or {}).get("part_estimates") or []
print(f"estimate_summary.part_estimates: {len(est_parts)} (pricing output — may lack pages/materials)")

targets = ["11367-09-08A", "11367-09-06A", "ESSENTRA", "M6 - 6H"]

for label, part_list in [
    ("manufacturing_writeup", mfg_parts),
    ("data[parts]", raw_parts),
]:
    print(f"\n=== {label} ===")
    for pn_target in targets:
        p = next((p for p in part_list if pn_target in str(p.get("part_number", ""))), None)
        if not p:
            continue
        print(f"\n--- {pn_target} ---")
        print("  materials:", p.get("materials"))
        print("  normalized_material:", p.get("normalized_material"))
        print("  page_roles:", p.get("page_roles"))
        print("  pages:", p.get("pages"))
        print("  textual_operations:", p.get("textual_operations"))
        print("  review_flags:", p.get("review_flags"))
