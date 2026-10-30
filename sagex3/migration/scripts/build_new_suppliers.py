"""New supplier accounts: who to add, their new codes, and their YA004BPS rows.

Input is the output of sql/new_supplier_details.sql, saved as one tab-delimited file:
  grid 1  live suppliers with no Sage code (11 columns: code, name, country, note, last
          invoice, last order, last ledger entry, open items, open balance, open PO lines,
          products bought in 24 months)
  grid 2  their migration.vw_BPS rows (20 columns)

Who is added:
  * open invoices or open PO lines - always, or BISX / POH drop them again
  * traded in the last 24 months - yes, the same rule as customers
  * left out, for Finance to confirm: employee expense accounts with nothing open, and
    accounts that aren't suppliers (petty cash, HMRC, card terminals) or are marked "do not use"
New code: first 3 letters of the name (THE ignored), then the next free number from 500;
within a group, accounts with open items first, then the most recent.

Rows follow the 33-column layout of the clean-run supplier file (out_v8/YA004BPS_load6_suppliers.txt)
and its rules: Ethan's character rule, tax rule EU -> ROWS, and no dummy VAT numbers (the reason
179 suppliers were rejected in UAT). Writes the decision list, the mapped spreadsheets, and
sql/xref_new_supplier_accounts.sql. Supplier names stay out of git (Claire's rule): only codes
go into the SQL.

Usage:
    python build_new_suppliers.py <details .txt> <out folder>
"""
import collections
import csv
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_new_customers import COUNTRY, VAT_FORMAT, VAT_PREFIX, uk_postcode, x3  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V8 = f"{BASE}/out_v8"
REPO = Path(__file__).resolve().parent.parent
ENC = "cp850"
NAME, DESC, LIG, COUNTY, PC, PHONE, WEB, EMAIL = 35, 30, 40, 29, 10, 19, 50, 57
EXPENSES = re.compile(r"\bEXPS?\b|EXPENSE", re.I)
NOT_SUPPLIER = re.compile(r"PETTY CASH|REVENUE|CARDNET|DO NOT USE|\(SEE |^JOINERY$", re.I)
COMPANY = re.compile(r"\b(LTD|LIMITED|PLC|LLP|CO|GROUP|SERVICES|SA|SAS|GMBH|INC|BANK|HIRE|MOTORS|CARS|"
                     r"ENERGY|TRADING|DISPLAY|ART|DESIGN|PROJECTS|COURIERS|CONSULTANTS|WORKS)\b", re.I)
SDI_MAIL = re.compile(r"@(wearesdi\.com|sdidisplays\.co\.uk)", re.I)
UK_WORDS = {"UK", "ENGLAND", "UNITED KINGDOM", "GREAT BRITAIN", "GB"}


def read(p):
    with open(p, newline="", encoding=ENC) as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(p, rows):
    with open(p, "w", newline="", encoding=ENC) as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def base(name):
    n = re.sub(r"^THE\s+", "", name.upper().strip())
    return (re.sub(r"[^A-Z]", "", n) + "XXX")[:3]


def person_expenses(g, v):
    """An employee's expense account: says so, is addressed to the person's own SDI email, or is
    a person's name with no address and no outside email."""
    if EXPENSES.search(g[1]) or EXPENSES.search(v[11]):
        return True
    m = SDI_MAIL.search(v[18])
    if m and any(len(w) > 2 and w.lower() in v[18][:m.start()].lower() for w in g[1].split()[-1:]):
        return True
    no_address = not any(x.strip() for x in v[11:17])
    return no_address and (m or not v[18].strip()) and not COMPANY.search(g[1])


def decide(g, v):
    live_open = int(g[7]) > 0 or int(g[9]) > 0
    if live_open:
        return "Add", "Has open invoices or open PO lines - needed for BISX / POH"
    if NOT_SUPPLIER.search(g[1]):
        return "Leave out (not a supplier)", "Petty cash, HMRC, card terminal or marked do not use - Finance to confirm"
    if person_expenses(g, v):
        return "Leave out (employee expenses)", "Employee expense account, nothing open - Finance to confirm"
    return "Add", "Traded in the last 24 months"


def vat(v, cry, report, code):
    v = re.sub(r"[\s.\-]", "", v.upper())
    if not v:
        return ""
    if re.fullmatch(r"GB(\d{9}|\d{12})", v) or (v[:2] in VAT_PREFIX and v[:2] != "GB"
                                                and re.fullmatch(r"[A-Z]{2}[0-9A-Z]{5,13}", v)):
        return v
    fits = VAT_FORMAT.get(cry)
    hint = f"{cry}{v}" if fits and re.fullmatch(fits, v) else ""
    report.append([code, "VAT number", v, hint, "blank until Finance confirms - a dummy or unprefixed number "
                   "is what rejected 179 suppliers" + (f"; {hint} fits the {cry} format" if hint else "")])
    return ""


def row(g, v, new, report):
    lines = [x for x in (v[11], v[12], v[13], v[14]) if x.strip()]
    cry = v[3].strip().upper() or "GB"
    for l in list(lines):
        key = l.upper().strip(" .,")
        if key in UK_WORDS:
            lines.remove(l)
        elif key in COUNTRY:
            lines.remove(l)
            if COUNTRY[key] != cry:
                report.append([new, "country", cry, COUNTRY[key], "the address names another country"])
                cry = COUNTRY[key]
        elif key.endswith(tuple(f" {c}" for c in COUNTRY)) and cry == "GB":
            c = next(COUNTRY[c] for c in COUNTRY if key.endswith(f" {c}"))
            report.append([new, "country", cry, c, f"the address ends with the country ({l.strip()})"])
            cry = c
    pc = " ".join(v[16].split()).upper()
    if pc in COUNTRY:                                   # the country typed in the postcode field
        if COUNTRY[pc] != cry:
            report.append([new, "country", cry, COUNTRY[pc], f"the postcode field says {pc}"])
            cry = COUNTRY[pc]
        pc = ""
    if cry == "GB":
        if pc and not uk_postcode(pc):
            fixed = uk_postcode(re.sub(r"(\s)O", r"\g<1>0", pc))       # MK8 OES: a letter O for a zero
            if fixed:
                report.append([new, "postcode", pc, fixed, "letter O typed for a zero"])
                pc = fixed
            else:
                report.append([new, "postcode", pc, "", "not a UK postcode - check"])
        elif pc:
            pc = uk_postcode(pc)
        else:
            for l in reversed(lines):
                if uk_postcode(l):
                    lines.remove(l)
                    pc = uk_postcode(l)
                    report.append([new, "postcode", "", pc, "moved out of the address lines"])
                    break
    lines = [x3(l)[:LIG].rstrip() for l in lines]
    lines = [l for l in lines if l]
    county = lines.pop()[:COUNTY].rstrip() if len(lines) == 4 else ""
    lines += [""] * (3 - len(lines))
    if not lines[0]:
        report.append([new, "address", "", "", "no address in Access - X3 may want one"])
    tax = "ROWS" if v[7] in ("EU", "ROWS") else v[7]
    cat = "DOM" if cry in ("GB", "IM") else "ROWS"
    if (cat == "DOM") != (tax in ("DOM", "XVRS")):
        report.append([new, "tax rule", v[7], f"{cat} / {tax}",
                       f"Access VAT code kept; the address is in {cry} - Finance to confirm"])
    mails = [e for e in re.split(r"[\s;,/]+", v[18]) if "@" in e]
    return [cat, new, x3(g[1])[:NAME].rstrip(), cry, v[4], "", vat(v[6], cry, report, new), tax, v[8], "STD",
            "001", x3(v[10])[:DESC].rstrip(), *lines, county, "", pc[:PC], cry, v[17].strip()[:PHONE], "",
            mails[1][:WEB] if len(mails) > 1 else "", (mails[0] if mails else v[18].strip())[:EMAIL],
            *[""] * 9, "2"]


def main(details, out):
    text = open(details, encoding="utf-8", newline="").read().split("\r\n")
    gap = [l.split("\t") for l in text if l.count("\t") == 10]
    det = {l.split("\t")[1]: l.split("\t") for l in text if l.count("\t") == 19}
    assert len(gap) == len(det), (len(gap), len(det))
    existing = read(f"{V8}/YA004BPS_load6_suppliers.txt")
    used = {r[1] for r in existing}
    order = sorted(gap, key=lambda g: (base(g[1]), -(int(g[7]) + int(g[9])),
                                       -int(max((g[4], g[5], g[6]), key=lambda d: d if d != "NULL" else "").replace("-", "") or 0),
                                       g[0]))
    plan, rows, report = [], [], []
    for g in order:
        v = det[g[0]]
        act, why = decide(g, v)
        new = ""
        if act == "Add":
            b, i = base(g[1]), 500
            while f"{b}{i}" in used:
                i += 1
            new = f"{b}{i}"
            used.add(new)
            rows.append(row(g, v, new, report))
        plan.append([g[0], g[1], g[3], g[4] if g[4] != "NULL" else None, g[5] if g[5] != "NULL" else None,
                     int(g[7]), float(g[8]), int(g[9]), act, new, why])

    bad = re.compile(r"[^A-Za-z0-9._\- ]")
    assert all(len(r) == 33 for r in rows)
    assert len({r[1] for r in rows}) == len(rows) and not ({r[1] for r in rows} & {r[1] for r in existing})
    assert not any(bad.search(r[c]) for r in rows for c in (2, 11, 12, 13, 14, 15))
    assert all(r[7] in ("DOM", "ROWS", "XVRS") for r in rows)

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / "YA004BPS_new_suppliers.txt", rows)
    write(out / "YA004BPS_load7_suppliers.txt", existing + rows)
    pairs = [(p[0], p[9]) for p in plan if p[9]]
    sql = ["-- xref_new_supplier_accounts.sql  -  generated by scripts/build_new_suppliers.py", "--",
           "-- Live suppliers that were not in the first supplier import, with their new Sage X3 codes.",
           "-- Adds them to migration.XREF_SAGE_BPS so vw_BISX_V2, vw_POH_V2 and the product-supplier",
           "-- extract stop dropping their open invoices, open orders and product links. The accounts",
           "-- are created by the supplier import (new rows in YA004BPS), which loads first.",
           "-- Codes only - the names come from Access when it runs.", "--",
           "-- Run AFTER xref_sage_codes.sql (it drops and rebuilds the table) and BEFORE the extract.",
           "USE SDILive;", "GO", "SET NOCOUNT ON;",
        "-- Only our own migration tables change. The table may be an older build whose text columns",
        "-- were sized to what it held then ('new account' and some names didn't fit), so widen them.",
        "ALTER TABLE migration.XREF_SAGE_BPS ALTER COLUMN SAGE_CODE varchar(10) COLLATE DATABASE_DEFAULT NULL;",
        "ALTER TABLE migration.XREF_SAGE_BPS ALTER COLUMN ACCESS_NAME nvarchar(100) COLLATE DATABASE_DEFAULT NULL;",
        "ALTER TABLE migration.XREF_SAGE_BPS ALTER COLUMN SAGE_NAME nvarchar(100) COLLATE DATABASE_DEFAULT NULL;",
        "ALTER TABLE migration.XREF_SAGE_BPS ALTER COLUMN MATCHED_BY varchar(20) COLLATE DATABASE_DEFAULT NULL;",
        "GO",
           "DELETE FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account';",
           "INSERT INTO migration.XREF_SAGE_BPS (ACCESS_CODE, SAGE_CODE, ACCESS_NAME, SAGE_NAME, MATCHED_BY)",
           "SELECT p.ACCESS_CODE, p.SAGE_CODE, LTRIM(RTRIM(a.SUNAME)), LTRIM(RTRIM(a.SUNAME)), 'new account'",
           "FROM (VALUES"]
    sql += [f"    ('{c}', '{s}')" + ("," if i < len(pairs) - 1 else "") for i, (c, s) in enumerate(pairs)]
    sql += [") p (ACCESS_CODE, SAGE_CODE)",
            "JOIN dbo.PL_ACCOUNTS a ON LTRIM(RTRIM(a.SUCODE)) COLLATE DATABASE_DEFAULT = p.ACCESS_CODE COLLATE DATABASE_DEFAULT",
            "WHERE NOT EXISTS (SELECT 1 FROM migration.XREF_SAGE_BPS x",
            "                   WHERE x.ACCESS_CODE = p.ACCESS_CODE COLLATE DATABASE_DEFAULT);", "",
            "-- Check: added = expected, and a new code must never already belong to another account",
            f"SELECT COUNT(*) AS new_accounts_added, {len(pairs)} AS expected,",
            "       (SELECT COUNT(*) FROM migration.XREF_SAGE_BPS n JOIN migration.XREF_SAGE_BPS o",
            "          ON o.SAGE_CODE = n.SAGE_CODE AND o.ACCESS_CODE <> n.ACCESS_CODE",
            "        WHERE n.MATCHED_BY = 'new account') AS new_codes_clashing",
            "FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account';", "GO", ""]
    (REPO / "sql" / "xref_new_supplier_accounts.sql").write_text("\n".join(sql), encoding="utf-8")
    counts = collections.Counter(p[8] for p in plan)
    print(dict(counts), len(rows), "rows;", collections.Counter(r[1] for r in report))
    return existing, rows, plan, report, counts


def sheets(existing, rows, plan, report, counts, out):
    import build_bp_sheets as bp
    hf, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")

    wb = Workbook()
    n = wb.active
    n.title = "Notes"
    opn = [p for p in plan if p[5] or p[7]]
    for line in [["Live suppliers missing from Sage X3"], [],
                 ["Source", "new_supplier_details.sql, 27 Oct 2026: every Access supplier with no Sage code that has "
                            "open invoices or PO lines, or traded in the last 24 months"],
                 ["Why it matters", f"{len(opn)} of them have open items or open PO lines (GBP "
                                    f"{sum(p[6] for p in opn):,.2f} outstanding). Without a supplier account the views "
                                    "drop those invoices and orders from BISX and POH"],
                 ["Totals", ", ".join(f"{k}: {v}" for k, v in counts.most_common())],
                 ["New codes", "First three letters of the name (THE ignored), then the next free number from 500. "
                               "Proposed - final once loaded"],
                 ["Left out", "Employee expense accounts with nothing open, and accounts that aren't suppliers "
                              "(petty cash, HMRC, card terminal, marked do not use). Finance to confirm"]]:
        n.append(line)
    n["A1"].font = Font(bold=True, size=13)
    n.column_dimensions["A"].width, n.column_dimensions["B"].width = 22, 120
    for r in n.iter_rows(min_row=3):
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws = wb.create_sheet("Suppliers to add")
    ws.append(["Old Access code", "Name", "Access note", "Last invoice", "Last order", "Open items", "Open balance",
               "Open PO lines", "Action", "Proposed new code", "Why"])
    for p in plan:
        ws.append(p)
    for c in ws[1]:
        c.font, c.fill, c.alignment = hf, fill, Alignment(wrap_text=True)
    for i, w in enumerate([14, 38, 30, 12, 12, 10, 14, 10, 28, 14, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in ws.iter_rows(min_row=2):
        r[6].number_format = "#,##0.00"
    ws.freeze_panes, ws.auto_filter.ref = "A2", ws.dimensions
    wb.save(f"{out}/Suppliers_to_add.xlsx")

    head = ["New code", "What", "Access had", "Now / suggested", "Note"]
    by = collections.Counter(r[1] for r in report)
    notes = [["New accounts", f"{len(rows)} suppliers that were missing from X3, from the Access details of 27 Oct. "
                              "Codes as in Suppliers_to_add.xlsx"],
             ["Tax rule", "From the Access VAT code, EU set to ROWS as in the rest of the file. "
                          f"{by['tax rule']} where the address country says otherwise are on the Check tab"],
             ["VAT number", f"{by['VAT number']} dummy or unprefixed numbers blank - the reason 179 suppliers were "
                            "rejected before. Suggested numbers on the Check tab"],
             ["Country", f"{by['country']} suppliers Access had as GB whose address names another country now carry it"],
             ["Postcodes", f"UK postcodes tidied, {by['postcode']} fixed or moved out of the address lines"],
             ["No address", f"{by['address']} suppliers have no address in Access (listed on the Check tab)"],
             ["Names and addresses", "Ethan's character rule. Emails, phones and websites untouched"]]
    sh = f"{BASE}/out_sheets"
    # Complete files only - no new-accounts-only file (runbook, rule 1b)
    bp.build("YA004BPS", "Suppliers", bp.SUPPLIER, existing + rows, bp.read(f"{BASE}/upl2/bps.txt"), [
        ["VAT numbers", "Dummy numbers removed - the PL numbers copied across 117 suppliers, TEMPJAF placeholders, GB "
                        "numbers on overseas companies. 185 suppliers. UK suppliers load with a blank"],
        ["Tax rule", "28 suppliers on EU set to ROWS - X3 has no EU tax rule. Finance to confirm"],
        ["Names and addresses", "Ethan's character rule. Emails, phones and websites untouched"], []] + notes,
             path=f"{sh}/YA004BPS_suppliers_MAPPED.xlsx", extra=[("Check new accounts", head, report)])


if __name__ == "__main__":
    sheets(*main(*sys.argv[1:3]), sys.argv[2])
