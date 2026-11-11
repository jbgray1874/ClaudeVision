"""YA004BICY and YA004BISY: the customer and supplier open-item files in their new layout.

What changed from BICX / BISX (James, 28 Oct):
  * the templates are renamed BICY and BISY
  * BISY loses the CURLED column
  * both get a new column, Company, between C (Customer / Supplier) and D (Site). Its value is
    the X3 company code, C01: S01A is the site, already in Site; C01 is the company Acuity put
    in it for Run 2, and BICY then loaded with 0 errors (Run 2 notes, 28 Oct). COMPANY below.
  * Document (NUM, B) and Source Document (BPRVCR, N) swap over, as Acuity did for Run 2 (Run 2
    notes). Each new Document stays unique, so no two items can merge into one X3 document: a
    value used more than once takes -2, -3 (the convention already used for repeated
    references), and a blank or 0 takes the old Document (the Access invoice number). Those
    were the rows Acuity filled with BLANK / 0 by hand.
  * BISY only, from 11 Nov (Ethan / Jim, Run 4): Document stays the Access document number. No
    -2, -3 of our own. Rows that share one Access number (same supplier, currency, payment terms
    and type) become lines 1, 2, 3 ... of that document (Line, column R). They are written next to
    each other, and the header amounts (GBP Amount, Transaction Amount) carry the document total.
    Two cases still take a suffix, listed on the "Lines" tab: the same Access number on a second
    supplier (or currency / terms), and a Document that is not an Access number (Access number
    blank, so the supplier reference stood in; with SDI Finance to explain, 11 Nov).
    LINES=0 keeps the old one-row-per-document file.
Everything else is the BICX / BISX file exactly as built (populate_guides.py): same rows,
same values, same order. The build reads every data row back and checks that.

Usage:
    python build_bicy_bisy.py          (COMPANY=<code> to override C01; SWAP=0 to keep B and N as built)
"""
import os
import re
from collections import Counter, defaultdict

import sys

from openpyxl import load_workbook
from openpyxl.styles import Font

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rebuild"))
from common import write_load  # noqa: E402  the X3 load file, one writer for the whole kit

BASE = os.environ.get("MIG_BASE", "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad")   # run_transactions.py sets a fresh folder per run
SRC = os.environ.get("SRC_DIR", f"{BASE}/out_mapped")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_mapped")
COMPANY = os.environ.get("COMPANY", "C01")
SWAP = os.environ.get("SWAP", "1") != "0"
LINES = os.environ.get("LINES", "1") != "0"
ONLY = os.environ.get("ONLY")             # e.g. ONLY=YA004BISY rebuilds just that file
ACCESS_DOC = re.compile(r"5\d{6}")      # an Access purchase document number: 5 and six digits
TYPE, BP, CUR, AMT_GBP, AMT, TERMS, LINE, LINE_AMT = 1, 3, 7, 8, 9, 13, 18, 24   # 1-based columns
NUM, BPRVCR = 2, 14                      # columns once Company is in: B Document, N Source Document
NOTE = ("New in this layout (28 Oct): between {bp} and Site. The X3 company code that site S01A "
        "belongs to" + (f": {COMPANY}" if COMPANY else " - to confirm with Marc, blank until then"))


def swap(d):
    """Document (B) <-> Source Document (N). The new Document is the old Source Document, made
    unique: blank or 0 -> the old Document; second and later uses -> -2, -3 (18 characters + suffix,
    as the views do for repeated references). The new Source Document is the old Document."""
    rows = [r for r in range(2, d.max_row + 1) if d.cell(r, 1).value is not None]
    old_num = {r: d.cell(r, NUM).value for r in rows}
    new_num = {}
    for r in rows:
        v = str(d.cell(r, BPRVCR).value or "").strip()
        new_num[r] = (v, False) if v not in ("", "0") else (str(old_num[r] or "").strip(), True)
    seen, count, n = set(), Counter(), Counter()
    taken = {v for v, _ in new_num.values()}
    for r in rows:
        v, was_blank = new_num[r]
        n["blank"] += was_blank
        if v in seen:
            k = 2
            while f"{v[:18]}-{k}" in taken or f"{v[:18]}-{k}" in seen:
                k += 1
            v = f"{v[:18]}-{k}"
            n["repeat"] += 1
        seen.add(v)
        d.cell(r, NUM, v)
        d.cell(r, BPRVCR, old_num[r])
    return n


def lines(d):
    """BISY: one X3 document per Access document number, its rows as lines 1..n (Ethan, 11 Nov).
    Returns the rows of the "Lines" tab and counts. Expects swap() to have run with suffixes."""
    rows = [r for r in range(2, d.max_row + 1) if d.cell(r, 1).value is not None]
    width = d.max_column
    vals = [[d.cell(r, c).value for c in range(1, width + 1)] for r in rows]
    old = [v[NUM - 1] for v in vals]
    taken = set(old)

    def root(x):                         # undo the -2, -3 swap() added, never a real reference
        m = re.fullmatch(r"(.+)-(\d+)", str(x))
        return m.group(1) if m and ACCESS_DOC.fullmatch(m.group(1)) and m.group(1) in taken else str(x)

    groups = defaultdict(list)           # (Access no., supplier, currency, terms, type) -> rows
    order = []
    for i, v in enumerate(vals):
        doc = root(v[NUM - 1])
        key = (doc, v[BP - 1], v[CUR - 1], v[TERMS - 1], v[TYPE - 1]) if ACCESS_DOC.fullmatch(doc) else ("#", i)
        if key not in groups:
            order.append(key)
        groups[key].append(i)
    per_doc = defaultdict(list)
    for k in order:
        if k[0] != "#":
            per_doc[k[0]].append(k)
    out, tab, n = [], [], Counter()
    for k in order:
        idx = groups[k]
        if k[0] == "#":                  # not an Access number: as built (suffix if repeated)
            v = vals[idx[0]]
            out.append(v)
            n["not an Access number"] += 1
            continue
        doc = k[0]
        pos = per_doc[doc].index(k)
        name = doc if pos == 0 else f"{doc}-{pos + 1}"
        if pos:
            n["same Access number, second supplier / currency / terms (suffix kept)"] += 1
        tot_gbp = round(sum(float(vals[i][AMT_GBP - 1] or 0) for i in idx), 2)
        tot = round(sum(float(vals[i][LINE_AMT - 1] or 0) for i in idx), 2)
        for ln, i in enumerate(idx, 1):
            v = list(vals[i])
            v[NUM - 1], v[LINE - 1] = name, ln
            if len(idx) > 1:
                v[AMT_GBP - 1], v[AMT - 1] = tot_gbp, tot
            out.append(v)
            if len(idx) > 1 or pos:
                tab.append([name, ln, len(idx), v[BP - 1], old[i], v[BPRVCR - 1], vals[i][9], vals[i][11],
                            vals[i][LINE_AMT - 1], tot,
                            "second supplier / currency / terms on this Access number: suffix kept" if pos else
                            ("lines differ in source date or due date - X3 keeps the first line's" if
                             len({(vals[j][9], vals[j][11]) for j in idx}) > 1 else "")])
        if len(idx) > 1:
            n["documents now with more than one line"] += 1
            n["rows that became lines 2 and later"] += len(idx) - 1
    assert len(out) == len(vals)
    for r, v in zip(rows, out):
        for c in range(1, width + 1):
            d.cell(r, c, v[c - 1])
    return tab, n, vals, out


def rows_of(ws):
    return [[c.value for c in r] for r in ws.iter_rows(min_row=2) if any(c.value is not None for c in r)]


def find_row(ws, col, value, start=1):
    for r in range(start, ws.max_row + 1):
        if ws.cell(r, col).value == value:
            return r
    raise KeyError(value)


def build(old, new, bp, drop_curled):
    wb = load_workbook(f"{SRC}/{old}_guide_MAPPED.xlsx")
    d = wb["Data with Headings"]
    before = rows_of(d)
    heads = [c.value for c in d[1]]
    if drop_curled:
        d.delete_cols(heads.index("CURLED") + 1)
    d.insert_cols(4)
    d.cell(1, 4, "Company").font = Font(bold=True)
    for r in range(2, d.max_row + 1):
        if d.cell(r, 1).value is not None:
            d.cell(r, 4, COMPANY or None)
    swapped = swap(d) if SWAP else Counter()
    multi = None
    if LINES and new == "YA004BISY" and SWAP:
        multi = lines(d)

    # read back: the same rows, with Company in D and (BISY) no CURLED
    after = rows_of(d)
    if multi:                            # rows moved and merged: check the money and every other cell
        tab, nlines, was, now = multi
        assert len(now) == len(was) == len(after)
        assert round(sum(float(r[LINE_AMT - 1] or 0) for r in after), 2) == round(sum(float(r[LINE_AMT - 1] or 0) for r in was), 2)
        keep = [c for c in range(len(was[0])) if c not in (NUM - 1, LINE - 1, AMT_GBP - 1, AMT - 1)]
        assert sorted(tuple(str(r[c]) for c in keep) for r in was) == sorted(tuple(str(r[c]) for c in keep) for r in after), new
        docs = [(r[NUM - 1], r[LINE - 1]) for r in after]
        assert len(set(docs)) == len(docs), new + ": a Document / Line is used twice"
        seen, prev = set(), None
        for r in after:                  # each document's lines sit together, numbered 1, 2, 3
            if r[NUM - 1] != prev:
                assert r[NUM - 1] not in seen and r[LINE - 1] == 1, r[NUM - 1]
                seen.add(r[NUM - 1])
            prev = r[NUM - 1]
        lt = wb.create_sheet("Lines")
        lt.append(["Document", "Line", "Lines on document", "Supplier", "Document before (11 Nov)", "Source Document (supplier ref)",
                   "Source date", "Due date", "Line amount", "Document total", "Note"])
        for c in lt[1]:
            c.font = Font(bold=True)
        for t in tab:
            lt.append(t)
        swapped.update(nlines)
    expect = []
    if multi:                            # checked above; the generic read-back is for the unchanged layout
        expect = None
    for r in (before if expect is not None else []):
        r = list(r)
        if drop_curled:
            del r[heads.index("CURLED")]
        expect.append(r[:3] + [COMPANY or None] + r[3:])
    if expect is None:
        pass
    elif SWAP:                           # B and N swapped: the old B is now N, every new B unique
        assert [a[BPRVCR - 1] for a in after] == [e[NUM - 1] for e in expect], new
        assert len({a[NUM - 1] for a in after}) == len(after), new + ": a Document is used twice"
        assert all(str(a[NUM - 1] or "").strip() not in ("", "0") for a in after), new
        expect = [e[:NUM - 1] + [a[NUM - 1]] + e[NUM:BPRVCR - 1] + [a[BPRVCR - 1]] + e[BPRVCR:]
                  for e, a in zip(expect, after)]
    if expect is not None:
        assert [a[:len(e)] for a, e in zip(after, expect)] == expect and len(after) == len(before), new

    m = wb["Mapping"]
    m.cell(1, 1, str(m.cell(1, 1).value).replace(old, new))
    if drop_curled:
        m.delete_rows(find_row(m, 2, "CURLED"))
    at = find_row(m, 2, bp, 4) + 1
    m.insert_rows(at)
    for c, v in enumerate([None, "Company", None, "", "(new column)", "-", NOTE.format(bp=bp), "To confirm"], 1):
        m.cell(at, c, v)
    n = 1
    for r in range(find_row(m, 1, "#") + 1, m.max_row + 1):
        if m.cell(r, 2).value:
            m.cell(r, 1, n)
            n += 1

    g = wb["Guide"]
    if drop_curled:                      # the CURLED row has no field name, example GBP
        cur = find_row(g, 1, "Currency")
        if g.cell(cur + 1, 1).value is None and g.cell(cur + 1, 2).value == "GBP":
            g.delete_rows(cur + 1)
    at = find_row(g, 1, "Customer") + 1   # the supplier guide labels its code "Customer" too
    g.insert_rows(at)
    for c, v in enumerate(["Company", COMPANY or None, COMPANY or None, "Sage X3 company of the site - new column (C01)"], 1):
        g.cell(at, c, v)

    nt = wb["Notes"]
    nt.cell(1, 1, str(nt.cell(1, 1).value).replace(old, new))
    nt.insert_rows(3, 3)
    nt.cell(3, 1, f"{new} layout").font = Font(bold=True)
    nt.cell(4, 1, f"Was {old}. New column Company (D), between {bp} and Site"
                  + ("; the CURLED column is removed" if drop_curled else "")
                  + ". " + ("Company = " + COMPANY if COMPANY else "Company is blank until Marc confirms the code")
                  + (". 11 Nov (Ethan): Document is the Access number; rows sharing one are lines 1, 2, 3 of "
                     "that document, written together, header amounts = document total. See the Lines tab"
                     if multi else "")
                  + (". Document (B) and Source Document (N) swapped, as Acuity did for Run 2: "
                     f"{swapped['repeat']} repeated values took -2, -3 and {swapped['blank']} blank or 0 took "
                     "the Access invoice number, so every Document is unique" if SWAP else "")
                  + ". Every row and value is otherwise as in the " + old + " file.")
    path = f"{OUT}/{new}_guide_MAPPED.xlsx"
    wb.save(path)
    txt, n_lines, _ = write_load(path, "Data with Headings", 2)     # one heading row (rule 1c)
    assert n_lines == len(after), (n_lines, len(after))
    print(path.split("/")[-1], len(after), "rows checked,", len(after[0]) if after else 0, "columns",
          f"| company {COMPANY} | swap: {dict(swapped)}" if SWAP else f"| company {COMPANY} | no swap")


if ONLY in (None, "YA004BICY"):
    build("YA004BICX", "YA004BICY", "Customer", drop_curled=False)
if ONLY in (None, "YA004BISY"):
    build("YA004BISX", "YA004BISY", "Supplier", drop_curled=True)
