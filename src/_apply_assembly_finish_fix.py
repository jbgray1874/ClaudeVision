#!/usr/bin/env python3
r"""
_apply_assembly_finish_fix.py

WHY THE LAST PATCH DID NOT FIRE

No ASSEMBLY-LEVEL FINISH flag, powder still dropped on all three parts, £4.84 unchanged.

The gate resolves a part's finish with a FALLBACK:

    _fin = str(_mp.get("normalized_finish") or "").strip()
    if not _fin:
        _fin = " ".join(str(x) for x in (_mp.get("surface_finishes") or [])).strip()
    _fin_u = _fin.upper()

My _raw_components comprehension, twenty lines later, checked ONLY normalized_finish.

7670's parts carry their finish in surface_finishes (normalized_finish is None — exactly as
the powder record did). So my list came back empty and the rule never ran.

Reading the same value two different ways, twenty lines apart. It is the same disease as the
other four half-applied fixes today, just at a smaller scale: A VALUE WITH NO SINGLE HOME.

THE FIX

Resolve the finish ONCE, into _fin_by_pn, and read it from there in both places. The two
readers can no longer disagree because there is only one reader.

AND A DIAGNOSTIC, so there is no third blind attempt

If the rule still does not fire, the console will now say precisely why:
  * no assembly page states a POWDER finish, or
  * the assembly IS powder, nothing else qualifies, but no part's finish reads RAW —
    and it will PRINT THE FINISHES IT ACTUALLY SAW.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_assembly_finish_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_fin_by_pn"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# 1. declare the single store
OLD_DECL = '''    _mw_parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _powder_ok = {}'''

NEW_DECL = '''    _mw_parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _powder_ok = {}
    # Resolve each part's finish ONCE, here, and let every later reader use this. The last
    # attempt at the assembly-level rule re-derived the finish from normalized_finish alone
    # and missed the surface_finishes fallback below — so it silently found nothing and did
    # nothing. One value, one home.
    _fin_by_pn = {}'''


# 2. populate it inside the existing loop
OLD_FIN = '''        _fin_u = _fin.upper()'''
NEW_FIN = '''        _fin_u = _fin.upper()
        _fin_by_pn[_pn] = _fin_u'''


# 3. replace the broken assembly-level block with one that reads the single store
OLD_BLOCK = '''    _assembly_level_powder = False
    if _assembly_is_powder and not any(_powder_ok.values()):
        _raw_components = [
            _pn2 for _pn2, _ok in _powder_ok.items()
            if not _ok and _pn2 and "RAW" in (
                str(next((_m.get("normalized_finish") or "") for _m in _mw_parts
                         if str(_m.get("part_number") or "") == _pn2), "")
            ).upper()
        ]
        if _raw_components:
            _assembly_level_powder = True
            for _pn2 in _raw_components:
                _powder_ok[_pn2] = True
            _flag(f"ASSEMBLY-LEVEL FINISH: every detail says RAW, the assembly drawing says "
                  f"POWDER. The components are formed raw, welded, and the ASSEMBLY is coated "
                  f"({', '.join(_raw_components)}). P.Coat applied once, to one object — not "
                  f"once per component.", flags)'''

NEW_BLOCK = '''    _assembly_level_powder = False
    if not any(_powder_ok.values()):
        if not _assembly_is_powder:
            _flag("nothing in this job carries a POWDER finish, and no assembly page states "
                  "one either. If the product IS coated, the drawing does not say so — raise "
                  "with Design. NOT coating anything, and not guessing.", flags)
        else:
            # Read the finish from the ONE place it was resolved. (The previous attempt
            # re-derived it from normalized_finish only, missed the surface_finishes
            # fallback, found nothing, and failed silently.)
            _raw_components = [
                _pn2 for _pn2, _ok in _powder_ok.items()
                if (not _ok) and _pn2 and "RAW" in _fin_by_pn.get(_pn2, "")
            ]
            if _raw_components:
                _assembly_level_powder = True
                for _pn2 in _raw_components:
                    _powder_ok[_pn2] = True
                _flag(f"ASSEMBLY-LEVEL FINISH: every detail says RAW, the assembly drawing "
                      f"says POWDER. The components are formed raw, welded, and the ASSEMBLY "
                      f"is coated ({', '.join(_raw_components)}). P.Coat applied ONCE, to one "
                      f"object — not once per component.", flags)
            else:
                # Loud, specific, and it prints what it actually saw. No third blind attempt.
                _flag(f"assembly drawing says POWDER and nothing else in the job qualifies, "
                      f"but no part's finish reads RAW. Finishes seen: "
                      f"{ {k: (v[:24] or '<empty>') for k, v in _fin_by_pn.items()} }. "
                      f"NOT coating anything. Check the drawing finish fields.", flags)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    if "_assembly_level_powder" not in src:
        sys.exit("Run _apply_assembly_level_finish.py first — its block is the anchor.")

    src = sub(src, OLD_DECL,  NEW_DECL,  "declare _fin_by_pn (one home for the resolved finish)")
    src = sub(src, OLD_FIN,   NEW_FIN,   "populate it in the gate loop")
    src = sub(src, OLD_BLOCK, NEW_BLOCK, "assembly-level rule reads the single store + diagnostics")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_asmfinishfix_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670 (Tim £6.74):
    * flag: "ASSEMBLY-LEVEL FINISH: every detail says RAW, the assembly drawing says POWDER
             ... P.Coat applied ONCE, to one object"
    * ONE P.Coat row, qty 1     ~£2.55       (Tim £1.92)
    * unit cost  £4.84 -> ~£7.39             (Tim £6.74)

IF IT STILL DOES NOT FIRE, the console now says WHY and prints the finishes it saw. No third
blind attempt.

REGRESSIONS — BOTH MUST BE UNCHANGED:
    1310  £9.07   — parts carry POWDER via a SEE-ASSEMBLY pointer, so something already
                    qualifies and the rule must NOT fire.
    1282  £207.16 — nine parts already coated; the four RAW weldment children must STAY
                    uncoated, or we are hanging one object five times.
""")


if __name__ == "__main__":
    main()
