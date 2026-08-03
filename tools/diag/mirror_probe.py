"""Why did the mirrored part not inherit its rollup? Reads a saved job JSON only."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
pools = [("manufacturing_writeup.parts",
          (doc.get("manufacturing_writeup") or {}).get("parts") or []),
         ("parts", doc.get("parts") or []),
         ("estimate_summary.part_estimates",
          (doc.get("estimate_summary") or {}).get("part_estimates") or [])]

WANT = ("11350-01-02", "11350-01-02 MIR", "11350-01-02MIR")
for name, pool in pools:
    print(f"\n=== {name} ({len(pool)} records)")
    for p in pool:
        pn = str(p.get("part_number") or "")
        if pn not in WANT:
            continue
        ng = p.get("normalized_geometry") or {}
        gr = p.get("geometry_rollup") or {}
        print(f"  {pn}")
        print(f"     geometry_source     {ng.get('geometry_source') or p.get('geometry_source')}")
        print(f"     mirrored_from       {ng.get('mirrored_from')}")
        print(f"     blank keys          {[k for k in ng if 'blank' in k or 'developed' in k or 'bounding' in k]}")
        print(f"     perimeter_mm        {ng.get('perimeter_mm')}")
        print(f"     geometry_rollup     {'ABSENT' if not gr else sorted(gr)[:8]}")
        print(f"     cut_length_mm       {gr.get('cut_length_mm') or gr.get('estimated_cut_length_mm')}")
        print(f"     hole/pierce count   {gr.get('estimated_hole_count')} / {gr.get('estimated_pierce_count')}")
        print(f"     bend_count_dxf      {p.get('bend_count_dxf')}")
        _f = [str(x)[:70] for x in (p.get("review_flags") or []) if "MIRROR" in str(x).upper()]
        print(f"     mirror flags        {_f or 'none'}")
