r"""
patch_powder_include_statedweight.py — make the powder-area sum robust to stock_form.

CONFIRMED BY MEASUREMENT: shapely (valid blank_area_mm2) flips steel parts to
stock_form="stated_weight" (the weight-costing path). The powder loop (wb_populate:506)
only sums stock_form in ("sheet","plate",""), EXCLUDING "stated_weight" — so those steel
parts dropped from the powder sum and powder fell 5.361 -> 1.639 m2. Meanwhile the ROUTING
logic (wb_populate:387) already treats STEEL_STOCK_FORMS = {"sheet","stated_weight"} as
steel. The powder filter is simply inconsistent with the routing filter.

FIX: align the powder inclusion with the routing — accept "stated_weight" too. Then powder
sums all coated steel on GROSS L x W regardless of stock_form, so re-applying shapely (which
flips stock_form) leaves powder UNCHANGED. Powder basis stays GROSS (unchanged); this only
stops steel parts falling out of the sum.

This is the prerequisite for safely re-deploying shapely net-area. Powder stays on gross
pending Tim; net area (once shapely is re-applied) feeds WEIGHT separately.

One-line change, exact-match-or-refuse, TIMESTAMPED backup (no collision with stale .bak).
"""
import sys, shutil, ast, datetime
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

OLD = '        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", ""):'
NEW = '        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", "stated_weight", ""):  # include stated_weight: it is coated steel routed by weight, must not drop from the powder sum (aligns with STEEL_STOCK_FORMS routing filter). Powder basis stays GROSS L x W; this only keeps steel parts in the sum when a valid blank area flips them onto the weight path.'

def main():
    if not TARGET.is_file():
        sys.exit(f"NOT FOUND: {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if '"stated_weight", ""' in src and 'not in ("sheet", "plate", "stated_weight"' in src:
        sys.exit("Already patched (powder filter includes stated_weight). No change made.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"REFUSE: anchor found {n} times (expected 1). Live bytes differ — no change written.")

    src2 = src.replace(OLD, NEW, 1)
    try:
        ast.parse(src2)
    except SyntaxError as e:
        sys.exit(f"REFUSE: patched file does not parse: {e}")

    # TIMESTAMPED backup — never collides with an existing stale .bak
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = TARGET.with_suffix(f".py.bak_powderinc_{ts}")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src2, encoding="utf-8")
    print(f"PATCHED {TARGET}")
    print(f"  backup: {bak}")
    print("  line 506: powder filter now includes 'stated_weight' (aligns with routing STEEL_STOCK_FORMS)")
    print("  effect NOW (shapely still reverted): powder should stay 5.3610 m2 / £10.85 — NO CHANGE")
    print("    (these parts are currently 'sheet'/'' so already summed; the fix is inert until shapely flips them)")
    print("  THEN: re-apply shapely -> parts flip to stated_weight -> STILL summed -> powder holds 5.3610.")

if __name__ == "__main__":
    main()
