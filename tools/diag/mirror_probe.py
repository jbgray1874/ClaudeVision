"""Where did a mirrored part's evidence stop? Reads a saved job JSON, writes nothing.

    python tools/diag/mirror_probe.py <job.json> [part_code ...]

With no part codes it finds the handed pairs itself — every record whose code the naming
conventions read as a mirror — and reports each one beside the part it mirrors. Name codes
explicitly to look at a pair the conventions do not recognise.

The three pools are the point. A mirrored part's geometry is filled on the RAW record and
the workbook reads only the COSTED one, so "the rule ran" and "the sheet saw it" are
different questions, and for three runs of job 11350 they had different answers.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from part_code_conventions import mirror_base
except Exception:                                    # run from a checkout without src/
    mirror_base = lambda _s: ""                      # noqa: E731

if len(sys.argv) < 2:
    sys.exit(__doc__)

doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
POOLS = [("manufacturing_writeup.parts",
          (doc.get("manufacturing_writeup") or {}).get("parts") or []),
         ("parts", doc.get("parts") or []),
         ("estimate_summary.part_estimates",
          (doc.get("estimate_summary") or {}).get("part_estimates") or [])]


def _codes(p):
    return str(p.get("part_number") or "")


def _norm(s):
    return "".join(str(s or "").split()).upper()


# WHICH PARTS TO LOOK AT. Named on the command line, or every mirror the conventions find
# plus whatever each one says it mirrors — including a part that only declares its seed in
# `mirrored_from`, which is the case a naming rule alone would miss.
wanted = [a for a in sys.argv[2:]]
if not wanted:
    seen = []
    for _name, pool in POOLS:
        for p in pool:
            pn = _codes(p)
            base = mirror_base(pn) or (p.get("normalized_geometry") or {}).get("mirrored_from")
            if not base:
                continue
            for c in (base, pn):
                if c and _norm(c) not in {_norm(x) for x in seen}:
                    seen.append(c)
    wanted = seen

if not wanted:
    sys.exit("no mirrored parts found — name part codes explicitly to probe a pair the "
             "naming conventions do not recognise")

WANT = {_norm(w) for w in wanted}
print(f"probing: {', '.join(wanted)}")

for name, pool in POOLS:
    print(f"\n=== {name} ({len(pool)} records)")
    hits = 0
    for p in pool:
        pn = _codes(p)
        if _norm(pn) not in WANT:
            continue
        hits += 1
        ng = p.get("normalized_geometry") or {}
        gr = p.get("geometry_rollup") or {}
        print(f"  {pn}")
        print(f"     geometry_source     {ng.get('geometry_source') or p.get('geometry_source')}")
        print(f"     mirrored_from       {ng.get('mirrored_from')}")
        print(f"     blank keys          {[k for k in ng if 'blank' in k or 'developed' in k or 'bounding' in k]}")
        print(f"     perimeter_mm        {ng.get('perimeter_mm')}")
        print(f"     geometry_rollup     {'ABSENT' if not gr else sorted(gr)[:8]}")
        # Both spellings of each datum, and which record answered — the sheet asks
        # normalized_geometry first and the rollup only where it is silent, so a value
        # present in one and not the other is the whole story.
        for label, names in (("cut length", ("cut_length_mm", "estimated_cut_length_mm")),
                             ("hole count", ("hole_count", "estimated_hole_count")),
                             ("pierce count", ("pierce_count", "estimated_pierce_count"))):
            _ng_v = next((ng.get(n) for n in names if ng.get(n) is not None), None)
            _gr_v = next((gr.get(n) for n in names if gr.get(n) is not None), None)
            print(f"     {label:<12}        ng={_ng_v}  rollup={_gr_v}")
        print(f"     bend_count_dxf      {p.get('bend_count_dxf')}")
        _f = [str(x)[:70] for x in (p.get("review_flags") or []) if "MIRROR" in str(x).upper()]
        print(f"     mirror flags        {_f or 'none'}")
    if not hits:
        print("  (none of the probed codes appear in this pool)")
