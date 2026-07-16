#!/usr/bin/env python3
r"""
_apply_powder_gate_excludes_boughtin.py

WHY IT STILL DID NOT FIRE — and the clue was that NEITHER diagnostic printed.

If _assembly_is_powder had been False, my new flag would have said so. If no part's finish
read RAW, the other flag would have printed the finishes it saw. Neither appeared. So the
whole block was SKIPPED, which means:

        any(_powder_ok.values())  ==  True

Something in this job already looked "coated". It was the POWDER ITSELF.

    parts[3]   part_number:      None
               page_roles:       ["bought_in"]
               surface_finishes: ["POWDER COATED - FINE TEXTURE"]

The RYOBI GREEN BOM line contains the word POWDER — of course it does, IT IS POWDER. With
part_number=None it registered in the gate as _powder_ok[""] = True. The job therefore
looked like it already had a coated part, and the assembly-level rule stood down.

A TIN OF PAINT WAS COUNTED AS A PAINTED OBJECT.

THE FIX

A bought-in consumable is not a fabricated part and cannot be the thing that goes through the
booth. Skip records with no part number, or with a bought_in page role, when building the
powder gate.

WHY THIS IS SAFE FOR THE REGRESSIONS

1282 and 1310 have their coated parts under REAL part numbers (1449-01C, 1455-C-101, 1310-01
...), so excluding blank-PN bought-in stubs cannot change either. Bought-in parts do not
generate fabrication labour rows in the first place (labour_parts excludes the BOM bucket
apart from tubes), so nothing downstream loses a row.

GENERAL: any job carrying a powder CODE in its BOM would have had this bug — the code would
mask the assembly-level rule on every one of them.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_powder_gate_excludes_boughtin.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_pg_roles_boughtin"

OLD = '''    for _mp in _mw_parts:
        _pn = str(_mp.get("part_number") or "")
        _fin = str(_mp.get("normalized_finish") or "").strip()'''

NEW = '''    for _mp in _mw_parts:
        _pn = str(_mp.get("part_number") or "")
        # ── A TIN OF PAINT IS NOT A PAINTED OBJECT ───────────────────────────────────
        # The bought-in powder line (TLP-J125-T RYOBI GREEN) carries
        # surface_finishes = ["POWDER COATED - FINE TEXTURE"] — of course it does, IT IS
        # POWDER — and its part_number is None. It was landing in the gate as
        # _powder_ok[""] = True, so the job LOOKED like it already had a coated part. That
        # silently suppressed the assembly-level finish rule (and both of its diagnostics),
        # and cost 7670 its entire £1.92 of P.Coat.
        #
        # A bought-in consumable is not a fabricated part and cannot be the thing that goes
        # through the booth. Any job carrying a powder CODE in its BOM had this bug.
        _pg_roles_boughtin = [str(_r).lower() for _r in (_mp.get("page_roles") or [])]
        if (not _pn) or ("bought_in" in _pg_roles_boughtin):
            continue
        _fin = str(_mp.get("normalized_finish") or "").strip()'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    if "_fin_by_pn" not in src:
        sys.exit("Run _apply_assembly_finish_fix.py first.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match, found {n}. Nothing written.")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_powdergate_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  bought-in / no-part-number records excluded from the powder gate")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670 (Tim £6.74):
    * flag: "ASSEMBLY-LEVEL FINISH: every detail says RAW, the assembly drawing says POWDER
             ... P.Coat applied ONCE, to one object (7670-01-001, -002, -003)"
    * ONE P.Coat row, qty 1   ~£2.55     (Tim £1.92 — his 1276/hr vs our 458/hr default;
                                          small wire parts hang many-per-bar. NAMED, not tuned.)
    * unit cost  £4.84 -> ~£7.39         (Tim £6.74)

REGRESSIONS — BOTH MUST BE UNCHANGED. Their coated parts carry REAL part numbers, so
excluding blank-PN bought-in stubs cannot reach them:
    1310  £9.07     (stud £0.04)
    1282  £207.16   (materials frozen; the four RAW weldment children stay uncoated)
""")


if __name__ == "__main__":
    main()
