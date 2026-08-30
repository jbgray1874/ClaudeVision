#!/usr/bin/env python3
r"""
_apply_assembly_level_finish.py

THE MODELLING GAP

The powder gate is PER-PART. But a finish is applied to the OBJECT THAT GOES THROUGH THE
BOOTH, and that object is often an ASSEMBLY, not a part.

7670: you form raw wire, weld the frame, THEN coat the finished frame.

    page 2/3/4 (details):  SURFACE FINISH: RAW              <- correct
    page 1     (assembly): POWDER COATED - FINE TEXTURE     <- the thing that gets coated

The drawings are right. The engine is not: it sees three RAW parts, drops powder on all
three, and loses Tim's £1.92 of P.Coat. RAW on a DETAIL is not the same as RAW on the
finished product.

THE TRAP IN THE OBVIOUS FIX  (probed before patching, unlike four earlier fixes today)

1282 has exactly the same shape — RAW children, coated parent:

    1455-C-001..004   RAW              <- welded into...
    1455-C-101        POWDER COATED    <- ...the header weldment

But 1282's P.Coat group ALREADY contains 9 parts INCLUDING the weldment 1455-C-101. If we
naively flip its four RAW children to "coated", we would hang ONE OBJECT FIVE TIMES.

THE DISCRIMINATOR

Apply the rule ONLY when NOTHING ELSE in the job qualifies for powder.

    7670  nothing is coated  -> the RAW parts ARE what goes through the booth. Coat them.
    1282  nine parts coated  -> the weldment already represents its children. Leave them.

Conservative, correct on both known cases, and it cannot double-coat.

AND THE QUANTITY FALLS OUT OF IT

When the coat happens at ASSEMBLY level, the quantity is 1 — ONE welded frame on the hook,
not three loose components. That is precisely what Tim books:

    Tim:  P.Coat  qty 1  1276/hr  setup 15  ->  £1.92

With qty 1 and our measured 458/hr default we land at ~£2.55. Over by 33%, and the reason
is known and named: Tim's 1276/hr reflects small wire parts hanging many-per-bar, which coat
far faster than sheet. One P.Coat throughput cannot serve both. That is a real finding, not
a fudge factor — and it is flagged rather than tuned away.

WHAT THIS DOES *NOT* FIX

The powder MATERIAL (Tim £0.40) is still £0. The workbook's Powder Qty Calculator sums
SHEET AREA over the steel block; a wire frame has no sheet area and lives in a different
block, so it can never contribute. That needs the coverage rate resolved first —
powder_rule.sql. This patch flags the uncosted area loudly instead of guessing at it.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_assembly_level_finish.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_assembly_level_powder"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


OLD_GATE = '''        elif _fin_u:
            _powder_ok[_pn] = False      # RAW / SCRAPED EDGES / etc — explicit
        else:
            _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)'''

NEW_GATE = '''        elif _fin_u:
            _powder_ok[_pn] = False      # RAW / SCRAPED EDGES / etc — explicit
        else:
            _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)

    # ── ASSEMBLY-LEVEL FINISH ────────────────────────────────────────────────────
    # A finish belongs to the OBJECT THAT GOES THROUGH THE BOOTH, and that object is often
    # an ASSEMBLY, not a part. On 7670 you form raw wire, weld the frame, THEN coat it:
    #
    #     details  (pages 2-4): SURFACE FINISH: RAW            <- correct
    #     assembly (page 1)   : POWDER COATED - FINE TEXTURE   <- the thing that gets coated
    #
    # The drawings are right; the per-part gate is not. It saw three RAW parts, dropped
    # powder on all three, and lost Tim's £1.92 of P.Coat.
    #
    # THE TRAP: 1282 has the same shape — 1455-C-001..004 are RAW and are welded into
    # 1455-C-101, which IS powder coated. But 1282's P.Coat group already contains nine
    # parts INCLUDING that weldment. Flipping its four RAW children to "coated" would hang
    # ONE OBJECT FIVE TIMES.
    #
    # So: apply this ONLY when NOTHING ELSE in the job qualifies for powder.
    #     7670  nothing coated -> the RAW parts ARE what goes through the booth. Coat them.
    #     1282  nine coated    -> the weldment already represents its children. Leave them.
    _assembly_level_powder = False
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


OLD_QTY = '''        _qty = 1 if wb_op in _PACK_OPS else int(g["qty"] or 1)'''

NEW_QTY = '''        # Assemble/pack is PER PRODUCT: you pack the finished product once, not once per part.
        # P.Coat is the same WHEN THE COAT HAPPENS AT ASSEMBLY LEVEL: one welded frame goes
        # on the hook, not three loose components. Tim books exactly that — P.Coat qty 1.
        # (When the parts themselves carry POWDER, they are coated individually before
        #  assembly and the per-part count is right — so this only applies to the
        #  assembly-level case.)
        _qty = 1 if (wb_op in _PACK_OPS
                     or (wb_op == "P.Coat" and _assembly_level_powder)) else int(g["qty"] or 1)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    src = sub(src, OLD_GATE, NEW_GATE, "RAW components of a coated assembly ARE coated")
    src = sub(src, OLD_QTY, NEW_QTY, "assembly-level P.Coat is hung as ONE object (qty 1)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_asmfinish_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670 (Tim £6.74):
    * flag: "ASSEMBLY-LEVEL FINISH: every detail says RAW, the assembly says POWDER..."
    * ONE P.Coat row, qty 1        ~£2.55      (Tim £1.92)
    * unit cost  £4.84 -> ~£7.39   (Tim £6.74, +10%)

    The +33% on P.Coat is NAMED, not mysterious: Tim books 1276/hr, our measured default is
    458/hr. Small wire parts hang many-per-bar and coat far faster than sheet — ONE P.Coat
    throughput cannot serve both. Flagged, not tuned away.

    STILL A NAMED GAP: powder MATERIAL £0 vs Tim's £0.40. The workbook's Powder Qty
    Calculator sums SHEET area over the steel block; a wire frame has no sheet area and sits
    in a different block, so it can never contribute. That needs the coverage rate resolved
    (powder_rule.sql) — the template's 0.167 kg/m2 assumes 100% transfer, and Tim's sheets
    book 2.7x to 10x more.

REGRESSIONS — BOTH MUST BE UNCHANGED:
    1310  £9.07   — its parts carry POWDER via a SEE-ASSEMBLY pointer, so something already
                    qualifies and the new rule must NOT fire. If P.Coat qty flips to 1, the
                    discriminator is wrong: revert.
    1282  £207.16 — nine parts already coated, so the rule must NOT fire and the four RAW
                    weldment children must STAY uncoated. If P.Coat moves, we are hanging one
                    object five times: revert.
""")


if __name__ == "__main__":
    main()
