"""YA004BPC column Q (ACCCOD, customer accounting code) from Finance's customer list.

    python fill_customer_acccod.py <YA004BPC .xlsx> <acccod.json>

<acccod.json> is built from Claire's Customer_List_master column T in the private sign-off folder
({"res": {sage code: {"codes": [...], "cur": ..., "access": "CODE(T value),..."}}}):
ASSIGNED -> ID, EURO -> EU, NON-ASSIGNED -> STD.

Rules (James, 18 Nov: "we can ask the questions but we can't wait"):
  - one code from Finance's list            -> that code
  - merged Access accounts that disagree    -> the code most of its Access accounts have; a tie
                                               goes to ID (the commonest code). PROVISIONAL
  - not on Finance's list                   -> EU for a euro account, otherwise STD. PROVISIONAL
Every provisional code is listed on the "ACCCOD" tab for Finance to confirm; a change later is one
field per customer. The file is rewritten in place, with its load file.
"""
import json
import re
import sys
from collections import Counter

from openpyxl import load_workbook

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/rebuild")
from common import add_sheet, write_load  # noqa: E402

ACCCOD = 16          # 0-based column Q
T_TO_CODE = {"ASSIGNED": "ID", "EURO": "EU", "NON-ASSIGNED": "STD"}


def decide(v):
    codes = v.get("codes") or []
    if len(codes) == 1:
        return codes[0], ""
    if codes:
        votes = Counter(T_TO_CODE.get(t) for t in re.findall(r"\(([A-Z-]+)\)", v.get("access") or ""))
        votes.pop(None, None)
        top = max(votes.values())
        best = sorted(c for c, n in votes.items() if n == top)
        code = "ID" if len(best) > 1 and "ID" in best else best[0]
        return code, f"PROVISIONAL - merged Access accounts disagree ({v.get('access')}); majority, tie -> ID"
    code = "EU" if (v.get("cur") or "") == "EUR" else "STD"
    return code, f"PROVISIONAL - not on Finance's list; {'euro account' if code == 'EU' else 'default'} -> {code}"


def main(bpc, json_path):
    res = json.load(open(json_path))["res"]
    wb = load_workbook(bpc)
    ws = wb["Data with Headings"]
    chosen, tab, n = {}, [], Counter()
    for code, v in res.items():
        chosen[code] = decide(v)
        n[chosen[code][0]] += 1
        if chosen[code][1]:
            tab.append([code, v.get("access") or "", v.get("cur") or "", chosen[code][0], chosen[code][1]])
    changed = 0
    for r in range(3, ws.max_row + 1):
        cust = ws.cell(r, 2).value
        if cust in chosen and ws.cell(r, ACCCOD + 1).value != chosen[cust][0]:
            ws.cell(r, ACCCOD + 1).value = chosen[cust][0]
            changed += 1
    if "ACCCOD" in wb.sheetnames:
        del wb["ACCCOD"]
    add_sheet(wb, "ACCCOD", ["Customer", "Access accounts (Finance's column T)", "Currency", "Code used", "Why"],
              sorted(tab), [10, 60, 8, 10, 90])
    wb["Notes"].append([])
    wb["Notes"].append(["ACCCOD (18 Nov)", f"Column Q from Finance's customer list (ASSIGNED -> ID, EURO -> EU, "
                        f"NON-ASSIGNED -> STD): {dict(n)}. {len(tab)} provisional, listed on 'ACCCOD' for Finance"])
    wb.save(bpc)
    write_load(bpc, "Data with Headings", 3)
    print(f"customers coded: {dict(n)}; provisional {len(tab)}; rows changed {changed:,}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
