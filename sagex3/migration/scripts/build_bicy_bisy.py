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
Everything else is the BICX / BISX file exactly as built (populate_guides.py): same rows,
same values, same order. The build reads every data row back and checks that.

Usage:
    python build_bicy_bisy.py          (COMPANY=<code> to override C01; SWAP=0 to keep B and N as built)
"""
import os
from collections import Counter

import sys

from openpyxl import load_workbook
from openpyxl.styles import Font

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rebuild"))
from common import write_load  # noqa: E402  the X3 load file, one writer for the whole kit

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SRC = os.environ.get("SRC_DIR", f"{BASE}/out_mapped")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_mapped")
COMPANY = os.environ.get("COMPANY", "C01")
SWAP = os.environ.get("SWAP", "1") != "0"
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

    # read back: the same rows, with Company in D and (BISY) no CURLED
    after = rows_of(d)
    expect = []
    for r in before:
        r = list(r)
        if drop_curled:
            del r[heads.index("CURLED")]
        expect.append(r[:3] + [COMPANY or None] + r[3:])
    if SWAP:                             # B and N swapped: the old B is now N, every new B unique
        assert [a[BPRVCR - 1] for a in after] == [e[NUM - 1] for e in expect], new
        assert len({a[NUM - 1] for a in after}) == len(after), new + ": a Document is used twice"
        assert all(str(a[NUM - 1] or "").strip() not in ("", "0") for a in after), new
        expect = [e[:NUM - 1] + [a[NUM - 1]] + e[NUM:BPRVCR - 1] + [a[BPRVCR - 1]] + e[BPRVCR:]
                  for e, a in zip(expect, after)]
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


build("YA004BICX", "YA004BICY", "Customer", drop_curled=False)
build("YA004BISX", "YA004BISY", "Supplier", drop_curled=True)
