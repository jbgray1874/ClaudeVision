#!/usr/bin/env python3
r"""
_probe_powder_finish.py  —  READ-ONLY.

TWO JOBS, ONE GATE, OPPOSITE VERDICTS — and we must not "fix" one by breaking the other.

  1282: the gate drops powder on EIGHT parts. That is very likely CORRECT and deliberate —
        it is last week's phantom-P.Coat kill (13 P.Coat lines -> 4). The sheet shows
        exactly 4 P.Coat lines and 0.9097 kg powder material at £9.73 = £8.85. Working.

  1310: the gate drops powder on the ONLY part. That is WRONG — Tim charges £2.00 P.Coat
        + £0.30 powder material. The detail drawing says:
              SURFACE FINISH: SEE ASSEMBLY DRAWING
        i.e. the finish is a POINTER to the assembly, and the gate reads a pointer as
        "no finish".

HYPOTHESIS: the gate is right to drop RAW / weldment / assembly-rollup parts, but wrong to
drop parts whose finish text merely POINTS at the assembly. The fix is to RESOLVE the
pointer (inherit the assembly's finish), not to loosen the gate.

BEFORE PATCHING we must know what the dropped parts actually carry. If 1282's eight parts
ALSO say "SEE ASSEMBLY DRAWING", then resolving the pointer would resurrect the 13 phantom
P.Coat lines we killed last week — and the fix needs to be narrower still.

This probe prints, for BOTH jobs, every part with:
    surface_finishes (raw), normalized_finish, page_roles, is weldment?, has DXF?
and marks which ones the gate dropped powder on.

Usage:
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_powder_finish.py
"""
from __future__ import annotations
import json, glob, os

JOBS = {
    "1282 (gate drops 8 — believed CORRECT)": "*1282*",
    "1310 (gate drops 1 — believed WRONG)":  "*1310*",
}
JSON_DIR = r"C:\ClaudeVision\output\json"

POINTER_HINTS = ("SEE ASSEMBLY", "SEE GA", "AS ASSEMBLY", "PER ASSEMBLY", "REFER TO ASSEMBLY")
POWDER_HINTS = ("POWDER", "P.COAT", "PCOAT", "POWDERCOAT")


def main():
    print("POWDER-GATE FINISH PROBE  (read-only)")
    print("Question: do the powder-dropped parts carry a FINISH, a POINTER, or nothing?\n")

    for label, pat in JOBS.items():
        cands = glob.glob(os.path.join(JSON_DIR, pat + ".json"))
        if not cands:
            print(f"!! no JSON for {label} ({pat})")
            continue
        path = max(cands, key=os.path.getmtime)

        print("=" * 100)
        print(label)
        print(os.path.basename(path))
        print("=" * 100)

        data = json.load(open(path, "r", encoding="utf-8"))
        parts = data.get("parts") or data.get("part_estimates") or []

        # document-level finish (what a pointer SHOULD resolve to)
        doc_fin = (data.get("document_analysis") or {}).get("surface_finishes") \
                  or data.get("surface_finishes") or []
        print(f"\n  DOCUMENT-LEVEL finish: {doc_fin}")
        print(f"  parts: {len(parts)}\n")

        hdr = f"  {'part':<16} {'norm_finish':<16} {'raw surface_finishes':<40} {'roles':<22} flags"
        print(hdr)
        print("  " + "-" * (len(hdr) + 10))

        for p in parts:
            pn = str(p.get("part_number") or "")[:15]
            nf = str(p.get("normalized_finish") or "-")[:15]
            raw = p.get("surface_finishes") or []
            raw_s = ", ".join(str(x) for x in raw)[:39] or "-"
            roles = ",".join(p.get("page_roles") or [])[:21] or "-"

            blob = (raw_s + " " + nf).upper()
            marks = []
            if any(h in blob for h in POINTER_HINTS):
                marks.append("<<POINTER")
            if any(h in blob for h in POWDER_HINTS):
                marks.append("POWDER")
            if not raw:
                marks.append("no-finish")
            if p.get("assembly_candidate"):
                marks.append("assembly")
            if p.get("flat_pattern_detected") or p.get("dxf_augmented"):
                marks.append("dxf")
            if "bought_in" in (p.get("page_roles") or []):
                marks.append("bought-in")

            print(f"  {pn:<16} {nf:<16} {raw_s:<40} {roles:<22} {' '.join(marks)}")

        print()

    print("""
====================================================================================
READ THIS CAREFULLY

  If 1310's part shows  <<POINTER  and 1282's eight dropped parts show  no-finish /
  assembly / weldment  (and NOT <<POINTER), then the fix is clean and narrow:

      resolve "SEE ASSEMBLY DRAWING" to the document/assembly finish,
      and leave every other gate decision exactly as it is.

  1282 keeps its 4 P.Coat lines. 1310 gets its powder back. Nothing else moves.

  If 1282's dropped parts ALSO carry a POINTER, STOP — resolving pointers would
  resurrect the 13 phantom P.Coat lines killed last week (-£105). We would then need a
  narrower rule (e.g. resolve the pointer only when the part has its own DXF/flat
  pattern, i.e. it is a real fabricated part rather than an assembly rollup).
====================================================================================
""")


if __name__ == "__main__":
    main()
