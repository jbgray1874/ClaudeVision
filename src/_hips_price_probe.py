"""
READ-ONLY DB probe. Finds where sheet-material prices (HIPS, acrylic, etc.) live
in SDILive, so we can wire the REAL HIPS rate instead of guessing.

- Reuses the udef_sqlserver connection from config.
- SELECT-only. No writes, no DDL. Safe.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _hips_price_probe.py
"""
import pyodbc
import config

c = config.PRICE_SOURCE_CONFIG.get("udef_sqlserver", {})
conn_str = (
    f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
    f"SERVER={c.get('server')};DATABASE={c.get('database')};"
    f"UID={c.get('username')};PWD={c.get('password')};"
    "Encrypt=yes;TrustServerCertificate=yes;"
)
conn = pyodbc.connect(conn_str, timeout=30)
cur = conn.cursor()
print(f"Connected to {c.get('database')} on {c.get('server')}\n")

def q(sql, params=None):
    try:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, rows
    except Exception as e:
        print(f"  [query error] {e}")
        return [], []

# 1. Find tables whose name suggests material / sheet / price / UDEF / catalogue
print("=" * 70)
print("1. Tables mentioning material / sheet / price / udef / stock / catalogue")
print("=" * 70)
cols, rows = q("""
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE IN ('BASE TABLE','VIEW')
      AND (
        TABLE_NAME LIKE '%material%' OR TABLE_NAME LIKE '%sheet%' OR
        TABLE_NAME LIKE '%price%'   OR TABLE_NAME LIKE '%udef%'  OR
        TABLE_NAME LIKE '%stock%'   OR TABLE_NAME LIKE '%catalog%' OR
        TABLE_NAME LIKE '%rate%'    OR TABLE_NAME LIKE '%acrylic%' OR
        TABLE_NAME LIKE '%plastic%' OR TABLE_NAME LIKE '%board%'
      )
    ORDER BY TABLE_SCHEMA, TABLE_NAME
""")
for r in rows:
    print(f"  {r[0]}.{r[1]}")
if not rows:
    print("  (none matched — will search columns next)")

# 2. Find COLUMNS that mention HIPS / acrylic / material anywhere
print("\n" + "=" * 70)
print("2. Columns mentioning material / hips / acrylic / thickness / gauge")
print("=" * 70)
cols, rows = q("""
    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE COLUMN_NAME LIKE '%material%' OR COLUMN_NAME LIKE '%hips%'
       OR COLUMN_NAME LIKE '%acrylic%' OR COLUMN_NAME LIKE '%thickness%'
       OR COLUMN_NAME LIKE '%sheet%'   OR COLUMN_NAME LIKE '%price%'
    ORDER BY TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
""")
seen_tables = set()
for r in rows:
    key = f"{r[0]}.{r[1]}"
    print(f"  {key}.{r[2]} ({r[3]})")
    seen_tables.add(key)

# 3. Search UDEF (the main catalogue) for HIPS and acrylic descriptions
print("\n" + "=" * 70)
print("3. UDEF rows where Description mentions HIPS")
print("=" * 70)
cols, rows = q("""
    SELECT TOP (15) [Part code], [Description], [Supplier name], [Unit cost]
    FROM UDEF
    WHERE [Description] LIKE '%HIPS%'
    ORDER BY [Part code]
""")
if cols:
    print("  " + " | ".join(cols))
    for r in rows:
        print("  " + " | ".join(str(x) for x in r))
if not rows:
    print("  (no HIPS rows, or column names differ — see section 2 output)")

print("\n" + "=" * 70)
print("4. UDEF rows where Description mentions ACRYLIC or PERSPEX (for structure)")
print("=" * 70)
cols, rows = q("""
    SELECT TOP (15) [Part code], [Description], [Supplier name], [Unit cost]
    FROM UDEF
    WHERE [Description] LIKE '%ACRYLIC%' OR [Description] LIKE '%PERSPEX%'
    ORDER BY [Part code]
""")
if cols:
    print("  " + " | ".join(cols))
    for r in rows:
        print("  " + " | ".join(str(x) for x in r))
if not rows:
    print("  (no acrylic rows via those columns)")

conn.close()
print("\nDone. (read-only — nothing written)")
