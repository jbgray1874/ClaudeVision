import pyodbc

conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.200;"
    "DATABASE=SDILive;"
    "UID=AIBot;"
    "PWD=AIAgentPW2026;"
    "TrustServerCertificate=yes;"
    "Encrypt=yes;"
)

try:
    print("Connecting to SDILive at 10.0.0.200...")
    conn = pyodbc.connect(conn_str, timeout=10)
    print("✅ Connection SUCCESSFUL!")
    
    cursor = conn.cursor()
    # This query verifies that the AIBot can actually read the table list
    cursor.execute("SELECT TOP 5 TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
    
    tables = [row[0] for row in cursor.fetchall()]
    print("Sample tables found:", tables)
    
    conn.close()
except Exception as e:
    print("❌ Connection failed!")
    print(f"Error details: {e}")