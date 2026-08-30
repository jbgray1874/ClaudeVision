#!/usr/bin/env python3
r"""
_apply_spotweld_only_when_all_wire.py

THE REGRESSION I CAUSED

1310 moved £9.07 -> £8.12, and the delta is exactly one line:

    was:  Weld (CO2)   29/hr   £41.77/hr  ->  £1.86
    now:  Spotweld     51/hr   £32.90/hr  ->  £0.97
                                              ------
                                              -£0.89   = the ENTIRE change

Everything else held byte-for-byte (wire £0.04, fold £0.84, laser £1.08, P.Coat £3.33 qty 2,
Robomac £0.20, pack £0.64), and the assembly-level finish discriminator behaved exactly as
designed: 1310's parts resolve to POWDER via the SEE-ASSEMBLY pointer, so something already
qualified and the new rule correctly stood down.

WHY THE CHANGE IS WRONG

1310-02 is an 8mm ROUND STUD welded to a 2mm HOOK PLATE. You cannot spot-weld that. Spot
welding squeezes two thin overlapping sheets between electrodes. A bar-to-plate joint is MIG
or a stud weld.

I had evidence from ONE job — 7670, where every part is 4mm wire and Tim spotwelds — and
generalised it to "any part with stock_form=wire". It caught the stud, and the NUMBER moved
closer to Tim's £1.25 while the PHYSICS got worse. That is exactly the trade we keep saying
we will not make: a lucky match that hides a wrong model.

THE DISTINGUISHER: WHAT IS BEING JOINED

    7670   3 wire, 0 sheet   wire -> wire    SPOTWELD   (Tim confirms: buttweld + spotweld)
    1310   1 wire, 1 sheet   bar  -> plate   CO2
    1282   all sheet         sheet-> sheet   CO2

The engine cannot see which part is welded to which — the joint list is not in the geometry.
So the honest rule is the conservative one: only call it Spotweld when EVERYTHING fabricated
in the job is wire/bar. The moment there is sheet in the job, we cannot tell what the wire is
being welded to, and CO2 (the more expensive, more general process) is the safe assumption.

When the job is mixed, say so out loud rather than picking silently.

RESTORES 1310 TO £9.07 EXACTLY. 7670 keeps its Spotweld.

STILL OPEN, AND IT IS A QUESTION FOR TIM, NOT A PATCH:
    1310 weld  £1.86 (ours) vs £1.25 (Tim)  — setup minutes, most likely
    7670 weld  £2.91 (ours) vs £1.61 (Tim)  — Tim writes TWO rows for a three-part frame,
                                              so it is per WELD TYPE. How many welds a frame
                                              needs is his judgement, and it is not in the
                                              geometry. Do not invent a rule for it.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_spotweld_only_when_all_wire.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_all_fabricated_are_wire"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# 1. compute the job-level fact, once, before the labour loop
OLD_DECL = '''    _PACK_OPS = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)"}'''

NEW_DECL = '''    _PACK_OPS = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)"}

    # ── YOU CANNOT SPOT-WELD A BAR TO A PLATE ────────────────────────────────────
    # Spot welding squeezes two thin OVERLAPPING SHEETS between electrodes. 7670 is three
    # 4mm wire forms welded to each other — Tim spotwelds it (buttweld 150/hr + spotweld
    # 45/hr). 1310-02 is an 8mm ROUND STUD welded to a 2mm HOOK PLATE — that is MIG/stud
    # weld, not spot weld.
    #
    # I generalised from 7670 to "any part with stock_form=wire" and it caught 1310's stud:
    # the number moved closer to Tim's £1.25 while the PHYSICS got worse. A lucky match
    # hiding a wrong model is the one thing worse than an honest gap.
    #
    # The engine cannot see WHICH part is welded to which — the joint list is not in the
    # geometry. So the honest rule is the conservative one: Spotweld only when EVERYTHING
    # fabricated in the job is wire/bar. The moment there is sheet present, we cannot tell
    # what the wire is being joined to, and CO2 is the safe assumption.
    _fab_forms = [
        str((_p.get("material_estimate") or {}).get("stock_form") or "").lower()
        for _p in labour_parts
    ]
    _all_fabricated_are_wire = bool(_fab_forms) and all(
        _f in ("wire", "bar") for _f in _fab_forms
    )
    if (not _all_fabricated_are_wire) and any(_f in ("wire", "bar") for _f in _fab_forms):
        _flag("welding: this job mixes wire/bar with sheet, and the drawing does not say "
              "which parts are joined to which. Assuming Weld (CO2) — a wire-to-wire joint "
              "would be Spotweld and cheaper. Estimator to check.", flags)'''


# 2. gate the mapping on it
OLD_MAP = '''            # 4mm wire frames go on the SPOT WELDER, not the CO2 torch.
            # Engine: Weld (CO2) 29/hr, £41.77/hr -> £6.18.  Tim: Spotweld -> £1.61.
            if wb_op == "Weld (CO2)" and str(_sf or "").lower() == "wire":
                wb_op = "Spotweld"'''

NEW_MAP = '''            # Wire frames go on the SPOT WELDER — but ONLY when the whole job is wire.
            # 7670 (3 wire forms welded to each other): Spotweld, £1.61 on Tim's sheet.
            # 1310 (8mm stud welded to a 2mm plate):    CO2 — you cannot spot-weld a bar
            #                                           to a plate, whatever the number says.
            if (wb_op == "Weld (CO2)"
                    and str(_sf or "").lower() in ("wire", "bar")
                    and _all_fabricated_are_wire):
                wb_op = "Spotweld"'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    src = sub(src, OLD_DECL, NEW_DECL, "job-level: are ALL fabricated parts wire/bar?")
    src = sub(src, OLD_MAP,  NEW_MAP,  "Spotweld only on an all-wire job; CO2 otherwise")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_spotweldnarrow_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50), 7670 (qty 50), 1282 (qty 10).

EXPECT:
    1310   Weld (CO2) RESTORED   £0.97 -> £1.86   =>  £8.12 -> £9.07   (Tim £6.90)
           plus a flag: "this job mixes wire/bar with sheet ... Assuming Weld (CO2)"
    7670   Spotweld KEPT         £2.91 unchanged  =>  £7.58            (Tim £6.74)
    1282   unchanged             £207.16

If 1310 does not return to EXACTLY £9.07, this patch reached further than the weld mapping.
""")


if __name__ == "__main__":
    main()
