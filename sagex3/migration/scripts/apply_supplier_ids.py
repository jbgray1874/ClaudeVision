"""Put Finance's / the public register's VAT and company numbers into YA004BPS (EECNUM, CRN).

    python apply_supplier_ids.py <YA004BPS .xlsx> <Finance_Suppliers_VAT_SIRET.xlsx> [--mock]

--mock (James, 18 Nov: "mock up data we know will load" for SDI source data that's missing, TRIAL LOADS
ONLY): a supplier with nothing given gets an OBVIOUSLY FAKE number that passes X3's checks -
  FR: SIREN 0000000nn (no real company has one), SIRET = SIREN + 0001n, VAT = FR + key + SIREN
  ES: ESB0000000n (a CIF of zeros with its control digit)
Each is marked MOCK on the "Supplier ID fixes" tab. Without --mock, a file that already holds a mock
is refused (is_mock), so mocks can't reach the dress rehearsal or go-live by accident.

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


MOCK_SIREN = re.compile(r"^0{7}\d{2}$")


def is_mock(value):
    v = re.sub(r"\D", "", str(value or ""))
    return bool(MOCK_SIREN.match(v[:9])) or str(value or "").upper().startswith("ESB000000")


def mock_ids(n, cry):
    """The n-th obviously fake but check-valid number pair for a country: (vat, crn)."""
    if cry == "ES":
        return f"ESB{n:07d}{es_control(f'{n:07d}')}", None
    k = 0
    for a in range(1, 100):            # never all zeros - X3 could read that as empty
        siren = f"0000000{a:02d}"
        if luhn(siren):
            k += 1
            if k == n:
                break
    nic = next(f"0001{d}" for d in range(10) if luhn(siren + f"0001{d}"))
    return fr_vat(siren), siren + nic


def es_control(digits7):
    """Control digit of a Spanish CIF for an SL (letter B): numeric."""
    a = sum(int(d) for d in digits7[1::2])
    b = sum(sum(int(x) for x in str(int(d) * 2)) for d in digits7[0::2])
    return str((10 - (a + b) % 10) % 10)


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


def main(bps, sheet, mock=False):
    fw = load_workbook(sheet).worksheets[0]
    rows = list(fw.iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "Supplier")
    head = [str(c or "") for c in rows[h]]
    c_vat = next(i for i, t in enumerate(head) if t.startswith("VAT number to load"))
    c_crn = next(i for i, t in enumerate(head) if t.startswith("Company no. to load"))
    given = {r[0]: (r[2], r[c_vat], r[c_crn]) for r in rows[h + 1:] if r and r[0]}

    wb = load_workbook(bps)
    ws = wb["Data with Headings"]
    fixes, left, n_mock = [], [], 0
    if not mock:
        logged = set()                 # mocks a fake pattern can't show (a mock site number on a real SIREN)
        if "Supplier ID fixes" in wb.sheetnames:
            logged = {(r[0], str(r[3]).split()[0]) for r in wb["Supplier ID fixes"].iter_rows(min_row=2, values_only=True)
                      if r and r[3] and "MOCK" in str(r[3])}
        found = [ws.cell(r, 2).value for r in range(3, ws.max_row + 1)
                 if is_mock(ws.cell(r, EECNUM + 1).value) or is_mock(ws.cell(r, CRN + 1).value)
                 or (ws.cell(r, 2).value, str(ws.cell(r, CRN + 1).value)) in logged
                 or (ws.cell(r, 2).value, str(ws.cell(r, EECNUM + 1).value)) in logged]
        if found:
            raise SystemExit(f"MOCK numbers in {bps}: {found} - real numbers needed (mocks are for trial loads only)")
    for r in range(3, ws.max_row + 1):
        sup = ws.cell(r, 2).value
        if sup not in given:
            continue
        cry, vat_in, crn_in = given[sup]
        held = str(ws.cell(r, EECNUM + 1).value or "")
        if not vat_in and cry == "FR" and held.startswith("FR"):
            vat_in = held          # a real VAT number already in the file is kept, never mocked over
        if not (vat_in or crn_in) and mock and cry in ("FR", "ES"):
            n_mock += 1
            vat, crn = mock_ids(n_mock, cry)
            for col, new in ((EECNUM, vat), (CRN, crn)):
                if new:
                    fixes.append([sup, ws.cell(1, col + 1).value, ws.cell(r, col + 1).value, f"{new}  MOCK"])
                    ws.cell(r, col + 1).value = new
            left.append([sup, cry, "MOCK numbers loaded for the trial - real ones needed before the dress rehearsal"])
            continue
        if not (vat_in or crn_in):
            left.append([sup, cry, "nothing given yet"])
            continue
        vat, crn, problem = check(cry, str(vat_in or ""), str(crn_in or ""))
        for col, new in ((EECNUM, vat), (CRN, crn)):
            if new and ws.cell(r, col + 1).value != new:
                fixes.append([sup, ws.cell(1, col + 1).value, ws.cell(r, col + 1).value, new])
                ws.cell(r, col + 1).value = new
        if problem == "SIRET still needed" and mock and cry == "FR":
            nic = next(f"0001{d}" for d in range(10) if luhn(vat[4:] + f"0001{d}"))
            fixes.append([sup, ws.cell(1, CRN + 1).value, ws.cell(r, CRN + 1).value, f"{vat[4:]}{nic}  MOCK site no."])
            ws.cell(r, CRN + 1).value = vat[4:] + nic
            left.append([sup, cry, "real SIREN, MOCK site number (0001n) - real SIRET needed before the dress rehearsal"])
        elif problem:
            left.append([sup, cry, problem])
    if "Supplier ID fixes" in wb.sheetnames:
        del wb["Supplier ID fixes"]
    add_sheet(wb, "Supplier ID fixes", ["Supplier", "Field", "Was", "Now"], fixes + [[]] +
              [["Still open", "", "", ""]] + [[s, c, p, ""] for s, c, p in left], [10, 10, 30, 30])
    wb.save(bps)
    write_load(bps, "Data with Headings", 3)
    print(f"{len(fixes)} values loaded; still open: {left}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--mock"]
    main(args[0], args[1], mock="--mock" in sys.argv)
