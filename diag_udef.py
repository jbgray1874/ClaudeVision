import sys
sys.path.insert(0, 'src')
import config, pyodbc

c = config.PRICE_SOURCE_CONFIG.get('sqlserver', {})
conn_str = (
    f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
    f"SERVER={c.get('server')};DATABASE={c.get('database')};"
    f"UID={c.get('username')};PWD={c.get('password')};"
    "Encrypt=yes;TrustServerCertificate=yes;"
)
conn = pyodbc.connect(conn_str, timeout=30)
cur = conn.cursor()
try:
    cur.execute("""
        SELECT TOP 1 u.[Part code], u.[Description], 
               CAST(u.[System cost per] AS decimal(18,4))
        FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
        WHERE u.[Part code] = LTRIM(RTRIM(?))
    """, ['MAGNET23'])
    row = cur.fetchone()
    print(f'UDEF result: {row}')
except Exception as e:
    print(f'UDEF ERROR: {e}')
conn.close()
