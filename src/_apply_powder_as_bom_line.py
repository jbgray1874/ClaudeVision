#!/usr/bin/env python3
r"""
_apply_powder_as_bom_line.py

DAVE: "No powder allowed for on AI estimate."

He was reading the BILL OF MATERIALS, and he was right to. Tim writes powder as a BOM line:

    Powder      GBP 9.73    0.03 kg    4%    GBP 0.30

Ours is costed but INVISIBLE. It lives in the Powder Qty Calculator off to the right of
the sheet and is bolted onto the material total as a separate term:

    M92 = SUM(M11:M50) + SUM(M53:M60) + SUM(M63:M81) + SUM(M84:M91) + AF83
                                                                      ^^^^
    AF83 = AD82 * AF82        = total kg x GBP/kg
    AD82 = SUM(AD63:AD81)     = per-part kg from the calculator

So it DOES reach the total. It just never appears as a line, and an estimator scanning the
BOM sees nothing. That is a fair complaint about a deliverable.

WHAT THIS DOES

  1. Computes the coated area in Python, from real geometry:
         sheet:  blank L x W x 2 faces x qty
         wire:   pi x dia x length x qty        (a cylinder; the template cannot see this)
     For 1310-01 that gives 0.03775 m2 — which matches the template's own AB63 exactly, so
     we know the area maths agrees with theirs.

  2. Writes it as a REAL BOM ROW: description, GBP/kg, kg, 4% scrap, line total.
     Same shape as Tim's. If the drawing names a specific powder (7670's TLP-J125-T RYOBI
     GREEN) that row is used and its catalogue rate kept; if the drawing names none (1310)
     a generic "Powder" row is added, because the part still gets coated.

  3. Sets AF83 = 0, so the template's own term contributes nothing and the powder is NOT
     double-counted.

WHAT THIS DELIBERATELY DOES NOT DO — THE COVERAGE RATE

The kg is still area x config.POWDER_KG_PER_M2 = 0.1667, which is 6 m2 per kilo = 100%
TRANSFER EFFICIENCY. Nothing coats at 100%. So the quantity is too LOW, and the flag says
so, loudly, on every job.

The obvious move is to fit the constant to Tim's sheets. Do not:

    1298 bracket      area ?         Tim 0.025 kg     -> 0.45 kg/m2
    1310 hook plate   0.039 m2       Tim 0.03  kg     -> 0.76 kg/m2
    7670 wire frame   0.023 m2       Tim 0.04  kg     -> 1.70 kg/m2

The rate goes UP as the part gets SMALLER. That is backwards for a coverage model, and it
means Tim is very likely booking a rule of thumb per piece (30g, 40g) rather than computing
from area at all.

And the stakes are real: 1282 carries 5.46 m2 of coated area. At a fitted 0.80 kg/m2 that
is 4.4 kg of powder on ONE wall bay — GBP 42, against the GBP 8.85 it books today. Fitting a
constant to three small parts and applying it to a bay would be a serious error.

So: MECHANISM NOW, RATE WHEN TIM TELLS US. One line in config.py the moment he does.

EXPECTED EFFECT — small and explainable, which is the point

    1310   powder moves from the calculator to a BOM row.
           kg rises slightly (the stud's area is now included; the template only sees sheet).
           ~GBP 0.06 -> ~GBP 0.07 with scrap.        Tim: GBP 0.30.  The GAP IS THE RATE.

    1282   powder moves from AF83 to a BOM row at the SAME kg. The only change is the 4%
           scrap the BOM row applies and AF83 did not — which is what Tim's own sheet does.
           GBP 8.85 -> GBP 9.20. Unit cost +~GBP 0.38.

    7670   already had a powder BOM row (the RYOBI GREEN catalogue line). Unchanged in shape;
           its kg now also includes any sheet area, of which it has none.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_powder_as_bom_line.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_powder_kg_total"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# 1. Total coated area = sheet + wire, and a real total kg.
OLD_1 = '''    _wire_powder_kg = round(_wire_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)'''

NEW_1 = '''    # ── SHEET AREA TOO ──────────────────────────────────────────────────────────
    # The template's calculator sees only the Sheet Steel block. Now that powder is a BOM
    # LINE and no longer comes from that calculator, we must compute the sheet area here
    # as well — otherwise moving it to the BOM would silently drop it.
    #
    # Two faces, because a sheet has two sides. For 1310-01 this gives
    #     167.04 x 113 x 2 / 1e6 = 0.03775 m2
    # which matches the template's own AB63 to five decimal places. The area maths agrees
    # with theirs; only the coverage RATE is in dispute.
    _sheet_powder_area_m2 = 0.0
    for _sp in _all_pes_pw:
        _sme = _sp.get("material_estimate") or {}
        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", ""):
            continue
        _sng = _sp.get("normalized_geometry") or {}
        _sl = _safe(_sme.get("blank_length_mm") or _sng.get("blank_length_mm"))
        _sw = _safe(_sme.get("blank_width_mm") or _sng.get("blank_width_mm"))
        _sq = _safe(_sp.get("quantity"), 1) or 1
        if _sl and _sw:
            _sheet_powder_area_m2 += (_sl / 1000.0) * (_sw / 1000.0) * 2.0 * float(_sq)

    _powder_area_m2 = _sheet_powder_area_m2 + _wire_powder_area_m2
    _powder_kg_total = round(_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)
    _wire_powder_kg = _powder_kg_total          # the BOM branch below reads this name'''


# 2. The BOM branch prices the whole powder quantity, not just the wire's.
OLD_2 = '''                price = _cat_rate
                qty = _wire_powder_kg'''

NEW_2 = '''                price = _cat_rate
                qty = _powder_kg_total'''


# 3. If the drawing names no powder, add the row anyway — the part still gets coated.
OLD_3 = '''    b = cm["bom"]
    row = b["first_row"]
    for pe in bom_parts:'''

NEW_3 = '''    # ── POWDER IS A LINE ON THE BILL OF MATERIALS ───────────────────────────────
    # Tim writes it as one:   Powder | GBP 9.73 | 0.03 kg | 4% | GBP 0.30
    # We had it hidden in the Powder Qty Calculator and bolted onto M92 via AF83, so an
    # estimator reading the BOM saw nothing. That is Dave's "no powder allowed for".
    #
    # If the drawing NAMES a powder (7670's TLP-J125-T RYOBI GREEN) that row already exists
    # and gets the quantity. If the drawing names none (1310) the part is still coated, so
    # add a generic row rather than let the cost vanish.
    def _is_powder_row(_p):
        return ("POWDER" in str(_p.get("part_number") or "").upper()
                or "POWDER" in str(_p.get("description") or "").upper()
                or bool(_p.get("_consumable_qty_unknown")))

    if _powder_kg_total > 0 and not any(_is_powder_row(_p) for _p in bom_parts):
        bom_parts = list(bom_parts) + [{
            "part_number": "POWDER",
            "description": "Powder — computed from coated surface area "
                           f"({_powder_area_m2:.4f} m2)",
            "quantity": 1,
            "_price_explicitly_withheld": True,   # routes through the consumable branch,
            "_consumable_qty_unknown": True,      # which sets qty = kg and price = GBP/kg
            "_catalogue_rate_gbp": float(_POWDER_COST_PER_KG or 9.73),
        }]

    # Kill the template's own powder term. M92 adds AF83 (= total kg x GBP/kg) on top of the
    # material blocks. Powder is now a BOM row inside SUM(M11:M50), so leaving AF83 alive
    # would charge it TWICE.
    try:
        ws["AF83"] = 0
    except Exception:
        pass

    b = cm["bom"]
    row = b["first_row"]
    for pe in bom_parts:'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    src = sub(src, OLD_1, NEW_1, "coated area = sheet (L x W x 2) + wire (pi.d.L)")
    src = sub(src, OLD_2, NEW_2, "BOM powder row prices the WHOLE quantity")
    src = sub(src, OLD_3, NEW_3, "add the powder BOM row; zero AF83 so nothing double-counts")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_powderbom_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print("""
RUN 1310 (qty 50), THEN 1282 (qty 10), THEN 7670 (qty 50).

1310  — a POWDER row appears on the Bill of Materials, which is what Dave asked for:
            Powder ...  GBP 9.73   0.0066 kg   4%   GBP 0.07
        Tim books 0.03 kg / GBP 0.30. WE ARE 4.6x UNDER, AND THAT IS THE COVERAGE RATE,
        NOT THE MECHANISM. The area (0.0394 m2) matches the template's own calculation.
        config.POWDER_KG_PER_M2 = 0.1667 assumes 100% transfer efficiency.

1282  — powder simply MOVES from AF83 to a BOM row at the same kg. The only change is the
        4% scrap the BOM row applies (which is what Tim's sheet does too).
            GBP 8.85 -> GBP 9.20,  unit cost 206.65 -> ~207.03
        DIFF IT. The only cells that may move are the powder row and the totals below it.
        Anything else moving is a bug.

7670  — already had a powder BOM row. Shape unchanged.

THE QUESTION FOR TIM, and it is the last unknown on powder:

    "You book 0.025 kg on a bracket, 0.03 kg on a hook plate and 0.04 kg on a wire frame.
     Those parts get SMALLER as the powder goes UP, so it does not look like you are
     computing from surface area. What is the rule? And what would you book on a 500mm
     wall bay with 5.5 m2 of surface?"

    That last number is the one we cannot guess. Everything else is measured.
""")


if __name__ == "__main__":
    main()
