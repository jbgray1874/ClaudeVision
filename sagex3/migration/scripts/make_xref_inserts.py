"""Rebuild xref_sage_codes.sql from the template and the supplier and customer load files.

The supplier and customer names are not kept in git (Claire's rule: who our suppliers are
stays private), so sql/xref_sage_codes_TEMPLATE.sql has two markers where the name lists
go. This puts them back.

Use the files that were LOADED into X3 - supplier V4, customer V7 - not the cleaned V8
ones. The match is on the name as Access holds it, and V8 rewrote & as AND, which would
stop names matching.

Usage:
    python make_xref_inserts.py <supplier load .txt> <customer load .txt> <output .sql>
"""
import csv
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "sql" / "xref_sage_codes_TEMPLATE.sql"
BATCH = 200                      # SQL Server takes at most 1000 rows per VALUES list


def accounts(path):
    """Code and name, once per account, in file order (customer files repeat per address)."""
    seen = {}
    with open(path, newline="", encoding="cp850") as f:
        for r in csv.reader(f, delimiter=";"):
            if len(r) > 2 and r[1].strip() and r[1] not in seen:
                seen[r[1]] = r[2]
    return seen


def inserts(table, rows):
    out = []
    items = list(rows.items())
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        out.append(f"INSERT INTO migration.{table} (SAGE_CODE, SAGE_NAME) VALUES")
        for j, (code, name) in enumerate(chunk):
            name = name.replace("'", "''")
            out.append(f"    ('{code}', N'{name}')" + (";" if j == len(chunk) - 1 else ","))
    return out


def main(sup, cus, dest):
    lines = []
    for line in TEMPLATE.read_text(encoding="utf-8").split("\n"):
        if line.startswith("-- @@SAGE_BPS_CODES@@"):
            lines += inserts("SAGE_BPS_CODES", accounts(sup))
        elif line.startswith("-- @@SAGE_BPC_CODES@@"):
            lines += inserts("SAGE_BPC_CODES", accounts(cus))
        else:
            lines.append(line)
    Path(dest).write_text("\n".join(lines), encoding="utf-8")
    print(f"{dest}: {len(accounts(sup))} suppliers, {len(accounts(cus))} customers")


if __name__ == "__main__":
    main(*sys.argv[1:4])
