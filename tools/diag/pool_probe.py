"""Which pool is this part actually in? Reads a saved job JSON, writes nothing.

    python tools/diag/pool_probe.py <job.json> [token ...]

Lists every record whose part number contains one of the tokens, in each of the three
pools, with the description and the fields that decide whether passes will match it.

WHY THIS EXISTS. Four defects on this branch have been a correct rule running on the wrong
population: the mirror rollup, the native cut length, the truncated-code merge (twice).
"Where does this record live, and what does it look like there?" is the question that
settles it, and guessing at it has cost more runs than any actual bug.

Descriptions are shown RAW and NORMALISED, because a guard that compares descriptions will
decline a merge over a decoration the sheet does not show — a trailing "- NOT YET PRICED"
looks identical to a person and is a different string to a rule.
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)

doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
tokens = [t.upper() for t in sys.argv[2:]] or [
    "79814", "LOW068", "FIXING", "SCREW", "STD PART"]

POOLS = [
    ("manufacturing_writeup.parts",
     (doc.get("manufacturing_writeup") or {}).get("parts") or []),
    ("parts", doc.get("parts") or []),
    ("estimate_summary.part_estimates",
     (doc.get("estimate_summary") or {}).get("part_estimates") or []),
]


def norm(text):
    return " ".join(str(text or "").upper().split())


print(f"tokens: {', '.join(tokens)}")
for name, pool in POOLS:
    hits = [p for p in pool
            if isinstance(p, dict)
            and any(t in str(p.get("part_number") or "").upper() for t in tokens)]
    print(f"\n=== {name}  ({len(pool)} records, {len(hits)} matching)")
    if not hits:
        print("    (none)")
        continue
    for p in hits:
        pn = str(p.get("part_number") or "")
        raw = str(p.get("description") or "")
        ng = p.get("normalized_geometry") or {}
        blank = (ng.get("blank_length_mm"), ng.get("blank_width_mm"))
        print(f"    {pn!r}")
        print(f"        description raw   {raw!r}")
        print(f"        description norm  {norm(raw)!r}")
        print(f"        quantity          {p.get('quantity')!r}")
        print(f"        stock_form        "
              f"{(p.get('material_estimate') or {}).get('stock_form')!r}")
        print(f"        roles             {p.get('roles') or p.get('page_roles')!r}")
        print(f"        blank             {blank[0]!r} x {blank[1]!r}")
        print(f"        assembly_children {p.get('assembly_children')!r}")

# THE MERGE'S OWN VERDICT, on the pool it actually runs against — so the answer is the
# rule's, not an eyeball's.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from part_identity import stem_duplicate_target
    parts = (doc.get("manufacturing_writeup") or {}).get("parts") or []
    codes = [str(p.get("part_number") or "") for p in parts if isinstance(p, dict)]
    by = {c: p for c, p in zip(codes, parts)}
    print("\n=== what merge_truncated_part_codes would decide (writeup parts)")
    any_hit = False
    for code in codes:
        if not any(t in code.upper() for t in tokens):
            continue
        target = stem_duplicate_target(code, [c for c in codes if c != code])
        if not target:
            print(f"    {code!r:<26} -> no single fuller code (stands alone or ambiguous)")
            continue
        any_hit = True
        keeper = by.get(target) or {}
        same = norm(by.get(code, {}).get("description")) == norm(keeper.get("description"))
        print(f"    {code!r:<26} -> {target!r}  descriptions match: {same}")
        if not same:
            print(f"        this   {norm(by.get(code, {}).get('description'))!r}")
            print(f"        keeper {norm(keeper.get('description'))!r}")
    if not any_hit:
        print("    (no stem/target pair found among these codes in this pool)")
except Exception as exc:                                   # pragma: no cover - diagnostic
    print(f"\n(merge verdict unavailable: {type(exc).__name__}: {exc})")
