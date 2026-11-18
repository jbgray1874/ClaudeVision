"""Fill Finance's supplier list with the email addresses Access holds (Claire, 18 Nov).

    python fill_supplier_emails.py "<Supplier List.xlsx>" <supplier_emails.txt> <out.xlsx>

<supplier_emails.txt> is the output of sql/supplier_emails.sql (tab delimited; with or without
headers; SUMMARY and EMAIL grids in one file is fine - only EMAIL rows are read).

What it does to the list (sheet "List Data", headings in row 1, a note row 2, data from row 3):
  - Column J "Remittance email address": the address from the supplier's statements /
    remittance email field (the PL_ACCOUNTS column with MAIL in its name; else the first other
    PL_ACCOUNTS column with an address; else the supplier's address record).
  - New columns after the last one:
      "Other emails in Access"   every other address found, with where it came from
      "Email check"              why an address may be the bounce or the "don't know who" case
  - Nothing else is changed. Rows Access has no address for are marked in the check column.

Checks (Claire: some bounce, some are wrong, some don't say which company they are):
  - not a valid address (spaces, no domain, two '@', ...);
  - several addresses in one field;
  - free mail (gmail, hotmail, outlook, yahoo, btinternet, ...);
  - neither the name part nor the domain contains a word of the supplier's name, so it may not
    say who it's from (a hint to look at, not proof of a problem).

Read-only on Access. The output names suppliers: keep it in the private folder, never in git.
"""
import csv
import re
import sys
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
VALID_RE = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
FREE = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
        "live.co.uk", "yahoo.com", "yahoo.co.uk", "btinternet.com", "aol.com", "icloud.com",
        "sky.com", "talktalk.net", "virginmedia.com", "msn.com", "mail.com", "gmx.com", "ntlworld.com"}
STOP = {"limited", "ltd", "the", "and", "plc", "group", "company", "services", "service", "uk",
        "international", "solutions", "systems", "products", "trading", "sales", "llp", "gmbh",
        "sarl", "srl", "inc", "co"}
AMBER = PatternFill("solid", fgColor="FFF2CC")
RED = PatternFill("solid", fgColor="F8CBAD")


def read_emails(path):
    """{supplier code: [(table, column, raw value)]} from the EMAIL grid."""
    found = defaultdict(list)
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.reader(f, delimiter="\t"):
            row = [c.strip() for c in row]
            if len(row) >= 5 and row[0] == "EMAIL":
                found[row[1].upper()].append((row[2], row[3], row[4]))
    return found


def rank(src):
    tbl, col = src[0].upper(), src[1].upper()
    if tbl == "PL_ACCOUNTS" and "MAIL" in col:
        return 0
    if tbl == "PL_ACCOUNTS" and not any(w in col for w in ("NOTE", "MEMO", "COMMENT")):
        return 1
    if "ADDRESS" in tbl and "MAIL" in col:
        return 2
    return 3


def name_words(name):
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) >= 4 and w not in STOP}


def checks(addr, raw, name):
    out = []
    if not VALID_RE.match(addr):
        out.append("not a valid address")
    if len(EMAIL_RE.findall(raw)) > 1:
        out.append("several addresses in one field")
    local, _, domain = addr.lower().partition("@")
    if domain in FREE:
        out.append("free mail address")
    words = name_words(name)
    if words and not any(w in local or w in domain for w in words):
        out.append("doesn't contain the supplier's name - check who it belongs to")
    return out


def main(list_path, emails_path, out_path):
    found = read_emails(emails_path)
    wb = openpyxl.load_workbook(list_path)
    ws = wb["List Data"]
    hdr = [c.value for c in ws[1]]
    c_code, c_name = hdr.index("Account Code") + 1, hdr.index("Account Name") + 1
    c_rem = hdr.index("Remittance email address") + 1
    c_other, c_check = ws.max_column + 1, ws.max_column + 2
    for col, title in ((c_other, "Other emails in Access"), (c_check, "Email check")):
        cell = ws.cell(1, col, title)
        cell.font = Font(bold=True)
    ws.cell(2, c_other, "Where each was found (table.column)")
    ws.cell(2, c_check, "Added 18 Nov from Access")

    n = defaultdict(int)
    for r in range(3, ws.max_row + 1):
        code = str(ws.cell(r, c_code).value or "").strip().upper()
        if not code:
            continue
        name = str(ws.cell(r, c_name).value or "")
        srcs = sorted(found.get(code, []), key=rank)
        addrs = []  # (address, raw, source), first occurrence of each address only
        for tbl, col, raw in srcs:
            hits = EMAIL_RE.findall(raw) or [raw]
            for a in hits:
                a = a.strip().strip(";,")
                if a.lower() not in {x[0].lower() for x in addrs}:
                    addrs.append((a, raw, f"{tbl}.{col}"))
        if not addrs:
            ws.cell(r, c_check, "no email in Access").fill = RED
            n["none"] += 1
            continue
        main_addr, raw, _ = addrs[0]
        ws.cell(r, c_rem, main_addr)
        others = "; ".join(f"{a} ({s})" for a, _, s in addrs[1:])
        if others:
            ws.cell(r, c_other, others)
        msg = checks(main_addr, raw, name)
        if msg:
            ws.cell(r, c_check, "; ".join(msg)).fill = RED if "not a valid address" in msg else AMBER
            n["flagged"] += 1
        n["filled"] += 1
    ws.column_dimensions[openpyxl.utils.get_column_letter(c_rem)].width = 38
    ws.column_dimensions[openpyxl.utils.get_column_letter(c_other)].width = 50
    ws.column_dimensions[openpyxl.utils.get_column_letter(c_check)].width = 45
    wb.save(out_path)
    print(f"suppliers with an email: {n['filled']} (of which flagged to check: {n['flagged']}); "
          f"no email in Access: {n['none']}")
    print("written", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:4])
