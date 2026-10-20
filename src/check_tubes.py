import config
c = config.get_connection()
cur = c.cursor()

print("=== vCurrentBoughtIn — tube-like entries ===")
cur.execute("""
    SELECT TOP 30 supplier_sku, description, unit_price_gbp, uom, source
    FROM AIEstimating.vCurrentBoughtIn
    WHERE UPPER(description) LIKE '%TUBE%'
       OR UPPER(description) LIKE '%RHS%'
       OR UPPER(description) LIKE '%SHS%'
       OR UPPER(description) LIKE '%BOX SECTION%'
       OR UPPER(description) LIKE '%60%30%'
       OR UPPER(description) LIKE '%30%30%'
    ORDER BY description
""")
rows = cur.fetchall()
if not rows:
    print("  (none found)")
for r in rows:
    print(f"  sku={r[0]!s:24} | {str(r[1])[:45]:45} | GBP {r[2]} | {r[3]} | src={r[4]}")

print()
print("=== Direct hit test: do the Trestle tube part numbers match? ===")
for pn in ("11087-17-05M","11087-17-08M","11087-17-10M","11087-17-11M"):
    cur.execute("""
        SELECT supplier_sku, description, unit_price_gbp
        FROM AIEstimating.vCurrentBoughtIn
        WHERE UPPER(LTRIM(RTRIM(supplier_sku))) = UPPER(LTRIM(RTRIM(?)))
    """, [pn])
    hit = cur.fetchone()
    print(f"  {pn:16} -> {'HIT '+str(hit[2]) if hit else 'no match'}")
