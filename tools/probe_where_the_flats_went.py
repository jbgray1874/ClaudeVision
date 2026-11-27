"""Ask the record which DXF bound to what, and what happened to the gauges.

WHY THIS EXISTS. On 12349-02 the folder holds seven flats for 01A — `-01 2MM`, `-02 3MM` and
five `5MM` — and the sheet nested four of them as synthesised `01A-DXF…` parts, all at 5 mm,
with the 2 mm and 3 mm nowhere. Two mechanisms would produce that and they need different
fixes:

  A. the flats bound, but the filename gauge was lost on the way, so everything reads 5 mm
  B. the flats never bound, one per bbox cluster was picked and the rest discarded

The filename readers are NOT the problem — `part_number_from_dxf_path`,
`thickness_mm_from_dxf_filename` and `material_from_dxf_filename` were tested against this
pack's real names and return 12349-02-69-01A / 2.0 / HIGH IMPACT ACRYLIC correctly for every
one. So the loss is downstream of reading, and this prints where.

    python tools\\probe_where_the_flats_went.py C:\\ClaudeVision\\output\\json\\12349-02.json 12349-02-69-01A

Read-only. Needs no re-run.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    stem = (sys.argv[2].strip().upper() if len(sys.argv) > 2 else "")
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        doc = json.load(fh)

    parts = ((doc.get("manufacturing_writeup") or {}).get("parts") or [])

    def _match(p):
        pn = str(p.get("part_number") or "").upper()
        return not stem or pn.startswith(stem)

    print(f"\n=== flats and gauges for {stem or 'every part'} in {path}\n")

    print("1. PART RECORDS — what each one thinks its gauge is, and who said so")
    for p in parts:
        if not isinstance(p, dict) or not _match(p):
            continue
        _dxf = p.get("dxf_orphan") or {}
        print(f"   {str(p.get('part_number')):34} gauge={p.get('normalized_thickness_mm')!s:>6} "
              f"from={p.get('thickness_source')!s:<18} mat={str(p.get('normalized_material'))[:18]:<18} "
              f"roles={','.join(str(r) for r in (p.get('page_roles') or []))}")
        if p.get("dxf_source_file") or _dxf.get("path"):
            print(f"        file: {p.get('dxf_source_file') or _dxf.get('path')}")

    print("\n2. SYNTHESISED PARTS — every part minted from a flat rather than bound to a BOM line")
    _minted = [p for p in parts if isinstance(p, dict) and "-DXF" in str(p.get("part_number") or "").upper()]
    if not _minted:
        print("   none")
    for p in _minted:
        print(f"   {str(p.get('part_number')):34} gauge={p.get('normalized_thickness_mm')!s:>6} "
              f"from={p.get('thickness_source')!s:<18} source={p.get('source')}")

    print("\n3. THE MERGE REPORT — what the binder says it did")
    for _key in ("dxf_merge_report", "drawing_job_merge", "dxf_report"):
        _rep = doc.get(_key) or (doc.get("document_analysis") or {}).get(_key)
        if not isinstance(_rep, dict):
            continue
        print(f"   [{_key}]")
        for _k, _v in _rep.items():
            if isinstance(_v, list):
                print(f"     {_k}: {len(_v)}")
                for _e in _v[:12]:
                    print(f"        {json.dumps(_e)[:190] if isinstance(_e, dict) else str(_e)[:190]}")
            elif not isinstance(_v, dict):
                print(f"     {_k}: {str(_v)[:160]}")

    print("\n4. EVERY DXF THE RUN SAW, and whether a part claims it")
    _claimed = set()
    for p in parts:
        if not isinstance(p, dict):
            continue
        for _k in ("dxf_source_file", "dxf_path"):
            if p.get(_k):
                _claimed.add(str(p[_k]))
        _o = p.get("dxf_orphan") or {}
        if _o.get("path"):
            _claimed.add(str(_o["path"]))
    _seen = doc.get("dxf_files") or (doc.get("document_analysis") or {}).get("dxf_files") or []
    if not _seen:
        print("   the record does not list the DXFs it saw under a key this probe knows;")
        print("   the claimed files above are the evidence available")
    for _f in _seen:
        _fp = _f if isinstance(_f, str) else str((_f or {}).get("path") or _f)
        print(f"   {'CLAIMED ' if _fp in _claimed else 'UNCLAIMED'} {_fp}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
