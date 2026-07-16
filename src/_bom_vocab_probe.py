# -*- coding: utf-8 -*-
"""Read-only: get the REAL columns of bought_in_parts and historical_quote_material, then
sample each. bought_in_parts may be the cleanest dictionary source of all.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_bom_vocab_probe2.py"""
import config
conn = config.get_connection()
cur = conn.cursor()

def cols(table):
    cur.execute("""
        SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=? ORDER BY ORDINAL_POSITION
    """, table)
    return cur.fetchall()

for t in ("bought_in_parts", "historical_quote_material", "historical_quote_material_line"):
    print(f"\n=== columns of dbo.{t} ===")
    try:
        for c in cols(t):
            print(f"   {c[0]:30s} {c[1]}")
    except Exception as e:
        print("   ERR:", e)

# Row counts
print("\n=== row counts ===")
for t in ("bought_in_parts", "historical_quote_material", "historical_quote_material_line"):
    try:
        cur.execute(f"SELECT COUNT(*) FROM dbo.{t}")
        print(f"   dbo.{t}: {cur.fetchone()[0]:,}")
    except Exception as e:
        print(f"   dbo.{t}: ERR {e}")

# Sample bought_in_parts fully (likely small & curated)
print("\n=== sample rows: dbo.bought_in_parts (first 30) ===")
try:
    cur.execute("SELECT TOP 30 * FROM dbo.bought_in_parts")
    headers = [d[0] for d in cur.description]
    print("   COLS:", headers)
    for r in cur.fetchall():
        print("   ", tuple(str(x)[:40] for x in r))
except Exception as e:
    print("   ERR:", e)

conn.close()
