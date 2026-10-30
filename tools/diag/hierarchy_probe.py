"""Is the assembly tree in the extract, and does it name this job's parts? Reads only.

EITHER FILE WORKS, and which one you have decides which question gets answered:

    python tools/diag/hierarchy_probe.py <job.json>
        What the run DECIDED. Reads the verdict the pass stamped onto the job — the tree it
        built, the edge count, which reader supplied each edge, the reason when it applied
        nothing, and which nodes the invariants still call disconnected. No extract needed
        and nothing to re-run: the answer is already in the file the estimate wrote.

    python tools/diag/hierarchy_probe.py <_sw_native_extract.json> [job.json]
        What the models CARRY. Per assembly record: its title, BOM line count, parent/child
        EDGE count, and how many of its BOM lines name a parent. Then the connector's own
        parser over the same file, so the tree shown is the tree the estimate would get.
        Given a job JSON as well, it says which of those parent codes exist among the job's
        parts — the difference between "the models describe no tree" and "the models
        describe a tree about codes this job does not use".

The file type is detected, not declared. Someone diagnosing a problem should not have to
know the answer in order to ask the question.

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

# ── A SAVED JOB ALREADY CARRIES THE ANSWER ───────────────────────────────────────────
# The pass stamps its verdict onto the job — the tree it built, the edge count, which
# reader supplied each edge, and, when it applied nothing, the reason. So the ordinary
# question ("why was there no hierarchy on this run?") is answerable from the file the run
# already wrote, with no extract to locate and nothing to re-run. Handed a job JSON, this
# reads that record instead of parsing an extract.
if isinstance(doc, dict) and ("manufacturing_writeup" in doc or "estimate_summary" in doc):
    print(f"job: {extract_path.name}\n")
    _sw = doc.get("solidworks_native") or {}
    if not _sw:
        print("solidworks_native: ABSENT — no extract was applied to this job at all.")
    else:
        print(f"solidworks_native.found       {_sw.get('found')}")
        print(f"  extract_path                {_sw.get('extract_path')}")
        print(f"  refused_wrong_job           {_sw.get('refused_wrong_job')}")
        print(f"  hierarchy_edges             {_sw.get('hierarchy_edges')}")
        print(f"  hierarchy_sources           {_sw.get('hierarchy_sources')}")
        for _p, _kids in sorted((_sw.get("hierarchy") or {}).items()):
            print(f"      {_p!r} holds {', '.join(f'{c} x{q:g}' for c, q in _kids)}")
        _applied = _sw.get("hierarchy_applied")
        if _applied is not None:
            print(f"  stamped onto {len(_applied)} part(s)")
            for _a in _applied:
                print(f"      {_a['part_number']} <- {', '.join(_a['children'])}")

    # THE REASON, IN THE ESTIMATOR'S OWN RECORD. Written to review_flags rather than only to
    # a console, because an unattended run leaves no console behind.
    _flags = [f for f in (doc.get("review_flags") or [])
              if "hierarchy" in str(f).lower()]
    print("\nreview flags mentioning hierarchy:")
    for _f in _flags or ["    (none — the pass either applied a tree or did not run)"]:
        print(f"    {_f}")

    # AND WHAT IS STILL DISCONNECTED, which is the symptom the tree exists to cure.
    _viol = [v for v in ((doc.get("invariants") or {}).get("violations") or [])
             if "disconnected" in str(v.get("code", "")).lower()]
    if _viol:
        print("\nstill disconnected:")
        for _v in _viol:
            print(f"    [{_v.get('severity')}] {_v.get('code')}: {_v.get('message')}")
            _d = _v.get("detail") or {}
            if _d:
                print(f"        detail: {json.dumps(_d)[:600]}")

    _parts = (doc.get("manufacturing_writeup") or {}).get("parts") or []
    _kids = [(p.get("part_number"), p.get("assembly_children"))
             for p in _parts if isinstance(p, dict) and p.get("assembly_children")]
    print(f"\nparts carrying assembly_children: {len(_kids)} of {len(_parts)}")
    for _pn, _cs in _kids:
        print(f"    {_pn} -> {', '.join(str(c) for c in _cs)}")
    raise SystemExit(0)
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
