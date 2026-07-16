#!/usr/bin/env python3
r"""
_apply_powder_gate.py

PROBLEM: wb_populate writes one labour row per key in labour_estimate.costs_gbp
(line 561). costs_gbp carries 'powder_coating' for 13 of 30 parts on 1282 — but the
DRAWING only powder-coats 4 (1449-01C, 1450-01C, 2621-01C, 3886-01). The other 9 are
RAW (1455-C-001..004), a weldment (1455-C-101), or 'SEE ASSEMBLY DRAWING'
(1448-01/02, 3886-02/03). costs_gbp was built blind to finish (part_estimates carries
finish=None), so powder is over-applied -> ~£120 phantom P.Coat labour, workbook 2x Tim.

FIX: the reliable signal lives in manufacturing_writeup.parts[*].textual_operations
(the fuller record), which contains 'powder_coating' ONLY for the genuine 4. Build a
{part_number -> True/False powder-coated} lookup from that record, and in the labour
loop SKIP the 'powder_coating' op when the fuller record says the part is NOT powder.

This mirrors the existing _is_spurious_operation drop (same loop, line ~573) — an op
that shouldn't fire is skipped with a flag. Only powder is gated; all other ops
untouched. If the fuller record has no entry for a part (defensive), powder is KEPT
(fail-safe: don't silently strip cost we're unsure about).

Two edits:
  1. Build the powder lookup once, before the labour loop.
  2. In the op loop, skip 'powder_coating' when the lookup says False.

Exact-string, asserted once each, backs up, idempotent.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# ---- Edit 1: build the lookup just before the labour loop `for pe in labour_parts:` ----
OLD_LOOP = (
    '    for pe in labour_parts:\n'
    '        le = pe.get("labour_estimate") or {}\n'
    '        costs = le.get("costs_gbp") or {}\n'
    '        batch_hours = le.get("batch_hours") or {}\n'
    '        ops = list(costs.keys())   # the operation names\n'
    '        if not ops:\n'
    '            continue\n'
)
NEW_LOOP = (
    '    # Powder gate: costs_gbp carries powder_coating blind to finish (part_estimates\n'
    '    # has finish=None). The reliable drawing-derived signal is textual_operations on\n'
    '    # the fuller manufacturing_writeup.parts record. Build {part_number -> is_powder}.\n'
    '    _mw_parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []\n'
    '    _powder_ok = {}\n'
    '    for _mp in _mw_parts:\n'
    '        _pn = str(_mp.get("part_number") or "")\n'
    '        _tops = _mp.get("textual_operations") or []\n'
    '        if isinstance(_tops, str):\n'
    '            _tops = [_tops]\n'
    '        _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)\n'
    '\n'
    '    for pe in labour_parts:\n'
    '        le = pe.get("labour_estimate") or {}\n'
    '        costs = le.get("costs_gbp") or {}\n'
    '        batch_hours = le.get("batch_hours") or {}\n'
    '        ops = list(costs.keys())   # the operation names\n'
    '        if not ops:\n'
    '            continue\n'
)

# ---- Edit 2: skip powder op when the fuller record says not-powder ----
OLD_SKIP = (
    '            if _is_spurious_operation(op, part_stock_form, part_material):\n'
    '                _flag(f"dropped spurious op \'{op}\' on {pe.get(\'part_number\')} "\n'
    '                      f"(stock_form={part_stock_form}, material={part_material})", flags)\n'
    '                continue\n'
)
NEW_SKIP = (
    '            if _is_spurious_operation(op, part_stock_form, part_material):\n'
    '                _flag(f"dropped spurious op \'{op}\' on {pe.get(\'part_number\')} "\n'
    '                      f"(stock_form={part_stock_form}, material={part_material})", flags)\n'
    '                continue\n'
    '            # Powder gate: skip powder_coating when the drawing finish is NOT powder\n'
    '            # (RAW / SEE ASSEMBLY / weldment). costs_gbp over-applies it; the fuller\n'
    '            # record\'s textual_operations is the reliable signal. Fail-safe: if the\n'
    '            # part is unknown to the lookup, KEEP powder (do not silently strip).\n'
    '            if "powder" in str(op).lower():\n'
    '                _pn2 = str(pe.get("part_number") or "")\n'
    '                if _pn2 in _powder_ok and not _powder_ok[_pn2]:\n'
    '                    _flag(f"dropped powder on {_pn2} — drawing finish is not powder "\n'
    '                          f"(RAW/assembly/weldment); costs_gbp over-applied it.", flags)\n'
    '                    continue\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if "_powder_ok" in src:
        sys.exit("Already applied (found _powder_ok). No change made.")

    for label, old in (("labour-loop-start", OLD_LOOP), ("spurious-skip", OLD_SKIP)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label} block, found {n}. "
                     f"Source drifted — re-pull and re-anchor. No change made.")

    new = src.replace(OLD_LOOP, NEW_LOOP).replace(OLD_SKIP, NEW_SKIP)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_powdergate_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- powder gate installed ---")
    print("  lookup: manufacturing_writeup.parts[*].textual_operations -> is_powder")
    print("  loop  : skip powder_coating when fuller record says NOT powder")
    print("  fail-safe: unknown part -> keep powder (no silent strip)")
    print("\nEXPECT on 1282: P.Coat lines 13 -> 4 (keep 1449-01C,1450-01C,2621-01C,3886-01;")
    print("  drop 1455-C-001..004 RAW, 1455-C-101 weldment, 1448-01/02, 3886-02/03).")
    print("  Workbook total should DROP toward Tim's ~£169 (that is the fix working).")
    print("\nREGRESSION GATE (revert if it fails):")
    print("  - the 4 real powder parts MUST still have P.Coat")
    print("  - the 9 phantoms MUST be gone")
    print("  - nothing else moves")


if __name__ == "__main__":
    main()
