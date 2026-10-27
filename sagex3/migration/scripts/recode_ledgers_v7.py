"""Clean-run copies of the stock and order load files on V7 product codes.

The load1 files stay on the codes loaded in UAT. These copies change only the product
code column: SMR col 8, SOHPJ col 17, POH col 8.
"""
import csv
import zipfile

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"


def read(p):
    with open(p, newline="", encoding="cp850") as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(p, rows):
    with open(p, "w", newline="", encoding="cp850") as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


v6 = [r[1] for r in read(f"{BASE}/out_std6/ZSDIITM_load6_products.txt")]
v7 = [r[1] for r in read(f"{BASE}/out_v7/ZSDIITM_load7_products.txt")]
code = dict(zip(v6, v7))
for name, col in (("YA004SMR", 7), ("YA004SOHPJ", 16), ("YA004POH", 7)):
    rows = read(f"{BASE}/out_mapped/load_files/{name}_load1.txt")
    n = 0
    for r in rows:
        if code.get(r[col], r[col]) != r[col]:
            r[col] = code[r[col]]
            n += 1
    write(f"{BASE}/out_v7/{name}_load7_clean_run.txt", rows)
    with zipfile.ZipFile(f"{BASE}/out_v7/V7_load_files.zip", "a", zipfile.ZIP_DEFLATED) as z:
        if f"{name}_load7_clean_run.txt" not in z.namelist():
            z.write(f"{BASE}/out_v7/{name}_load7_clean_run.txt", f"{name}_load7_clean_run.txt")
    print(name, len(rows), "codes changed", n)
