r"""READ-ONLY. My probe used the wrong ODBC driver name. The app connects fine — find HOW
pricing_service connects (the exact connection string / helper) and reuse it to read the tiebreaker
columns. Two parts:
  1) grep the real connection method (pyodbc.connect(...), driver name, server, trusted vs sql auth).
  2) reuse it to list columns + PK for the 4 tables so the ORDER BY tiebreaker uses a real column.
No edits."""
import os, re

SRC=r"C:\ClaudeVision\src"
print("="*66); print("1 — how the app connects (real connection string / driver)"); print("="*66)
found_conn=None
for fn in ("pricing_service.py","config.py","db.py","database.py","live_enquiry_collector.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(pyodbc\.connect|DRIVER=|SERVER=|Trusted_Connection|autocommit|def .*conn|CONN_STR|connection_string|DATABASE=)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:110]}")

# 2) try to actually connect using whatever pricing_service exposes
print("\n"+"="*66); print("2 — read columns via the app's own connection"); print("="*66)
import importlib.util, sys
sys.path.insert(0, SRC)
cn=None
# try common entry points the app might expose
for modname, attr in [("pricing_service","_connect"),("pricing_service","get_connection"),
                      ("pricing_service","connect"),("config","get_connection"),
                      ("config","SDILIVE_CONN")]:
    try:
        m=importlib.import_module(modname)
        obj=getattr(m, attr, None)
        if obj is None: 
            continue
        cn = obj() if callable(obj) else __import__("pyodbc").connect(obj)
        print(f"  connected via {modname}.{attr}")
        break
    except Exception as e:
        print(f"  {modname}.{attr} -> {type(e).__name__}: {str(e)[:60]}")

if cn is None:
    # last resort: enumerate installed drivers so I can pick the right one
    try:
        import pyodbc
        print("\n  installed ODBC drivers on this machine:")
        for d in pyodbc.drivers():
            print("    -", d)
        print("\n  -> paste these; I'll set the correct DRIVER= and retry.")
    except Exception as e:
        print("  couldn't list drivers:", e)
    raise SystemExit

cur=cn.cursor()
for t in ["UDEF_PARTS_TABLE_FOR_ESTIMATING","bought_in_parts","estimating_supplier_catalog_url","labour_rates"]:
    print("\n  "+"-"*50); print("  "+t); print("  "+"-"*50)
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", t)
        for name,typ in cur.fetchall(): print(f"    {name:<32}{typ}")
        cur.execute("""SELECT c.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c ON tc.CONSTRAINT_NAME=c.CONSTRAINT_NAME
            WHERE tc.TABLE_NAME=? AND tc.CONSTRAINT_TYPE='PRIMARY KEY'""", t)
        pk=[r[0] for r in cur.fetchall()]
        print(f"    --> PK: {pk if pk else '(none)'}")
    except Exception as e:
        print(f"    (couldn't read: {e})")
cn.close()
