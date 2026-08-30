#!/usr/bin/env python3
r"""
_apply_powder_rate_from_config.py

PROBLEM: the powder £/kg rate lives as a STATIC value (4) in the Excel master template
(cell AF57), not in code. config.py's POWDER_COST_PER_KG is completely orphaned —
wb_populate never imports it and never writes AF57. So changing config.py to 9.73 had
NO effect: the workbook still priced powder at £4/kg.

Proven: config.py = 9.73 but the populated 1303A workbook showed AF57 = 4.

EVIDENCE for 9.73: Tim's manual sheets price powder at £9.73/kg on BOTH job 1303A
(0.0575 kg -> £0.58) and job 1304 (0.025 kg -> £0.25). Two independent real sheets.

FIX (Option 2 — code-controlled rate): wb_populate now imports POWDER_COST_PER_KG from
config and WRITES it into AF57 on every populate, overwriting the template's static
default. The template's AF58 formula (=AD57*AF57) then computes powder cost at the
correct rate automatically.

  * single source of truth = config.py (versioned, visible, reviewable)
  * no network-template surgery needed (template's 4 becomes a harmless default)
  * future rate changes = one config line

Two edits:
  1. import POWDER_COST_PER_KG (with a safe fallback if config lacks it)
  2. write ws["AF57"] = POWDER_COST_PER_KG just after the worksheet is obtained

KNOCK-ON (deliberate): powder cost rises on every powder-coated job.
  1303A : £0.22 -> ~£0.53   (Tim £0.58 — closes the gap)
  1304  : £0.04 -> ~£0.09
  1282  : £3.64 -> ~£8.85   => total ~£273.55 -> ~£278.76
  12532 : ~£11  -> ~£26.76  => total ~£439.96 -> ~£455.72
1282/12532 reports were written at £4/kg — annotate or re-run them.

Exact-string, asserted once each, backs up, idempotent.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# ---- Edit 1: import the rate from config (safe fallback if missing) ----
OLD_IMP = (
    "import os, json, re, shutil, sys\n"
    "from datetime import datetime\n"
)
NEW_IMP = (
    "import os, json, re, shutil, sys\n"
    "from datetime import datetime\n"
    "\n"
    "# Powder material rate (£/kg). Single source of truth is config.py — the Excel\n"
    "# template carries only a static default, which we overwrite on every populate.\n"
    "try:\n"
    "    from config import POWDER_COST_PER_KG as _POWDER_COST_PER_KG\n"
    "except Exception:\n"
    "    _POWDER_COST_PER_KG = None  # fall back to whatever the template holds\n"
)

# ---- Edit 2: write AF57 from config right after the worksheet is obtained ----
OLD_WS = '    ws = wb[cm["estimate_sheet"]]\n'
NEW_WS = (
    '    ws = wb[cm["estimate_sheet"]]\n'
    '\n'
    '    # Powder £/kg — write the code-controlled rate into the sheet (cell AF57),\n'
    '    # overwriting the template\'s static default. AF58 (=AD57*AF57) then computes\n'
    '    # powder material cost at the correct rate. Source: config.POWDER_COST_PER_KG.\n'
    '    if _POWDER_COST_PER_KG is not None:\n'
    '        try:\n'
    '            ws["AF57"] = float(_POWDER_COST_PER_KG)\n'
    '        except Exception:\n'
    '            pass\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if "_POWDER_COST_PER_KG" in src:
        sys.exit("Already applied (found _POWDER_COST_PER_KG). No change made.")

    for label, old in (("import block", OLD_IMP), ("worksheet assignment", OLD_WS)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label}, found {n}. "
                     f"Source drifted — re-check wb_populate.py. No change made.")

    new = src.replace(OLD_IMP, NEW_IMP).replace(OLD_WS, NEW_WS)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_powderratecfg_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- powder rate is now CODE-CONTROLLED ---")
    print("  config.py POWDER_COST_PER_KG -> written to sheet cell AF57 on every populate")
    print("  template's static AF57 default is overwritten; AF58 (=AD57*AF57) picks it up")
    print(f"\nCurrent config value will now actually take effect.")
    print("\nVERIFY after next run:")
    print("  AF57 should read 9.73 (was 4)")
    print("\nEXPECT on 1303A (qty 50): powder £0.22 -> ~£0.53 (Tim £0.58); Unit Cost ~£9.58")
    print("NOTE: 1282 (~£278.76) and 12532 (~£455.72) will rise when next run.")


if __name__ == "__main__":
    main()
