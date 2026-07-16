#!/usr/bin/env python3
r"""
_apply_wire_ops_corrections.py

Three corrections to the labour pass. Two of them are mine, from the grouping patch.

------------------------------------------------------------------------------------
1. ROBOMAC IS DOUBLE-BOOKED  (my bug)
------------------------------------------------------------------------------------
7670 currently books TWO Robomac rows for the same work:

    Robomac — MILD STEEL      (7670-01-001, -002, -003)   £0.33
    Robomac — 4mm MILD STEEL  (7670-01-001, -002, -003)   £0.33

The injected group keys on ("Robomac", "", "") while the NATURAL op group — the pricing
record does carry a 'robomac' op on this job — keys on ("Robomac", "MILD_STEEL", "4").
Two keys, one operation, both listing all three parts.

I wrote the injection for 1310, where the pricing record had NO robomac op and the row was
missing entirely. I injected it unconditionally instead of only when absent.

FIX: inject only if the part's own ops do not already map to Robomac.

------------------------------------------------------------------------------------
2. ROBOMAC IS ONE ROW PER WIRE FORM, NOT ONE PER JOB  (my bug)
------------------------------------------------------------------------------------
Tim's 7670 sheet:

    Robomac  Robo main frame    qty 1  100/hr  setup 15  £0.47
    Robomac  Robo back wire     qty 2  450/hr  setup 15  £0.30
    Robomac  Robo bottom frame  qty 1  300/hr  setup 15  £0.26

THREE rows, three setups, and the throughput swings 100 -> 450. Every wire form is a
different bend program on the machine, so each one is a genuine separate setup. I put
Robomac in _ONE_ROW_PER_JOB. That is wrong, and it UNDER-charges — the failure mode we
cannot see, which is worse than the one we can.

FIX: Robomac keys per PART.

------------------------------------------------------------------------------------
3. YOU DO NOT CO2-WELD A 4mm WIRE FRAME
------------------------------------------------------------------------------------
    engine:  Weld (CO2)  29/hr   £6.18
    Tim:     Spotweld  x2        £1.61   (buttweld 150/hr + spotweld 45/hr)

Wire frames go on the SPOT WELDER. 'welding' on stock_form=wire must map to Spotweld
(51/hr measured, £32.90/hr) rather than Weld (CO2) (29/hr, £41.77/hr).

WHAT I AM DELIBERATELY *NOT* DOING
-----------------------------------
Tim writes TWO Spotweld rows for a THREE-part frame — so Spotweld is per WELD TYPE, not
per part. Nothing in the engine's data tells us how many welds a frame needs; that is Tim's
judgement, and welding time is not in the geometry.

So Spotweld stays ONE row per job. The engine will land near £2.91 against Tim's £1.61 —
still over, but honestly over, and £3.27 better than now. Inventing a weld-count rule to
close that gap would be fitting, not fixing, and the next wire job would expose it.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_ops_corrections.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_PER_PART_OPS"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    # ---- 1. Robomac out of ONE_ROW_PER_JOB; new PER_PART set --------------
    src = sub(src,
              '''    _ROBOMAC_STOCK_FORMS = {"wire"}''',
              '''    _ROBOMAC_STOCK_FORMS = {"wire"}
    # Robomac is ONE ROW PER WIRE FORM, not one per job. Tim's 7670 sheet:
    #     Robomac  main frame    qty 1  100/hr  setup 15  £0.47
    #     Robomac  back wire     qty 2  450/hr  setup 15  £0.30
    #     Robomac  bottom frame  qty 1  300/hr  setup 15  £0.26
    # Three rows, three setups, throughput swinging 100 -> 450. Each wire form is a
    # different bend program on the machine, so each is a genuine separate setup.
    # Grouping these into one row UNDER-charges — the failure mode we cannot see.
    _PER_PART_OPS = {"Robomac"}''',
              "Robomac -> per wire form (_PER_PART_OPS)")

    # ---- 2. key selection ------------------------------------------------
    src = sub(src,
              '''            if wb_op in _ONE_ROW_PER_JOB:
                key = (wb_op, "", "")          # one setup for the whole job
            else:
                key = (wb_op, str(_mat), "%g" % (_thk or 0))   # one setup per tooling change''',
              '''            # 4mm wire frames go on the SPOT WELDER, not the CO2 torch.
            # Engine: Weld (CO2) 29/hr, £41.77/hr -> £6.18.  Tim: Spotweld -> £1.61.
            if wb_op == "Weld (CO2)" and str(_sf or "").lower() == "wire":
                wb_op = "Spotweld"

            if wb_op in _PER_PART_OPS:
                key = (wb_op, _pn, "")         # one setup PER PART (per wire form)
            elif wb_op in _ONE_ROW_PER_JOB:
                key = (wb_op, "", "")          # one setup for the whole job
            else:
                key = (wb_op, str(_mat), "%g" % (_thk or 0))   # one setup per tooling change''',
              "wire welding -> Spotweld; per-part keying")

    # ---- 3. don't inject Robomac if it is already there -------------------
    src = sub(src,
              '''        if str(_sf or "").lower() in _ROBOMAC_STOCK_FORMS:
            _rg = _groups.setdefault(("Robomac", "", ""), {
                "wb_op": "Robomac", "material": _mat, "thickness": 0,
                "qty": 0, "bh": 0.0, "parts": [], "bends": 0, "holes": 0,
            })
            _rg["qty"] += _qty_pu
            if _pn and _pn not in _rg["parts"]:
                _rg["parts"].append(_pn)''',
              '''        # Inject Robomac ONLY if the pricing record did not already carry the op.
        # 1310's stud had no robomac op at all, so the row was missing and I injected it
        # unconditionally. On 7670 the op IS present — and the unconditional injection
        # produced TWO Robomac rows for the same work (one keyed ("Robomac","",""), one
        # keyed ("Robomac","MILD_STEEL","4")). Check before injecting.
        if str(_sf or "").lower() in _ROBOMAC_STOCK_FORMS:
            _has_robo = any(
                _map_operation(_o, _is_acr, _sf or "") == "Robomac" for _o in ops
            )
            if not _has_robo:
                _rg = _groups.setdefault(("Robomac", _pn, ""), {
                    "wb_op": "Robomac", "material": _mat, "thickness": 0,
                    "qty": 0, "bh": 0.0, "parts": [], "bends": 0, "holes": 0,
                })
                _rg["qty"] += _qty_pu
                if _pn and _pn not in _rg["parts"]:
                    _rg["parts"].append(_pn)''',
              "Robomac injected only when absent (kills the duplicate row)")

    # ---- 4. per-part ops use the measured default throughput --------------
    src = sub(src,
              '        if (wb_op in _ONE_ROW_PER_JOB or wb_op == "Robomac") and default_tp:',
              '        if (wb_op in _ONE_ROW_PER_JOB or wb_op in _PER_PART_OPS) and default_tp:',
              "per-part ops use the measured default (no geometry to derive from)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_wireops2_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 (qty 50) and 1282 (qty 10) as regressions.

EXPECT ON 7670 (Tim £6.74):
    Robomac    THREE rows, one per wire form   (Tim: 3 rows, £1.03 total)
    Spotweld   replaces Weld (CO2)             £6.18 -> ~£2.91   (Tim £1.61)
    unit cost  £17.01 -> ~£13.40

STILL OVER, AND HONESTLY SO:
    * £8.03 RYOBI GREEN powder — wrong colour AND 25x the quantity. Untouched here.
      This is now the biggest single error in the job, and we do not yet know whether the
      code came from the drawing or the engine reached for it. That is the next probe.
    * Spotweld ~£2.91 vs Tim's £1.61. Tim writes TWO spotweld rows for a three-part frame,
      so it is per WELD TYPE, not per part — and nothing in the engine's data says how many
      welds a frame needs. Welding time is not in the geometry. Leaving it honestly over
      rather than inventing a weld-count rule that the next job would expose.
    * No P.Coat — the assembly-level finish gap. Tim charges £1.92.

REGRESSIONS:
    1310: Robomac was INJECTED there (no robomac op on the pricing record), so it should
          still appear, now keyed per-part. Unit cost must stay ~£9.07 and the stud £0.04.
    1282: no wire parts, so no Robomac and no Spotweld. Materials MUST NOT MOVE.
""")


if __name__ == "__main__":
    main()
