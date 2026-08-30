"""Show the DXF picture for the pooled 1282 job: which parts got real DXF flat-pattern
geometry vs PDF fallback, and the augmentation report (matched / unmatched / skipped /
ambiguous). Reads the existing PRECACHE JSON — no re-run. Run on the laptop:
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_audit.py
"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
d = json.load(open(PATH, encoding="utf-8"))

# 1. Augmentation report — the authoritative matched/unmatched/skipped breakdown
aug = d.get("dxf_augmentation") or {}
print("=== DXF augmentation report ===")
for k in ("matched","unmatched_dxf","ambiguous_dxf","orphan_dxf_promoted","skipped","parts_without_dxf"):
    v = aug.get(k) or []
    print(f"  {k}: {len(v)}")
    for item in v:
        if isinstance(item, dict):
            label = item.get("part_number") or item.get("path") or item
            reason = item.get("reason","")
            print(f"      - {label}  {reason}")

# 2. Per-part: DXF or PDF geometry?
parts = (d.get("manufacturing_writeup") or {}).get("parts") or []
print(f"\n=== per-part geometry source ({len(parts)} parts) ===")
print(f"{'part':<14}{'source':<20}{'rel':>5}{'cut_mm':>9}{'bends':>6}{'holes':>6}")
for p in parts:
    pn = str(p.get("part_number") or "?")[:13]
    g = p.get("geometry_rollup") or {}
    src = str(p.get("geometry_source") or "?")[:19]
    rel = (g.get("confidence") or {}).get("geometry_reliability")
    rel = f"{rel:.2f}" if isinstance(rel,(int,float)) else "?"
    cut = g.get("estimated_cut_length_mm") or 0
    bends = g.get("estimated_bend_line_count") or 0
    holes = g.get("estimated_hole_count") or g.get("estimated_pierce_count") or 0
    dxf_aug = "DXF" if p.get("dxf_augmented") else ""
    print(f"{pn:<14}{src:<20}{rel:>5}{cut:>9.0f}{bends:>6}{holes:>6}  {dxf_aug}")