#!/usr/bin/env python3
r"""
check_bought_in_catalogue.py  --  does the DB hold the captured bought-in items?

READ-ONLY (SELECT only). Answers James's question directly: for each bought-in
item the drawing scan now captures, is there a price in the catalogue, and from
which source? It mirrors the engine's OWN lookups so the answer matches what
pricing_service will actually do at runtime:

  • AIEstimating.vCurrentBoughtIn   (_get_catalogue_part — checked first for
                                      BOM-scan parts)
  • dbo.bought_in_parts             (_get_bought_in_part)
  • dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING (UDEF anchor)

Connection details are read from config.PRICE_SOURCE_CONFIG['sqlserver'] — no
secrets in this file. RUN FROM C:\ClaudeVision\src (so `import config` works):

    python check_bought_in_catalogue.py

A hit means that item will price from the catalogue. A miss means it falls
through to the lower tiers and (today) ends up flagged/unpriced — which is the
correct, honest behaviour, not a silent £0.
"""

from __future__ import annotations

import sys

try:
    import pyodbc
except ImportError:
    print("pyodbc not installed in this environment. Run from the .venv in src.", file=sys.stderr)
    raise

try:
    import config
except ImportError:
    print("Could not import config — run this from C:\\ClaudeVision\\src.", file=sys.stderr)
    raise


# The four items the drawing scan now captures from 1282 (code, drawing desc).
# Edit freely to probe other items.
ITEMS = [
    ("ELECTRICS", "50cm LOOM LIGHTING ELECTRICS"),
    ("FIXING5",   "4.0x10mm DOME RIVET"),
    ("FIXING125", "M8x38mm DIA GLIDE (THREAD LENGTH: 25mm)"),
    ("FIXING236", "M8 FLANGED NUTSERT"),
]


def connect():
    c = config.PRICE_SOURCE_CONFIG["sqlserver"]
    conn_str = (
        f"DRIVER={{{c['driver']}}};"
        f"SERVER={c['server']};DATABASE={c['database']};"
        f"UID={c['username']};PWD={c['password']};"
        f"Encrypt={'yes' if c.get('encrypt') else 'no'};"
        f"TrustServerCertificate={'yes' if c.get('trust_server_certificate') else 'no'};"
    )
    return pyodbc.connect(conn_str, timeout=10)


def fetchone(cur, sql, params):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception as exc:  # table/view may not exist; report and continue
        return ("__ERROR__", str(exc).splitlines()[0][:80])


# Same WHERE logic the engine uses (pricing_service).
Q_CATALOGUE = """
SELECT TOP 1 supplier_sku, description, unit_price_gbp, uom, source
FROM AIEstimating.vCurrentBoughtIn
WHERE UPPER(LTRIM(RTRIM(supplier_sku))) = UPPER(LTRIM(RTRIM(?)))
   OR (LEN(LTRIM(RTRIM(?))) >= 5 AND UPPER(description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%')
ORDER BY CASE WHEN UPPER(LTRIM(RTRIM(supplier_sku))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,
         effective_from DESC
"""

Q_BOUGHT_IN = """
SELECT TOP 1 part_code, description, unit_price_gbp, supplier_name
FROM dbo.bought_in_parts
WHERE is_active = 1
  AND ( UPPER(LTRIM(RTRIM(part_code))) = UPPER(LTRIM(RTRIM(?)))
        OR (LEN(LTRIM(RTRIM(?))) >= 5 AND UPPER(description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%') )
ORDER BY CASE WHEN UPPER(LTRIM(RTRIM(part_code))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,
         effective_date DESC
"""

Q_UDEF = """
SELECT TOP 1 u.[Part code] AS part_code, u.[Description] AS description,
       u.[System cost per] AS price, u.[Supplier name] AS supplier_name
FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
WHERE LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
   OR u.[Description] COLLATE Latin1_General_CI_AS LIKE '%' + LTRIM(RTRIM(?)) + '%'
"""


def show(label, row, price_idx, src_extra_idx=None):
    if row is None:
        print(f"      {label:<22} MISS")
        return False
    if row and row[0] == "__ERROR__":
        print(f"      {label:<22} ERROR: {row[1]}")
        return False
    price = row[price_idx]
    if price is None or float(price) <= 0:
        print(f"      {label:<22} found row but price={price} (treated as miss)")
        return False
    extra = f"  src={row[src_extra_idx]}" if src_extra_idx is not None else f"  supplier={row[-1]}"
    print(f"      {label:<22} HIT  £{float(price):.4f}  code/sku={row[0]}  desc={str(row[1])[:34]}{extra}")
    return True


def main() -> int:
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not connect to SDILive: {exc}", file=sys.stderr)
        return 2
    cur = conn.cursor()

    bar = "=" * 78
    print(bar)
    print(" BOUGHT-IN CATALOGUE CHECK — would the captured items price?")
    print(bar)

    priceable = 0
    for code, desc in ITEMS:
        print(f"\n  {code}   (drawing desc: '{desc}')")
        hit_cat  = show("vCurrentBoughtIn",  fetchone(cur, Q_CATALOGUE, [code, desc, desc, code]), 2, 4)
        hit_bip  = show("bought_in_parts",   fetchone(cur, Q_BOUGHT_IN, [code, desc, desc, code]), 2)
        hit_udef = show("UDEF",              fetchone(cur, Q_UDEF, [code, desc]), 2)
        if hit_cat or hit_bip or hit_udef:
            priceable += 1

    print()
    print(bar)
    print(f" RESULT: {priceable}/{len(ITEMS)} captured items have a usable price in the catalogue.")
    if priceable < len(ITEMS):
        print(" The rest will fall through to lower tiers -> flagged/unpriced (honest, not")
        print(" silent £0). To price them: add verified rows to dbo.bought_in_parts or")
        print(" AIEstimating.BoughtInCatalogue (humans WRITE prices; the engine only READS).")
    print(bar)
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
