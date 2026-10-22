import pandas as pd

import config

target_tables = ['CUS_TBL', 'PMA_TBL', 'SUP_TBL', 'WOR_TBL', 'COR_TBL']

def query_to_df(cursor, sql):
    """Execute SQL and return a clean DataFrame — no pandas/SQLAlchemy warnings."""
    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)

def extract_db_knowledge_base(tables):
    try:
        conn = config.get_connection(timeout=10)
        cursor = conn.cursor()
        print("Connected Successfully. Commencing Extraction...\n")

        for table in tables:
            print(f"{'#'*80}")
            print(f"DATABASE ENTITY: {table}")
            print(f"{'#'*80}")

            # 1. SCHEMA
            schema_query = f"""
            SELECT 
                column_name AS [Column], 
                data_type AS [Type], 
                is_nullable AS [Nulls],
                character_maximum_length AS [Len]
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE table_name = '{table}'
            ORDER BY ordinal_position;
            """
            print(f"\n>>> SQL: {schema_query.strip()}")
            df_schema = query_to_df(cursor, schema_query)
            print("\n[SCHEMA DEFINITION]")
            print(df_schema.to_string(index=False))

            # 2. DATA SAMPLE
            data_query = f"SELECT TOP 10 * FROM {table}"
            print(f"\n>>> SQL: {data_query}")
            df_data = query_to_df(cursor, data_query)
            print(f"\n[DATA SAMPLE - TOP 100 ROWS] ({len(df_data)} rows returned)")
            print(df_data.to_string())
            print("\n" + "="*80 + "\n")

        conn.close()
        print("Extraction Complete.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    extract_db_knowledge_base(target_tables)