#!/usr/bin/env python3
r"""
_apply_acrylic_rate_key_fix.py

The rate card (estimators' authoritative £/hr by department) caught a real bug on 12439:

    engine Peel line:  'manual_labour_acrylic ... MANM ... £31.18'
                        ^ labelled ACRYLIC, priced at the METAL rate (MANM £31.18)
    rate card says:     Manual labour (Acrylic) = MANA = £25.43

The Peel op is over-priced by 31.18/25.43 = 23%. Diamond Polish (£31.60), Linebend (£25.43)
and Assemble/pack (£25.43) all match the card exactly — only the acrylic MANUAL op resolves
to the metal department.

ROOT (estimator.py ~1838-1848): the op's rate comes from _resolve_labour_rate(op), which goes
through the pricing service and returns the METAL manual rate (£31.18) as applied_hourly_rate.
Then:

    _rate_key = op
    if _mat_u in _ACRYLIC_LIKE:
        if op == "laser_cutting"  -> _rate_key = "laser_cutting_acrylic"
        elif op == "assembly"     -> _rate_key = "assembly_acrylic"
    rate = applied_hourly_rate if applied_hourly_rate is not None else HOURLY_RATES_GBP.get(_rate_key)

Two problems:
  1. The material-aware remap only covers laser_cutting and assembly — NOT manual_labour or
     any other acrylic op. So manual_labour_acrylic never gets remapped.
  2. Even the remap that exists is INERT when applied_hourly_rate is not None, because the
     resolved (metal) rate WINS over HOURLY_RATES_GBP.get(_rate_key). Setting _rate_key does
     nothing unless the resolver returned None.

config.py ALREADY has the right values:
    "manual_labour_acrylic": 25.43,   # MANA
    "manual_labour_metal":   31.18,   # MANM
    "laser_cutting_acrylic": ...,     # LASA
    "assembly_acrylic":      ...,     # PACP
They just aren't being used for acrylic parts because the metal resolution wins.

THE FIX: when the part material is acrylic-like AND the op has an explicit acrylic rate key in
HOURLY_RATES_GBP, use THAT config rate (the authoritative MANA/LASA/PACP/DPOL etc.), overriding
the metal rate the resolver returned. This is general — it covers manual_labour, laser, assembly,
and any acrylic op with a dedicated key — not a one-off patch for Peel.

Rate keys tried for an acrylic part, in order: the op's own "<op>_acrylic" variant, then the op
name itself if it's already an acrylic key. Metal-only ops (fold, weld, punch) are unaffected —
they have no acrylic variant key, so nothing changes for them.

Result on 12439: Peel £/hr 31.18 -> 25.43 (MANA). Peel cost £0.32 -> ~£0.26. Closer to Tony's
£0.22 (the small remainder is the corpus-vs-Tony throughput difference, which is honest).

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_rate_key_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "acrylic_rate_key_override"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


ANCHOR = '''        _rate_key = op
        if _mat_u in _ACRYLIC_LIKE:
            if op == "laser_cutting" and "laser_cutting_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "laser_cutting_acrylic"
            elif op == "assembly" and "assembly_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "assembly_acrylic"
        rate = applied_hourly_rate if applied_hourly_rate is not None else HOURLY_RATES_GBP.get(_rate_key)'''

NEW = '''        _rate_key = op
        # acrylic_rate_key_override (2026-07-15): for an acrylic part, an acrylic op must be
        # priced at its ACRYLIC department rate (MANA/LASA/PACP/DPOL from the rate card), NOT
        # the metal department. The pricing resolver returns the METAL manual rate (MANM
        # £31.18) for manual_labour, and that was winning over the correct MANA £25.43 — the
        # Peel line came out 23% over. This picks the authoritative acrylic rate from
        # HOURLY_RATES_GBP and OVERRIDES the resolved metal rate for acrylic parts.
        _acr_rate = None
        if _mat_u in _ACRYLIC_LIKE:
            # existing laser/assembly remaps (kept), now also actually applied via _acr_rate
            if op == "laser_cutting" and "laser_cutting_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "laser_cutting_acrylic"
            elif op == "assembly" and "assembly_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "assembly_acrylic"
            # general: the op's own explicit "<op>_acrylic" variant, or the op name if it is
            # already an acrylic-specific key (manual_labour_acrylic, diamond_polish, linebend).
            for _cand in (f"{op}_acrylic", _rate_key, op):
                if _cand in HOURLY_RATES_GBP:
                    _acr_rate = HOURLY_RATES_GBP[_cand]
                    _rate_key = _cand
                    break
        if _acr_rate is not None:
            rate = _acr_rate   # authoritative acrylic dept rate wins for acrylic parts
        else:
            rate = applied_hourly_rate if applied_hourly_rate is not None else HOURLY_RATES_GBP.get(_rate_key)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    src = sub(src, ANCHOR, NEW, "estimator: acrylic ops use acrylic dept rate (MANA not MANM)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_acrylicratekey_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected:
    - Peel (manual_labour_acrylic) £/hr  31.18 -> 25.43 (MANA, matches rate card).
      Dept code should read MANA, not MANM. Peel cost £0.32 -> ~£0.26.
    - Diamond Polish (31.60), Linebend (25.43), Assemble/pack (25.43) UNCHANGED
      (they already matched the card).
    - Unit cost drops by ~£0.06.

REGRESSION — re-run 1282 (steel). Its manual/handling ops must STILL use the metal rate
(MANM £31.18) — 1282 is not acrylic, so _mat_u not in _ACRYLIC_LIKE, and _acr_rate stays
None. Steel rates untouched. Confirm 1282 unit cost is unchanged.

VERIFY against the rate card the estimators gave us — every acrylic op's £/hr should now
match:  DPOL 31.60, MANA 25.43, LINE 25.43, PACP 25.43, LASA 41.21, DRIL 25.13, CNC 43.36.
""")


if __name__ == "__main__":
    main()
