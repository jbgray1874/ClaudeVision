import config
c = config.get_connection()
cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM dbo.historical_quote_header")
print("Total jobs:", cur.fetchone()[0])
