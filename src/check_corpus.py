"""
check_corpus.py — historical RAG corpus health check.

Reads the live SDILive DB through the same connection PricingService uses and
reports:
  1. corpus size + duplicate detection (COUNT vs DISTINCT quote_key)
  2. width of every code/description column across historical_quote_* tables
     (so we catch any column still narrow enough to truncate the raw labels)
  3. whether the previously-rejected jobs (Fragrance lightsheet, Rose veneer)
     actually loaded
  4. job count by client

No web/LLM calls — read-only, costs nothing. Run:
    python check_corpus.py
"""

from __future__ import annotations

import re

from pricing_service import PricingService


def q(cur, sql, params=None):
    cur.execute(sql, params or [])
    return cur.fetchall()


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    with PricingService() as svc:
        cur = svc.conn.cursor()

        # ── 1. size + duplicates ─────────────────────────────────────────────
        section("1. CORPUS SIZE + DUPLICATE CHECK")
        try:
            total, distinct = q(
                cur,
                "SELECT COUNT(*), COUNT(DISTINCT quote_key) "
                "FROM dbo.historical_quote_header",
            )[0]
            print(f"  header rows         : {total}")
            print(f"  distinct quote_key  : {distinct}")
            if total == distinct:
                print("  -> OK: no duplicate jobs (loader is idempotent)")
            else:
                print(f"  -> WARNING: {total - distinct} duplicate header rows — "
                      "the reload added dupes; RAG will double-count. Needs a dedupe.")
        except Exception as exc:
            print(f"  ERROR: {exc!r}")

        # ── 2. code/description column widths across historical tables ───────
        section("2. CODE-COLUMN WIDTHS  (any < 255 can still truncate raw labels)")
        try:
            rows = q(cur, """
                SELECT s.name AS sch, t.name AS tbl, c.name AS col,
                       CASE WHEN c.max_length = -1 THEN -1 ELSE c.max_length/2 END AS nchar
                FROM sys.columns c
                JOIN sys.tables   t  ON c.object_id    = t.object_id
                JOIN sys.schemas  s  ON t.schema_id    = s.schema_id
                JOIN sys.types    ty ON c.user_type_id = ty.user_type_id
                WHERE t.name LIKE 'historical_quote_%'
                  AND ty.name IN ('nvarchar', 'varchar')
                  AND (c.name LIKE '%code%' OR c.name LIKE '%description%'
                       OR c.name LIKE '%department%' OR c.name = 'revision')
                ORDER BY s.name, t.name, c.name
            """)
            narrow = 0  # count only dbo — that is the schema the loader writes to
            for sch, tbl, col, n in rows:
                width = "MAX" if n == -1 else str(n)
                flag = ""
                if n != -1 and n < 255:
                    flag = "   <-- still narrow"
                    if sch == "dbo":
                        narrow += 1
                        flag += " (dbo: loader target)"
                print(f"  {sch}.{tbl}.{col:22} nvarchar({width}){flag}")
            print(f"\n  {'OK: all dbo code/description columns >= 255' if narrow == 0 else f'{narrow} dbo column(s) under 255 — widen before reloading'}")
        except Exception as exc:
            print(f"  ERROR: {exc!r}")

        # ── 3. previously-rejected jobs present? ─────────────────────────────
        section("3. PREVIOUSLY-REJECTED JOBS LOADED?")
        checks = [
            ("Fragrance lightsheet (10919)", "historical_quote_labour_line",
             ["operation_code", "department_code"], "539 x 249 x 6mm%"),
            ("Rose veneer (11657/12300)", "historical_quote_operation",
             ["operation_code", "department_code"], "3050 x 1220 x 0.6mm White Oak%"),
        ]
        for label, tbl, columns, like in checks:
            found = 0
            for col in columns:
                try:
                    found += q(cur, f"SELECT COUNT(*) FROM dbo.{tbl} WHERE {col} LIKE ?",
                               [like])[0][0]
                except Exception:
                    pass
            print(f"  {label:32} {found} rows  -> {'LOADED' if found else 'STILL MISSING'}")

        # ── 4. job count by client ───────────────────────────────────────────
        section("4. JOBS BY CLIENT")
        try:
            cols = [r[0] for r in q(
                cur,
                "SELECT name FROM sys.columns "
                "WHERE object_id = OBJECT_ID('dbo.historical_quote_header')",
            )]
            client_col = next((c for c in cols if re.search(r"client|customer", c, re.I)), None)
            path_col = next((c for c in cols if re.search(r"path|source|workbook|file", c, re.I)), None)

            if client_col:
                rows = q(cur, f"SELECT [{client_col}], COUNT(*) FROM dbo.historical_quote_header "
                              f"GROUP BY [{client_col}] ORDER BY COUNT(*) DESC")
                print(f"  (grouped by header column '{client_col}')")
                for name, n in rows[:25]:
                    print(f"    {str(name or '(blank)')[:40]:40} {n}")
            elif path_col:
                # derive client from the parent folder of the workbook path
                rows = q(cur, f"SELECT [{path_col}] FROM dbo.historical_quote_header")
                from collections import Counter
                c = Counter()
                for (p,) in rows:
                    parts = re.split(r"[\\/]", str(p or ""))
                    client = parts[-2] if len(parts) >= 2 else "(unknown)"
                    c[client] += 1
                print(f"  (derived from folder in header column '{path_col}')")
                for name, n in c.most_common(25):
                    print(f"    {str(name)[:40]:40} {n}")
            else:
                print("  No client/customer or path column found in historical_quote_header.")
                print("  Available columns: " + ", ".join(cols))
                print("  Tell me which column carries the client and I'll wire the breakdown.")
        except Exception as exc:
            print(f"  ERROR: {exc!r}")

    print("\nDone.")


if __name__ == "__main__":
    main()
