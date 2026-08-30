"""READ-ONLY. Check whether the electrical BOM items have REAL prices in the live
historical-quote tables (dbo.historical_quote_material_line), so the recogniser prices
from genuine prior quotes before ever reaching the LLM.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _hq_electrical_probe.py
"""
import pyodbc, config

c = config.PRICE_SOURCE_CONFIG["udef_sqlserver"]
conn = pyodbc.connect(
    f"DRIVER={{{c['driver']}}};SERVER={c['server']};DATABASE={c['database']};"
    f"UID={c['username']};PWD={c['password']};Encrypt=yes;TrustServerCertificate=yes;",
    timeout=30)
cur = conn.cursor()

# First: what columns does the live material-line table have?
print("=" * 70); print("dbo.historical_quote_material_line columns"); print("=" * 70)
cur.execute("""SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='historical_quote_material_line'
               ORDER BY ORDINAL_POSITION""")
cols = cur.fetchall()
for name, dt in cols:
    print(f"  {name} ({dt})")
colnames = [c2[0] for c2 in cols]

# Guess the description + price columns
desc_col = next((c2 for c2 in colnames if "desc" in c2.lower()), None)
price_cols = [c2 for c2 in colnames if any(k in c2.lower() for k in ("price","cost","val","rate","unit"))]
print(f"\n  desc column guess: {desc_col}")
print(f"  price column guesses: {price_cols}\n")

if desc_col:
    TERMS = ["JUNCTION BOX", "MAINS CABLE", "EARTH STRAP", "LED LINK LIGHT",
             "GU10", "DOWNLIGHT", "LOOM", "LIGHTING LOOM"]
    sel = ", ".join([f"[{desc_col}]"] + [f"[{p}]" for p in price_cols[:4]])
    for t in TERMS:
        print("=" * 70); print(f"historical_quote_material_line: '{t}'"); print("=" * 70)
        try:
            cur.execute(f"""SELECT TOP 6 {sel} FROM dbo.historical_quote_material_line
                            WHERE [{desc_col}] LIKE ?""", [f"%{t}%"])
            rows = cur.fetchall()
            for r in rows:
                print("  " + " | ".join("" if x is None else str(x) for x in r))
            print(f"  --- {len(rows)} row(s) ---")
        except Exception as e:
            print(f"  [error] {e}")
        print()

conn.close()
print("Done (read-only).")
