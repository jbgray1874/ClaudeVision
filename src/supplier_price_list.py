"""Turn a supplier's price file into catalogue rows the engine can actually price from.

    python src/supplier_price_list.py --file "Elite net prices Aug26.xlsx" --supplier "Elite Sourcing"
    python src/supplier_price_list.py --file eagle.csv --supplier "Eagle Plastics" --class "ABS, HIPS"
    python src/supplier_price_list.py --file elite.xlsx --supplier "Elite Sourcing" --commit
    python src/supplier_price_list.py --file odd.xlsx --supplier X --map their_sku=B,description=C,net_gbp=G

WHY THIS EXISTS, and it is a hole with a measured size. The audit against SDILive:

    1. UDEF                      93,837 rows     41,123 priced
    2. PMA purchased             20,400 rows     11,208 priced
    3. Bought-in catalogue            0 rows          0 priced   <-- the hole
    4. Historical RAG            68,489 rows     27,386 priced
    5. Supplier catalogue           138 rows         82 priced

Rung 3 is empty, so every screw, castor, lock, clip and POS mount falls past it to text-matched
history or to a model. That is why fixings come back at £0 or with a number that changes between
runs. Twenty-four suppliers were surveyed and NONE offers an API; two have portals and the rest
send a file. So the way this hole gets filled is price files, not integrations, and the tool that
matters is a reader.

ONE ROW SHAPE, NOT ONE FORMAT PER MERCHANT. Every supplier's spreadsheet is laid out differently
and none of them will change for us. So the variation is absorbed HERE, once, into a single shape:

    supplier | their_sku | our_sku | description | class | unit | thickness_mm
             | sheet_l_mm | sheet_w_mm | net_gbp | valid_from | source_file

`our_sku` IS NOT DECORATION. Twenty-three of the twenty-four suppliers quote on their own codes;
Elite Sourcing quotes on SDI's (FIXING1081, VINYL76). That single exception is the easiest match
in the whole programme — the drawing says FIXING1081 and so does the price file — and it is
exactly the column a well-meaning "normalise the SKUs" pass would throw away. When our_sku is
present it becomes the code the engine matches on, and the supplier's own code is kept beside it
rather than instead of it.

A PRICE THAT IS NOT A NUMBER IS NOT A PRICE. "POA", "on application", a blank cell and a dash all
mean the supplier has not told us, and every one of them becomes 0.0 if you call float() with a
try/except. A zero in this table is a free part on a quote. They are rejected by name and counted,
because the powder-at-£0.00 fault and the 60-inch-monitor-at-£0.00 row both came from a number
that was really an absence.

DRY RUN BY DEFAULT. Nothing is written without --commit. The write itself is delegated to
catalogue_loader.upsert_catalogue, which already knows how to version a price: close the current
row the day before, insert the new one, and do nothing at all when the price has not moved. That
discipline is worth more than the parsing, and reimplementing it would be two of them to keep
right.

WHAT THIS DOES NOT DO. It does not touch UDEF, which stays the spine, and it does not decide what
a part costs on a job -- the pricing chain still runs UDEF -> PMA -> this -> history -> LLM, and a
contract price still beats a list price. It loads rung 3 and stops.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ── the canonical shape ────────────────────────────────────────────────────────

FIELDS = ("supplier", "their_sku", "our_sku", "description", "class", "unit",
          "thickness_mm", "sheet_l_mm", "sheet_w_mm", "net_gbp", "valid_from", "source_file")

# Header words that identify a column, most specific first. Order matters: "net price" must be
# tested before "price", or a file with both "list price" and "net price" takes the wrong one --
# and paying list when a net was offered is a silent over-charge on every line.
_HEADER_HINTS: List[Tuple[str, Tuple[str, ...]]] = [
    ("our_sku", ("sdi code", "sdi part", "our code", "our part", "customer part",
                 "customer code", "your code", "your part", "your ref")),
    ("their_sku", ("supplier code", "supplier sku", "part code", "part no", "part number",
                   "product code", "item code", "sku", "catalogue no", "cat no", "stock code",
                   "code", "ref")),
    ("net_gbp", ("net price", "net each", "nett price", "nett", "trade price", "your price",
                 "contract price", "unit price", "price each", "price gbp", "£", "price")),
    ("description", ("description", "product description", "item description", "product",
                     "item", "details")),
    ("unit", ("uom", "unit of measure", "unit", "per", "sold as")),
    ("thickness_mm", ("thickness", "gauge", "thk")),
    ("sheet_l_mm", ("length", "sheet length", "size l", "long")),
    ("sheet_w_mm", ("width", "sheet width", "size w", "wide")),
    ("class", ("category", "class", "group", "range", "material")),
    ("valid_from", ("valid from", "effective", "price date", "date")),
]

# What a price is quoted PER. Sheet goods are not "each", and loading acrylic as an each-price is
# how a 3m x 2m sheet gets costed like a washer.
_UNITS = {
    "ea": ("ea", "each", "unit", "pc", "pcs", "piece", "no", "off", "item"),
    "kg": ("kg", "kilo", "kilogram", "per kg", "/kg"),
    "m2": ("m2", "m²", "sqm", "sq m", "square metre", "square meter", "per m2"),
    "m": ("m", "lm", "linear metre", "per metre", "mtr"),
    "sheet": ("sheet", "board", "panel", "per sheet"),
    "t": ("t", "te", "tonne", "ton", "per tonne", "/t"),
    "box": ("box", "pack", "bag", "carton", "100", "1000"),
}

# Rejected rather than coerced. Every one of these becomes 0.0 through a lazy float().
_NOT_A_PRICE = ("poa", "p.o.a", "on application", "on request", "quote", "quoted", "tbc", "tba",
                "call", "ring", "n/a", "na", "-", "--", "", "nil", "see below", "ask")


class RowRejected(Exception):
    """Carries the reason, because a count of rejects nobody can explain is not a report."""


# ── reading whatever they sent ─────────────────────────────────────────────────

def read_table(path: Path) -> List[List[Any]]:
    """Every cell, as a list of rows. Format sniffed from the suffix."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            return [list(r) for r in csv.reader(fh, delimiter=delim)]
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl                                       # noqa: PLC0415
        ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if suffix == ".xls":
        import xlrd                                           # noqa: PLC0415
        sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    raise SystemExit(f"Cannot read {path.suffix} — send it as .xlsx or .csv.")


def find_header_row(rows: List[List[Any]], limit: int = 25) -> int:
    """Which row holds the column names.

    Price files open with a logo, an address, a date and two blank rows before anything useful.
    Assuming row 1 loses the header on most real files, so the header is the row that identifies
    the most distinct fields -- ties going to the earliest, because a later row that scores the
    same is usually the first data row echoing its own headings.
    """
    best, best_score = 0, 0
    for i, row in enumerate(rows[:limit]):
        found = {f for f, _ in _map_row(row).items()}
        if len(found) > best_score:
            best, best_score = i, len(found)
    return best


def _map_row(row: Iterable[Any]) -> Dict[str, int]:
    """Which canonical field each cell in this row names. First field to claim a column wins."""
    out: Dict[str, int] = {}
    taken: set = set()
    cells = [str(c or "").strip().lower() for c in row]
    for field, hints in _HEADER_HINTS:
        # HINTS OUTSIDE, COLUMNS INSIDE, and the nesting is the whole correctness of this.
        #
        # Written the other way round -- columns outside -- a file with "List Price" in C and
        # "Net Price" in D takes C, because the generic hint "price" matches "list price" on the
        # first column scanned and the specific hint "net price" is never reached. Paying list
        # when a net was offered is a silent over-charge on every line of every job, and nothing
        # in the output would look wrong.
        #
        # So the most specific hint gets to look at every column before the next hint gets to
        # look at any. That is what "most specific first" in _HEADER_HINTS is FOR, and the first
        # version of this had the comment and not the behaviour.
        matched = None
        for hint in hints:
            for idx, text in enumerate(cells):
                if idx in taken or not text:
                    continue
                if text == hint or text.startswith(hint) or hint in text:
                    matched = idx
                    break
            if matched is not None:
                break
        if matched is not None:
            out[field] = matched
            taken.add(matched)
    return out


# ── normalising a cell ─────────────────────────────────────────────────────────

def parse_price(value: Any) -> float:
    """A number, or RowRejected naming what was there instead."""
    if value is None:
        raise RowRejected("no price cell")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        price = float(value)
        if price <= 0:
            raise RowRejected(f"price is {price} — a zero is an absence, not a free part")
        return price
    text = str(value).strip()
    if text.lower() in _NOT_A_PRICE:
        raise RowRejected(f"price reads {text!r} — the supplier has not quoted it")
    cleaned = re.sub(r"[£$€,\s]", "", text)
    cleaned = re.sub(r"(?i)\b(each|ea|per|kg|m2|m²|sheet|tonne)\b", "", cleaned).strip()
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        raise RowRejected(f"price {text!r} holds no number")
    price = float(m.group(0))
    if price <= 0:
        raise RowRejected(f"price {text!r} resolves to {price}")
    return price


def _unit_in(text: Any) -> Optional[str]:
    t = str(text or "").strip().lower()
    if not t:
        return None
    for unit, hints in _UNITS.items():
        for h in hints:
            if re.search(rf"(?<![a-z0-9]){re.escape(h)}(?![a-z0-9])", t):
                return unit
    return None



# The unit-versus-description check lives in unit_parsing, because the PRICE CHAIN needs
# it too: rung 3 reads rows the migration wrote, not rows this loader parsed, and one of
# them is wrong by 10x today. A guard only the importer runs cannot protect a table that
# was filled before the importer existed.
from unit_parsing import unit_conflicts  # noqa: E402  (re-exported for callers here)

def parse_unit(value: Any, description: str = "", price_header: Any = "") -> Tuple[str, str]:
    """ea / kg / m2 / m / sheet / t / box, and WHERE it was read from.

    THE ORDER HERE IS THE WHOLE POINT, and the first version got it wrong in a way that would
    have cost real money. Eagle's file has no unit column; its price column is headed
    "Price per m2" and its descriptions read "ABS sheet white textured". Falling back to the
    description matched the word "sheet" -- the PRODUCT, not the unit -- and loaded a per-square-
    metre price as a per-sheet price. On a 2500 x 1250 board that is a three-fold under-charge on
    every line, and nothing downstream would have questioned it.

    So: an explicit unit column first, then the PRICE COLUMN'S OWN HEADING, which is where a file
    with no unit column almost always says it ("Price per m2", "Net £/kg", "Price each"), and the
    description last and reluctantly. The caller is told which, so a unit inferred from a product
    name can be shown as the guess it is.
    """
    for source, text in (("column", value), ("price header", price_header)):
        unit = _unit_in(text)
        if unit:
            return unit, source
    unit = _unit_in(description)
    if unit:
        return unit, "description (GUESS — check it)"
    return "ea", "assumed"


def parse_mm(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(m.group(0)) if m else None


def parse_date(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()[:19].replace("T", " ")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text[:len(fmt) + 2].strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── the parse ──────────────────────────────────────────────────────────────────

def parse(path: Path, supplier: str, *, material_class: str = "",
          overrides: Optional[Dict[str, int]] = None,
          valid_from: Optional[str] = None) -> Dict[str, Any]:
    """The file as canonical rows, plus everything that did not make it and why."""
    rows = read_table(path)
    if not rows:
        return {"rows": [], "rejected": [], "mapping": {}, "header_row": None,
                "error": "the file is empty"}

    header_at = find_header_row(rows)
    mapping = _map_row(rows[header_at])
    mapping.update(overrides or {})
    if "net_gbp" not in mapping:
        return {"rows": [], "rejected": [], "mapping": mapping, "header_row": header_at,
                "error": "no price column found — name it with --map net_gbp=<column letter>"}
    if "description" not in mapping and "their_sku" not in mapping and "our_sku" not in mapping:
        return {"rows": [], "rejected": [], "mapping": mapping, "header_row": header_at,
                "error": "no description or code column found — a price with no identity cannot "
                         "be matched to anything"}

    # The price column's own heading, kept because it is where a file with no unit column says
    # what the price is per.
    _pi = mapping.get("net_gbp")
    price_header = (rows[header_at][_pi] if _pi is not None and _pi < len(rows[header_at]) else "")

    default_date = valid_from or dt.date.today().strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    def cell(row, field):
        i = mapping.get(field)
        return row[i] if i is not None and i < len(row) else None

    for n, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        if not any(str(c or "").strip() for c in row):
            continue                                          # blank spacer, not a reject
        desc = str(cell(row, "description") or "").strip()
        their = str(cell(row, "their_sku") or "").strip()
        ours = str(cell(row, "our_sku") or "").strip()
        try:
            if not (desc or their or ours):
                raise RowRejected("no description and no code")
            price = parse_price(cell(row, "net_gbp"))
        except RowRejected as exc:
            rejected.append({"line": n, "why": str(exc),
                             "text": (desc or their or ours or "")[:60]})
            continue
        unit, unit_from = parse_unit(cell(row, "unit"), desc, price_header)
        out.append({
            "supplier": supplier,
            "their_sku": their or None,
            "our_sku": ours or None,
            "description": desc or their or ours,
            "class": str(cell(row, "class") or material_class or "").strip() or None,
            "unit": unit,
            "unit_from": unit_from,
            "thickness_mm": parse_mm(cell(row, "thickness_mm")),
            "sheet_l_mm": parse_mm(cell(row, "sheet_l_mm")),
            "sheet_w_mm": parse_mm(cell(row, "sheet_w_mm")),
            "net_gbp": price,
            "valid_from": parse_date(cell(row, "valid_from")) or default_date,
            "source_file": path.name,
            "line": n,
        })
    # DOES THIS EVEN LOOK LIKE A PRICE LIST?
    #
    # Pointed at the SUPPLIER SURVEY spreadsheet -- a list of merchants, contacts and "how you get
    # the price today" -- this happily reported "1 priceable row, 23 rejected" and offered to
    # commit it. The sniffer had done as it was told: column D is headed "How you get the price
    # today (email / PDF / portal / phone)", which contains the word "price", and column G is
    # "Their part codes on the quote?", which contains "part code". Every mapping was defensible
    # and the answer was nonsense.
    #
    # A tool that produces confident output from the wrong file is the same fault as a £0.00 that
    # reads as free: the output looks like an answer. So when almost everything is rejected, the
    # conclusion is about the FILE, not about its rows -- a real price list from a real merchant
    # does not have 96% unquotable lines.
    total = len(out) + len(rejected)
    if total and len(out) / total < 0.25 and len(out) < 10:
        header_text = " | ".join(str(c or "")[:40] for c in rows[header_at] if str(c or "").strip())
        return {"rows": [], "rejected": rejected, "mapping": mapping, "header_row": header_at,
                "error": (
                    f"{len(rejected)} of {total} rows carry no usable price, so this does not look "
                    f"like a supplier price list.\n"
                    f"  the row taken as the header was: {header_text[:180]}\n"
                    f"  if that is a summary or survey sheet rather than the merchant's own price "
                    f"file, you want the file THEY sent.\n"
                    f"  if it really is a price list, name the columns yourself: "
                    f"--map net_gbp=<col>,description=<col>")}

    return {"rows": out, "rejected": rejected, "mapping": mapping,
            "header_row": header_at, "error": None}


def match_key(row: Dict[str, Any]) -> str:
    """The code the ENGINE will match a drawing against.

    Ours when we have it. `_get_bought_in_part` compares a drawing's part_number to part_code, and
    a drawing says FIXING1081 -- it has never heard of the supplier's own number for the same
    thing. Elite quote on our codes, which is why they are first in the queue and why this
    preference is not a detail."""
    return str(row.get("our_sku") or row.get("their_sku") or "").strip()


# ── reporting ──────────────────────────────────────────────────────────────────

def report(parsed: Dict[str, Any], *, sample: int = 12) -> str:
    if parsed.get("error"):
        return f"Could not read it: {parsed['error']}\n  columns found: {parsed.get('mapping')}"

    rows, rejected = parsed["rows"], parsed["rejected"]
    lines = [f"\nheader on row {parsed['header_row'] + 1}; columns mapped:"]
    for f in FIELDS:
        i = parsed["mapping"].get(f)
        if i is not None:
            lines.append(f"    {f:14} <- column {chr(65 + i) if i < 26 else i}")
    missing = [f for f in ("our_sku", "their_sku", "unit", "thickness_mm")
               if f not in parsed["mapping"]]
    if missing:
        lines.append(f"    (not present: {', '.join(missing)})")

    by_unit: Dict[str, int] = {}
    for r in rows:
        by_unit[r["unit"]] = by_unit.get(r["unit"], 0) + 1
    ours = sum(1 for r in rows if r["our_sku"])

    lines += ["", f"{len(rows):,} priceable rows, {len(rejected):,} rejected",
              f"    units: " + ", ".join(f"{k}×{v}" for k, v in sorted(by_unit.items()))]
    if ours:
        lines.append(f"    {ours:,} carry OUR part code — those match a drawing directly")
    if not ours and rows:
        lines.append("    none carry our part code, so these match on description only")

    # UNITS THAT ARGUE WITH THEIR OWN DESCRIPTION. Shown with the rejects rather than after
    # them, because a rejected row costs nothing and one of these costs a multiple on every
    # line that uses it. FIXING1784 is in the live catalogue at 10x for exactly this reason.
    conflicts = [(r, unit_conflicts(r["description"], r["unit"])) for r in rows]
    conflicts = [(r, why) for r, why in conflicts if why]
    if conflicts:
        lines += ["", f"  {len(conflicts):,} row(s) where the UNIT CONTRADICTS THE DESCRIPTION.",
                  "  Not rejected -- the price may be right and the unit wrong, or the other",
                  "  way round, and only the supplier knows which. Ask before --commit:"]
        for r, why in conflicts[:12]:
            lines.append(f"    {(r['their_sku'] or r['our_sku'] or '?'):<18} "
                         f"£{r['net_gbp']:>9,.4f} /{r['unit']:<6} {r['description'][:40]}")
            lines.append(f"        {why}")
        if len(conflicts) > 12:
            lines.append(f"    ... and {len(conflicts) - 12} more")

    guessed = [r for r in rows if "GUESS" in r.get("unit_from", "")]
    if guessed:
        lines.append(f"    !! {len(guessed):,} row(s) took their unit from the DESCRIPTION, not "
                     f"from a column or the price heading — check before committing.")
        lines.append(f"       a per-m2 price loaded as per-sheet is a 3x under-charge on a "
                     f"2500x1250 board, and nothing downstream would question it.")

    lines += ["", "first rows as they would land:"]
    for r in rows[:sample]:
        mark = "  <- unit guessed" if "GUESS" in r.get("unit_from", "") else ""
        lines.append(f"    {match_key(r) or '(no code)':18} {r['description'][:42]:44} "
                     f"£{r['net_gbp']:>9,.4f} /{r['unit']}{mark}")

    if rejected:
        lines += ["", f"rejected ({len(rejected)}) — each one named, none silently zeroed:"]
        seen: Dict[str, int] = {}
        for r in rejected:
            seen[r["why"]] = seen.get(r["why"], 0) + 1
        for why, n in sorted(seen.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"    {n:>5}  {why}")
        lines.append(f"    e.g. line {rejected[0]['line']}: {rejected[0]['text']!r}")
    return "\n".join(lines)


# ── writing ────────────────────────────────────────────────────────────────────

def commit(parsed: Dict[str, Any], *, source_label: str,
           allow_unit_conflicts: bool = False) -> Dict[str, Any]:
    """Delegated to catalogue_loader, which already versions a price correctly.

    Reimplementing "close the old row, insert the new, do nothing when it has not moved" would
    give this codebase two of them to keep right, and they would diverge on the first edge case.

    A ROW WHOSE UNIT ARGUES WITH ITS DESCRIPTION IS NOT WRITTEN. The dry run has already
    printed it; refusing it here is what makes that printing matter. FIXING1784 went into this
    table by exactly this route -- "10m Roll" stored per metre at the roll's price, out by ten
    on every line that has used it since -- and Elite's file is the first one large enough for
    that to happen at scale without anybody reading every row.

    A WARNING WOULD NOT HAVE BEEN ENOUGH. It is printed above the summary in a dry run of
    several hundred rows, and the person running it is looking for the number of rows that
    parsed. The refusal is the thing that stops.

    allow_unit_conflicts=True writes them anyway, for when the supplier has confirmed the file
    is right and the checker is being conservative. It is an argument somebody has to type,
    which is the point: it records that a person decided, rather than that nobody looked.
    """
    import catalogue_loader as cl                             # noqa: PLC0415
    conn = cl.connect()
    cur = conn.cursor()
    today = dt.date.today()
    actions: Dict[str, int] = {}
    failures: List[str] = []
    refused: List[str] = []
    for r in parsed["rows"]:
        conflict = unit_conflicts(r["description"], r["unit"])
        if conflict and not allow_unit_conflicts:
            refused.append(f"{match_key(r) or r['description'][:40]}: {conflict}")
            continue
        line = {
            "part_code": match_key(r) or None,
            "description": r["description"],
            "unit_price_gbp": r["net_gbp"],
            "supplier": r["supplier"],
            "category": r["class"],
            "uom": r["unit"],
        }
        try:
            action = cl.upsert_catalogue(cur, line, source_label, today)
            actions[action.split()[0]] = actions.get(action.split()[0], 0) + 1
        except Exception as exc:                              # noqa: BLE001
            failures.append(f"{match_key(r)}: {str(exc)[:120]}")
    conn.commit()
    conn.close()
    return {"actions": actions, "failures": failures, "refused": refused}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Load a supplier price file into the bought-in catalogue.")
    ap.add_argument("--file", required=True)
    ap.add_argument("--supplier", required=True)
    ap.add_argument("--class", dest="material_class", default="",
                    help="material class when the file does not carry one")
    ap.add_argument("--map", default="",
                    help="column overrides, e.g. their_sku=B,description=C,net_gbp=G")
    ap.add_argument("--valid-from", default=None, help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--commit", action="store_true", help="write it (default is a dry run)")
    # NOT a default and not a flag anybody sets once and forgets: it has to be typed on the
    # run that writes. That is the record that a person decided these rows are right, rather
    # than that nobody read them.
    ap.add_argument("--allow-unit-conflicts", action="store_true",
                    help="write rows whose unit contradicts their description (only after "
                         "the supplier has confirmed the file is right)")
    args = ap.parse_args(argv)

    overrides: Dict[str, int] = {}
    for pair in filter(None, (p.strip() for p in args.map.split(","))):
        field, _, col = pair.partition("=")
        field, col = field.strip(), col.strip()
        if field not in FIELDS:
            ap.error(f"--map names {field!r}, which is not one of: {', '.join(FIELDS)}")
        overrides[field] = (ord(col.upper()) - 65) if col.isalpha() else int(col)

    parsed = parse(Path(args.file), args.supplier,
                   material_class=args.material_class, overrides=overrides,
                   valid_from=args.valid_from)
    print(report(parsed))
    if parsed.get("error"):
        return 2
    if not args.commit:
        print(f"\nDRY RUN — nothing written. Add --commit when the mapping above looks right.")
        return 0

    result = commit(parsed, source_label=f"supplier_file:{Path(args.file).name}",
                    allow_unit_conflicts=args.allow_unit_conflicts)
    if result.get("refused"):
        print(f"\n  {len(result['refused'])} row(s) NOT WRITTEN -- the unit contradicts the "
              f"description:")
        for line in result["refused"][:12]:
            print(f"    {line}")
        if len(result["refused"]) > 12:
            print(f"    ... and {len(result['refused']) - 12} more")
        print("  Ask the supplier which is right, then either fix the file or re-run with "
              "--allow-unit-conflicts.")
    print("\nwritten:")
    for action, n in sorted(result["actions"].items()):
        print(f"    {n:>6}  {action}")
    for f in result["failures"][:10]:
        print(f"    FAILED  {f}")
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
