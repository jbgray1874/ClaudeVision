import config
c = config.get_connection()
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
