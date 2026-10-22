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
import datetime
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


NO_SUPPLIER = "(no supplier recorded)"


def _used_rows(cur):
    """What we have ACTUALLY BOUGHT, from the historical quotes.

    THE CATALOGUE IS NOT THE QUESTION. Ranking suppliers by how many lines they hold in UDEF
    ranks them by how much of their price list somebody once imported. A supplier with five
    thousand catalogue lines we have never bought from matters less than one with forty lines
    that appear on every job, and an integration aimed by catalogue size is aimed at the
    wrong supplier.

    dbo.historical_quote_material_line is what we really bought, across every quote this
    business has raised. Joined to the header for the date, because a supplier we stopped
    using in 2019 does not need an API however big they are.
    """
    cur.execute(
        "SELECT hml.supplier_name, hml.part_code, "
        "       CAST(COALESCE(hml.line_total_gbp, 0) AS decimal(18,4)), hh.quote_date "
        "FROM dbo.historical_quote_material_line hml "
        "LEFT JOIN dbo.historical_quote_header hh ON hml.quote_id = hh.quote_id "
        "WHERE hml.unit_price_gbp IS NOT NULL AND hml.unit_price_gbp > 0")
    for supplier, code, total, when in cur.fetchall():
        yield ((str(supplier or "").strip() or NO_SUPPLIER),
               str(code or "").strip().upper(), float(total or 0), when)


def recommend(used_lines: int, uncovered_spend: float, reference_share: float,
              months_since_last_use) -> str:
    """API, price file, or nothing — from what the numbers actually say.

    THREE FACTS DECIDE IT AND NONE OF THEM IS OPINION.

    Do we still buy from them. A supplier nobody has quoted in two years is not where an
    integration goes, whatever their catalogue looks like.

    Can we already price them. Spend on lines that ARE in UDEF today is spend we can
    reproduce; chasing that supplier buys nothing. The number that matters is the spend on
    lines we CANNOT price, because that is what an estimator is guessing at.

    Can an API be asked anything. A line carrying a manufacturer reference can be queried
    the moment somebody publishes an endpoint. A line of free text cannot, however good
    their API is, because nothing on our side would know what to ask for -- for those a
    price file is not the second-best route, it is the only route that can work.
    """
    if months_since_last_use is not None and months_since_last_use > 24:
        return "dormant — not bought from in 2 years"
    if used_lines < 5:
        return "too few lines to be worth integrating"
    if uncovered_spend < 250.0:
        return "already covered by UDEF"
    return ("API — references present to query with" if reference_share >= 0.5
            else "PRICE FILE — descriptions are free text, an API has nothing to ask for")


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
    # A SUPPLIER WE HAVE NEVER QUOTED CANNOT BE A PRIORITY. The first run printed 25 rows
    # of catalogue names with nothing bought against any of them -- alphabetical noise
    # occupying the whole screen where the answer should have been.
    ap.add_argument("--min-bought", type=int, default=1,
                    help="hide suppliers with fewer quoted lines than this (default 1; "
                         "0 shows catalogue-only names too)")
    args = ap.parse_args()

    import config
    from supplier_reference import find_references

    # config.get_connection() IS THE ENTRY POINT. This asked for config.SQL_CONNECTION_STRING,
    # which has never existed on any branch, and died on the estimating machine with
    # AttributeError before reading a row. Thirteen tracked scripts hand-roll their own
    # DRIVER={...};UID=...;PWD=... string instead of calling it, so there was no single
    # obvious answer to "how does a tool reach UDEF" to copy -- which is how a name that
    # exists nowhere got written down as if it did. One connector, called by everything.
    cn = config.get_connection()
    try:
        # THE WHOLE TABLE, NOT A PAGE OF IT. get_connection bounds query execution at
        # sql_query_timeout_s (30s) so a locked query cannot hang an estimate -- correct for
        # the engine, wrong here: this is one deliberate full scan by a person at a prompt,
        # and being cut off at 30 seconds would report a partial catalogue as the catalogue.
        # A supplier ranking that silently omits suppliers is worse than no ranking.
        try:
            cn.timeout = 0          # pyodbc: no query timeout
        except Exception:
            pass
        cur = cn.cursor()
        lines = defaultdict(int)
        spend = defaultdict(float)
        with_ref = defaultdict(int)
        families = defaultdict(lambda: defaultdict(int))
        examples = defaultdict(list)
        total = 0
        priceable_codes = set()

        for code, desc, supplier, cost in _rows(cur):
            total += 1
            lines[supplier] += 1
            spend[supplier] += cost
            families[supplier][_family(code)] += 1
            if code:
                priceable_codes.add(code.upper())
            # THE FIELD THAT DECIDES API OR EMAIL. A line whose description carries an article
            # number can be queried; one that is free text can only be a price file, because
            # nothing on our side would know what to ask for.
            refs = find_references(desc, code)
            if refs:
                with_ref[supplier] += 1
                if len(examples[supplier]) < 3:
                    examples[supplier].append(f"{code}: {refs[0]['reference']}")

        # ── what we actually bought, and what of it we cannot price ─────────────────
        used_lines = defaultdict(int)
        used_spend = defaultdict(float)
        uncovered_lines = defaultdict(int)
        uncovered_spend = defaultdict(float)
        last_used = {}
        try:
            for supplier, code, total_gbp, when in _used_rows(cur):
                used_lines[supplier] += 1
                used_spend[supplier] += total_gbp
                if not code or code not in priceable_codes:
                    # THE MONEY THAT MATTERS. Spend on a line already in UDEF is spend we can
                    # reproduce today; chasing that supplier buys nothing. Spend on a line we
                    # cannot price is what an estimator is guessing at.
                    uncovered_lines[supplier] += 1
                    uncovered_spend[supplier] += total_gbp
                if when is not None and (supplier not in last_used or when > last_used[supplier]):
                    last_used[supplier] = when
        except Exception as exc:                             # noqa: BLE001
            # SAID, NOT SWALLOWED. Without this half the report ranks by catalogue size
            # again, and a ranking that quietly answers a different question is worse than
            # one that fails.
            print(f"\n[warn] historical quote lines unavailable ({type(exc).__name__}: "
                  f"{exc}) — suppliers below are ranked by CATALOGUE SIZE, not by what we "
                  f"actually buy, and the recommendation column is not meaningful.",
                  flush=True)
    finally:
        try:
            cn.close()
        except Exception:
            pass

    def _months_since(when):
        if when is None:
            return None
        try:
            when = when.date() if hasattr(when, "date") else when
            return (datetime.date.today() - when).days / 30.44
        except Exception:                                    # noqa: BLE001
            return None

    # RANKED BY WHAT WE CANNOT PRICE, which is the question. Suppliers are listed by the
    # spend an estimator currently has to guess at, biggest first, because that is where an
    # integration or a price file changes an estimate. Catalogue size ranks by whose price
    # list somebody once imported.
    everyone = set(lines) | set(used_lines)
    ranked = sorted(everyone, key=lambda s: (-uncovered_spend.get(s, 0.0),
                                             -used_spend.get(s, 0.0), s))
    print(f"\n{total:,} catalogue line(s); {sum(used_lines.values()):,} line(s) actually "
          f"quoted, across {len(everyone):,} supplier(s)\n")

    # ── CAN THIS REPORT ANSWER THE QUESTION AT ALL? ────────────────────────────────────
    #
    # The first live run produced a ranking that was A-Z and a spend of £2,207,650,244,185.
    # Neither was a bug in the sort: every named supplier scored zero on both keys, so the
    # alphabetical tie-break was all that was left, and the money column was simply believed.
    # The report was confidently wrong three ways at once and said nothing, which is the one
    # outcome a tool built to aim a month of work must not produce.
    #
    # So the degenerate cases are now named BEFORE the table, and the table is labelled
    # unusable when they fire. A ranking nobody can act on is fine; a ranking that looks
    # actionable and is not costs whatever it aims.
    quoted_lines = sum(used_lines.values())
    quoted_spend = sum(used_spend.values())
    blank = used_spend.get(NO_SUPPLIER, 0.0)
    matched_lines = quoted_lines - sum(uncovered_lines.values())
    faults = []

    if quoted_lines and blank / max(quoted_spend, 0.01) > 0.5:
        faults.append(
            f"{blank / max(quoted_spend, 0.01) * 100:.0f}% of quoted spend has NO SUPPLIER NAME.\n"
            "     historical_quote_material_line.supplier_name is empty on those rows, so this\n"
            "     cannot rank merchants -- it can only say that most of the money is\n"
            "     unattributed. That is a real finding and it is not a ranking: filling that\n"
            "     column is an Estimating/ERP job, not a supplier conversation.")

    if quoted_lines:
        mean_line = quoted_spend / quoted_lines
        if mean_line > 100_000:
            faults.append(
                f"the mean quoted line is £{mean_line:,.0f}, which is not a line total.\n"
                "     line_total_gbp is not the column this assumes -- pence, a running total,\n"
                "     or a join fanning rows out. Every £ figure below is meaningless until\n"
                "     that is established, and the ORDER is meaningless with it.")

    if quoted_lines and matched_lines == 0:
        faults.append(
            "NOT ONE quoted part code matches a UDEF code. That is a join that does not\n"
            "     join -- different padding, prefixes or case -- not a catalogue that cannot\n"
            "     price anything. Taken at face value it says every penny is unpriceable,\n"
            "     which would aim the whole programme at the wrong problem.")

    if faults:
        print("THIS RANKING CANNOT BE ACTED ON YET")
        for fault in faults:
            print(f"  *  {fault}")
        print("\n  The table below is printed so the shape can be seen. Do not email anyone\n"
              "  from it, and do not read the order as a priority.\n")

    # WIDE ENOUGH FOR THE NUMBER, because the columns ran together and turned an absurd
    # figure into a wall of digits nobody could see was absurd.
    print(f"{'supplier':<32}{'bought':>8}{'spend £':>18}{'unpriceable £':>18}"
          f"{'ref':>6}  what to do")
    print("-" * 132)
    shown = [s for s in ranked if used_lines.get(s, 0) >= args.min_bought]
    if not shown:
        print("  (nothing quoted -- every supplier has 0 bought lines at this threshold)")
    for s in shown[:args.top]:
        n = max(1, lines.get(s, 0))
        share = with_ref.get(s, 0) / n
        print(f"{s[:31]:<32}{used_lines.get(s, 0):>8}{used_spend.get(s, 0.0):>18,.0f}"
              f"{uncovered_spend.get(s, 0.0):>18,.0f}{share*100:>5.0f}%  "
              + recommend(used_lines.get(s, 0), uncovered_spend.get(s, 0.0), share,
                          _months_since(last_used.get(s))))

    print("\nHOW TO READ THIS")
    print("  bought        — lines we have actually quoted, not lines in their catalogue.")
    print("  unpriceable £ — of that spend, what sits on a part code UDEF does not hold, so")
    print("                  the engine cannot price it and an estimator is guessing. THIS")
    print("                  IS THE COLUMN THAT DECIDES WHERE EFFORT GOES.")
    print("\nHOW TO READ THE REFERENCE COLUMN")
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
            w.writerow(["supplier", "catalogue_lines", "lines_bought", "spend_gbp",
                        "unpriceable_spend_gbp", "unpriceable_lines", "avg_cost_gbp",
                        "lines_with_reference", "reference_share_pct", "months_since_last_use",
                        "recommendation", "families"])
            for s in ranked:
                n = max(1, lines.get(s, 0))
                share = with_ref.get(s, 0) / n
                since = _months_since(last_used.get(s))
                w.writerow([s, lines.get(s, 0), used_lines.get(s, 0),
                            round(used_spend.get(s, 0.0), 2),
                            round(uncovered_spend.get(s, 0.0), 2),
                            uncovered_lines.get(s, 0),
                            round(spend.get(s, 0.0) / n, 4), with_ref.get(s, 0),
                            round(share * 100, 1),
                            "" if since is None else round(since, 1),
                            recommend(used_lines.get(s, 0), uncovered_spend.get(s, 0.0),
                                      share, since),
                            "; ".join(f"{f}={c}" for f, c in
                                      sorted(families.get(s, {}).items(),
                                             key=lambda kv: -kv[1]))])
        print(f"\nfull ranking -> {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
