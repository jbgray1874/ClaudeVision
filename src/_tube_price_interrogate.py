# -*- coding: utf-8 -*-
r"""READ-ONLY DB interrogation for genuine tube/section prices.
Checks, in order: (1) UDEF (dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING) — where loom/fixings price from,
(2) estimating_tube_rate, (3) BoughtInCatalogue. Shows what tube prices genuinely exist so we
wire the section path to a real source instead of the £0.80/kg fallback.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _tube_price_interrogate.py
"""
import pyodbc, config

def conn():
    return config.get_connection(timeout=30)

cn = conn(); cur = cn.cursor()

def run(title, sql):
    print(f"\n{'='*70}\n{title}\n{'='*70}")
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if not rows:
            print("   (no rows)")
            return
        print("   " + " | ".join(cols))
        for r in rows[:30]:
            print("   " + " | ".join(str(v)[:28] for v in r))
        print(f"   ... {len(rows)} row(s)")
    except Exception as e:
        print("   ERROR:", str(e)[:200])

# 1. UDEF — tube/section parts (by description keyword + SLOTTEDTUBE code + Preferred supplier)
run("1. UDEF — TUBE / SLOTTEDTUBE / section parts",
    """SELECT TOP 30 [Part code],[Description],[Supplier name],[System cost per],[UOM]
       FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
       WHERE [Description] LIKE '%TUBE%' OR [Part code] LIKE 'SLOTTEDTUBE%'
          OR [Description] LIKE '%30 x 60%' OR [Description] LIKE '%60 x 30%'
          OR [Description] LIKE '%RHS%' OR [Description] LIKE '%SHS%'
          OR [Supplier name] LIKE '%PREFER%'
       ORDER BY [Part code]""")

# 2. estimating_tube_rate — the named tube-rate table
run("2. estimating_tube_rate (try both schemas)",
    "SELECT TOP 30 * FROM AIEstimating.estimating_tube_rate")
run("2b. estimating_tube_rate (dbo)",
    "SELECT TOP 30 * FROM dbo.estimating_tube_rate")

# 3. BoughtInCatalogue — tube rows
run("3. AIEstimating.BoughtInCatalogue — tube rows",
    """SELECT TOP 30 * FROM AIEstimating.BoughtInCatalogue
       WHERE [Description] LIKE '%TUBE%' OR [PartCode] LIKE '%TUBE%' OR [Description] LIKE '%30 x 60%'""")

# 4. what does 1282's actual SLOTTEDTUBE01/02 resolve to anywhere?
run("4. ANY table row mentioning SLOTTEDTUBE",
    """SELECT TOP 20 [Part code] AS code,[Description] AS descr,[System cost per] AS cost
       FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING WHERE [Part code] LIKE '%SLOTTED%' OR [Description] LIKE '%SLOTTED%'""")

cur.close(); cn.close()
print("\nDONE.")
