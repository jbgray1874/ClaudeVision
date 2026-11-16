"""Who actually wrote this number? Reads a saved job JSON, writes nothing.

    python tools/diag/field_source_probe.py <job.json> <part_code> [field ...]

Prints each field's value AND the source apply_field recorded beside it, across all three
record pools. Defaults to the fields that drive the laser and fold rows.

WHY THIS EXISTS. Four defects on this branch have had the same shape: a rule that is
correct, runs, and is then overwritten or bypassed by a later writer — the mirror rollup,
the material placeholder, the native cut length. "Did my pass apply?" and "is my value on
the sheet?" are different questions, and only the recorded source can tell them apart:

  source == the pass you expect   -> it applied, and something LATER overwrote it by direct
                                     assignment, bypassing the resolver
  source == something else        -> it was refused on rank; that source outranked yours
  source absent, value present    -> whoever wrote it never went through the resolver at all
  value absent                    -> the pass never reached this record
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 3:
    sys.exit(__doc__)

DEFAULT_FIELDS = [
    "geometry_rollup.estimated_cut_length_mm",
    "geometry_rollup.estimated_hole_count",
    "geometry_rollup.estimated_pierce_count",
    "geometry_rollup.estimated_bend_line_count",
    "normalized_geometry.cut_length_mm",
    "normalized_geometry.hole_count",
    "normalized_geometry.blank_length_mm",
    "normalized_geometry.blank_width_mm",
    "normalized_material",
    "normalized_thickness_mm",
]

doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
want = "".join(sys.argv[2].split()).upper()
fields = sys.argv[3:] or DEFAULT_FIELDS

# The source key convention apply_field uses: "<leaf>_source", with three fields overridden.
SOURCE_KEY = {"normalized_material": "material_source",
              "quantity": "quantity_source",
              "normalized_thickness_mm": "thickness_source"}

POOLS = [("manufacturing_writeup.parts",
          (doc.get("manufacturing_writeup") or {}).get("parts") or []),
         ("parts", doc.get("parts") or []),
         ("estimate_summary.part_estimates",
          (doc.get("estimate_summary") or {}).get("part_estimates") or [])]

MISSING = object()


def _dig(rec, dotted):
    node = rec
    parts = dotted.split(".")
    for key in parts[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return MISSING, MISSING, None
    leaf = parts[-1]
    if not isinstance(node, dict) or leaf not in node:
        return MISSING, MISSING, node if isinstance(node, dict) else None
    skey = SOURCE_KEY.get(leaf, f"{leaf}_source")
    return node.get(leaf), node.get(skey, MISSING), node


def _show(v):
    return "ABSENT" if v is MISSING else repr(v)


print(f"part: {sys.argv[2]}")
for name, pool in POOLS:
    hits = [p for p in pool
            if "".join(str(p.get("part_number") or "").split()).upper() == want]
    print(f"\n=== {name} ({len(pool)} records, {len(hits)} matching)")
    for rec in hits:
        for f in fields:
            value, source, node = _dig(rec, f)
            if value is MISSING and source is MISSING:
                continue
            verdict = ""
            if value is not MISSING and source is MISSING:
                verdict = "  <- NO SOURCE RECORDED: written outside the resolver"
            print(f"  {f:52s} = {_show(value):<14s} source={_show(source)}{verdict}")
        # Anything else in the same dict that carries a source, so a field this probe does
        # not know about still shows up rather than being invisible.
        for f in fields:
            _, _, node = _dig(rec, f)
            if not isinstance(node, dict):
                continue
            extra = sorted(k for k in node
                           if k.endswith("_source") and k not in
                           {SOURCE_KEY.get(x.split(".")[-1], x.split(".")[-1] + "_source")
                            for x in fields})
            if extra:
                print(f"     other sourced fields here: "
                      f"{', '.join(f'{k}={node[k]!r}' for k in extra[:6])}")
            break
