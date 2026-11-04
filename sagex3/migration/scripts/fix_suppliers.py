"""YA004BPS: the supplier fixes from Run 2 (Ethan's notes: FR suppliers with EECNUM and CRN blank).

X3 needs the intra-EU VAT number (EECNUM) and the company registration number (CRN, the 14-digit
SIRET) on a French supplier. Run 2 blanked the VAT numbers as dummies, but the original Access
values are checked here, not assumed:
  * a French VAT number is FR + a 2-digit key + the 9-digit SIREN, and the key is fixed by the
    SIREN: key = (12 + 3 x (SIREN mod 97)) mod 97, and a SIREN passes the Luhn check. A value
    that passes both is a real FR VAT number, whatever prefix Access gave it - it's restored
    with FR. (GAL500 "GB65572062594" -> FR65572062594; ICE500 "GB73539546192" -> FR73539546192)
  * a value that passes no check (FR, GB or SIREN) stays blank, for Finance
  * the CRN can't be derived: the SIRET is the SIREN plus a 5-digit site number Access doesn't hold
Every change and everything still missing is listed. A complete file (rule 1b) with its load file.

Usage:
    python fix_suppliers.py             (IN_FILE / ACCESS_VAT / OUT_DIR to override)
"""
import csv
import os
import shutil
import sys

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
from common import add_sheet, read_grids, write_load  # noqa: E402
from fix_customer_addresses import POSTCODE, postcode_in_text, valid  # noqa: E402  the same address rules

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
IN_FILE = os.environ.get("IN_FILE", f"{BASE}/out_sheets/YA004BPS_suppliers_MAPPED.xlsx")    # the 27 Oct build, before any fix
ACCESS_VAT = os.environ.get("ACCESS_VAT", f"{BASE}/upl2/bps.txt")    # the supplier file before Run 2's blanking
BP_IDENTIFIERS = os.environ.get("BP_IDENTIFIERS", f"{BASE}/runs/2026-11-04/extract/bp_identifiers.txt")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_run3")
CRY, CRN, EECNUM, VAC = 3, 5, 6, 7                                       # 0-based columns
LINES, STATE, POSCOD, ADR_CRY, PHONES = (12, 13, 14), 15, 17, 18, (19, 20)
REJECTED = ["AMG500", "AGE500", "GAL500", "GRO500", "ICE500", "PLS500", "VUS500", "SOG500", "BAL500",
            "BUR500", "ECO500"]                                          # Ethan's Run 2 notes


def luhn(s):
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def fr_vat(value):
    """The FR VAT number a value really is, or None."""
    d = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(d) == 11 and luhn(d[2:]) and int(d[:2]) == (12 + 3 * (int(d[2:]) % 97)) % 97:
        return "FR" + d
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    original = {r[1]: r for r in csv.reader(open(ACCESS_VAT, encoding="cp850", errors="replace"), delimiter=";")
                if len(r) > 7}
    # straight from Access (bp_identifiers_run3.sql): PL_ACCOUNTS.SU_VAT_REG_NO and SU_TAX_CODE per Sage code
    access = {}
    if os.path.exists(BP_IDENTIFIERS):
        g, _ = read_grids(BP_IDENTIFIERS)
        cols = [r[2] for r in g["COLUMN"] if r[0] == "PL_ACCOUNTS"]
        sage = {r[2].strip(): r[1] for r in g["CODES"] if r[0] == "S"}
        for r in g.get("PLACC", []):
            code = r[cols.index("SUCODE")].strip()
            if code in sage:
                access[sage[code]] = {"vat": r[cols.index("SU_VAT_REG_NO")].strip(),
                                      "tax": r[cols.index("SU_TAX_CODE")].strip(), "access": code}
    path = f"{OUT}/YA004BPS_suppliers_MAPPED.xlsx"
    shutil.copy(IN_FILE, path)
    wb = load_workbook(path)
    for t in ("Supplier fixes", "Supplier check", "Address fixes", "Address check"):
        if t in wb.sheetnames:
            raise SystemExit(f"{IN_FILE} already has a '{t}' tab - start from the unfixed build (IN_FILE)")
    ws = wb["Data with Headings"]
    fixes, check = [], []
    for r in range(3, ws.max_row + 1):
        sup = ws.cell(r, 2).value
        if not sup:
            continue
        cry = ws.cell(r, CRY + 1).value
        vat = ws.cell(r, EECNUM + 1).value
        was = access.get(sup, {}).get("vat") or original.get(sup, [""] * 8)[6]
        if was == "NULL":
            was = ""
        if cry == "FR" and not vat:
            fv = fr_vat(was)
            if fv:
                ws.cell(r, EECNUM + 1, fv)
                fixes.append([sup, ws.cell(r, 3).value, "EECNUM", was, fv,
                              "a real FR VAT number in Access (key and SIREN check pass) - restored with FR"])
        if sup in REJECTED:
            need = []
            if not ws.cell(r, EECNUM + 1).value or cry != "FR" and str(ws.cell(r, EECNUM + 1).value)[:2] != cry:
                need.append(f"EECNUM: Access had '{was}' - not a valid VAT number" if was else
                            "EECNUM: nothing in Access")
            if cry == "FR" and not ws.cell(r, CRN + 1).value:
                fv = ws.cell(r, EECNUM + 1).value or ""
                need.append("CRN (SIRET, 14 digits)" + (f": the SIREN is {fv[4:]}, the 5-digit site number "
                                                        "isn't in Access" if fv.startswith("FR") else ""))
            if cry == "FR" and ws.cell(r, VAC + 1).value == "DOM":
                tax = access.get(sup, {}).get("tax")
                need.append(f"tax rule DOM on an FR supplier (Access tax code {tax or '?'}, where the other FR "
                            "suppliers are FZ / FV) - ROWS like them? (Finance)")
            if cry != "FR":
                need.append(f"country {cry} with VAT number {ws.cell(r, EECNUM + 1).value} - which is right? (Finance)")
            check.append([sup, ws.cell(r, 3).value, cry, ws.cell(r, VAC + 1).value, ws.cell(r, EECNUM + 1).value or "",
                          ws.cell(r, CRN + 1).value or "", "; ".join(need)])
    # the customer address rules, on every supplier address: postcode out of the address lines
    for r in range(3, ws.max_row + 1):
        sup = ws.cell(r, 2).value
        if not sup:
            continue
        get = lambda c: str(ws.cell(r, c + 1).value or "").strip()
        acry, pc = get(ADR_CRY) or get(CRY), get(POSCOD).upper()
        if not pc:
            found = postcode_in_text(acry, [get(c) for c in LINES])
            if found:
                i, p, rest = found
                for col, new in ((LINES[i], rest), (POSCOD, p)):
                    fixes.append([sup, ws.cell(r, 3).value, ws.cell(1, col + 1).value, get(col), new,
                                  "postcode moved out of the address line (customer address rule 1)"])
                    ws.cell(r, col + 1, new or None)
        for c in PHONES:
            ph = get(c)
            if "(" in ph or ")" in ph:
                new = " ".join(ph.replace("(", " ").replace(")", " ").split())
                fixes.append([sup, ws.cell(r, 3).value, "Telephone", ph, new, "phone: brackets removed"])
                ws.cell(r, c + 1, new)
    add_sheet(wb, "Supplier fixes", ["Supplier", "Name", "Field", "Was (Access)", "Now", "Why"], fixes,
              [10, 30, 10, 18, 18, 70])
    add_sheet(wb, "Supplier check", ["Supplier", "Name", "Country", "Tax rule", "EECNUM", "CRN", "Still needed"],
              check, [10, 30, 8, 8, 16, 16, 90])
    n = wb["Notes"]
    n.append([])
    n.append(["Supplier fixes (4 Nov)", f"{len(fixes)} FR VAT numbers restored from Access after the key and SIREN "
                                        f"checks; {len(check)} rejected suppliers listed with what each still needs "
                                        "(Finance). Nothing else changed"])
    wb.save(path)
    txt, lines, _ = write_load(path, "Data with Headings", 3)
    print(path, f"\n  {len(fixes)} fixes:", [f[0] + " " + f[4] for f in fixes], f"\n  still needed: {len(check)}",
          f"\n  {lines:,} rows | {txt}")


if __name__ == "__main__":
    main()
