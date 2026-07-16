# -*- coding: utf-8 -*-
r"""Where does the loom's £539.42 come from? The desc-LIKE probe found NO match,
yet the chain returned UDEF £539.42. Test the part-code branch: does 'ELECTRICS'
match a UDEF [Part code]? Read-only.

  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _udef_loom_probe.py
"""
import sys, os
sys.path.insert(0, os.getcwd()); sys.path.insert(0, r"C:\ClaudeVision\src")
from pricing_service import PricingService

ps = PricingService()
cn = ps._get_db_connection()
cur = cn.cursor()

print("=== UDEF rows where [Part code] = 'ELECTRICS' (exact) ===")
cur.execute("""
    SELECT u.[Part code], u.[Description], CAST(u.[System cost per] AS decimal(18,4))
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE LTRIM(RTRIM(u.[Part code])) = 'ELECTRICS'
""")
for r in cur.fetchall():
    print(f"   code='{r[0]}'  GBP {float(r[2]):>9.2f}  {str(r[1])[:55]}")

print("\n=== UDEF rows where [Part code] LIKE '%ELECTRICS%' ===")
cur.execute("""
    SELECT TOP 10 u.[Part code], u.[Description], CAST(u.[System cost per] AS decimal(18,4))
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE UPPER(u.[Part code]) LIKE '%ELECTRICS%'
    ORDER BY u.[System cost per] DESC
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"   code='{r[0]}'  GBP {float(r[2]):>9.2f}  {str(r[1])[:55]}")
else:
    print("   (none)")

print("\n=== exactly what _get_udef_anchor returns for the loom part ===")
loom = {"part_number": "ELECTRICS", "description": "50cm LOOM LIGHTING ELECTRICS"}
res = ps._get_udef_anchor(loom)
if res:
    print(f"   price=GBP {res.get('unit_price_gbp')}")
    print(f"   provenance={res.get('provenance')}")
else:
    print("   _get_udef_anchor returned None")

print("\n=== and what does RAG find for the loom if we lower the bar? ===")
print("   (RAG returned None at 0.12 overlap earlier; show top LIKE candidates)")
cur.execute("""
    SELECT TOP 8 line_description, unit_price_gbp
    FROM dbo.historical_quote_material_line
    WHERE unit_price_gbp > 0 AND UPPER(line_description) LIKE '%LOOM%'
    ORDER BY unit_price_gbp
""")
for r in cur.fetchall():
    print(f"   GBP {float(r[1]):>8.2f}  {str(r[0])[:55]}")

cn.close()
