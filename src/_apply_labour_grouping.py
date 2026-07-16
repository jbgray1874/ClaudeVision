#!/usr/bin/env python3
r"""
_apply_labour_grouping.py

THE DEFECT — the engine invents a machine setup for every part
---------------------------------------------------------------
The WB books SETUP on EVERY labour row:

    hours = (qty_per_unit / throughput) * order_qty  +  (setup_mins / 60)

  Fold   setup 30 min @ £40.47  = £20.24  per row
  P.Coat setup 15 min @ £355.43 = £88.86  per row
  Weld   setup 30 min @ £41.77  = £20.89  per row

The engine writes ONE ROW PER PART. On 1282 that is ~9 fold rows, ~8 laser rows, ~13
assemble/pack rows — nine press-brake setups, thirteen packing setups, for one product.

MEASURED across 1,982 historical jobs — what the estimators ACTUALLY write:

    operation                3-5 parts   6-10 parts   11+ parts     ENGINE
    ---------------------------------------------------------------------------
    Assemble/pack (Metal)       1.05        1.21         2.87      one per part (~13)
    Weld (CO2)                  1.00        1.23         2.34      one per part
    Fold                        1.71        2.03         4.49      one per part (~9)
    Laser (Metal)               1.41        1.92         5.14      one per part (~8)
    P.Coat                      1.68        1.70         5.16      one per part (4 -> 9)

Nobody writes one row per part. But nobody writes exactly one row per job either — and
that matters, because it tells us WHY.

THE RULE THE DATA SUPPORTS
--------------------------
SETUP BELONGS TO A TOOLING CHANGE, NOT TO A PART.

You set the press brake for 1.2mm, run every 1.2mm part through it, then change tooling for
1.0mm. That is precisely why Tim writes ~2 fold lines on a ten-part job and not ten: two
gauges, two setups.

    Fold / Laser / Punch / P.Coat  ->  group by (operation, material, gauge)
    Assemble/pack                  ->  ONE row per job — you pack the finished product once
    Weld / Spotweld                ->  ONE row per job — you weld the assembly, not the parts

Nothing is lost from the audit trail: every part number in a group is named in the
description cell.

ONE DELIBERATE ASYMMETRY, AND THE REASONING
--------------------------------------------
For Assemble/pack and Weld the MEASURED default throughput is used, not the geometry-derived
one. Assembly and welding time is NOT in the DXF — there is no geometry from which to derive
"how long does it take to pack this". The engine's derived numbers for those ops are fiction
dressed as measurement (1310's weld derived at 14.85/hr against a corpus average of 29).
For genuinely geometry-driven ops — laser from cut path, fold from bend count — the derived
value is kept, because there the geometry really does carry the information.

WHAT WILL STILL BE WRONG AFTERWARDS — say it now, not after the run
-------------------------------------------------------------------
Tim also overrides the SETUP MINUTES. His 1298 sheet books Assemble/pack setup at 5 min; the
WB dept table says 15. The corpus average for P.Coat setup is 6.0 min against the table's 15.
This patch does NOT touch setup minutes — they come from the WB's own lookup table and
changing them means changing the estimators' template. So expect pack and P.Coat to remain
somewhat over even after grouping. That residual is a SETUP-MINUTES question for Tim, and it
should be put to him rather than guessed at here.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_labour_grouping.py
"""
from __future__ import annotations
import re, shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_ONE_ROW_PER_JOB"

# Match the whole existing per-part labour loop: from "for pe in labour_parts:" up to and
# including the "if labour_overflow: break" that closes it. Regex (not an exact string)
# because the deployed file contains unicode em-dashes and multiplication signs that do not
# survive a console round-trip cleanly.
PAT = re.compile(
    r"    for pe in labour_parts:\n.*?\n        if labour_overflow:\n            break\n",
    re.DOTALL,
)

NEW = '''    # ── LABOUR — GROUPED BY SETUP, NOT BY PART ──────────────────────────────
    # The WB books SETUP on every row (Fold 30min = £20.24, P.Coat 15min = £88.86,
    # Weld 30min = £20.89). The engine wrote ONE ROW PER PART, so a ten-part job invented
    # ten press-brake setups that never happen on the floor.
    #
    # Measured across 1,982 historical jobs, on a 6-10 part job the estimators write:
    #     Assemble/pack 1.21 rows | Weld 1.23 | Fold 2.03 | Laser 1.92 | P.Coat 1.70
    # Not one per part. But not exactly one per job either — and that tells us the rule:
    #
    #     SETUP BELONGS TO A TOOLING CHANGE, NOT TO A PART.
    #
    # You set the brake for 1.2mm, run every 1.2mm part, then change for 1.0mm. Two gauges,
    # two setups — which is exactly why Tim writes ~2 fold lines on a ten-part job.
    #
    #     Fold / Laser / Punch / P.Coat  -> group by (operation, material, gauge)
    #     Assemble/pack                  -> ONE row per job (pack the product once)
    #     Weld / Spotweld                -> ONE row per job (weld the assembly)
    #
    # Every part number in a group is named in the description cell — nothing is lost.
    _ONE_ROW_PER_JOB = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)",
                        "Weld (CO2)", "Spotweld", "Dress Welds"}
    _PACK_OPS = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)"}

    _groups = {}
    for pe in labour_parts:
        le = pe.get("labour_estimate") or {}
        costs = le.get("costs_gbp") or {}
        batch_hours = le.get("batch_hours") or {}
        ops = list(costs.keys())
        if not ops:
            continue
        _pn = str(pe.get("part_number") or "")
        _qty_pu = int(_safe(pe.get("quantity"), 1))
        _is_acr = _is_board(str(pe.get("normalized_material") or ""))
        _sf = (pe.get("material_estimate") or {}).get("stock_form")
        _mat = pe.get("normalized_material") or ""
        _me2 = pe.get("material_estimate") or {}
        _ng2 = pe.get("normalized_geometry") or {}
        _thk = _safe(pe.get("normalized_thickness_mm") or _me2.get("thickness_mm"), 0)

        for op in ops:
            if _is_spurious_operation(op, _sf, _mat):
                _flag(f"dropped spurious op '{op}' on {_pn} "
                      f"(stock_form={_sf}, material={_mat})", flags)
                continue
            if "powder" in str(op).lower():
                if _pn in _powder_ok and not _powder_ok[_pn]:
                    _flag(f"dropped powder on {_pn} — drawing finish is not powder "
                          f"(RAW/assembly/weldment); costs_gbp over-applied it.", flags)
                    continue
            if "diamond" in str(op).lower() or ("polish" in str(op).lower()
                                                and "edge" not in str(op).lower()):
                if _finish_is_powder.get(_pn):
                    _flag(f"dropped diamond_polish on {_pn} — part is POWDER COATED "
                          f"(diamond-polish is spurious/boilerplate on a powder finish).", flags)
                    continue

            wb_op = _map_operation(op, _is_acr, _sf or "")
            if wb_op is None:
                _flag(f"labour op '{op}' ({_pn}) not in OP_NAME_MAP — WB rate lookup will "
                      f"return 0 for it. Add mapping.", flags)
                wb_op = str(op)

            if wb_op in _ONE_ROW_PER_JOB:
                key = (wb_op, "", "")          # one setup for the whole job
            else:
                key = (wb_op, str(_mat), "%g" % (_thk or 0))   # one setup per tooling change

            g = _groups.setdefault(key, {
                "wb_op": wb_op, "material": _mat, "thickness": _thk,
                "qty": 0, "bh": 0.0, "parts": [], "bends": 0, "holes": 0,
            })
            g["qty"] += _qty_pu
            _bh = _safe(batch_hours.get(op))
            if _bh and _bh > 0:
                g["bh"] += float(_bh)
            if _pn and _pn not in g["parts"]:
                g["parts"].append(_pn)
            _ol = str(op).lower()
            if _ol == "folding":
                g["bends"] += int(_safe((_ng2 or {}).get("estimated_bend_line_count"), 0)) * _qty_pu
            elif _ol in ("hole_machining", "drilling", "punch"):
                g["holes"] += int(_safe((_ng2 or {}).get("estimated_hole_count"), 0)) * _qty_pu

    for _key in sorted(_groups.keys()):
        g = _groups[_key]
        if row > lb["last_row"]:
            labour_overflow = True
            break
        wb_op = g["wb_op"]

        # Assemble/pack is PER PRODUCT: you pack the finished product once, not once per
        # part. Tim books qty 1 (1298: "Poly bag & bulk pack", qty 1, 90/hr).
        _qty = 1 if wb_op in _PACK_OPS else int(g["qty"] or 1)

        _matx = str(g["material"] or "").replace("_", " ").strip()
        _spec = []
        if g["thickness"]:
            _spec.append(("%g" % g["thickness"]) + "mm")
        if _matx:
            _spec.append(_matx)
        _detail = ""
        if g["bends"]:
            _detail = " (%d bend%s)" % (g["bends"], "" if g["bends"] == 1 else "s")
        elif g["holes"]:
            _detail = " (%d hole%s)" % (g["holes"], "" if g["holes"] == 1 else "s")
        _pl = g["parts"]
        _ptxt = ", ".join(_pl[:6]) + (", +%d more" % (len(_pl) - 6) if len(_pl) > 6 else "")
        _rd = str(wb_op)
        if _spec:
            _rd += " \\u2014 " + " ".join(_spec)
        if _ptxt:
            _rd += " (" + _ptxt + ")"
        _rd += _detail

        ws.cell(row=row, column=lb["col_operation"], value=wb_op)
        ws.cell(row=row, column=lb["col_desc"],      value=_rd[:200])
        ws.cell(row=row, column=lb["col_qty"],       value=_qty)

        default_tp = _THROUGHPUT_DEFAULTS.get(wb_op or "")

        # Assembly, packing and welding time is NOT in the DXF. There is no geometry from
        # which to derive "how long does it take to pack this" — the engine's derived value
        # for those ops is fiction dressed as measurement (1310's weld derived at 14.85/hr
        # against a corpus average of 29). Use the MEASURED default and say so.
        # For laser (cut path) and fold (bend count) the geometry genuinely does carry the
        # information, so the derived value is kept.
        if wb_op in _ONE_ROW_PER_JOB and default_tp:
            ws.cell(row=row, column=lb["col_throughput"], value=float(default_tp))
        else:
            bh = g["bh"]
            if bh and bh > 0:
                _total_pieces = order_qty * _qty
                _derived = _total_pieces / bh
                throughput = _derived
                if default_tp:
                    _ceiling = default_tp * _THROUGHPUT_CEILING_MULTIPLIER
                    _floor = default_tp / _THROUGHPUT_FLOOR_DIVISOR
                    if _derived > _ceiling:
                        throughput = float(default_tp)
                        _flag(f"throughput CEILING hit on '{wb_op}': derived {_derived:.2f}/hr "
                              f"is {_derived/default_tp:.1f}x the default {default_tp}/hr "
                              f"— using default (was UNDER-charging).", flags)
                    elif _derived < _floor:
                        throughput = float(default_tp)
                        _flag(f"throughput FLOOR hit on '{wb_op}': derived {_derived:.2f}/hr "
                              f"is {default_tp/_derived:.1f}x SLOWER than the default "
                              f"{default_tp}/hr — using default (was OVER-charging).", flags)
                ws.cell(row=row, column=lb["col_throughput"], value=round(throughput, 4))
            elif default_tp:
                ws.cell(row=row, column=lb["col_throughput"], value=float(default_tp))
            else:
                _flag(f"labour op '{wb_op}' has no batch_hours and no default throughput — "
                      f"WB hours/cost will be #DIV/0! for this row.", flags)
        row += 1

    _flag(f"labour: {len(_groups)} grouped row(s) — setup is booked once per tooling group, "
          f"not once per part.", flags)
    if False:
        if labour_overflow:
            break
'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    hits = PAT.findall(src)
    if len(hits) != 1:
        sys.exit(f"ABORT: expected 1 match for the labour loop, found {len(hits)}. "
                 f"Nothing written.")

    body = NEW.replace('\\u2014', '\u2014').replace(
        '''    if False:
        if labour_overflow:
            break
''', '')

    src = PAT.sub(lambda _m: body, src, count=1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_labourgroup_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  labour rows now grouped by tooling setup, not by part")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50) then 1282 (qty 10).

EXPECT ON 1310 (Tim £6.90):
  * ONE Assemble/pack row, not two          (Tim £0.29)
  * ONE Weld row, using the measured 29/hr  (Tim £1.25)  — was £3.23 on a derived 14.85/hr
  * ONE Robomac row                         (Tim £0.17)
  * ONE P.Coat row per gauge                (Tim £2.00)  — was two
  * flag: "labour: N grouped row(s)"

EXPECT ON 1282 (qty 10):
  * labour rows collapse from ~40 to roughly 10-12
  * labour cost falls HARD — it was carrying ~30 phantom machine setups
  * BOM and steel blocks MUST be untouched. If a material number moves, this patch has
    reached somewhere it should not have: revert.

WHAT WILL STILL BE OVER, AND WHY — do not mistake this for the fix failing:
  Tim ALSO overrides setup MINUTES. His 1298 sheet books Assemble/pack setup at 5 min; the
  WB dept table says 15. The corpus average for P.Coat setup is 6.0 min against the table's
  15. This patch does not touch setup minutes — they live in the estimators' own lookup
  table. Pack and P.Coat will therefore remain somewhat over. That residual is a question
  for Tim about his template, not something to guess at here.
""")


if __name__ == "__main__":
    main()
