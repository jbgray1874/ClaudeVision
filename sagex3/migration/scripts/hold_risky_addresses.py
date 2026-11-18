"""Get the six rejected customers loaded: hold back the delivery addresses X3 is likely to reject.

    python hold_risky_addresses.py <YA004BPC .xlsx> <YA004BPCDL .xlsx> <out dir>

Why (18 Nov): X3 rejects a whole customer when one of its addresses fails (XPOSCOD postcode
format, XSAT missing State / Region). MAR101 has 1,205 addresses, so one bad one kept the whole
account - and £1.12m of open items - out of X3 in Run 4. Nothing here is invented: the account
loads with its sound addresses, and the held ones wait in their own file until X3's country
set-up is fixed (Ethan), then load as an update.

Only the six customers X3 rejected are touched (MAR101, TEC105, PER101, TEC100, UNI103, DRE100).
A non-default address of theirs is held when:
  1. its country needs a State / Region (AE, CA, AU, US) - the template's region column has no
     X3 field code, so X3 never receives the region we fill (asked of Ethan); or
  2. its country appears only on these six customers in the whole file (PT, CA, SG, MY, TH, BR,
     PY, MC, MT, CY, IN, RO, TR, BM...) - every other customer loaded, so X3's set-up for these
     countries is the likely cause; or
  3. its postcode doesn't match our format check for its country.
A DEFAULT address (BPAADDFLG = 2) can't be held - the customer needs it - so it's reported.

Writes to <out dir>:
  YA004BPC_customers_MAPPED.xlsx / .txt        the customer file without the held rows
  YA004BPCDL_delivery_addresses_MAPPED.xlsx / .txt   the delivery-address file without them
  Held_addresses_for_later.xlsx                every held row (full BPC row + BPCDL row) and why
"""
import os
import shutil
import sys
from collections import Counter

from openpyxl import Workbook, load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
sys.path.insert(0, HERE)
from common import add_sheet, write_load  # noqa: E402
from fix_customer_addresses import valid  # noqa: E402
from run3_fix_lists import POSTCODE  # noqa: E402

SIX = {"MAR101", "TEC105", "PER101", "TEC100", "UNI103", "DRE100"}
REGION = {"AE", "CA", "AU", "US"}
ADDR, POSCOD, CRY, FLAG = 17, 22, 24, 32      # 0-based columns in YA004BPC


def main(bpc_in, dl_in, out):
    os.makedirs(out, exist_ok=True)
    bpc_out = os.path.join(out, "YA004BPC_customers_MAPPED.xlsx")
    dl_out = os.path.join(out, "YA004BPCDL_delivery_addresses_MAPPED.xlsx")
    if os.path.abspath(bpc_in) != os.path.abspath(bpc_out):
        shutil.copy(bpc_in, bpc_out)
    shutil.copy(dl_in, dl_out)

    wb = load_workbook(bpc_out)
    ws = wb["Data with Headings"]
    rows = {r: [c.value for c in ws[r]] for r in range(3, ws.max_row + 1) if ws.cell(r, 2).value}
    by_country = Counter()
    for v in rows.values():
        by_country[(v[CRY] or "", v[1] in SIX)] += 1
    only_six = {c for (c, six), n in by_country.items() if six and not by_country.get((c, False))}

    held, report = {}, []
    for r, v in rows.items():
        cust, addr, cry, pc = v[1], str(v[ADDR] or ""), str(v[CRY] or ""), str(v[POSCOD] or "").strip().upper()
        if cust not in SIX:
            continue
        why = []
        if cry in REGION:
            why.append(f"{cry} needs a State/Region X3 doesn't receive yet")
        if cry in only_six and cry != "GB":
            why.append(f"{cry} is only on the rejected customers (X3 country set-up)")
        if pc and cry in POSTCODE and not valid(cry, pc):
            why.append(f"postcode '{pc}' isn't a {cry} format")
        if not why:
            continue
        if str(v[FLAG] or "") == "2":
            report.append([cust, addr, cry, pc, "DEFAULT address - can't be held; needs X3's set-up (Ethan): "
                           + "; ".join(why)])
            continue
        held[(cust, addr)] = (r, v, "; ".join(why))

    # the held rows out of the customer file (bottom up, so row numbers stay right)
    for r in sorted((h[0] for h in held.values()), reverse=True):
        ws.delete_rows(r)
    n = wb["Notes"]
    n.append([])
    n.append(["Held addresses (18 Nov)",
              f"{len(held):,} delivery addresses of the six customers X3 rejected are held back, so the "
              f"customers load (one bad address rejected the whole account in Run 4). They are in "
              f"Held_addresses_for_later.xlsx, to load once X3's country set-up is fixed. Nothing invented."])
    wb.save(bpc_out)
    write_load(bpc_out, "Data with Headings", 3)

    dwb = load_workbook(dl_out)
    dws = dwb["Data with headings"]
    dl_held = []
    for r in range(dws.max_row, 2, -1):
        key = (dws.cell(r, 1).value, str(dws.cell(r, 2).value or ""))
        if key in held:
            dl_held.append([c.value for c in dws[r]])
            dws.delete_rows(r)
    dwb.save(dl_out)
    write_load(dl_out, "Data with headings", 3)

    hw = Workbook()
    hw.remove(hw.active)
    head = [c.value for c in ws[1]]
    add_sheet(hw, "Why held", ["Customer", "Address", "Country", "Postcode", "Why"],
              [[k[0], k[1], h[1][CRY], h[1][POSCOD], h[2]] for k, h in sorted(held.items())] + report,
              [10, 8, 8, 12, 90])
    add_sheet(hw, "YA004BPC rows", [str(h or "") for h in head], [h[1] for _, h in sorted(held.items())])
    add_sheet(hw, "YA004BPCDL rows", ["BPCNUM", "BPAADD", "BPDNAM"], list(reversed(dl_held)), [10, 8, 40])
    hw.save(os.path.join(out, "Held_addresses_for_later.xlsx"))

    per = Counter(k[0] for k in held)
    print(f"held {len(held):,} addresses: {dict(sorted(per.items()))}; BPCDL rows held {len(dl_held):,}")
    print(f"default addresses that can't be held: {[(r[0], r[1], r[2]) for r in report]}")
    print(f"countries only on the six: {sorted(only_six)}")
    print("written", bpc_out, dl_out, os.path.join(out, "Held_addresses_for_later.xlsx"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
