"""Fill the five mapped guides with the real data and write a load file for each.

Source: the five export grids from views_v2.sql (run1/out.txt), checked against the
V6 item file and the customer and supplier loads. Rows that X3 would reject are not
put in the load: they go on a 'Held back' sheet with the reason, so the load itself
should go in clean.

Fixes applied on the way through, each one counted on the Notes sheet:
  * blank descriptions filled from the item file (ITMDES1, then ITMDES3, then ITMDES2)
  * units that are not EA - 'EACH', '100', 'M' - set to EA, since every item in the
    load has EA as its stock unit and X3 rejects a unit the item does not have
  * semicolons inside a value replaced, so the .txt cannot split a field
  * Ethan's character rule (Import Notes, 23 Oct): X3 takes letters, numbers, - _ and .
    in text. & becomes AND, / becomes -, accents lose the accent, the rest goes.
    References (document numbers, supplier lots) also lose their spaces
  * SOH ship and requested delivery dates before 2025 moved to the accounting date -
    Ethan's log shows the 2024 dates rejected
  * SOH written as YA004SOHPJ: Dim Code D02 and Dimension P00003 added between Header
    text and Line
"""
import csv
import json
import os
import re
import unicodedata
from collections import Counter

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
OUT = f"{BASE}/out_mapped"
LOADS = f"{OUT}/load_files"
os.makedirs(LOADS, exist_ok=True)
HF = Font(name="Arial", bold=True, size=10, color="FFFFFF")
HFILL = PatternFill("solid", fgColor="C00000")
BF = Font(name="Arial", size=10)
BOLD = Font(name="Arial", bold=True, size=10)


def read_semi(p):
    with open(p, newline="", encoding="cp850", errors="replace") as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


# --- the export grids -------------------------------------------------------
# EXTRA: an export of rows to add to the same files (export_new_accounts_orders_invoices.sql,
# four grids: SOH, POH, BICX, BISX). Its rows are cut to the columns of the original export
# (the views also return REF_ columns) and go through exactly the same rules.
EXTRA = os.environ.get("EXTRA_EXPORT")
CUSTOMER_FILE = os.environ.get("CUSTOMER_FILE", f"{BASE}/upl2/bpc.txt")
SUPPLIER_FILE = os.environ.get("SUPPLIER_FILE", f"{BASE}/upl2/bps.txt")
blocks, cur = [], []
for line in open(f"{BASE}/run1/out.txt", encoding="utf-8", errors="replace").read().split("\n"):
    if line.strip() == "":
        if cur:
            blocks.append(cur)
            cur = []
    else:
        cur.append(line)
if cur:
    blocks.append(cur)
DATA = {
    "YA004SOH": [r.split("\t") for r in blocks[6]],
    "YA004POH": [r.split("\t") for r in blocks[7]],
    "YA004SMR": [r.split("\t") for r in blocks[8]],
    "YA004BICX": [r.split("\t") for r in blocks[9]],
    "YA004BISX": [r.split("\t") for r in blocks[10]],
}
if EXTRA:
    extra = [[l.split("\t") for l in b.strip("\n").splitlines()]
             for b in open(EXTRA, encoding="utf-8", errors="replace").read().replace("\r\n", "\n").split("\n\n")
             if b.strip()]
    for name, rows in zip(("YA004SOH", "YA004POH", "YA004BICX", "YA004BISX"), extra):
        width = len(DATA[name][0])
        assert all(len(r) >= width for r in rows), name
        DATA[name] += [r[:width] for r in rows]

# --- what the rows have to agree with --------------------------------------
items = {}
for r in read_semi(f"{BASE}/uploads_final/ZSDIITM_Cleansing.txt"):
    code = r[1].strip().upper()
    d = next((x.strip() for x in (r[2], r[4], r[3]) if x.strip()), "")
    items.setdefault(code, d[:30])
customers = {r[1].strip() for r in read_semi(CUSTOMER_FILE)}
suppliers = {r[1].strip() for r in read_semi(SUPPLIER_FILE)}

# template layout: header rows, columns that are numbers, and where the codes sit
SPEC = {
    "YA004SOH": dict(head=2, nums={4, 5, 8, 10, 13, 17, 18}, item=14, desc=15, unit=[16],
                     bp=3, bps=customers, qty=17, price=18),
    "YA004POH": dict(head=2, nums={2, 6, 11, 12, 13}, item=7, desc=8, unit=[10],
                     bp=3, bps=suppliers, qty=11, price=13),
    "YA004SMR": dict(head=2, nums={0, 3, 6, 9, 11, 12, 14}, item=7, desc=None, unit=[8, 10, 13],
                     bp=None, bps=None, qty=9, price=12),
    "YA004BICX": dict(head=1, nums={4, 6, 7, 8, 10, 16, 22}, item=None, desc=None, unit=[],
                      bp=2, bps=customers, qty=None, price=None),
    "YA004BISX": dict(head=1, nums={4, 7, 8, 9, 11, 17, 23}, item=None, desc=None, unit=[],
                      bp=2, bps=suppliers, qty=None, price=None),
}


def as_cell(i, v, nums):
    v = v.strip()
    if i in nums and v != "":
        try:
            f = float(v)
            return int(f) if f.is_integer() and "." not in v else f
        except ValueError:
            return v
    return v


# the free-text columns in each template and the length the guide allows them
TEXT_LIMITS = {
    "YA004SMR": {4: 30, 15: 30},
    "YA004SOH": {6: 30, 15: 30},
    "YA004POH": {8: 30},
    "YA004BICX": {12: 20, 13: 30, 14: 30, 15: 30, 21: 30},
    "YA004BISX": {13: 20, 14: 30, 15: 30, 16: 30, 22: 30},
}

# Ethan's character rule, by column: free text keeps its spaces, references do not
X3_TEXT = {"YA004SMR": [4], "YA004SOH": [6, 12, 15, 19], "YA004POH": [5, 8, 14],
           "YA004BICX": [13, 14, 15, 21], "YA004BISX": [14, 15, 16, 22]}
X3_REF = {"YA004SMR": [15, 16], "YA004BICX": [1, 12], "YA004BISX": [1, 13]}   # customer PO keeps its spaces
OUTNAME = {"YA004SOH": "YA004SOHPJ"}
SOH_NEW = ["D02", "P00003"]           # Dim Code, Dimension - inserted before Line (col N)
ACCOUNTING_DATE, OLDEST_DATE = "20261031", "20250101"


# a supplier lot keeps its word breaks as hyphens - "5019032 04.12" must not become one number
REF_SPACE = {"YA004SMR": "-"}


def x3_text(v, ref=False, space=""):
    v = unicodedata.normalize("NFKD", v)
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    v = v.replace("&", "AND" if ref else " AND ").replace("/", "-")
    v = re.sub(r"[^A-Za-z0-9._\- ]", "", v)
    return space.join(v.split()) if ref else " ".join(v.split())


summary = {}
for tmpl, rows in DATA.items():
    s = SPEC[tmpl]
    fixes = Counter()
    good, held, good_oid = [], [], []
    # The view numbers each Access order's lines from 1000, so 1000 marks an order start
    # exactly. Tag every row with its order now, before any line is held back - working it
    # out afterwards from the line numbers merges orders whose first line was removed.
    ln_col = {"YA004SOH": 13, "YA004POH": 6}.get(tmpl)
    oids, oid = [], 0
    for r in rows:
        if ln_col is not None and r[ln_col].strip() == "1000":
            oid += 1
        oids.append(oid)
    for r, this_oid in zip(rows, oids):
        if any(";" in x for x in r):
            fixes["values with a semicolon cleaned"] += 1
        r = [x.replace(";", " ").replace("\xa0", " ").strip() for x in r]
        if s["item"] is not None and " " in r[s["item"]]:
            r[s["item"]] = r[s["item"]].replace(" ", "")
            fixes["stray space removed from a product code"] += 1
        reason = None
        if s["item"] is not None and r[s["item"]].strip().upper() not in items:
            reason = "Product is not in the item load"
        if s["bp"] is not None and r[s["bp"]].strip() not in s["bps"]:
            reason = (reason + "; " if reason else "") + "Account is not in the customer/supplier load"
        # Marc: every value field is a positive number - credits are carried by the
        # document type, not the sign. A negative price on a sales order line is a credit
        # sitting on an order, which the order template cannot take.
        if any(r[c].strip() and float(r[c]) < 0 for c in s["nums"] if c < len(r)
               and r[c].strip().lstrip("-").replace(".", "", 1).isdigit()):
            reason = (reason + "; " if reason else "") + \
                "Negative value - a credit on an order, which X3 needs as a credit note instead"
        if reason:
            held.append(r + [reason])
            continue
        if s["desc"] is not None and not r[s["desc"]].strip():
            r[s["desc"]] = items.get(r[s["item"]].strip().upper(), "")
            fixes["descriptions filled from the item file"] += 1
        for u in s["unit"]:
            if r[u].strip() != "EA":
                fixes[f"unit '{r[u].strip()}' set to EA"] += 1
                r[u] = "EA"
        # a pound sign in free text would rely on the file encoding; spell it out instead
        if any("\u00a3" in x for x in r):
            r = [x.replace("\u00a3", "GBP ") for x in r]
            fixes["pound sign in text written as GBP"] += 1
        # free-text fields: one space between words, characters the X3 file may not read
        # the same way spelled out, and nothing longer than the template allows
        for c, limit in TEXT_LIMITS.get(tmpl, {}).items():
            v = r[c]
            for a, b in (("\u00d8", "DIA "), ("\u00f8", "dia "), ("\u00b0", " deg"), ("\u00bd", "1/2"),
                         ("\u00bc", "1/4"), ("\u2013", "-"), ("\u2014", "-"), ("\u2019", "'")):
                v = v.replace(a, b)
            # a '?' in a description is a character Access lost before export - a dash
            # between words, a trademark sign after a model number
            v = v.replace(" ? ", " - ").replace("?", "")
            v = " ".join(v.split())
            if len(v) > limit:
                v = v[:limit].rstrip()
            if v != r[c]:
                fixes["text tidied (double spaces, special characters, length)"] += 1
                r[c] = v
        for cols, ref in ((X3_TEXT.get(tmpl, []), False), (X3_REF.get(tmpl, []), True)):
            for c in cols:
                v = x3_text(r[c], ref, REF_SPACE.get(tmpl, ""))
                limit = TEXT_LIMITS.get(tmpl, {}).get(c)
                if limit and len(v) > limit:
                    v = v[:limit].rstrip()
                if v != r[c]:
                    fixes["references: spaces and characters X3 does not allow removed" if ref else
                          "text: characters X3 does not allow replaced or removed"] += 1
                    r[c] = v
        good.append(r)
        good_oid.append(this_oid)

    # Renumber within each Access order so every order starts at 1000 and goes up in
    # 1000s, as the guide asks - held-back lines leave gaps otherwise.
    if ln_col is not None:
        seq, last, renum = 0, None, 0
        for r, o in zip(good, good_oid):
            seq = 1 if o != last else seq + 1
            last = o
            if r[ln_col] != str(seq * 1000):
                renum += 1
            r[ln_col] = str(seq * 1000)
        if renum:
            fixes["line numbers renumbered from 1000"] = renum

    # Requested delivery date and ship date are header fields in the template but are
    # held per line in Access. Different values on one order could make X3 split it, so
    # every line takes the order's earliest date - nothing becomes late by it.
    if tmpl == "YA004SOH":
        by = {}
        for r, o in zip(good, good_oid):
            by.setdefault(o, []).append(r)
        changed = 0
        for lines_ in by.values():
            for c in (5, 8):
                first = min(x[c] for x in lines_)
                for x in lines_:
                    if x[c] != first:
                        x[c] = first
                        changed += 1
        if changed:
            fixes["order dates made the same on every line (earliest kept)"] = changed
        moved = 0
        for x in good:
            hit = False
            for c in (5, 8):
                if x[c] < OLDEST_DATE:
                    x[c], hit = ACCOUNTING_DATE, True
            moved += hit
        if moved:
            fixes[f"lines with a ship or delivery date before 2025 moved to {ACCOUNTING_DATE}"] = moved
        # A ship date before the order date is a typing error in Access (BOO101: ordered
        # 20260819, due 20261218, ship 20250620). Ship on the requested delivery date instead.
        early = 0
        for x in good:
            if x[8] < x[4]:
                x[8], early = x[5], early + 1
        if early:
            fixes["lines shipping before their order date given the requested delivery date"] = early

    # Cleaning a reference can make two the same. The template rejects duplicates, so the
    # second and later take a suffix, as the view does for references that repeat in Access.
    if tmpl in ("YA004BICX", "YA004BISX"):
        seen = Counter()
        for r in good:
            seen[r[1]] += 1
            if seen[r[1]] > 1:
                r[1] = f"{r[1][:18]}-{seen[r[1]]}"
                fixes["document references made unique after cleaning"] += 1
        assert len({r[1] for r in good}) == len(good)

    # Stock locations: Access bins mapped to Marc's X3 location list (build/map_bins.py).
    # A bin with no X3 equivalent, or no bin at all, goes to A001 for UAT.
    if tmpl == "YA004SMR":
        bin_map = {k.upper(): v for k, v in json.load(open(f"{BASE}/loclist/bin_map.json")).items()}
        moved = Counter()
        for r in good:
            src = r[17].strip().upper() or "(NO BIN)"
            r[17] = bin_map.get(src, "A001")
            moved["mapped" if r[17] != "A001" else "A001"] += 1
        fixes["stock lots given an X3 location from Marc's list"] = moved["mapped"]
        fixes["stock lots sent to A001 (no X3 equivalent, or no bin)"] = moved["A001"]

    # With Order no blank, X3 has to tell orders apart from the rows themselves. If two
    # orders with identical header details sit next to each other they could be read as
    # one. Reorder so that never happens - safe whether X3 splits on the header changing
    # or on the line number going back to 1000.
    hdr_cols = {"YA004SOH": range(0, 13), "YA004POH": range(0, 6)}.get(tmpl)
    if hdr_cols is not None:
        groups, last = [], None
        for r, o in zip(good, good_oid):
            if o != last:
                groups.append([])
                last = o
            groups[-1].append(r)
        hkey = lambda g: tuple(g[0][c] for c in hdr_cols)
        arranged, pending = [], list(groups)
        while pending:
            for i, g in enumerate(pending):
                if not arranged or hkey(g) != hkey(arranged[-1]):
                    arranged.append(pending.pop(i))
                    break
            else:                      # only identical headers left - nothing to separate them with
                arranged.append(pending.pop(0))
        moved = sum(1 for a, b in zip(groups, arranged) if a is not b)
        clash = sum(1 for a, b in zip(arranged, arranged[1:]) if hkey(a) == hkey(b))
        good = [r for g in arranged for r in g]
        good_oid = [i for i, g in enumerate(arranged) for _ in g]
        if moved:
            fixes["orders reordered so identical headers are not adjacent"] = moved
        if clash:
            fixes["adjacent orders that could not be separated"] = clash

    # ---- the guide -------------------------------------------------------
    name = OUTNAME.get(tmpl, tmpl)
    if tmpl == "YA004SOH":
        out_good = [r[:13] + SOH_NEW + r[13:] for r in good]
        out_held = [r[:13] + SOH_NEW + r[13:] for r in held]
        nums = {c if c < 13 else c + 2 for c in s["nums"]}
    else:
        out_good, out_held, nums = good, held, s["nums"]
    path = f"{OUT}/{name}_guide_MAPPED.xlsx"
    wb = load_workbook(path)
    ws = wb["Data with Headings"]
    ws.delete_rows(s["head"] + 1, ws.max_row)
    for r in out_good:
        ws.append([as_cell(i, v, nums) for i, v in enumerate(r)])
    ws.freeze_panes = ws.cell(s["head"] + 1, 1)

    if held:
        hs = wb.create_sheet("Held back")
        hdr = [c.value for c in ws[1]][:len(out_held[0]) - 1] + ["Why it is held back"]
        hs.append(hdr)
        for c in hs[1]:
            c.font, c.fill = HF, HFILL
        for r in out_held:
            hs.append([as_cell(i, v, nums) for i, v in enumerate(r)])
        hs.freeze_panes = "A2"
        hs.column_dimensions["A"].width = 12

    # ---- numbers for the Notes sheet --------------------------------------
    n = {"rows in the load": len(good), "rows held back": len(held)}
    if tmpl == "YA004SOH":
        n["orders"] = len(set(good_oid))
    if s["qty"] is not None and s["price"] is not None and tmpl == "YA004SMR":
        n["stock value in the load"] = round(sum(float(r[9]) * float(r[12]) for r in good), 2)
        n["stock value held back"] = round(sum(float(r[9]) * float(r[12]) for r in held), 2)
    if tmpl == "YA004BICX":
        n["GBP total"] = round(sum(float(r[6]) for r in good), 2)
    if tmpl == "YA004BISX":
        n["GBP total"] = round(sum(float(r[7]) for r in good), 2)
    if tmpl == "YA004POH":
        n["orders"] = len(set(good_oid))
        n["lines priced at zero"] = sum(1 for r in good if float(r[13] or 0) == 0)
    if tmpl == "YA004SOH":
        n["lines priced at zero"] = sum(1 for r in good if float(r[18] or 0) == 0)
    n.update(fixes)

    notes = wb["Notes"]
    notes.insert_rows(3, amount=len(n) + 4)
    notes.cell(3, 1, "This file, as built").font = BOLD
    notes.cell(4, 1, "Data exported 21 October 2026 from views_v2.sql. Stock and open items "
                     "move daily - re-export on the agreed as-at date before the real load.").font = BF
    for i, (k, v) in enumerate(n.items(), start=5):
        notes.cell(i, 1, k).font = BF
        c = notes.cell(i, 2, v)
        c.font = BF
        if isinstance(v, float):
            c.number_format = "#,##0.00"
    wb.save(path)

    # ---- the load file: data rows only, same delimiter and encoding as the others ----
    with open(f"{LOADS}/{name}_load1.txt", "w", newline="", encoding="cp850", errors="replace") as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(out_good)
    summary[name] = n

for t, n in summary.items():
    print(t)
    for k, v in n.items():
        print(f"    {k:42} {v}")
