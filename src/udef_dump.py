"""Dump the actual UDEF rows for ELECTRICS and a known-good fixing, so we can see
the REAL column names, code format, and description. Run on the laptop:
  C:\ClaudeVision\.venv\Scripts\python.exe _udef_dump.py
"""
import pyodbc, config

cs = config.SQL_CONNECTION_STRING
cn = pyodbc.connect(cs, timeout=10)
cur = cn.cursor()

# First: confirm the real column names of the table
print("=== UDEF columns ===")
cur.execute("""SELECT TOP 1 * FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING""")
cols = [d[0] for d in cur.description]
print(cols)

# Find anything with ELECTRICS in code or description
print("\n=== rows where Part code or Description LIKE %ELECTRIC% ===")
cur.execute("""SELECT TOP 10 [Part code], [Description], [System cost per], [Supplier name]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [Part code] LIKE '%ELEC%' OR [Description] LIKE '%ELECTRIC%' OR [Description] LIKE '%LOOM%'""")
for r in cur.fetchall():
    print(f"  code={r[0]!r:24} desc={str(r[1])[:40]!r:42} cost={r[2]} supplier={r[3]!r}")

# Find the FIXING5 row that DID price, to see its exact format
print("\n=== rows where Part code LIKE %FIXING5% (the one that priced at 0.01) ===")
cur.execute("""SELECT TOP 5 [Part code], [Description], [System cost per], [Supplier name]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [Part code] LIKE '%FIXING5%' OR [Part code] LIKE '%FIXING 5%'""")
for r in cur.fetchall():
    print(f"  code={r[0]!r:24} desc={str(r[1])[:40]!r:42} cost={r[2]} supplier={r[3]!r}")