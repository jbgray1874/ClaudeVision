#!/usr/bin/env python3
r"""
_apply_config_powder_rate.py

Adds a named powder-material rate to config.py so the £4/kg used in the workbook's
powder-material cost has one authoritative, documented home (like the tonne rates).

The workbook computes powder cost itself (Option A): AF58 = Total Powder kg (AD57) x
AF57 (price cell = 4), fed into M67. This config constant is the SOURCE OF TRUTH for
that price — record it here so it's changeable in one place and visible to the engine.

NOTE: the template currently holds the literal 4 in AF57 (hand-wired). This config
entry documents the rate and lets a future wb_populate step write AF57 from config so
the two never drift. For now it is the recorded rate; changing it here is the intended
single point of change.

Idempotent; appends after the sheet-steel / tonne rate area if found, else at a
clearly-marked block near the top-level rate constants.
"""
import shutil, sys, os, datetime, re

PATH = r"C:\ClaudeVision\src\config.py"

BLOCK = (
    "\n"
    "# ── Powder coating material rate ────────────────────────────────────────────\n"
    "# £ per kg of powder. The Estimate workbook computes powder MATERIAL kg per part\n"
    "# from geometry (area -> 6 m2/kg coverage -> kg), sums it (AD57 'Total Powder Per\n"
    "# Unit'), and multiplies by this rate (cell AF57) into the material total M67.\n"
    "# This is the single source of truth for the powder price; change it here.\n"
    "# Provisional rate from Tim's manual sheet (POWDER5 line reconciled to ~£4/kg).\n"
    "POWDER_COST_PER_KG = 4.00\n"
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if "POWDER_COST_PER_KG" in src:
        sys.exit("Already present (POWDER_COST_PER_KG). No change made.")

    # try to place it right after a tonne-rate constant if one exists, else append
    anchor = None
    for pat in (r"SHEET_STEEL_COST_PER_TONNE\s*=.*\n",
                r"STEEL_COST_PER_TONNE\s*=.*\n",
                r"WIRE_COST_PER_TONNE\s*=.*\n"):
        m = re.search(pat, src)
        if m:
            anchor = m.end()
            break

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_powderrate_{ts}"
    shutil.copy2(PATH, bak)

    if anchor:
        new = src[:anchor] + BLOCK + src[anchor:]
        where = "after a tonne-rate constant"
    else:
        new = src.rstrip() + "\n" + BLOCK
        where = "appended at end (no tonne-rate anchor found)"

    open(PATH, "w", encoding="utf-8").write(new)
    print("PATCHED:", PATH)
    print("backup :", bak)
    print(f"added POWDER_COST_PER_KG = 4.00  ({where})")
    print("\nVerify:")
    print(r'  Select-String -Path C:\ClaudeVision\src\config.py -Pattern "POWDER_COST_PER_KG" -Context 1,1')


if __name__ == "__main__":
    main()
