"""READ-ONLY. One question: what HIPS sheet materials exist in the estimating view,
and what do they cost? Queries UDEF_PARTS_TABLE_FOR_ESTIMATING (PMA_USAGE_2 = 'System cost per').
Run: C:\ClaudeVision\.venv\Scripts\python.exe _hips_lookup.py"""
import pyodbc, config
c = config.PRICE_SOURCE_CONFIG["udef_sqlserver"]
conn = pyodbc.connect(
    f"DRIVER={{{c['driver']}}};SERVER={c['server']};DATABASE={c['database']};"
    f"UID={c['username']};PWD={c['password']};Encrypt=yes;TrustServerCertificate=yes;",
    timeout=30)
cur = conn.cursor()

def run(where, title):
    print("=" * 68); print(title); print("=" * 68)
    cur.execute(
        "SELECT [Part code],[Description],[UOM],[Proc code],"
        "[System cost per],[Supplier name] "
        f"FROM UDEF_PARTS_TABLE_FOR_ESTIMATING WHERE {where} ORDER BY [Part code]")
    rows = cur.fetchall()
    for r in rows:
        print("  " + " | ".join("" if x is None else str(x) for x in r))
    print(f"  --- {len(rows)} row(s) ---\n")

run("[Description] LIKE '%HIPS%'", "HIPS materials")
run("[Description] LIKE '%POLYSTYRENE%' OR [Description] LIKE '%STYRENE%'", "Polystyrene (HIPS = High Impact PolyStyrene)")
conn.close()
