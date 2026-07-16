# -*- coding: utf-8 -*-
r"""Are 1282's FIXING / VINYL codes in the SDI database, so we can price them genuinely?
First discovers the real column names, then searches. READ ONLY.
  C:\ClaudeVision\.venv\Scripts\python.exe _fixing_lookup_diag.py
"""
import config

CODES = ["FIXING125","FIXING236","FIXING2","FIXING5","FIXING49","FIXING51","FIXING1101",
         "VINYL03","VINYL76"]

cn = config.get_connection(timeout=30)
cur = cn.cursor()

# 0. Discover the columns on the historical_quote_material table (names differ from my guess)
print("=== columns on dbo.historical_quote_material ===")
try:
    cur.execute("""SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_NAME = 'historical_quote_material' ORDER BY ORDINAL_POSITION""")
    cols = cur.fetchall()
    for c in cols:
        print(f"   {c[0]} ({c[1]})")
    colnames = [c[0].lower() for c in cols]
except Exception as e:
    print(f"  failed: {e}")
    colnames = []

# Find the likely code + description + price columns by name
def pick(cands):
    for cand in cands:
        for cn_ in colnames:
            if cand in cn_:
                return cn_
    return None
code_col = pick(["part_code","partcode","code","part_no","partno","part"])
desc_col = pick(["description","desc","detail"])
price_col = pick(["unit_price","price","cost","rate"])
print(f"\n  guessed columns -> code={code_col}  desc={desc_col}  price={price_col}")

# 1. UDEF catalogue search (fixed: 2 markers, 2 params)
print("\n=== UDEF_PARTS_TABLE_FOR_ESTIMATING matches ===")
for code in CODES:
    like = f"%{code}%"
    try:
        cur.execute("SELECT TOP 3 [Part code],[Description],[System cost per],[Supplier name] "
                    "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
                    "WHERE [Part code] LIKE ? OR [Description] LIKE ?", like, like)
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"  {code}: " + " | ".join(str(x) for x in r))
        else:
            print(f"  {code}: (none in UDEF)")
    except Exception as e:
        print(f"  {code}: query failed: {e}")

# 2. historical_quote_material search using discovered columns
if code_col and price_col:
    print(f"\n=== historical_quote_material ({code_col}/{desc_col}/{price_col}) ===")
    for code in CODES:
        like = f"%{code}%"
        try:
            sql = f"SELECT TOP 3 [{code_col}],[{desc_col}],[{price_col}] FROM dbo.historical_quote_material WHERE [{code_col}] LIKE ?"
            cur.execute(sql, like)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    print(f"  {code}: " + " | ".join(str(x) for x in r))
            else:
                print(f"  {code}: (none)")
        except Exception as e:
            print(f"  {code}: failed: {e}")

cn.close()
