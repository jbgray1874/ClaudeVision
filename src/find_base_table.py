import pyodbc
c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.200;DATABASE=SDILive;UID=AIBot;PWD=AIAgentPW2026;Encrypt=yes;TrustServerCertificate=yes")
cur = c.cursor()

print("=== Definition of vCurrentBoughtIn (find the base table) ===")
cur.execute("""
    SELECT m.definition
    FROM sys.sql_modules m
    JOIN sys.views v ON m.object_id = v.object_id
    JOIN sys.schemas s ON v.schema_id = s.schema_id
    WHERE v.name = 'vCurrentBoughtIn' AND s.name = 'AIEstimating'
""")
row = cur.fetchone()
print(row[0] if row else "  (definition not found)")

print()
print("=== Candidate base tables with sku/price/source columns ===")
cur.execute("""
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE COLUMN_NAME IN ('supplier_sku','unit_price_gbp','source')
    GROUP BY TABLE_SCHEMA, TABLE_NAME
    HAVING COUNT(DISTINCT COLUMN_NAME) >= 2
    ORDER BY TABLE_SCHEMA, TABLE_NAME
""")
for r in cur.fetchall():
    print(f"  {r[0]}.{r[1]}")
