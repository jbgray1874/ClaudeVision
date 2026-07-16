import pyodbc
c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.200;DATABASE=SDILive;UID=AIBot;PWD=AIAgentPW2026;Encrypt=yes;TrustServerCertificate=yes")
cur = c.cursor()

print("=== Columns in vCurrentBoughtIn ===")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'vCurrentBoughtIn'
    ORDER BY ORDINAL_POSITION
""")
for r in cur.fetchall():
    print(f"  {r[0]:28} {r[1]}")

print()
print("=== EVERY column for the 5 TUBE rows ===")
cur.execute("SELECT * FROM AIEstimating.vCurrentBoughtIn WHERE supplier_sku LIKE 'TUBE00%' ORDER BY supplier_sku")
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    print("  " + "-"*55)
    for col, val in zip(cols, row):
        print(f"    {col:28} = {val}")
