"""Is the assembly tree in the extract, and does it name this job's parts? Reads only.

    python tools/diag/hierarchy_probe.py <_sw_native_extract.json> [job.json]

Prints, per assembly record in the extract: its title, how many BOM lines it reports, how
many parent/child EDGES it carries, and how many of its BOM lines name a parent. Then runs
the connector's own parser over the file and shows the tree it builds — so the answer comes
from the code the estimate uses, not from an eyeball on JSON.

Given a saved job JSON as well, it also says which of those parent codes exist among the
job's parts, which is the difference between "the models describe no tree" and "the models
describe a tree about codes this job does not use".

WHY THIS EXISTS. The hierarchy pass printed nothing for several runs, and nothing is the
one output that names no cause: an absent extract, a refused extract, an extract with no
edges, and edges about other codes all looked identical from the console. Each of those
needs a different fix and only one of them is a code change.
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)

SW_ASM = 2
extract_path = Path(sys.argv[1])
doc = json.loads(extract_path.read_text(encoding="utf-8"))
records = doc.get("records") if isinstance(doc, dict) else doc
if not isinstance(records, list):
    records = (doc.get("results") or doc.get("files") or []) if isinstance(doc, dict) else []

print(f"extract: {extract_path}")
print(f"records: {len(records)}")

asm = [r for r in records if isinstance(r, dict) and int(r.get("doctype") or 1) == SW_ASM]
print(f"assembly documents: {len(asm)}")
if not asm:
    print("  -> the extract opened no .SLDASM. There is no tree to read; this is not a "
          "wiring fault.")

for r in asm:
    edges = r.get("assembly_edges")
    bom = r.get("bom") or []
    with_parent = [b for b in bom
                   if isinstance(b, dict) and str(b.get("parent_part_number") or "").strip()]
    print(f"\n  {r.get('title')!r}")
    print(f"      assembly_part_number  {r.get('assembly_part_number')!r}")
    print(f"      bom lines             {len(bom)}")
    print(f"      bom lines with parent {len(with_parent)}")
    if edges is None:
        print("      assembly_edges        KEY ABSENT — extract predates the analyser change")
    else:
        print(f"      assembly_edges        {len(edges)}")
        for e in (edges or [])[:12]:
            if isinstance(e, dict):
                print(f"          {e.get('parent')!r} -> {e.get('child')!r} "
                      f"qty={e.get('qty')} cfg={e.get('config')!r}")

# THE CONNECTOR'S OWN VERDICT, so the tree shown is the tree the estimate would get.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
try:
    from source_connectors.solidworks import native_extract_for_job
    job = native_extract_for_job(json_path=str(extract_path), run=False)
except Exception as exc:                                   # pragma: no cover - diagnostic
    print(f"\n(connector parse failed: {type(exc).__name__}: {exc})")
    raise SystemExit(1)

print(f"\n=== connector verdict")
print(f"found              {job.found}")
print(f"top_assembly       {job.meta.get('top_assembly')!r}")
print(f"hierarchy_edges    {job.meta.get('hierarchy_edges')}")
print(f"hierarchy_sources  {job.meta.get('hierarchy_sources')}")
for parent, kids in sorted((job.hierarchy or {}).items()):
    print(f"    {parent!r} holds {', '.join(f'{c} x{q:g}' for c, q in kids)}")
if not job.hierarchy:
    print("    (no edges)")

if len(sys.argv) < 3:
    raise SystemExit(0)

# DOES THE TREE NAME THIS JOB'S PARTS? An edge about a code the job does not carry stamps
# nothing, and looks exactly like no edge at all from the estimate's side.
job_doc = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
parts = (job_doc.get("manufacturing_writeup") or {}).get("parts") or []
codes = {str(p.get("part_number") or "").strip().upper() for p in parts if isinstance(p, dict)}
codes.discard("")
print(f"\n=== against {Path(sys.argv[2]).name}  ({len(codes)} part codes)")
for parent, kids in sorted((job.hierarchy or {}).items()):
    hit = parent.strip().upper() in codes
    kid_hits = [c for c, _ in kids if c.strip().upper() in codes]
    print(f"    parent {parent!r} in job: {hit}   children in job: "
          f"{len(kid_hits)}/{len(kids)}")
if job.hierarchy and not any(p.strip().upper() in codes for p in job.hierarchy):
    print("    -> every parent the models name is absent from the job's parts. The stamp "
          "has nothing to attach to; this is a part-code convention gap, not a tree gap.")
