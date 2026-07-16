"""
READ-ONLY. Trace why 1455-C-005 (HEADER LENS) ends up normalized_material=None
despite 'MATERIAL: HIPS' on page 16. Reads the run JSON and shows the fields that
drive material assignment, so we fix the real cause not a guess.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _lens_material_trace.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))

# Find the lens part wherever it lives
def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)

lens = None
for d in walk(data):
    if str(d.get("part_number") or "") == "1455-C-005":
        lens = d
        break

if not lens:
    print("Lens 1455-C-005 not found in JSON"); raise SystemExit

print("=== 1455-C-005 HEADER LENS — material-driving fields ===\n")
for k in ("part_number", "description", "materials", "normalized_material",
          "normalized_thickness_mm", "thicknesses", "material_inherited_from",
          "dxf_augmented", "flat_pattern_detected", "pages", "page_roles",
          "textual_operations", "inferred_operations", "review_flags"):
    print(f"  {k:26} : {lens.get(k)}")

# The material_estimate carries the pricing path result
me = lens.get("material_estimate") or {}
print("\n=== material_estimate ===")
for k in ("material", "thickness_mm", "cost_method", "cost_per_part_gbp",
          "extended_material_cost_gbp", "note"):
    print(f"  {k:26} : {me.get(k)}")

# Does the DXF filename carry HIPS + thickness? (augmentation source)
print("\n=== dxf / augmentation hints ===")
for k in ("dxf_file", "dxf_source", "dxf_path", "source_dxf", "augmented_from"):
    if lens.get(k):
        print(f"  {k:26} : {lens.get(k)}")
aug = lens.get("dxf_augmentation") or lens.get("augmentation") or {}
if aug:
    print(f"  augmentation keys          : {list(aug.keys())}")
