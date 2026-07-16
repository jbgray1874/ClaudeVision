#!/usr/bin/env python3
r"""
_apply_acrylic_m2_config.py

Adds ACRYLIC_PRICE_GBP_PER_M2 to config.py. The earlier v1 applier reported "ok config" but
ABORTED on its estimator half BEFORE reaching the file-write loop, so the config table was never
actually saved to disk (the "ok" only meant the in-memory string-replace matched). The v2
estimator patch now READS this table and falls back to £8.0/m2 without it — correct by luck for
a 2mm part, wrong for other gauges. This lands the real table.

UDEF-derived Clear/standard XT £/m2 by thickness (see _apply_acrylic_area_pricing_v2 header for
the full evidence: proven linear full-sheet-to-blank; 1.8/2mm STRONG n=3, thicker gauges
single-source). PROVISIONAL until estimating signs off.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_m2_config.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
SENTINEL = "ACRYLIC_PRICE_GBP_PER_M2"


def main():
    if not os.path.exists(CONFIG):
        sys.exit(f"not found: {CONFIG}")
    cfg = open(CONFIG, "r", encoding="utf-8").read()
    if SENTINEL in cfg:
        sys.exit("Already applied (ACRYLIC_PRICE_GBP_PER_M2 already present).")

    anchor = '''ACRYLIC_SHEET_PRICE_GBP = {
    2.0: 34.00,
    3.0: 46.20,    # 3mm high-impact @ 2050x1520 — confirmed from the M18 workbook
    5.0: 70.00,
    8.0: 112.00,
    10.0: 138.00,
    "default": 46.20,
}'''

    if cfg.count(anchor) != 1:
        # anchor may differ slightly in the live file; fall back to appending after the
        # first occurrence of the table name.
        marker = "ACRYLIC_SHEET_PRICE_GBP = {"
        idx = cfg.find(marker)
        if idx == -1:
            sys.exit("ABORT: could not find ACRYLIC_SHEET_PRICE_GBP to anchor after. NOTHING WRITTEN.\n"
                     "Paste the live ACRYLIC_SHEET_PRICE_GBP block and I'll re-anchor.")
        # find the closing brace of that dict
        close = cfg.find("}", idx)
        if close == -1:
            sys.exit("ABORT: malformed ACRYLIC_SHEET_PRICE_GBP block. NOTHING WRITTEN.")
        insert_at = close + 1
        block = "\n\n" + _NEW_TABLE
        cfg = cfg[:insert_at] + block + cfg[insert_at:]
        print("  ok  appended ACRYLIC_PRICE_GBP_PER_M2 after ACRYLIC_SHEET_PRICE_GBP (fallback anchor)")
    else:
        cfg = cfg.replace(anchor, anchor + "\n\n" + _NEW_TABLE, 1)
        print("  ok  inserted ACRYLIC_PRICE_GBP_PER_M2 after ACRYLIC_SHEET_PRICE_GBP")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{CONFIG}.bak_acrylicm2_{ts}"
    shutil.copy2(CONFIG, bak)
    open(CONFIG, "w", encoding="utf-8").write(cfg)
    print(f"  backup: {bak}")
    print("""
VERIFY:
    Select-String -Path config.py -Pattern "ACRYLIC_PRICE_GBP_PER_M2"
  should now return the line.

THEN re-run 12439 (qty 2025):
    - Other Sheet Material: Cost per sheet ~£50.02, Qty per sheet ~120, Cost per part ~£0.43.
    - Unit cost £2.83 -> ~£2.73.
  And 1282 (steel) — unchanged.
""")


_NEW_TABLE = '''# acrylic_area_pricing (2026-07-15): £/m2 by thickness, derived from UDEF (Access Supply Chain) —
# every priced acrylic line from Perspex Distribution / Plastics Plus / AMARI, isolated to
# Clear/standard XT stock. PROVEN LINEAR: for each thickness the £/m2 from a full sheet and a cut
# blank agree (2mm 7.8 vs 7.9/8.5; 3mm 11.5 vs 13.2), so a blank costs area × sheet-rate.
# Confidence: 1.8/2.0mm STRONG (3 lines each, tight); 3mm OK (2 lines); 4/5/6/8mm single-line
# (real current Perspex price, single-source). CLEAR/standard XT only — coloured / matt / cast /
# anti-reflective run ~1.5-2x higher and are NAMED on the drawing (separate tier, later).
# Used as: cost = blank_area_m2 × rate × (1+scrap), expressed through the WB's L/J. PROVISIONAL
# until estimating signs off these figures.
ACRYLIC_PRICE_GBP_PER_M2 = {
    1.5: 8.2,    # 1 line (full sheet clear XT) — single-source
    1.8: 7.8,    # 3 lines (blanks), £6.4-8.3 — STRONG
    2.0: 8.0,    # 3 lines (2 clear blank + 1 full sheet), £7.8-8.5 — STRONG
    3.0: 13.0,   # clear blank £13.2 + black full sheet £11.5 — OK
    4.0: 14.2,   # 1 line (full sheet clear XT) — single-source
    5.0: 19.5,   # 1 line (full sheet clear XT 3050x2050) — single-source
    6.0: 21.7,   # 1 line (full sheet clear XT) — single-source
    8.0: 30.9,   # 1 line (full sheet clear XT) — single-source
    "default": 8.0,   # thin-gauge standard (most display acrylic is 1.5-3mm)
}'''


if __name__ == "__main__":
    main()
