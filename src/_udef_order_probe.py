# -*- coding: utf-8 -*-
r"""Confirm the UDEF ordering bug + test the 'closest description' fix.
Read-only. Shows, for the loom and foam tape, what UDEF returns under:
  (a) current ordering: System cost per DESC  (the bug -> dearest match)
  (b) proposed: shortest description first     (closest/tightest match)
so we can SEE the fix produces a better price before changing pricing code.

  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _udef_order_probe.py
"""
import sys, os
sys.path.insert(0, os.getcwd()); sys.path.insert(0, r"C:\ClaudeVision\src")
from pricing_service import PricingService

ps = PricingService()
cn = ps._get_db_connection()
cur = cn.cursor()

TESTS = ["50cm LOOM LIGHTING ELECTRICS", "Foam Tape", "Adhesive Cable"]

for desc in TESTS:
    print("=" * 66)
    print(f"DESC = '{desc}'")
    print("=" * 66)

    # (a) current ordering — System cost per DESC (the bug)
    cur.execute(
        """
        SELECT TOP 5 u.[Part code], u.[Description],
               CAST(u.[System cost per] AS decimal(18,4)), LEN(u.[Description])
        FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
        WHERE LEN(LTRIM(RTRIM(?))) >= 8 AND u.[Description] LIKE '%' + LTRIM(RTRIM(?)) + '%'
        ORDER BY u.[System cost per] DESC
        """, desc, desc)
    rows = cur.fetchall()
    print("  (a) CURRENT  [price DESC] -> top pick is dearest:")
    if rows:
        for r in rows[:5]:
            print(f"        GBP {float(r[2]):>9.2f}  len={r[3]:>3}  {str(r[1])[:50]}")
    else:
        print("        (no LIKE matches)")

    # (b) proposed — shortest description first (tightest match)
    cur.execute(
        """
        SELECT TOP 5 u.[Part code], u.[Description],
               CAST(u.[System cost per] AS decimal(18,4)), LEN(u.[Description])
        FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
        WHERE LEN(LTRIM(RTRIM(?))) >= 8 AND u.[Description] LIKE '%' + LTRIM(RTRIM(?)) + '%'
        ORDER BY LEN(u.[Description]) ASC, u.[System cost per] ASC
        """, desc, desc)
    rows2 = cur.fetchall()
    print("  (b) PROPOSED [shortest desc] -> top pick is tightest match:")
    if rows2:
        for r in rows2[:5]:
            print(f"        GBP {float(r[2]):>9.2f}  len={r[3]:>3}  {str(r[1])[:50]}")
    else:
        print("        (no LIKE matches)")
    print()

cn.close()
print("Compare (a) vs (b) top rows: does shortest-description give a saner price?")
