"""YA004BPSC - supplier bank details, from sql/supplier_bank_details.sql.

Ethan's template (28 Oct): BPSNUM, BPAADD, CRY, BIDNUM, PAB1, BICCOD, PAB2, CUR, BIDNUMFLG.
  BPSNUM     the Sage supplier code (the query returns it)
  BPAADD     001 - the supplier's only address in the supplier import
  CRY        the supplier's country as loaded (the final supplier file)
  BIDNUM     XXXX + sort code (6 digits) + account number (8 digits). Access holds no bank
             identifier, so the XXXX placeholder stays, as the template says
  PAB1, BICCOD, PAB2   blank
  CUR        the supplier's currency as loaded
  BIDNUMFLG  2 (default bank)
Only suppliers paid by BACS (payment terms BAC_...), as the template's note says. A 7-digit
account number is padded with a leading zero (the UK convention); anything else that is not
6 + 8 digits, and every BACS supplier with no bank details, goes on the Check tab, not the load.

CONFIDENTIAL - bank details. The spreadsheet stays out of git; share it inside SDI only.

Usage:
    python build_bpsc.py <query output .txt> <output .xlsx>
"""
import csv
import re
import sys
from collections import Counter

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SUPPLIERS = f"{BASE}/out_sue/YA004BPS_load7_suppliers.txt"   # the final supplier file, 706
TEMPLATE = f"{BASE}/tmpl_bpsc/YA004BPSC_guide.xlsx"


def main(src, dest):
    sup = {r[1]: r for r in csv.reader(open(SUPPLIERS, encoding="cp850"), delimiter=";") if r}
    bank = {}
    for line in open(src, encoding="utf-8", errors="replace").read().replace("\r\n", "\n").split("\n"):
        f = line.split("\t")
        if len(f) == 9 and f[0].strip() and f[0] != "sage_code":
            bank.setdefault(f[0].strip(), f)
    rows, check, log = [], [], Counter()
    for code, s in sorted(sup.items()):
        if not s[8].startswith("BAC"):
            log["not paid by BACS - not loaded"] += 1
            continue
        b = bank.get(code)
        if b is None or not (b[2].strip() or b[3].strip()):
            check.append([code, s[2], b[1] if b else "", "", "", "BACS supplier with no bank details in Access"])
            log["BACS, no bank details"] += 1
            continue
        sort, acc = re.sub(r"\D", "", b[2]), re.sub(r"\D", "", b[3])
        note = ""
        if len(acc) == 7:
            acc, note = "0" + acc, "7-digit account number padded with a leading 0"
        if len(sort) != 6 or len(acc) != 8:
            check.append([code, s[2], b[1], b[2], b[3], "sort code must be 6 digits and account number 8"])
            log["bank details not 6 + 8 digits"] += 1
            continue
        if note:
            check.append([code, s[2], b[1], b[2], b[3], note + " - loaded"])
            log["account number padded"] += 1
        rows.append([code, "001", s[18] or s[3], f"XXXX{sort}{acc}", None, None, None, s[4], 2])
        log["loaded"] += 1
    assert len({r[0] for r in rows}) == len(rows)

    wb = load_workbook(TEMPLATE)
    # The template came as Sheet1 / Sheet2. Named like the other templates, because Marc's
    # macro looks for "Data with Headings" (and skips its two heading rows).
    ws = wb["Sheet1"]
    ws.title = "Data with Headings"
    wb["Sheet2"].title = "Guide"
    if ws.max_row >= 3:
        ws.delete_rows(3, ws.max_row)
    for r in rows:
        ws.append(r)
    for c in range(1, 10):
        ws.cell(1, c).font = Font(bold=True)
    ws.freeze_panes = "A3"
    hf, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")
    ck = wb.create_sheet("Check")
    ck.append(["Supplier", "Name", "Access code", "Sort code in Access", "Account number in Access", "Why"])
    for r in check:
        ck.append(r)
    for c in ck[1]:
        c.font, c.fill = hf, fill
    for col, w in zip("ABCDEF", (10, 36, 12, 16, 22, 50)):
        ck.column_dimensions[col].width = w
    nt = wb.create_sheet("Notes", 0)
    for line in [["YA004BPSC - supplier bank details"], [],
                 ["CONFIDENTIAL", "Bank account details. Share inside SDI only; keep out of email to outside parties."],
                 ["Rows", f"{len(rows)} BACS suppliers with a valid sort code and account number"],
                 ["Rules", "BIDNUM = XXXX + sort code + account number (Access holds no bank code, so XXXX stays). "
                           "Address 001, country and currency as in the supplier file, default bank (2). "
                           "Only suppliers paid by BACS"],
                 ["Check tab", "; ".join(f"{k}: {v}" for k, v in log.items() if k != "loaded")],
                 ["Load after", "the supplier file (YA004BPS)"]]:
        nt.append(line)
    nt["A1"].font = Font(bold=True, size=13)
    nt.column_dimensions["A"].width, nt.column_dimensions["B"].width = 14, 110
    for r in nt.iter_rows(min_row=3):
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(dest)

    got = [list(r) for r in load_workbook(dest, read_only=True)["Data with Headings"].iter_rows(min_row=3, values_only=True)
           if r[0] is not None]
    assert [g[:9] for g in got] == rows, "read-back mismatch"
    print(dest.split("/")[-1], dict(log))


if __name__ == "__main__":
    main(*sys.argv[1:3])
