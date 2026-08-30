import config, pyodbc

# Find however config exposes the DB connection — print what is available, then use it.
cands = [a for a in dir(config) if any(k in a.upper() for k in ("CONN","SQL","ODBC","DSN","DATABASE","SDILIVE"))]
print("config DB-ish attributes:", cands)

cs = None
for a in ("SQL_CONNECTION_STRING","CONNECTION_STRING","SQL_CONN_STR","ODBC_CONNECTION_STRING",
          "SQLALCHEMY_DATABASE_URI","DB_CONNECTION_STRING","SDILIVE_CONNECTION_STRING"):
    if hasattr(config, a):
        cs = getattr(config, a); print("using", a); break

# Some configs expose a helper instead of a raw string
if cs is None:
    for fn in ("get_connection","connect","get_sql_connection","sql_connection","get_conn"):
        if hasattr(config, fn):
            print("using config.%s()" % fn)
            cn = getattr(config, fn)()
            break
    else:
        raise SystemExit("No connection string or helper found — check the printed attributes above.")
else:
    cn = pyodbc.connect(cs, timeout=10)

cur = cn.cursor()
print("\n=== UDEF columns ===")
cur.execute("SELECT TOP 1 * FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING")
print([d[0] for d in cur.description])

print("\n=== rows LIKE ELECTRIC / LOOM ===")
cur.execute("""SELECT TOP 10 [Part code],[Description],[System cost per],[Supplier name]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [Part code] LIKE '%ELEC%' OR [Description] LIKE '%ELECTRIC%' OR [Description] LIKE '%LOOM%'""")
for r in cur.fetchall():
    print("  code=%r desc=%r cost=%s supplier=%r" % (r[0], str(r[1])[:45], r[2], r[3]))

print("\n=== rows LIKE FIXING5 ===")
cur.execute("""SELECT TOP 5 [Part code],[Description],[System cost per],[Supplier name]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [Part code] LIKE '%FIXING5%' OR [Part code] LIKE '%FIXING 5%'""")
for r in cur.fetchall():
    print("  code=%r desc=%r cost=%s supplier=%r" % (r[0], str(r[1])[:45], r[2], r[3]))
