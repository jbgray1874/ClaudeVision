r"""
udef_supplier_profile.py — which suppliers is SDI actually buying from, and what for.

WHY THIS EXISTS. The plan for closing the bought-in pricing gap is "APIs where they exist,
account price files where they do not" — and until now nobody has known which suppliers those
are. 11650 named four (Elite Sourcing, Essentra, Hafele, Yiree) because those four happened to
appear on one cabinet. That is a sample of one job, and the effort of an integration should be
aimed by the whole catalogue, not by whichever pack was open this week.

So this counts. It reads UDEF read-only and answers three questions in one pass:

  WHO      how many priced lines each supplier holds, and what they are worth
  WHAT     the product families they supply, from the leading token of the part code
  KEYS     how many of their lines carry a manufacturer reference we could query an API with

The third is the one that decides API-versus-email, and it cannot be guessed. A supplier whose
descriptions carry article numbers can be integrated the moment somebody publishes an endpoint.
One whose lines are free text can only ever be a price file, however good their API is, because
nothing on our side would know what to ask for.

Read-only. No writes, no schema changes, no credentials printed.

    C:\ClaudeVision\.venv\Scripts\python.exe tools\pricing\udef_supplier_profile.py
    ... --top 40 --csv C:\ClaudeVision\work\udef_suppliers.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _rows(cur):
    """Every priced line, with the three fields this needs. TOP-less on purpose: a sample
    would rank suppliers by whatever the index happened to return first."""
    cur.execute(
        "SELECT [Part code], [Description], [Supplier name], "
        "       CAST([System cost per] AS decimal(18,4)) "
        "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
        "WHERE [System cost per] > 0")
    for code, desc, supplier, cost in cur.fetchall():
        yield (str(code or "").strip(), str(desc or "").strip(),
               (str(supplier or "").strip() or "(no supplier recorded)"), float(cost or 0))


def _family(part_code: str) -> str:
    """The catalogue family a code belongs to — FIXING, VINYL, ELECTRICS, SUBPLAS…

    The leading alpha run, which is how bought_in_pricing already splits these. Keyed on the
    code rather than the description because a description is prose and a code is a decision
    somebody made when the line was created.
    """
    head = ""
    for ch in part_code.upper():
        if ch.isalpha():
            head += ch
        else:
            break
    return head or "(numeric code)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25, help="suppliers to print (default 25)")
    ap.add_argument("--csv", help="write the full ranking here")
    args = ap.parse_args()

    import config
    import pyodbc
    from supplier_reference import find_references

    cn = pyodbc.connect(config.SQL_CONNECTION_STRING, timeout=30)
    try:
        cur = cn.cursor()
        lines = defaultdict(int)
        spend = defaultdict(float)
        with_ref = defaultdict(int)
        families = defaultdict(lambda: defaultdict(int))
        examples = defaultdict(list)
        total = 0

        for code, desc, supplier, cost in _rows(cur):
            total += 1
            lines[supplier] += 1
            spend[supplier] += cost
            families[supplier][_family(code)] += 1
            # THE FIELD THAT DECIDES API OR EMAIL. A line whose description carries an article
            # number can be queried; one that is free text can only be a price file, because
            # nothing on our side would know what to ask for.
            refs = find_references(desc, code)
            if refs:
                with_ref[supplier] += 1
                if len(examples[supplier]) < 3:
                    examples[supplier].append(f"{code}: {refs[0]['reference']}")
    finally:
        try:
            cn.close()
        except Exception:
            pass

    ranked = sorted(lines, key=lambda s: (-lines[s], s))
    print(f"\n{total:,} priced line(s) across {len(ranked):,} supplier(s)\n")
    print(f"{'supplier':<38}{'lines':>7}{'avg £':>9}{'with ref':>10}  families")
    print("-" * 100)
    for s in ranked[:args.top]:
        n = lines[s]
        fam = ", ".join(f"{f}×{c}" for f, c in
                        sorted(families[s].items(), key=lambda kv: -kv[1])[:4])
        print(f"{s[:37]:<38}{n:>7}{spend[s]/n:>9.2f}"
              f"{with_ref[s]*100//n:>9}%  {fam}")

    print("\nHOW TO READ THE LAST TWO COLUMNS")
    print("  with ref  — the share of that supplier's lines carrying a manufacturer reference")
    print("              we could put in an API query. HIGH means an integration has something")
    print("              to ask for. LOW means a price file is the only route that can work,")
    print("              however good their API is.")
    print("  families  — what they actually sell, from the part code, so effort is aimed at")
    print("              the categories that recur rather than the ones one job happened to use.")
    for s in ranked[:5]:
        if examples[s]:
            print(f"\n  {s} — references found: {'; '.join(examples[s])}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["supplier", "priced_lines", "avg_cost_gbp", "lines_with_reference",
                        "reference_share_pct", "families"])
            for s in ranked:
                n = lines[s]
                w.writerow([s, n, round(spend[s] / n, 4), with_ref[s],
                            round(with_ref[s] * 100 / n, 1),
                            "; ".join(f"{f}={c}" for f, c in
                                      sorted(families[s].items(), key=lambda kv: -kv[1]))])
        print(f"\nfull ranking -> {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
