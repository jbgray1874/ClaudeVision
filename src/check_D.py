import pyodbc
c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.200;DATABASE=SDILive;UID=AIBot;PWD=AIAgentPW2026;Encrypt=yes;TrustServerCertificate=yes")
cur = c.cursor()
cur.execute("""
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA='AIEstimating' AND TABLE_NAME='BoughtInCatalogue'
      AND COLUMN_NAME IN ('source_url','source_detail','verified_by','captured_at')
    ORDER BY COLUMN_NAME
""")
got = [r[0] for r in cur.fetchall()]
print("Provenance columns present:", got)
print("All 4 added:" , len(got)==4)
