r"""
patch_topN_determinism.py — make the TOP-1 pricing queries deterministic.

ROOT CAUSE (measured, not guessed): four `SELECT TOP 1 ... ORDER BY <non-unique>` queries in
pricing_service.py. When rows tie on the ORDER BY columns (guaranteed by the known dup-SKU
catalogue data — same part at two prices/dates), SQL Server returns an ARBITRARY tied row, and
which one can differ between executions. The winning bought-in PRICE flips run-to-run -> bought-in
material total moves -> unit cost drifts (£189.01 -> £187.95 -> £187.35). Fabricated material and
labour stay put (they don't go through this tie). This is the classic non-deterministic TOP-1 bug.

FIX: append a deterministic tiebreaker to each ORDER BY implementing JG's policy
'most reliable source first, then lowest price', ending in a UNIQUE key so ties ALWAYS resolve the
same way:
  - bought_in_parts (561):      ..., effective_date DESC, unit_price_gbp ASC, bought_in_id ASC
  - UDEF (171):                 ..., [System cost per] DESC (kept), then [Part code] ASC, [Supplier name] ASC
  - supplier_catalog_url (598): ..., sort_order ASC (kept), then unit_price_gbp ASC, catalog_url_id ASC
  - labour_rates (736):         ..., effective_date DESC (kept), then hourly_rate_gbp ASC, labour_rate_id ASC

Each edit appends to the EXISTING ORDER BY tail (exact-string match). No logic change to WHICH price
is 'best' by the intended sort — only ties now resolve identically. Match-or-refuse, AST-validated,
timestamped backup. SQL kept as plain strings (no decorative comments).
"""
import ast, re, shutil, datetime, os

T = r"C:\ClaudeVision\src\pricing_service.py"

# Each entry: the EXACT current ORDER BY tail (unique in file) -> replacement with tiebreaker.
# Using the last line of each ORDER BY as the anchor (must be unique).
EDITS = [
    # 561 bought_in_parts — anchor 'effective_date DESC' inside the bought_in block.
    # Make it unique by including the CASE line above it.
    (
        "bought_in_parts price (561)",
        "                CASE WHEN UPPER(LTRIM(RTRIM(part_code))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,\n                effective_date DESC",
        "                CASE WHEN UPPER(LTRIM(RTRIM(part_code))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,\n                effective_date DESC,\n                unit_price_gbp ASC,\n                bought_in_id ASC",
    ),
    # 171 UDEF — anchor 'u.[System cost per] DESC' (the ORDER BY tail).
    (
        "UDEF parts price (171)",
        "                CASE WHEN u.[Part code] = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,\n                u.[System cost per] DESC",
        "                CASE WHEN u.[Part code] = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,\n                u.[System cost per] DESC,\n                u.[Part code] ASC,\n                u.[Supplier name] ASC",
    ),
    # 598 supplier_catalog_url — anchor 'sort_order ASC'
    (
        "supplier_catalog_url (598)",
        "                ORDER BY sort_order ASC",
        "                ORDER BY sort_order ASC, unit_price_gbp ASC, catalog_url_id ASC",
    ),
    # 736 labour_rates — anchor 'ORDER BY effective_date DESC' (distinguish from bought_in's which
    # has the CASE prefix, so this bare form is unique to labour_rates).
    (
        "labour_rates (736)",
        "                ORDER BY effective_date DESC",
        "                ORDER BY effective_date DESC, hourly_rate_gbp ASC, labour_rate_id ASC",
    ),
]

def apply():
    src = open(T, encoding="utf-8").read()

    # Pre-check every anchor is present exactly once.
    for name, old, _ in EDITS:
        n = src.count(old)
        if n != 1:
            print(f"REFUSE at '{name}': anchor found {n} times (need exactly 1). No changes written.")
            print("  anchor was:\n    " + old.replace('\n', '\n    '))
            return False

    new = src
    for name, old, rep in EDITS:
        new = new.replace(old, rep, 1)

    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: patched file fails AST parse: {e}. No changes written.")
        return False

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_topndet_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: 4 TOP-1 queries now deterministic (tiebreaker appended). Backup: {os.path.basename(bak)}")
    print("Policy: exact-match -> newest -> lowest price -> unique PK. Ties now resolve identically.")
    print("Confirm with 2 runs: identical unit cost twice = drift pinned.")
    return True

if __name__ == "__main__":
    apply()
