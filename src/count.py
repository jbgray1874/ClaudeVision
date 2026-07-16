import pyodbc
c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.200;DATABASE=SDILive;UID=AIBot;PWD=AIAgentPW2026;Encrypt=yes;TrustServerCertificate=yes")
cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM dbo.historical_quote_header")
print("Total jobs:", cur.fetchone()[0])
