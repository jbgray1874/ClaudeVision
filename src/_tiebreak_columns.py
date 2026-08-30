r"""READ-ONLY. All 4 TOP-1 queries have non-unique ORDER BY = the drift. To fix, append a UNIQUE
final tiebreaker column that actually EXISTS on each table. Find a guaranteed-unique/stable column
per table (PK id, or the natural key that's unique enough to break ties deterministically).
Check via the DB: column list for UDEF_PARTS_TABLE_FOR_ESTIMATING, bought_in_parts,
estimating_supplier_catalog_url, labour_rates — so the tiebreaker uses a real column.
Read-only DB query (pyodbc). No edits."""
import os
try:
    import pyodbc
except ImportError:
    print("pyodbc not available in this interpreter — run with the venv python.")
    raise SystemExit

# reuse the app's connection approach if present; else standard SDILive on 10.0.0.200
CONN = os.getenv("SDILIVE_CONN") or (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=10.0.0.200;DATABASE=SDILive;Trusted_Connection=yes;"
)
tables = ["UDEF_PARTS_TABLE_FOR_ESTIMATING","bought_in_parts",
          "estimating_supplier_catalog_url","labour_rates"]
try:
    cn=pyodbc.connect(CONN, timeout=5); cur=cn.cursor()
except Exception as e:
    print(f"Could not connect ({e}). Trying SQL auth env SDILIVE_CONN if set, else skip.")
    raise SystemExit

for t in tables:
    print("\n"+"="*60); print(t); print("="*60)
    try:
        cur.execute(f"""SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION""", t)
        cols=cur.fetchall()
        for name,typ in cols:
            print(f"  {name:<32} {typ}")
        # is there a primary key?
        cur.execute(f"""SELECT c.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c ON tc.CONSTRAINT_NAME=c.CONSTRAINT_NAME
            WHERE tc.TABLE_NAME=? AND tc.CONSTRAINT_TYPE='PRIMARY KEY'""", t)
        pk=[r[0] for r in cur.fetchall()]
        print(f"  --> PRIMARY KEY: {pk if pk else '(none found — use a unique natural col)'}")
    except Exception as e:
        print(f"  (couldn't read columns: {e})")
cn.close()
