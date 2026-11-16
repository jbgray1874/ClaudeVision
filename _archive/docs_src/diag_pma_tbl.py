"""
diag_pma_tbl.py — drop in C:\ClaudeVision\src\ and run:
    python src\diag_pma_tbl.py
Inspects PMA_TBL (Access Supply Chain parts master) in SDILive.
"""
import sys
try:
    import pymssql
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pymssql", "--break-system-packages", "-q"])
    import pymssql

SERVER   = "10.0.0.200"
DATABASE = "SDILive"
USER     = "AIBot"
PASSWORD = ""

conn = pymssql.connect(server=SERVER, database=DATABASE, user=USER, password=PASSWORD)
cur  = conn.cursor()

# ── 1. Column map ──────────────────────────────────────────────────────────────
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
    FROM   INFORMATION_SCHEMA.COLUMNS
    WHERE  TABLE_NAME = 'PMA_TBL'
    ORDER  BY ORDINAL_POSITION
""")
cols = cur.fetchall()
print(f"\n=== PMA_TBL  — {len(cols)} columns ===")
for c in cols:
    print(f"  {c[0]:<35} {c[1]:<15} len={str(c[2]):<8} nullable={c[3]}")

# ── 2. Row count ───────────────────────────────────────────────────────────────
cur.execute("SELECT COUNT(*) FROM PMA_TBL")
total = cur.fetchone()[0]
print(f"\nTotal rows: {total:,}")

# ── 3. Which columns exist? (desc variants) ────────────────────────────────────
desc_cols_present = [c[0] for c in cols if "DESC" in c[0].upper() or "NAME" in c[0].upper()]
print(f"\nDescription-like columns: {desc_cols_present}")

# ── 4. Price / cost columns ────────────────────────────────────────────────────
cost_cols_present = [c[0] for c in cols if any(k in c[0].upper() for k in ("COST","PRICE","RATE","SELL","BUY","LAST","STD"))]
print(f"Cost / price columns:     {cost_cols_present}")

# ── 5. Five sample rows ────────────────────────────────────────────────────────
# Build SELECT dynamically from what's actually there
col_names = [c[0] for c in cols]
want = ["PMA_PART", "PMA_DESC_1", "PMA_DESC_2", "PMA_TYPE",
        "PMA_STOCK_UM", "PMA_STD_COST", "PMA_LAST_COST",
        "PMA_SELL_PRICE", "PMA_BUY_PRICE", "PMA_SUPP_PART",
        "PMA_SUPP", "PMA_GROUP", "PMA_CATEGORY"]
select_cols = [c for c in want if c in col_names]
if not select_cols:
    select_cols = col_names[:10]

sql = f"SELECT TOP 5 {', '.join(select_cols)} FROM PMA_TBL WHERE PMA_DESC_1 IS NOT NULL AND LEN(PMA_DESC_1) > 2 ORDER BY PMA_PART"
cur.execute(sql)
rows = cur.fetchall()
print(f"\n=== Sample rows (columns: {select_cols}) ===")
for r in rows:
    for label, val in zip(select_cols, r):
        print(f"  {label:<25} {val}")
    print()

# ── 6. Part-type breakdown ─────────────────────────────────────────────────────
if "PMA_TYPE" in col_names:
    cur.execute("SELECT PMA_TYPE, COUNT(*) AS cnt FROM PMA_TBL GROUP BY PMA_TYPE ORDER BY cnt DESC")
    types = cur.fetchall()
    print("=== PMA_TYPE breakdown ===")
    for t in types[:15]:
        print(f"  {str(t[0]):<10} {t[1]:>6} rows")

# ── 7. Cost coverage ──────────────────────────────────────────────────────────
for col in ["PMA_STD_COST", "PMA_LAST_COST", "PMA_SELL_PRICE", "PMA_BUY_PRICE"]:
    if col in col_names:
        cur.execute(f"SELECT COUNT(*) FROM PMA_TBL WHERE {col} IS NOT NULL AND {col} > 0")
        n = cur.fetchone()[0]
        print(f"  {col}: {n:,} rows with price > 0  ({100*n//max(total,1)}%)")

conn.close()
print("\nDone.")