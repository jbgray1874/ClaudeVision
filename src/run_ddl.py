#!/usr/bin/env python3
"""
run_ddl.py — Run the AIEstimating schema DDL via pyodbc (no sqlcmd needed).
Run from C:\\ClaudeVision\\src with the venv active.

    python run_ddl.py
"""
import sys, os, re

# ── locate config ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as _cfg
c = _cfg.PRICE_SOURCE_CONFIG.get("sqlserver", {})
server   = c.get("server",   "10.0.0.200")
database = c.get("database", "SDILive")
username = c.get("username", "AIAgent")
password = c.get("password", "")

import pyodbc
conn_str = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};"
    f"UID={username};PWD={password};"
    "Encrypt=yes;TrustServerCertificate=yes;"
)
print(f"Connecting to {server}/{database} as {username}...")
cn = pyodbc.connect(conn_str, autocommit=True)
cur = cn.cursor()
print("Connected.\n")

SQL_FILES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_estimating_rag_stores.sql"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_bought_in_materials.sql"),
]

for sql_file in SQL_FILES:
    if not os.path.exists(sql_file):
        print(f"SKIP (not found): {sql_file}")
        continue
    print(f"Running: {os.path.basename(sql_file)}")
    sql = open(sql_file, "r", encoding="utf-8").read()
    # Split on GO (T-SQL batch separator) — case-insensitive, own line
    batches = re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE | re.IGNORECASE)
    ok = 0
    for i, batch in enumerate(batches):
        batch = batch.strip()
        if not batch or batch.startswith("--"):
            continue
        try:
            cur.execute(batch)
            ok += 1
        except pyodbc.ProgrammingError as e:
            # Ignore "object already exists" — script is idempotent
            msg = str(e)
            if "already exists" in msg or "2714" in msg or "1913" in msg:
                print(f"  batch {i+1}: already exists (skipped)")
            else:
                print(f"  batch {i+1}: ERROR — {msg[:120]}")
    print(f"  {ok} batch(es) executed OK\n")

print("Done. Now retry:")
print('  python catalogue_loader.py --workbook "K:\\...\\0354158 - ... .xls" --commit')
cn.close()
