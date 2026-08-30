#!/usr/bin/env python3
r"""
_apply_acrylic_rates_from_corpus.py

Follow-up to _apply_acrylic_route_fix.py. That patch got the acrylic ROUTING right (Diamond
Polish + Peel + Linebend + Assemble/pack; glue/laser gated) but I had set two throughputs -
diamond_polish and peel - to 120/hr, which I had lifted from Tony's 12439 sheet. That is
exactly the circular hard-coding we refused on 1310.

So we mined the historical corpus (dbo.historical_quote_labour_line, throughput from
raw_line_json $.J.labels.left), the SAME source as the metal size-bands. Medians, independent
of Tony:

    operation                n    corpus median    (Tony's sheet)
    Diamond Polish          147       135/hr            120
    Manual (Peel)           230       100/hr            120
    Linebend                261        60/hr             80
    Assemble/pack (Acr)     253        45/hr            120   <- size-driven, see note
    Laser (Acrylic)         158        98/hr             -
    GLUE                    182        12/hr             -

The corpus numbers DIFFER from Tony's (135 vs 120, 100 vs 120) - proving that copying his
sheet would have been both wrong and circular. We use the CORPUS medians.

THIS PATCH:
  1. diamond_polish 120 -> 135/hr  (corpus median, n=147)
  2. peel            120 -> 100/hr  (corpus median, n=230)
  Both now provenance = historical corpus, not the sheet under test.

DELIBERATELY NOT CHANGED HERE:
  - Linebend already uses a per-bend derivation (min_per_linebend scales per bend) - the right
    model, corpus base ~60-80 is consistent. Left as is.
  - Assemble/pack (Acrylic): corpus median 45 is pulled DOWN by big display assemblies; a small
    cube packs at ~120. This is the SAME size-band story as metal pack, and wants the area-band
    treatment, NOT a flat 45 or a flat 120. Flagged for a follow-up size-band, not patched with a
    single wrong median here.
  - glue/laser gating unchanged (previous patch).

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_rates_from_corpus.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
SENTINEL = "acrylic_rates_corpus"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


C_ANCHOR = '''    # Added 2026-07-15 from Tony's 12439 sheet: the two ops every acrylic part needs and the
    # engine was omitting. Diamond Polish is the acrylic FINISH (not powder); Peel removes the
    # protective film. Both present on every acrylic part regardless of bonding.
    "diamond_polish_min_per_part": 0.5,       # DPOL: acrylic finish, ~120 parts/hr
    "diamond_polish_setup_min": 10.0,
    "peel_min_per_part": 0.5,                 # MANA/peel: ~120 parts/hr
    "peel_setup_min": 15.0,'''

C_NEW = '''    # acrylic_rates_corpus (2026-07-15): the two ops every acrylic part needs and the engine
    # was omitting. Diamond Polish is the acrylic FINISH (not powder); Peel removes the
    # protective film. Throughputs are CORPUS MEDIANS from dbo.historical_quote_labour_line
    # (raw_line_json $.J.labels.left), NOT copied from any single estimator sheet - the same
    # source as the metal size-bands. Corpus: Diamond Polish 135/hr (n=147), Peel 100/hr
    # (n=230). (Tony's 12439 sheet books 120 for each; the corpus differs and wins - a single
    # sheet is not evidence.)
    "diamond_polish_min_per_part": 0.4444,    # DPOL: 135 parts/hr (corpus median, n=147)
    "diamond_polish_setup_min": 10.0,
    "peel_min_per_part": 0.6,                 # MANA/peel: 100 parts/hr (corpus median, n=230)
    "peel_setup_min": 15.0,'''


def main():
    if not os.path.exists(CONFIG):
        sys.exit(f"not found: {CONFIG}")
    cfg = open(CONFIG, "r", encoding="utf-8").read()
    if SENTINEL in cfg:
        sys.exit("Already applied (sentinel present).")
    cfg = sub(cfg, C_ANCHOR, C_NEW, "config: acrylic DPOL/peel rates from corpus (135/100)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{CONFIG}.bak_acrylicrates_{ts}"
    shutil.copy2(CONFIG, bak)
    open(CONFIG, "w", encoding="utf-8").write(cfg)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025).

    Diamond Polish now 135/hr (was 120): slightly FASTER, so slightly CHEAPER than the
    previous run. Peel now 100/hr (was 120): slightly slower.

    The £-total will NOT exactly match Tony's £1.30 now - and that is CORRECT. It should
    match the CORPUS-grounded cost, not Tony's sheet. If it lands near £1.30 that is
    corroboration; if it is a little off, the difference is honest (corpus vs one sheet).

    Read the OPERATION SET first (that is the real fix):
        Diamond Polish + Peel(manual) + Linebend + Assemble/pack   - and NO glue/laser/powder.
    Then read the numbers as corpus-grounded, not sheet-matched.

    STILL OPEN on acrylic (flagged honestly, not patched):
      - Assemble/pack (Acrylic) wants SIZE-BANDING (corpus median 45 = big assemblies; a
        small cube is ~120). Same treatment as metal pack. Next.
      - Acrylic SHEET size/rate: 317x182 @ £46.20 -> £0.53 vs Tony 311x101 @ £0.12. Part
        dimensions read too big + sheet rate. Separate from routing/throughput.
      - Powder BOM line: confirm it is now GONE (acrylic_no_powder flag). If still present,
        the flag needs wiring into the wb_populate powder block.
""")


if __name__ == "__main__":
    main()
