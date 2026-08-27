"""What have we paid for this before? Asked of every price source we already hold.

    python src/price_history_lookup.py "VESA" "SWINGARM" "ELBOW ARM" "INGENICO"
    python src/price_history_lookup.py --codes TP-1113 TP-1314 TP-1433 TP-1325 TP-1205
    python src/price_history_lookup.py --bom "\\\\share\\...\\402179-01-GA.pdf"
    python src/price_history_lookup.py --json "VESA MOUNT"

WHY THIS EXISTS.

An estimator looking at a bought-in line on a new drawing has one question — "what did we pay
last time?" — and the answer is already in this building, spread across four places that each
need their own query and their own column names:

    UDEF_PARTS_TABLE_FOR_ESTIMATING   the contract anchor, Access Supply Chain
    bought_in_parts                   the bought-in catalogue
    historical_quote_material_line    every priced line from 1,982 ingested jobs
    Material Price Break sheets       inside the historical estimate workbooks

Asking all four by hand is enough work that in practice nobody does it, and the question gets
answered by ringing a supplier or by a market guess instead — with a firm, evidenced, already-paid
number sitting in the database the whole time. This asks all four in one command.

SEARCH BY DESCRIPTION, NOT ONLY BY CODE, AND THAT IS THE POINT.

The obvious version of this tool looks up a part code and stops. It would have found nothing on
the job that prompted it. M&S drawing 402179-01-GA lists five mounting items as TP-1113, TP-1314,
TP-1433, TP-1325 and TP-1205 — codes that appear nowhere in SDI's data or on the public web, and
are most likely somebody's internal purchase reference rather than a supplier SKU. What DOES
travel between jobs is the words: VESA, SWINGARM, ELBOW ARM, MULTIGRIP, INGENICO. A previous M&S
till podium bought the same class of hardware and its line description will say so, whatever code
was typed beside it.

So descriptions are matched token-wise as well as whole, and the code is one input among several
rather than the key.

WHAT IT WILL NOT DO. It does not pick a price. It reports every hit, with the date, the drawing,
the customer and the source it came from, and leaves the choice to a person — because "we paid
£46.20 on an M&S job in March" and "we paid £46.20 on a one-off in 2019" are different facts and
only an estimator can say which one governs. A tool that returned a single number would hide
exactly the context that makes the number worth anything.

READ-ONLY. Every statement here is a SELECT. Nothing writes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


# Words too common to be worth searching on their own — "MOUNT" alone returns half the catalogue,
# and a result set nobody reads is the same as no result set.
_STOPWORDS = {
    "the", "and", "for", "with", "to", "of", "in", "on", "a", "x", "mm", "dia",
    "assy", "assembly", "item", "qty", "no", "off",
}
_MIN_TOKEN = 4


def _tokens(text: str) -> List[str]:
    """The words in a description worth searching on individually."""
    words = re.split(r"[^A-Za-z0-9]+", str(text or "").upper())
    return [w for w in words
            if len(w) >= _MIN_TOKEN and w.lower() not in _STOPWORDS and not w.isdigit()]


# ── the four sources ───────────────────────────────────────────────────────────

_UDEF_SQL = """
SELECT TOP (?)
    LTRIM(RTRIM(u.[Part code]   COLLATE Latin1_General_CI_AS)),
    LTRIM(RTRIM(u.[Description] COLLATE Latin1_General_CI_AS)),
    u.[System cost per],
    LTRIM(RTRIM(u.[Supplier name] COLLATE Latin1_General_CI_AS)),
    u.[UOM] COLLATE Latin1_General_CI_AS
FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
WHERE LTRIM(RTRIM(u.[Part code]   COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
   OR u.[Description] COLLATE Latin1_General_CI_AS LIKE '%' + LTRIM(RTRIM(?)) + '%'
ORDER BY u.[System cost per] DESC
"""

_BOUGHT_IN_SQL = """
SELECT TOP (?)
    b.part_code, b.description, b.unit_price_gbp, b.supplier_name, NULL
FROM dbo.bought_in_parts b
WHERE b.part_code = ? OR UPPER(b.description) LIKE '%' + UPPER(?) + '%'
ORDER BY b.unit_price_gbp DESC
"""

_HISTORY_SQL = """
SELECT TOP (?)
    hml.line_description,
    hml.unit_price_gbp,
    hml.part_code,
    hml.supplier_name,
    hml.qty_per_unit,
    hh.drawing_number,
    hh.quote_date,
    hh.customer_name
FROM dbo.historical_quote_material_line hml
LEFT JOIN dbo.historical_quote_header hh ON hml.quote_id = hh.quote_id
WHERE hml.unit_price_gbp IS NOT NULL AND hml.unit_price_gbp > 0
  AND (UPPER(hml.line_description) LIKE '%' + UPPER(?) + '%'
       OR UPPER(COALESCE(hml.part_code, '')) = UPPER(?))
ORDER BY
    CASE WHEN hh.quote_date IS NOT NULL THEN 0 ELSE 1 END,
    hh.quote_date DESC
"""


def _word_match(term: str, *fields: Any) -> bool:
    """Does the term appear as a WHOLE WORD in any of these fields?

    SQL LIKE '%term%' is a substring test, and the first real run showed what that costs. A
    search for VESA returned six rows and four were noise:

        Shelf Support, Plug in, for Wooden Shel[VES A]n ...      £0.11
        PALLET WRAP WITH COLOURED SHEL[VES A]ND RE-INFO          £0.00

    "shelves and" contains "vesa". A price lookup that offers a shelf support at 11p against a
    line for a monitor mount is worse than one that finds nothing, because £0.11 and £35.95 are
    both plausible-looking numbers and nothing on the row says it is a coincidence.

    The LIKE stays: it is the coarse, index-friendly filter the server does well. This is the
    second pass that makes the match mean something. Same rule as bought_in_pricing._resolve --
    a containment that is not word-boundary aligned is not a match.
    """
    pattern = re.compile(r"(?<![A-Za-z0-9])" + r"[\s\-_]+".join(
        re.escape(w) for w in str(term).split()) + r"(?![A-Za-z0-9])", re.I)
    return any(pattern.search(str(f)) for f in fields if f)


def _rows(cur, sql: str, params: List[Any]) -> List[tuple]:
    """A source that is not present on this machine must not stop the other three. A missing
    table is a deployment fact, not an error in the question being asked."""
    try:
        cur.execute(sql, params)
        return list(cur.fetchall())
    except Exception as exc:                                  # noqa: BLE001
        return [("__error__", str(exc)[:160])]


def search(terms: Iterable[str], *, limit: int = 12) -> Dict[str, Any]:
    """Every source, for every term. Returns findings, never a chosen price."""
    out: Dict[str, Any] = {"terms": [], "connected": False, "error": None}
    try:
        conn = config.get_connection()
    except Exception as exc:                                  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["connected"] = True

    cur = conn.cursor()
    for term in terms:
        term = str(term).strip()
        if not term:
            continue
        raw = {
            "udef": (_rows(cur, _UDEF_SQL, [limit, term, term]), (0, 1)),
            "bought_in": (_rows(cur, _BOUGHT_IN_SQL, [limit, term, term]), (0, 1)),
            "history": (_rows(cur, _HISTORY_SQL, [limit, term, term]), (0, 2)),
        }
        found: Dict[str, Any] = {"term": term, "coincidences": 0}
        for source, (rows, cols) in raw.items():
            if rows and rows[0] and rows[0][0] == "__error__":
                found[source] = rows                       # an unavailable source is not noise
                continue
            kept = [r for r in rows if _word_match(term, *(r[c] for c in cols))]
            found["coincidences"] += len(rows) - len(kept)
            found[source] = kept
        found["hits"] = sum(len(v) for k, v in found.items()
                            if k not in ("term", "coincidences", "hits") and isinstance(v, list))
        out["terms"].append(found)

    try:
        cur.close(); conn.close()
    except Exception:                                         # noqa: BLE001
        pass
    return out


def terms_from_bom(pdf_path: str) -> List[str]:
    """Every description on a drawing's BOM, plus the individual words in each.

    A BOM row is the natural unit of the question — the estimator is pricing that line — but the
    row as written is often unique to one drawing ("TP-1113 TECHPOLE SCREEN MOUNT WITH 300MM
    ELBOW ARM" appears nowhere else, ever). The words inside it are what recur.
    """
    try:
        import pymupdf                                        # noqa: PLC0415
    except ImportError:                                       # pragma: no cover
        raise SystemExit("pymupdf is not installed in this interpreter, so a BOM cannot be read.")

    text = "\n".join(page.get_text() for page in pymupdf.open(pdf_path))
    seen, out = set(), []
    for line in text.splitlines():
        line = line.strip()
        # A description line: mostly letters, long enough to mean something, not a dimension.
        if len(line) < 8 or not re.search(r"[A-Za-z]{4}", line):
            continue
        for candidate in [line] + _tokens(line):
            key = candidate.upper()
            if key not in seen:
                seen.add(key)
                out.append(candidate)
    return out


# ── reporting ──────────────────────────────────────────────────────────────────

def _money(v: Any) -> str:
    try:
        return f"£{float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def report(result: Dict[str, Any]) -> str:
    if not result.get("connected"):
        return ("Could not reach the estimating database, so nothing was searched.\n"
                f"  {result.get('error')}\n"
                "This has to run on a machine with a route to the SQL Server — the laptop or "
                "SDI-APP01, not a cloud session.")

    lines: List[str] = []
    silent: List[str] = []
    for found in result["terms"]:
        if not found["hits"]:
            silent.append(found["term"] + (f" ({found['coincidences']} substring coincidence"
                                           f"{'s' if found['coincidences'] != 1 else ''} discarded)"
                                           if found.get("coincidences") else ""))
            continue
        lines.append(f"\n{found['term']}")
        lines.append("-" * max(12, len(found["term"])))
        if found.get("coincidences"):
            lines.append(f"  ({found['coincidences']} row(s) matched only as a substring and "
                         f"were discarded — 'shelves and' contains 'vesa')")

        for row in found["udef"]:
            if row and row[0] == "__error__":
                lines.append(f"  UDEF unavailable: {row[1]}"); continue
            lines.append(f"  UDEF       {_money(row[2])}  {row[0] or '—':16} {str(row[1])[:44]:44} "
                         f"{row[3] or ''}")
        for row in found["bought_in"]:
            if row and row[0] == "__error__":
                lines.append(f"  catalogue unavailable: {row[1]}"); continue
            lines.append(f"  CATALOGUE  {_money(row[2])}  {row[0] or '—':16} {str(row[1])[:44]:44} "
                         f"{row[3] or ''}")
        for row in found["history"]:
            if row and row[0] == "__error__":
                lines.append(f"  history unavailable: {row[1]}"); continue
            when = str(row[6])[:10] if row[6] else "no date"
            lines.append(f"  QUOTED     {_money(row[1])}  {str(row[0])[:44]:44} "
                         f"{when}  {row[5] or '—'}  {row[7] or ''}")

    if silent:
        lines.append("\nNothing found for: " + ", ".join(sorted(set(silent))))
        lines.append("  Nothing found is a real answer — it means this has not been bought "
                     "through a priced line we hold, and it needs a supplier quote.")
    return "\n".join(lines) if lines else "No hits in any source."


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="What have we paid for this before? UDEF, the bought-in catalogue, and "
                    "every priced line from the ingested historical jobs.")
    ap.add_argument("terms", nargs="*", help="descriptions or words to search for")
    ap.add_argument("--codes", nargs="*", default=[], help="part codes to search for")
    ap.add_argument("--bom", help="a drawing PDF: search every description on its BOM")
    ap.add_argument("--limit", type=int, default=12, help="rows per source per term")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    terms = list(args.terms) + list(args.codes)
    if args.bom:
        terms += terms_from_bom(args.bom)
    if not terms:
        ap.error("give at least one term, --codes, or --bom")

    result = search(terms, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(report(result))
    return 0 if result.get("connected") else 2


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
