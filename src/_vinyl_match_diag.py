# -*- coding: utf-8 -*-
r"""Can we safely match the page-9 vinyl callout to a UDEF SKU by DIMENSIONS?
Page 9 says: "MILWAUKEE LOGO WHITE 425 W X 190 H".
Tim uses VINYL76 = "Milwaukee 50cm Base Shelf Vinyl White Milwaukee Logo 425 x 190mm" @ £0.85.

Question: is "425 x 190" (or "MILWAUKEE LOGO") DISTINCTIVE enough in UDEF to match ONE SKU,
or does it match many (in which case we must NOT auto-price — flag instead)?
READ ONLY.
  C:\ClaudeVision\.venv\Scripts\python.exe _vinyl_match_diag.py
"""
import config
cn = config.get_connection(timeout=30)
cur = cn.cursor()

def show(label, where, *params):
    print(f"\n=== {label} ===")
    try:
        cur.execute(
            "SELECT [Part code],[Description],[System cost per],[Supplier name] "
            "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING WHERE " + where, *params)
        rows = cur.fetchall()
        if not rows:
            print("  (none)")
        for r in rows[:15]:
            print("  " + " | ".join(str(x) for x in r))
        print(f"  --> {len(rows)} row(s)")
    except Exception as e:
        print(f"  failed: {e}")

# 1. How many UDEF vinyls mention 425 x 190 (the drawing's dimensions)?
show("vinyl with 425 x 190", "[Description] LIKE '%425%190%' AND ([Part code] LIKE 'VINYL%' OR [Description] LIKE '%VINYL%')")
# 2. How many mention MILWAUKEE + LOGO?
show("MILWAUKEE LOGO vinyls", "[Description] LIKE '%MILWAUKEE%' AND [Description] LIKE '%LOGO%'")
# 3. How many mention 425 x 190 at all (any product)?
show("any product 425 x 190", "[Description] LIKE '%425%190%'")
# 4. The kick plate — page 9 also implies a kick plate vinyl (VINYL03). What dims?
show("VINYL03 / kick plate", "[Part code] = 'VINYL03' OR ([Description] LIKE '%KICK%' AND [Description] LIKE '%VINYL%')")

cn.close()
