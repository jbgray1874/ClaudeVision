"""Fill the blank customer VAT numbers (YA004BPC column EECNUM) from Access's address records.

    python fill_customer_vat.py <customer_vat_numbers.sql output>     (BPC_FILE to override the file)

The customer file took the VAT number from the account only (SL_ACCOUNTS.CU_VAT_REG_NO). Access
also keeps one on each address (SL_ADDRESSES.AD_VAT_REG_NO, and the old copy SL_ADDRESSES_COPYA).
For a customer whose EECNUM is blank, a number is filled only when all of these hold:
  * it passes the format of its country (and, for GB, the HMRC check digits)
  * its country is the customer's country (a Dutch number on a UK customer is a question, not a fix)
  * no other customer in the file has it
  * it is the customer's only number - or the only one on its invoice / statement / main address
Spaces, dots, dashes and non-breaking spaces are taken out and the country prefix is added
(GB123456789), matching the numbers already in the file. Anything else goes on 'VAT check' with
the reason; nothing already filled is changed. Works on the address-fixed file in place (run
fix_customer_addresses.py first), adds 'VAT filled' and 'VAT check', and rewrites the load file.
"""
import os
import re
import sys
from collections import Counter, defaultdict

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
from common import add_sheet, read_grids, write_load  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
BPC_FILE = os.environ.get("BPC_FILE", f"{BASE}/out_run3/YA004BPC_customers_MAPPED.xlsx")
CUS, ADD, EECNUM, DEF_ADD, ROW_ADD, CRY = 1, 5, 12, 7, 17, 24      # columns of 'Data with Headings' (0-based)

# the number after the country prefix (EU VIES formats, plus GB/XI, CH and NO)
FORMAT = {
    "AT": r"U\d{8}", "BE": r"[01]\d{9}", "BG": r"\d{9,10}", "CY": r"\d{8}[A-Z]", "CZ": r"\d{8,10}",
    "DE": r"\d{9}", "DK": r"\d{8}", "EE": r"\d{9}", "EL": r"\d{9}", "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "FI": r"\d{8}", "FR": r"[A-HJ-NP-Z0-9]{2}\d{9}", "HR": r"\d{11}", "HU": r"\d{8}",
    "IE": r"\d{7}[A-W][A-IW]?|\d[A-Z+*]\d{5}[A-W]", "IT": r"\d{11}", "LT": r"\d{9}|\d{12}", "LU": r"\d{8}",
    "LV": r"\d{11}", "MT": r"\d{8}", "NL": r"\d{9}B\d{2}", "PL": r"\d{10}", "PT": r"\d{9}", "RO": r"\d{2,10}",
    "SE": r"\d{12}", "SI": r"\d{8}", "SK": r"\d{10}", "GB": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}",
    "XI": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}", "CH": r"E\d{9}(MWST|TVA|IVA)?", "NO": r"\d{9}(MVA)?",
}
PREFIX = {"GR": "EL"}                                      # X3 country GR, VAT prefix EL


def gb_ok(digits):
    """HMRC check: weights 8..2 on the first seven digits plus the last two, mod 97 (old or new series)."""
    if not digits[:9].isdigit():
        return True                                        # GD / HA government numbers: no check digits
    s = sum(int(d) * w for d, w in zip(digits[:7], range(8, 1, -1))) + int(digits[7:9])
    return s % 97 == 0 or (s + 55) % 97 == 0


def clean(raw, country):
    """(number with prefix, None) if it is valid, else (None, reason)."""
    v = re.sub(r"[\s\xa0.\-/]", "", str(raw or "")).upper()
    if not v or v in ("NULL", "0") or set(v) <= {"X", "0"}:
        return None, "placeholder"
    want = PREFIX.get(country, country)
    if v[:2].isalpha() and v[:2] in FORMAT and re.fullmatch(FORMAT[v[:2]], v[2:]):
        pre, num = v[:2], v[2:]
    elif v[:2] == "GR" and re.fullmatch(FORMAT["EL"], v[2:]):
        pre, num = "EL", v[2:]
    elif want in FORMAT and re.fullmatch(FORMAT[want], v):
        pre, num = want, v
    else:
        fits = [c for c, f in FORMAT.items() if re.fullmatch(f, v)]
        if want not in FORMAT:
            return None, f"no VAT format known for {country}"
        return None, ("looks like a " + "/".join(fits) + " number" if fits and len(fits) < 4
                      else f"not a {want} VAT number")
    if pre != want and not (want == "GB" and pre == "XI"):
        return None, f"{pre} number on a {country} customer"
    if pre in ("GB", "XI") and not gb_ok(num):
        return None, "GB check digits fail"
    return pre + num, None


def main(vat_file):
    g, _ = read_grids(vat_file)
    if "VAT" not in g:
        raise SystemExit(f"{vat_file}: no VAT grid - was the whole of customer_vat_numbers.sql saved?")
    wb = load_workbook(BPC_FILE)
    for t in ("VAT filled", "VAT check"):
        if t in wb.sheetnames:
            raise SystemExit(f"{BPC_FILE} already has a '{t}' tab - rerun fix_customer_addresses.py first")
    ws = wb["Data with Headings"]
    rows = [r for r in range(3, ws.max_row + 1) if ws.cell(r, CUS + 1).value]
    country, current, name = {}, {}, {}
    for r in rows:
        c = ws.cell(r, CUS + 1).value
        current.setdefault(c, ws.cell(r, EECNUM + 1).value)
        name.setdefault(c, ws.cell(r, 3).value)
        if ws.cell(r, ROW_ADD + 1).value == ws.cell(r, DEF_ADD + 1).value or c not in country:
            country[c] = str(ws.cell(r, CRY + 1).value or "").upper()

    # every number Access holds, per customer: source, invoice/statement/main flags
    seen = defaultdict(lambda: defaultdict(lambda: {"sources": Counter(), "key": False, "raw": set()}))
    for sage, access, source, address, inv, stat, prim, _, raw in (r[:9] for r in g["VAT"]):
        if sage not in current:
            continue
        num, why = clean(raw, country[sage])
        k = num or f"!{why}|{raw}"
        e = seen[sage][k]
        e["sources"][source] += 1
        e["raw"].add(raw)
        e["key"] |= source == "ACCOUNT" or "1" in (inv, stat, prim)
    owners = defaultdict(set)
    for c, v in current.items():
        if v:
            owners[re.sub(r"\s", "", str(v)).upper()].add(c)
    for c, nums in seen.items():
        for k in nums:
            if not k.startswith("!"):
                owners[k].add(c)

    filled, check = [], []
    for c in sorted(seen):
        if current[c]:
            continue
        good = {k: e for k, e in seen[c].items() if not k.startswith("!")}
        for k, e in seen[c].items():
            if k.startswith("!"):
                why, raw = k[1:].split("|", 1)
                check.append([c, name[c], country[c], raw, why, ", ".join(f"{s} {n}" for s, n in e["sources"].items())])
        mine = {k: e for k, e in good.items() if owners[k] == {c}}
        for k, e in good.items():
            if k not in mine:
                check.append([c, name[c], country[c], k, "also held by " + ", ".join(sorted(owners[k] - {c})),
                              ", ".join(f"{s} {n}" for s, n in e["sources"].items())])
        pick = list(mine) if len(mine) == 1 else [k for k, e in mine.items() if e["key"]]
        if len(pick) == 1:
            k = pick[0]
            filled.append([c, name[c], country[c], k, " / ".join(sorted(map(str, mine[k]["raw"]))),
                           ", ".join(f"{s} {n}" for s, n in mine[k]["sources"].items())])
        elif mine:
            for k, e in mine.items():
                check.append([c, name[c], country[c], k, f"one of {len(mine)} different numbers for this customer",
                              ", ".join(f"{s} {n}" for s, n in e["sources"].items())])
    fill = {f[0]: f[3] for f in filled}
    for r in rows:
        c = ws.cell(r, CUS + 1).value
        if c in fill:
            ws.cell(r, EECNUM + 1).value = fill[c]

    head = ["Customer", "Name", "Country", "VAT number", "As Access holds it", "Where (rows)"]
    add_sheet(wb, "VAT filled", head, filled, [10, 34, 8, 18, 22, 30])
    add_sheet(wb, "VAT check", head[:4] + ["Why not filled", "Where (rows)"], check, [10, 34, 8, 18, 40, 30])
    blank = sum(1 for c, v in current.items() if not v and c not in fill)
    n = wb["Notes"]
    n.append([])
    n.append(["VAT numbers (4 Nov)", f"{len(filled):,} blank EECNUMs filled from Access's address VAT numbers "
              f"(SL_ADDRESSES), each checked against its country's format and unique to the customer. "
              f"{len({c[0] for c in check}):,} customers on 'VAT check'. {blank:,} customers still have no VAT "
              f"number - Access holds none for them. Numbers already in the file are unchanged"])
    wb.save(BPC_FILE)
    txt, lines, _ = write_load(BPC_FILE, "Data with Headings", 3)
    print(f"{BPC_FILE}\n  customers {len(current):,}; had VAT {sum(1 for v in current.values() if v):,}; "
          f"filled {len(filled):,}; to check {len({c[0] for c in check}):,}; still blank {blank:,}\n"
          f"  reasons: {dict(Counter(c[4].split(' held by')[0] for c in check))}\n  {lines:,} rows | {txt}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.split("\n\n")[1])
    main(sys.argv[1])
