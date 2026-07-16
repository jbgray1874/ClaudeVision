"""
Read-only. For each of the six note-scanned electrical items in 1282, search all
three price sources and show what (if anything) matches, with the price.

Sources, in trust order:
  1. dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING   (ERP parts master; 'System cost per' = PMA_USAGE_2)
  2. AIEstimating.vCurrentBoughtIn         (curated catalogue; unit_price_gbp)
  3. AIEstimating.vCurrentCommercialRate   (versioned rates; value_gbp)

No writes. Read-only SELECTs with LIKE matching on description.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _udef_electrical_check.py
"""
import pyodbc

CONN = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.200;DATABASE=SDILive;UID=AIBot;PWD=AIAgentPW2026;"
    "TrustServerCertificate=yes"
)

# The six note-scanned items from 1282, with search terms likely to hit ERP/catalogue descriptions.
ITEMS = [
    ("Junction box",         ["%junction box%", "%junction%box%", "%j-box%", "%jbox%"]),
    ("5m mains cable black",  ["%mains cable%", "%mains%cable%", "%3 core%cable%", "%flex%black%"]),
    ("Earth strap",          ["%earth strap%", "%earth%strap%", "%earth lead%", "%earth bond%"]),
    ("LED link light",       ["%link light%", "%led link%", "%led%link%", "%linkable%led%"]),
    ("GU10 LED downlight",   ["%gu10%", "%downlight%", "%down light%"]),
    ("50cm lighting loom",   ["%loom%", "%lighting loom%", "%50cm%loom%", "%harness%"]),
]

def q(cur, sql, params):
    try:
        return cur.execute(sql, params).fetchall()
    except Exception as e:
        return [("ERR", str(e))]

def main():
    conn = pyodbc.connect(CONN)
    cur = conn.cursor()

    for label, patterns in ITEMS:
        print("=" * 100)
        print(f"ITEM: {label}")
        print("=" * 100)
        any_hit = False

        for pat in patterns:
            # 1. UDEF (ERP parts master)
            udef = q(cur, """
                SELECT TOP 5 [Part code], [Part rev], [Description], [UOM],
                       [System cost per], [Supplier name]
                FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                WHERE [Description] LIKE ?
            """, [pat])
            for r in udef:
                if r and r[0] == "ERR":
                    print(f"  [UDEF] ERROR: {r[1]}")
                    break
                any_hit = True
                print(f"  [UDEF    ] {pat:<22} code={r[0]} rev={r[1]} "
                      f"'{str(r[2])[:40]}' UOM={r[3]} SYSCOST={r[4]} sup={r[5]}")

            # 2. vCurrentBoughtIn (curated catalogue)
            bi = q(cur, """
                SELECT TOP 5 supplier_sku, description, category, uom,
                       unit_price_gbp, supplier_name, source
                FROM AIEstimating.vCurrentBoughtIn
                WHERE description LIKE ?
            """, [pat])
            for r in bi:
                if r and r[0] == "ERR":
                    print(f"  [BoughtIn] ERROR: {r[1]}")
                    break
                any_hit = True
                print(f"  [BoughtIn] {pat:<22} sku={r[0]} '{str(r[1])[:36]}' "
                      f"cat={r[2]} GBP{r[4]} src={r[6]}")

        # 3. vCurrentCommercialRate — check electrical-ish rate keys once per item
        if any(t in label.lower() for t in ["loom", "light", "led", "cable"]):
            cr = q(cur, """
                SELECT TOP 10 rate_key, value_gbp, uom, basis, source
                FROM AIEstimating.vCurrentCommercialRate
                WHERE rate_key LIKE '%loom%' OR rate_key LIKE '%light%'
                   OR rate_key LIKE '%led%'  OR rate_key LIKE '%elec%'
            """, [])
            for r in cr:
                if r and r[0] == "ERR":
                    print(f"  [CommRate] ERROR: {r[1]}")
                    break
                any_hit = True
                print(f"  [CommRate] key={r[0]} GBP{r[1]} uom={r[2]} basis={r[3]}")

        if not any_hit:
            print("  (no match in any source)")
        print()

    conn.close()
    print("Done. Items with a UDEF or BoughtIn hit have a real price we should use instead of the LLM estimate.")
    print("Items with NO hit anywhere -> LLM/web estimate is genuinely all we have (flag as unverified).")

if __name__ == "__main__":
    main()
