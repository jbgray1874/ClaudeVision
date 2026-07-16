# -*- coding: utf-8 -*-
r"""Diagnose issue #3: why recognised bought-in items land at the 0.42 placeholder
instead of real historical prices (adhesive cable clip ~0.10, 50cm loom ~24.15).

Read-only. Tests the pricing chain against the LIVE DB for the actual 1282 bought-in
items, and reports exactly which lookup fires (or fails) for each.

  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _pricing_diagnose.py
"""
import sys, os
sys.path.insert(0, os.getcwd()); sys.path.insert(0, r"C:\ClaudeVision\src")

# The real bought-in items from the 1282 run, by description (as the engine sees them)
ITEMS = [
    {"part_number": "ELECTRICS", "description": "50cm LOOM LIGHTING ELECTRICS"},
    {"part_number": "", "description": "Adhesive Cable"},
    {"part_number": "", "description": "Junction box"},
    {"part_number": "", "description": "Earth strap"},
    {"part_number": "", "description": "5M mains cable, black"},
    {"part_number": "", "description": "GU10 LED downlight"},
    {"part_number": "", "description": "Foam Tape"},
    {"part_number": "FIXING5", "description": "4.0x10mm DOME RIVET"},
]

print("=" * 70)
print("STEP 1 — does PricingService._get_historical_rag find prices directly?")
print("=" * 70)
try:
    from pricing_service import PricingService
    ps = PricingService()
    for it in ITEMS:
        try:
            rag = ps._get_historical_rag(it)
            if rag:
                print(f"  '{it['description']}'")
                print(f"     RAG -> GBP {rag.get('unit_price_gbp')}  [{rag.get('source')}]")
                prov = str(rag.get('provenance') or '')[:90]
                print(f"     {prov}")
            else:
                print(f"  '{it['description']}'  -> RAG returned None (no match >= 0.12 overlap)")
        except Exception as e:
            print(f"  '{it['description']}'  -> RAG ERROR: {e}")
except Exception as e:
    print(f"  could not init PricingService: {e}")

print()
print("=" * 70)
print("STEP 2 — full anchor-price chain: which source wins for each item?")
print("=" * 70)
try:
    for it in ITEMS:
        try:
            res = ps._select_anchor_price_source(it)
            print(f"  '{it['description']}'")
            print(f"     source={res.get('source')}  price=GBP {res.get('unit_price_gbp')}  conf={res.get('confidence')}")
        except Exception as e:
            print(f"  '{it['description']}'  -> chain ERROR: {e}")
except Exception:
    pass

print()
print("=" * 70)
print("STEP 3 — what does _resolve_part_system_cost (the bay catalogue path) return?")
print("=" * 70)
try:
    from estimator import _resolve_part_system_cost
    for it in ITEMS:
        try:
            sc = _resolve_part_system_cost(it)
            print(f"  '{it['description']}'  -> applied_unit_cost={sc.get('applied_unit_cost')}  matched={sc.get('matched_part_code')}")
        except Exception as e:
            print(f"  '{it['description']}'  -> ERROR: {e}")
except Exception as e:
    print(f"  could not import _resolve_part_system_cost: {e}")

print()
print("=" * 70)
print("STEP 4 — confirm the historical data actually HAS these (raw SQL probe)")
print("=" * 70)
try:
    # Reuse the PricingService's own DB connection (don't guess the conn string)
    cn = ps._get_db_connection()
    cur = cn.cursor()
    for term in ["ADHESIVE CABLE", "LOOM", "EARTH STRAP", "JUNCTION BOX", "DOWNLIGHT"]:
        cur.execute("""
            SELECT TOP 3 line_description, unit_price_gbp
            FROM dbo.historical_quote_material_line
            WHERE unit_price_gbp > 0 AND UPPER(line_description) LIKE '%' + ? + '%'
            ORDER BY unit_price_gbp
        """, term)
        rows = cur.fetchall()
        print(f"  '{term}':")
        if rows:
            for r in rows:
                print(f"      GBP {r[1]:>8.2f}  {str(r[0])[:60]}")
        else:
            print("      (none found in historical_quote_material_line)")
    cn.close()
except Exception as e:
    print(f"  raw SQL probe failed: {e}")
