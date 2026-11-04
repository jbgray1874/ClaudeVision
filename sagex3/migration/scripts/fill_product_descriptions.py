"""ZSDIITM with real descriptions where description 1 is only the code (James, 2-4 Nov).

Sub-assemblies and parts ("zombie" parts) came across with STKNAME as description 1, and STKNAME on
those is just the code ("10074-02-SA01", "003.17.021"). The product file already holds the real
text in description 3 (PMA_DESC_3) or description 2 for most of them. This takes it, with the same
rule as rebuild/products.py: description 3 first, then description 2. The rest wait for PMA_DESC on
the next product extract.

It rebuilds the whole product file (rule 1b) from the current one: same products, same order,
every other value unchanged; checked on read-back. Writes the spreadsheet, a 'Descriptions filled'
tab listing every change, and the ; load file (rule 1c).

Usage:
    python fill_product_descriptions.py            (IN_FILE / OUT_DIR to override)
"""
import os
import shutil
import sys

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
from common import add_sheet, write_load  # noqa: E402
from products import code_only  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
IN_FILE = os.environ.get("IN_FILE", f"{BASE}/out_sheets/ZSDIITM_products_MAPPED.xlsx")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_run3")


def main():
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/ZSDIITM_products_MAPPED.xlsx"
    shutil.copy(IN_FILE, path)
    wb = load_workbook(path)
    ws = wb["Data with Headings"]
    before = [[c.value for c in r] for r in ws.iter_rows(min_row=4)]
    filled, left = [], []
    for r in range(4, ws.max_row + 1):
        code, d1 = ws.cell(r, 2).value, ws.cell(r, 3).value
        if not code or not code_only(str(d1 or ""), str(code)):
            continue
        d2, d3 = ws.cell(r, 4).value, ws.cell(r, 5).value
        new = next(((str(v).strip()[:30], f) for v, f in ((d3, "description 3"), (d2, "description 2"))
                    if v and not code_only(str(v), str(code))), None)
        if new:
            ws.cell(r, 3, new[0])
            filled.append([code, d1, new[0], new[1]])
        else:
            left.append([code, d1, "", "no other text in the product file - PMA_DESC on the next extract"])
    add_sheet(wb, "Descriptions filled", ["Product", "Description 1 before", "Description 1 now", "Taken from"],
              filled + left, [20, 32, 32, 60])
    n = wb["Notes"]
    n.append([])
    n.append(["Descriptions (4 Nov)", f"{len(filled):,} products whose description 1 was only the code now carry the "
                                      f"real text from description 3 or 2. {len(left):,} have no other text in the "
                                      "file and wait for PMA_DESC on the next product extract. 'Descriptions filled' "
                                      "lists each. Nothing else changed"])
    wb.save(path)

    after = [[c.value for c in r] for r in load_workbook(path, read_only=True)["Data with Headings"].iter_rows(min_row=4)]
    changed = {f[0] for f in filled}
    assert len(after) == len(before)
    for a, b in zip(after, before):
        b = b[:len(a)]
        if b[1] in changed:
            assert a[:2] == b[:2] and a[3:len(b)] == b[3:], b[1]
        else:
            assert a[:len(b)] == b, b[1]
    txt, lines, _ = write_load(path, "Data with Headings", 4)
    print(f"{path}\n  {len(filled):,} descriptions filled, {len(left):,} wait for PMA_DESC | {lines:,} products | {txt}")


if __name__ == "__main__":
    main()
