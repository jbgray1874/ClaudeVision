import config

TABLES = ["COR_TBL", "CUS_TBL", "PMA_TBL", "SUP_TBNL", "WOR_TBL"]

try:
    print("Connecting to SDILive at 10.0.0.200...")
    conn = config.get_connection(timeout=10)
    print("✅ Connection SUCCESSFUL!\n")

    cursor = conn.cursor()

    # Original verification query
    cursor.execute("SELECT TOP 5 TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Sample tables found:", tables)
    print("\n" + "=" * 60 + "\n")

    # Query each table one after the other
    for table in TABLES:
        sql = f"SELECT TOP 100 * FROM {table}"

        print(f">>> SQL: {sql}")
        print("-" * 60)

        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            # Print column headers
            header = " | ".join(columns)
            print(header)
            print("-" * len(header))

            # Print each row
            if rows:
                for row in rows:
                    print(" | ".join(str(val) if val is not None else "NULL" for val in row))
                print(f"\n✅ {len(rows)} row(s) returned from {table}")
            else:
                print(f"⚠️  No rows returned from {table}")

        except Exception as table_err:
            print(f"❌ Failed to query {table}: {table_err}")

        print("\n" + "=" * 60 + "\n")

    conn.close()
    print("Connection closed.")

except Exception as e:
    print("❌ Connection failed!")
    print(f"Error details: {e}")