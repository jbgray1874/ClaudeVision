#!/usr/bin/env python3
r"""
_apply_powder_rate_973.py

EVIDENCE: Tim's manual sheets price powder material at £9.73/kg on BOTH job 1303A
(Circular Saw Shelf, 0.0575 kg -> £0.58) and job 1304 (Grinder Holder, 0.025 kg ->
£0.25). Two independent real estimator sheets, same rate. Our provisional £4.00/kg was
a reconciled guess made when no powder price existed; it is less than half the real rate
and causes a consistent under-read of powder material on every powder-coated job.

CHANGE: config.py  POWDER_COST_PER_KG  4.00 -> 9.73

KNOCK-ON (deliberate, not a regression):
  1303A : powder £0.22 -> £0.53   (closes the parity gap vs Tim's £0.58)
  1304  : powder £0.04 -> £0.09
  1282  : powder £3.64 -> £8.85   => job total £273.55 -> ~£278.76
  12532 : powder ~£11  -> ~£26.76 => job total £439.96 -> ~£455.72

The 1282/12532 reports were written at the £4/kg provisional rate. They are NOT re-run
here; their published totals should be annotated ("powder rate provisional at time of
run; since corrected to supplier-confirmed £9.73/kg") or the jobs re-run when convenient.

Exact-string, asserted once, backs up, idempotent.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\config.py"

OLD = "POWDER_COST_PER_KG = 4.00"
NEW = "POWDER_COST_PER_KG = 9.73"


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if NEW in src:
        sys.exit("Already applied (POWDER_COST_PER_KG = 9.73). No change made.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected exactly 1 occurrence of '{OLD}', found {n}. "
                 f"Check config.py around line 1262. No change made.")

    new = src.replace(OLD, NEW)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_powderrate973_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n  POWDER_COST_PER_KG : 4.00  ->  9.73")
    print("  source: Tim's manual sheets, jobs 1303A and 1304 (both £9.73/kg)")
    print("\nEXPECT on 1303A re-run (qty 50):")
    print("  powder material £0.22 -> ~£0.53  (Tim: £0.58)")
    print("  Unit Cost £9.27 -> ~£9.58")
    print("\nNOTE: 1282 and 12532 totals will also rise when next run")
    print("  (1282 ~£278.76, 12532 ~£455.72) — their reports were written at £4/kg.")


if __name__ == "__main__":
    main()
