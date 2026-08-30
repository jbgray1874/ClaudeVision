#!/usr/bin/env python3
r"""
_apply_powder_quantity_model.py

WHAT IS SETTLED, AND WHAT IS ASSUMED. Say which is which, on the sheet.

SETTLED — not an assumption:
    GBP 9.73 / kg.  Tim's 1310 sheet:  Powder | 9.73 | 0.03 kg | 4% | 0.30
    We already carry 9.73 in config.POWDER_COST_PER_KG. It matches to the penny.
    JG is right that the powder PRICE behaves like steel: a fixed rate that moves now and
    then. Nothing to decide.

ASSUMED — and the flag says so, on every job:

    powder_kg = max( area x 0.20 kg/m2 ,  0.03 kg per coated object )

WHY 0.20 kg/m2 AND NOT THE TEMPLATE'S 0.1667

    0.1667 kg/m2 = 6 m2 per kilo = 100% TRANSFER EFFICIENCY. Nothing coats at 100% —
    most of the cloud misses the part and falls in the booth.

    The physics: a powder film is ~70 microns at ~1.5 g/cm3, so ~0.105 kg/m2 lands ON the
    part. At a realistic ~50% transfer efficiency you CONSUME ~0.20 kg/m2. That is a
    derivation, not a curve fit.

WHY A MINIMUM PER PIECE

    Tim's sheets do not behave like a coverage model at all:

        1298 bracket      0.025 kg
        1310 hook plate   0.030 kg     area 0.039 m2  -> implies 0.76 kg/m2
        7670 wire frame   0.040 kg     area 0.023 m2  -> implies 1.70 kg/m2

    The parts get SMALLER as the powder goes UP. Backwards for a coverage model — so he is
    not computing from area. He is booking a nominal minimum per piece: you cannot coat a
    40mm hook with six grams of powder. The gun does not care how small the part is, and
    there is overspray, sweep and colour-change loss on every piece regardless.

    25g, 30g, 40g. That is an experienced estimator carrying a floor in his head.

HOW IT LANDS

                       area x 0.20      floor       we book        Tim
        1310 hook          0.008        0.030      0.030 kg  0.30   0.30   EXACT
        7670 wire frame    0.005        0.030      0.030 kg  0.30   0.40   -25%
        1282 wall bay      1.092        0.030      1.09 kg  11.05   (8.85 today, +2.20)

    Note what the floor PREVENTS. Fitting a constant to the small parts (0.8 kg/m2, the
    median of Tim's three) would have put 4.4 kg of powder on 1282 — GBP 42 against the
    GBP 8.85 it books today. The floor model gives GBP 11.05: a sane correction, because on a
    big item the AREA term takes over and the floor stops mattering. That is the whole
    point of a max().

THE PIECE COUNT

    A "piece" is one object hanging on the booth line. If the job welds, the components
    become one object (the rule Dave gave us this morning). Otherwise each fabricated part
    hangs on its own.

    This is a simplification and the flag says so: on a job that welds SOME parts and bolts
    others, we count one object and may under-read the floor. On every such job we have seen,
    the area term dominates anyway and the floor never binds — so it does not reach the
    number. Worth revisiting if a counter-example appears.

EVERY NUMBER IS A NAMED LEVER IN config.py. When Tim gives us his actual rule it is a
one-line change, not a code change.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_powder_quantity_model.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_POWDER_MIN_KG_PER_PIECE"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# ── config.py ───────────────────────────────────────────────────────────────────
C_OLD = '''POWDER_KG_PER_M2 = 0.1667'''

C_NEW = '''# ASSUMPTION (2026-07-14) — estimator to confirm; see POWDER_MIN_KG_PER_PIECE below.
#
# The template's own calculator uses 0.1667 kg/m2 = 6 m2 per kilo = 100% TRANSFER
# EFFICIENCY. Nothing coats at 100%: most of the cloud misses the part and falls in the
# booth.
#
# A powder film is ~70 microns at ~1.5 g/cm3, so ~0.105 kg/m2 lands ON the part. At a
# realistic ~50% transfer efficiency you CONSUME ~0.20 kg/m2. That is a derivation from
# the physics, not a fit to our benchmark sheets.
POWDER_KG_PER_M2 = 0.20

# ASSUMPTION (2026-07-14) — estimator to confirm.
#
# Tim's sheets do not behave like a coverage model:
#     1298 bracket     0.025 kg
#     1310 hook plate  0.030 kg   (area 0.039 m2 -> implies 0.76 kg/m2)
#     7670 wire frame  0.040 kg   (area 0.023 m2 -> implies 1.70 kg/m2)
# The parts get SMALLER as the powder goes UP. That is backwards for coverage — so he is
# not computing from area on small parts. He is booking a nominal MINIMUM per piece.
#
# Which is right: you cannot coat a 40mm hook with six grams of powder. The gun does not
# care how small the part is, and there is overspray, sweep and colour-change loss on
# every piece regardless of its size.
#
# So:   powder_kg = max( area x POWDER_KG_PER_M2 , pieces x POWDER_MIN_KG_PER_PIECE )
#
# On a small part the floor binds and we land on Tim (1310: 0.030 kg, GBP 0.30, exact).
# On a big part the area term takes over and the floor never binds (1282: 1.09 kg) — which
# is why a floor is safe where a fitted coverage constant would NOT have been. Fitting
# 0.8 kg/m2 to the small parts would have put GBP 42 of powder on one wall bay.
POWDER_MIN_KG_PER_PIECE = 0.03'''


# ── wb_populate.py: import the new lever ────────────────────────────────────────
W_OLD_1 = '''try:
    from config import POWDER_KG_PER_M2 as _POWDER_KG_PER_M2
except Exception:
    _POWDER_KG_PER_M2 = 0.1667'''

W_NEW_1 = '''try:
    from config import POWDER_KG_PER_M2 as _POWDER_KG_PER_M2
except Exception:
    _POWDER_KG_PER_M2 = 0.20
# Minimum powder booked per coated object. Tim's sheets carry a floor (25-40g) that no
# coverage model explains — you cannot coat a 40mm hook with six grams. ASSUMPTION.
try:
    from config import POWDER_MIN_KG_PER_PIECE as _POWDER_MIN_KG_PER_PIECE
except Exception:
    _POWDER_MIN_KG_PER_PIECE = 0.03'''


# ── wb_populate.py: apply the floor ─────────────────────────────────────────────
W_OLD_2 = '''    _powder_area_m2 = _sheet_powder_area_m2 + _wire_powder_area_m2
    _powder_kg_total = round(_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)
    _wire_powder_kg = _powder_kg_total          # the BOM branch below reads this name'''

W_NEW_2 = '''    _powder_area_m2 = _sheet_powder_area_m2 + _wire_powder_area_m2
    _powder_by_area_kg = _powder_area_m2 * float(_POWDER_KG_PER_M2)

    # ── A MINIMUM PER PIECE, NOT JUST A COVERAGE RATE ───────────────────────────
    # A "piece" is one object on the booth line. If the job welds, the components become
    # ONE object — the rule the estimators gave us on 1310 this morning. Otherwise each
    # fabricated part hangs on its own.
    _mw_pw2 = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    _job_welds_pw = any(
        "weld" in str(_o).lower()
        for _m in _mw_pw2
        for _o in (_m.get("textual_operations") or _m.get("operations") or [])
    )
    _fab_pieces = 0
    for _fp in _all_pes_pw:
        _fsf = str((_fp.get("material_estimate") or {}).get("stock_form") or "").lower()
        if _fsf in ("sheet", "plate", "wire", "bar", "board"):
            _fab_pieces += int(_safe(_fp.get("quantity"), 1) or 1)
    _coated_pieces = 1 if _job_welds_pw else max(1, _fab_pieces)
    _powder_by_floor_kg = _coated_pieces * float(_POWDER_MIN_KG_PER_PIECE)

    _powder_kg_total = round(max(_powder_by_area_kg, _powder_by_floor_kg), 5)
    _powder_basis = ("MINIMUM PER PIECE" if _powder_by_floor_kg >= _powder_by_area_kg
                     else "COATED AREA")
    _wire_powder_kg = _powder_kg_total          # the BOM branch below reads this name

    if _powder_kg_total > 0:
        _flag(f"POWDER QUANTITY IS AN ASSUMPTION — estimator to confirm. "
              f"{_powder_area_m2:.4f} m2 coated x {_POWDER_KG_PER_M2} kg/m2 "
              f"= {_powder_by_area_kg:.4f} kg; floor of {_POWDER_MIN_KG_PER_PIECE} kg x "
              f"{_coated_pieces} coated object(s) = {_powder_by_floor_kg:.4f} kg. "
              f"BOOKED {_powder_kg_total} kg (the {_powder_basis}). "
              f"The template assumes 0.1667 kg/m2 = 100% transfer efficiency, which nothing "
              f"achieves; we use 0.20 (70um film, ~50% efficiency). The floor exists because "
              f"Tim's sheets show 25-40g on parts far too small to explain by area — you "
              f"cannot coat a 40mm hook with six grams. BOTH numbers are levers in config.py "
              f"(POWDER_KG_PER_M2, POWDER_MIN_KG_PER_PIECE) — tell us the real rule and it is "
              f"a one-line change.", flags)'''


def main():
    for p in (CONFIG, TARGET):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")

    cfg = open(CONFIG, "r", encoding="utf-8").read()
    wbp = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in wbp:
        sys.exit("Already applied (sentinel present).")

    # every replace BEFORE any write — abort leaves both files untouched
    cfg = sub(cfg, C_OLD, C_NEW, "config: coverage 0.1667 -> 0.20, add POWDER_MIN_KG_PER_PIECE")
    wbp = sub(wbp, W_OLD_1, W_NEW_1, "wb_populate: import the minimum-per-piece lever")
    wbp = sub(wbp, W_OLD_2, W_NEW_2, "wb_populate: kg = max(area x coverage, pieces x floor)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text, tag in ((CONFIG, cfg, "powderqty"), (TARGET, wbp, "powderqty")):
        bak = f"{path}.bak_{tag}_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
RUN 1310 (qty 50), THEN 1282 (qty 10), THEN 7670 (qty 50).

    1310   Powder | 9.73 | 0.030 kg | 4% | GBP 0.31      Tim: 0.03 kg, GBP 0.30   EXACT
           unit cost ~7.56 -> ~7.80
           The floor binds. Area alone would give 0.008 kg.

    7670   Powder 0.030 kg, GBP 0.31                     Tim: 0.04 kg, GBP 0.40   -25%
           The floor binds here too. An open wire frame lets most of the cloud through,
           so Tim books more than a flat part of the same area. We do not model that.

    1282   Powder ~1.09 kg, GBP ~11.05                   (books GBP 8.85 today, +GBP 2.20)
           The AREA term binds — 5.46 m2 of wall bay. The floor never comes near it.
           THIS IS WHY WE USED A FLOOR AND NOT A FITTED COVERAGE CONSTANT: fitting
           0.8 kg/m2 to Tim's small parts would have put GBP 42 of powder on this job.
           DIFF IT. Only the powder row and the totals below it may move.

THE QUESTION FOR TIM — send it with the write-up:

    "We now book powder as a BOM line, as you do, at your GBP 9.73/kg.
     For the QUANTITY we have assumed:  max(area x 0.20 kg/m2,  30g per coated piece).
     That lands exactly on your 0.03 kg for the 1310 hook.
     Two things we would like you to confirm or correct:
        1. Is there a minimum powder charge per piece, and is 30g about right?
        2. On a big item — a 500mm wall bay with 5.5 m2 of surface — do you compute
           from area, or judge it? What would you book?
     Both are single numbers in our config. Tell us and we change them today."
""")


if __name__ == "__main__":
    main()
