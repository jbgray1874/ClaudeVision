#!/usr/bin/env python3
r"""
_probe_double_cost.py  —  READ-ONLY.

Steel parts (e.g. 12532-02-02M BASE PLINTH) are tagged page_roles=['detail','bought_in'].
CONCERN: does a dual-tagged part get costed TWICE — once as a bought-in purchased item
(unit_cost_gbp / bought-in price) AND once as a fabricated part (steel material + laser
+ fold + powder labour)? That would double-count real money.

This probe lists every part tagged 'bought_in' and shows, side by side:
  - does it have a bought-in PURCHASE price? (unit_cost_gbp / unit_material_cost_gbp
    from a catalogue/UDEF/display-board source)
  - does it ALSO have FABRICATION signals? (stock_form=sheet, blank geometry, a
    labour_estimate.costs_gbp with laser/fold/powder ops)
  - which block would wb_populate put it in? (BOM if bought_in wins, Steel if stock_form)
  - a VERDICT: single-costed (ok) or potentially double-costed (bought-in price AND
    fabrication labour both present)

The key question per part: is it in ONE cost path or TWO?

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_double_cost.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json


def find_parts(data):
    best = {}
    def walk(o):
        if isinstance(o, dict):
            pn = o.get("part_number")
            if pn is not None:
                pn = str(pn)
                if pn not in best or len(o.keys()) > len(best[pn].keys()):
                    best[pn] = o
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    return best


def num(v):
    try: return float(v)
    except Exception: return None


def main(jpath):
    parts = find_parts(json.load(open(jpath, "r", encoding="utf-8")))

    print("=" * 100)
    print("DOUBLE-COST PROBE — do detail+bought_in parts get priced twice?")
    print("=" * 100)

    dual = []
    for pn, pe in sorted(parts.items()):
        roles = [str(r).lower() for r in (pe.get("page_roles") or [])]
        if "bought_in" not in roles:
            continue

        # bought-in purchase price?
        unit_cost = num(pe.get("unit_cost_gbp"))
        me = pe.get("material_estimate") or {}
        unit_mat = num(pe.get("unit_material_cost_gbp") or me.get("unit_material_cost_gbp"))
        cost_source = str(pe.get("cost_source") or pe.get("source") or "")
        has_bought_price = (unit_cost and unit_cost > 0) or (unit_mat and unit_mat > 0)

        # fabrication signals?
        stock_form = str(me.get("stock_form") or pe.get("normalized_geometry", {}).get("stock_form") or "").lower()
        blank_l = num(me.get("blank_length_mm"))
        le = pe.get("labour_estimate") or {}
        costs = le.get("costs_gbp") or {}
        fab_ops = [k for k in costs.keys() if k.lower() in
                   ("laser_cutting", "folding", "powder_coating", "punch", "welding")]
        is_fab = bool(stock_form == "sheet" or (blank_l and blank_l > 0) or fab_ops)

        # which block would wb_populate choose? (bought_in role -> BOM only if it reaches
        # rule 5 before steel rule; but steel rule 3 (stock_form in sheet) comes FIRST)
        # rules order: 3 steel(stock_form) -> 4 tube -> 5 bought_in.  So stock_form=sheet
        # WINS and it goes to STEEL. If stock_form empty, bought_in -> BOM.
        if stock_form == "sheet":
            block = "STEEL (stock_form=sheet wins over bought_in)"
        elif "bought_in" in roles:
            block = "BOM (bought_in)"
        else:
            block = "?"

        verdict = "single"
        if has_bought_price and is_fab and "STEEL" in block:
            # it's in steel (fabricated) — is the bought-in price ALSO used anywhere?
            verdict = "CHECK: has bought price AND fab; goes to STEEL — is bought price also added?"
        elif has_bought_price and "BOM" in block:
            verdict = "single (BOM, bought price only)"
        elif is_fab and "STEEL" in block and not has_bought_price:
            verdict = "single (STEEL, fabrication only)"

        dual.append(pn)
        print(f"\n{pn}  {pe.get('description')!r}")
        print(f"  roles={roles}")
        print(f"  bought-in price: unit_cost={unit_cost} unit_mat={unit_mat} source={cost_source!r} -> has_price={has_bought_price}")
        print(f"  fabrication    : stock_form={stock_form!r} blank_l={blank_l} fab_ops={fab_ops} -> is_fab={is_fab}")
        print(f"  wb block       : {block}")
        print(f"  VERDICT        : {verdict}")

    print("\n" + "=" * 100)
    print("KEY: wb_populate rule order is steel(stock_form=sheet) BEFORE bought_in.")
    print("So a sheet part tagged bought_in goes to the STEEL block (fabricated), and its")
    print("bought_in role is IGNORED for placement -> it is NOT also added to BOM.")
    print("=> If every dual-tagged sheet part shows block=STEEL and no separate BOM line,")
    print("   there is NO double count. Confirm by checking the BOM block on the sheet has")
    print("   no 02-xxM / 03-xxM fabricated part numbers in it.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_double_cost.py <json>"); sys.exit(1)
    main(sys.argv[1])
