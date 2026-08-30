#!/usr/bin/env python3
r"""
_apply_throughput_floor_wiring.py

Wires in the floor whose constant was added by _apply_wire_ops_and_throughput_floor.py.

THE ASYMMETRY (wb_populate.py:771)
-----------------------------------
    if default_tp and derived_throughput > default_tp * _THROUGHPUT_CEILING_MULTIPLIER:
        throughput = float(default_tp)      # too FAST  -> substituted
    else:
        throughput = derived_throughput     # too SLOW  -> sails straight through

Throughput is pieces/hour, so hours = pieces / throughput. A LOW throughput means MORE
HOURS, which INFLATES labour. The guard only catches the direction that UNDER-charges.
The direction that OVER-charges is completely unprotected.

On 1310: the stud's weld derived at 14.85/hr against a default of 42 (Tim's own sheet
implies ~50/hr). Result: £3.23 against Tim's £1.25.

TWO CHANGES
-----------
1. Symmetric floor: derived < default / 5 -> use the default.
   Same 5x tolerance as the existing ceiling, so it only fires on implausible outliers.

2. BOTH substitutions are now FLAGGED. Today cost hours because a £27 part vanished behind
   a warning nobody read; a silent substitution that changes a labour rate is the same
   disease. Every swap now prints derived, default and the multiple, so it is auditable.

HONEST SCOPE — READ THIS
------------------------
This does NOT fix 1310's weld. 14.85 vs a default of 42 is 2.8x too slow; the floor trips
at 5x (42/5 = 8.4). 14.85 > 8.4, so NO substitution occurs and the weld stays at £3.23.

The floor is protection against the PATHOLOGICAL case — a derived 2/hr against a default
of 180 — which would otherwise ship enormous labour silently. It is a guard rail, not a
correction. The weld over-read is a separate, real defect that stays on the open list.

Tightening the divisor to catch 2.8x would mean substituting defaults for genuinely slow
parts across every job — a much bigger behavioural change that should be made against
Tim's rate card, not inferred from one number on one job.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_throughput_floor_wiring.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "throughput FLOOR"

OLD = '''                if default_tp and derived_throughput > default_tp * _THROUGHPUT_CEILING_MULTIPLIER:
                    # engine value is implausible — use the realistic default
                    throughput = float(default_tp)
                else:
                    throughput = derived_throughput'''

NEW = '''                # Throughput is pieces/hour, so hours = pieces / throughput.
                # A derived value that is too HIGH under-charges (caught by the ceiling).
                # A derived value that is too LOW OVER-charges — and was never guarded at
                # all. 1310's stud weld derived at 14.85/hr against a default of 42 and
                # cost £3.23 vs Tim's £1.25. Both directions are now guarded, and BOTH
                # substitutions are FLAGGED: a silent swap of a labour rate is exactly the
                # kind of quiet wrong number that cost us a day.
                throughput = derived_throughput
                if default_tp:
                    _ceiling = default_tp * _THROUGHPUT_CEILING_MULTIPLIER
                    _floor = default_tp / _THROUGHPUT_FLOOR_DIVISOR
                    if derived_throughput > _ceiling:
                        throughput = float(default_tp)
                        _flag(f"throughput CEILING hit on '{wb_op}' ({pe.get('part_number')}): "
                              f"derived {derived_throughput:.2f}/hr is "
                              f"{derived_throughput/default_tp:.1f}x the default {default_tp}/hr "
                              f"— using default (was UNDER-charging).", flags)
                    elif derived_throughput < _floor:
                        throughput = float(default_tp)
                        _flag(f"throughput FLOOR hit on '{wb_op}' ({pe.get('part_number')}): "
                              f"derived {derived_throughput:.2f}/hr is "
                              f"{default_tp/derived_throughput:.1f}x SLOWER than the default "
                              f"{default_tp}/hr — using default (was OVER-charging).", flags)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()

    if "_THROUGHPUT_FLOOR_DIVISOR" not in src:
        sys.exit("The floor CONSTANT is not present. Run _apply_wire_ops_and_throughput_floor.py first.")
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{OLD}\n")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_tpfloor_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  throughput floor wired in; both substitutions now flagged")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50), then 1282 (qty 10).

EXPECT on 1310:
  * flag: dropped spurious op 'laser_cutting' on 1310-02   (the wire-ops fix)
  * NO Laser row on the Stud
  * unit cost ~£7.57                                        (Tim £6.90)
  * NO throughput-floor flag — 14.85 vs 42 is 2.8x, inside the 5x guard. The weld stays
    at £3.23 vs Tim's £1.25. That defect is NOT fixed by this change and remains open.
  * still missing, still named: Robomac £0.17, P.Coat £2.00

EXPECT on 1282:
  * £278.93, unchanged. It has no bars and no wire parts.
  * Watch for any throughput CEILING/FLOOR flags — those rows were previously being
    substituted SILENTLY. If flags appear, the numbers do not change (the behaviour is
    identical), but we finally get to SEE where the engine's derived rates are being
    overridden. That visibility is the real prize here.
""")


if __name__ == "__main__":
    main()
