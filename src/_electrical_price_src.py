"""READ-ONLY. Find where the electrical item prices (junction box, mains cable, earth
strap, LED link light, GU10 downlight, loom) genuinely resolve from, so the new
deterministic electrical recogniser prices from the REAL source (no hardcoding).

Checks: (1) UDEF catalogue for these descriptions, (2) historical_quote lines,
(3) any NOTE-* coded rows. Prints whatever real prices exist and their source table.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _electrical_price_src.py
"""
import pyodbc, config

c = config.PRICE_SOURCE_CONFIG["udef_sqlserver"]
conn = pyodbc.connect(
    f"DRIVER={{{c['driver']}}};SERVER={c['server']};DATABASE={c['database']};"
    f"UID={c['username']};PWD={c['password']};Encrypt=yes;TrustServerCertificate=yes;",
    timeout=30)
cur = conn.cursor()

TERMS = ["JUNCTION BOX", "MAINS CABLE", "EARTH STRAP", "LED LINK", "GU10", "DOWNLIGHT",
         "LOOM", "LIGHTING"]

def run(sql, title, params=None):
    print("=" * 70); print(title); print("=" * 70)
    try:
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        if cols: print("  " + " | ".join(cols))
        for r in rows[:20]:
            print("  " + " | ".join("" if x is None else str(x) for x in r))
        print(f"  --- {len(rows)} row(s) ---")
    except Exception as e:
        print(f"  [error] {e}")
    print()

# 1. UDEF catalogue — do these electrical items exist there with a System cost per?
for t in TERMS:
    run(f"""SELECT TOP 8 [Part code],[Description],[System cost per],[Supplier name]
            FROM UDEF_PARTS_TABLE_FOR_ESTIMATING
            WHERE [Description] LIKE '%{t}%' AND [System cost per] > 0
            ORDER BY [System cost per]""",
        f"UDEF: '{t}'")

# 2. Historical quote lines — are these priced in dbo.historical_quote_*?
run("""SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
       WHERE TABLE_NAME LIKE '%historical_quote%' ORDER BY TABLE_SCHEMA, TABLE_NAME""",
    "historical_quote tables available")

conn.close()
print("Done (read-only).")
