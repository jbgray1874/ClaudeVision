"""Put Finance's / the public register's VAT and company numbers into YA004BPS (EECNUM, CRN).

    python apply_supplier_ids.py <YA004BPS .xlsx> <Finance_Suppliers_VAT_SIRET.xlsx>

The fill-in sheet is deliver/Finance_Suppliers_VAT_SIRET.xlsx (headings on the row starting
"Supplier"): column "VAT number to load" and column "Company no. to load (SIRET / ...)".

French suppliers: only the SIRET is needed. It's 14 digits on the public register
(annuaire-entreprises.data.gouv.fr: search the name, take the head office "siège" SIRET); its first
9 digits are the SIREN, and the VAT number is FR + key + SIREN, key = (12 + 3 x (SIREN mod 97)) mod 97.
If a VAT number is given as well, it must agree with the SIRET.

Every number is checked before it goes in (no dummies - a wrong number can load and stick):
  SIREN and SIRET pass the Luhn check; an FR VAT number's key matches its SIREN; ES numbers are
  ES + 9 characters. Anything failing is reported and NOT loaded. Every change is listed on the
  "Supplier ID fixes" tab. The file is rewritten in place, with its load file.
"""
import re
import sys

from openpyxl import load_workbook

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/rebuild")
from common import add_sheet, write_load  # noqa: E402

CRN, EECNUM = 5, 6        # 0-based columns in YA004BPS


def luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def fr_vat(siren):
    return f"FR{(12 + 3 * (int(siren) % 97)) % 97:02d}{siren}"


def check(cry, vat, siret):
    """(vat, crn, problem)"""
    vat = re.sub(r"[\s.\-]", "", vat or "").upper()
    siret = re.sub(r"\D", "", siret or "")
    if cry == "FR":
        if siret:
            if len(siret) != 14 or not luhn(siret) or not luhn(siret[:9]):
                return None, None, f"SIRET '{siret}' fails its check (14 digits, Luhn)"
            want = fr_vat(siret[:9])
            if vat and vat != want:
                return None, None, f"VAT '{vat}' doesn't match the SIRET (expected {want})"
            return want, siret, ""
        if vat:
            m = re.fullmatch(r"FR(\d{2})(\d{9})", vat)
            if not m or fr_vat(m.group(2)) != vat or not luhn(m.group(2)):
                return None, None, f"VAT '{vat}' isn't a valid FR number"
            return vat, None, "SIRET still needed"
        return None, None, "nothing given"
    if cry == "ES":
        if vat and not re.fullmatch(r"ES[A-Z0-9]\d{7}[A-Z0-9]", vat):
            return None, None, f"VAT '{vat}' isn't ES + 9 characters"
        return vat or None, siret or None, "" if vat else "nothing given"
    return vat or None, siret or None, ""


def main(bps, sheet):
    fw = load_workbook(sheet).worksheets[0]
    rows = list(fw.iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "Supplier")
    head = [str(c or "") for c in rows[h]]
    c_vat = next(i for i, t in enumerate(head) if t.startswith("VAT number to load"))
    c_crn = next(i for i, t in enumerate(head) if t.startswith("Company no. to load"))
    given = {r[0]: (r[2], r[c_vat], r[c_crn]) for r in rows[h + 1:] if r and r[0]}

    wb = load_workbook(bps)
    ws = wb["Data with Headings"]
    fixes, left = [], []
    for r in range(3, ws.max_row + 1):
        sup = ws.cell(r, 2).value
        if sup not in given:
            continue
        cry, vat_in, crn_in = given[sup]
        if not (vat_in or crn_in):
            left.append([sup, cry, "nothing given yet"])
            continue
        vat, crn, problem = check(cry, str(vat_in or ""), str(crn_in or ""))
        for col, new in ((EECNUM, vat), (CRN, crn)):
            if new and ws.cell(r, col + 1).value != new:
                fixes.append([sup, ws.cell(1, col + 1).value, ws.cell(r, col + 1).value, new])
                ws.cell(r, col + 1).value = new
        if problem:
            left.append([sup, cry, problem])
    if "Supplier ID fixes" in wb.sheetnames:
        del wb["Supplier ID fixes"]
    add_sheet(wb, "Supplier ID fixes", ["Supplier", "Field", "Was", "Now"], fixes + [[]] +
              [["Still open", "", "", ""]] + [[s, c, p, ""] for s, c, p in left], [10, 10, 30, 30])
    wb.save(bps)
    write_load(bps, "Data with Headings", 3)
    print(f"{len(fixes)} values loaded; still open: {left}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
