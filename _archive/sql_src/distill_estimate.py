"""
distill_estimate.py — turn a verbose formula_parse JSON into a compact, priced
job record suitable for embedding / RAG recall.

A formula_parse.json is ~3.7 MB of formula plumbing; the signal for similarity
search is tiny: the job identity, the quantity, the three cost totals, the
non-zero material lines and operations, and a search string built from the
descriptions. This script extracts exactly that.

Usage:
    # one file -> print
    python distill_estimate.py --in output/formula_parse_2023/SOME.formula_parse.json

    # a folder of parses -> one JSONL of records (skips hollow/empty estimates)
    python distill_estimate.py --in output/formula_parse_2023 --out output/records_2023.jsonl

Validated against the SDI manual-estimate template (Estimate sheet: D6 qty,
G6/M105 unit cost, M59 material, M103 labour, materials rows 11-58, operations
rows 63-102). Spot-check on a from-parts build (Wire/Sheet-Steel rows populated)
before trusting it across the whole archive.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Structural labels on the Estimate sheet that are headers, not line items.
_HEADER_LABELS = {
    "part description", "wire", "sheet steel", "other sheet material",
    "operation", "labour", "total material cost", "unit cost", "dept.",
    "dept", "length", "part width", "thickness", "qty per unit",
}


def _num(v: Any) -> Optional[float]:
    """Parse a numeric cell value; None if blank/non-numeric. Keeps 0.0."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _grid(parse: Dict[str, Any], sheet_name: str = "Estimate") -> Dict[int, Dict[str, Any]]:
    """row -> {column_letter: raw value} for one sheet."""
    g: Dict[int, Dict[str, Any]] = {}
    for e in parse.get("parsed_entries", []):
        if str(e.get("sheet", "")).lower() != sheet_name.lower():
            continue
        m = re.match(r"([A-Z]+)(\d+)$", str(e.get("address", "")))
        if not m:
            continue
        col, row = m.group(1), int(m.group(2))
        g.setdefault(row, {})[col] = e.get("value")
    return g


def _cell(g: Dict[int, Dict[str, Any]], col: str, row: int) -> Any:
    return g.get(row, {}).get(col)


def _meta_from_path(path: str, name: str):
    """Pull job id / name / customer / year from the workbook path + filename."""
    segs = [s for s in re.split(r"[\\/]+", path or "") if s]
    year = customer = None
    if "Manual Estimates" in segs:
        i = segs.index("Manual Estimates")
        year = segs[i + 1] if i + 1 < len(segs) else None
        customer = segs[i + 2] if i + 2 < len(segs) else None
    stem = re.sub(r"\.(xls|xlsx)$", "", name or "", flags=re.I)
    m = re.match(r"\s*([0-9][0-9\-]*)\s*[-\u2013]?\s*(.*)$", stem)
    if m:
        job_id = m.group(1).strip("- ")
        job_name = m.group(2).strip() or stem
    else:
        job_id, job_name = stem, stem
    return job_id, job_name, customer, year


def distill(parse: Dict[str, Any], source_file: Optional[str] = None) -> Dict[str, Any]:
    g = _grid(parse)

    quantity = _num(_cell(g, "D", 6))

    # G6 / M105 is the QUOTED PRICE, not the cost:
    #   M105 = ((M59 + M103) / (100% - M107)) / 0.95   -> cost grossed up by margin.
    # So we keep the price separately and compute cost = material + labour, which
    # is the figure to compare the (cost-producing) AI engine against.
    quoted_unit_price = _num(_cell(g, "G", 6))
    if quoted_unit_price is None:
        quoted_unit_price = _num(_cell(g, "M", 105))

    # Material total: locate by label first (robust to row-shift), fallback M59.
    material_cost = None
    for row, cols in g.items():
        if str(cols.get("C", "")).strip().lower().startswith("total material"):
            material_cost = _num(cols.get("M"))
            break
    if material_cost is None:
        material_cost = _num(_cell(g, "M", 59))

    labour_cost = _num(_cell(g, "M", 103))   # M103 = SUM(M63:M102) = the operations

    material_lines: List[Dict[str, Any]] = []
    for row in range(11, 59):
        cols = g.get(row, {})
        desc = str(cols.get("C", "")).strip()
        line_cost = _num(cols.get("M"))
        unit_price = _num(cols.get("J"))
        if desc.lower() in _HEADER_LABELS:
            continue
        if not desc and line_cost in (None, 0.0):
            continue
        material_lines.append({
            "row": row,
            "description": desc or None,
            "unit_price": unit_price,
            "line_cost": line_cost,
        })

    operations: List[Dict[str, Any]] = []
    for row in range(63, 103):
        cols = g.get(row, {})
        name = str(cols.get("C", "")).strip()
        cost = _num(cols.get("M"))
        dept = str(cols.get("G", "")).strip() or None
        if name.lower() in _HEADER_LABELS:
            continue
        if not name and cost in (None, 0.0):
            continue
        operations.append({"row": row, "name": name or None, "dept": dept, "cost": cost})

    # Fallback labour = sum of the operations we extracted (== M103's own formula),
    # NOT quoted_price - material (that would wrongly absorb the margin).
    if labour_cost is None and operations:
        s = sum(o["cost"] for o in operations if o["cost"] is not None)
        labour_cost = round(s, 4) if s else None

    cost_total = None
    if material_cost is not None or labour_cost is not None:
        cost_total = round((material_cost or 0.0) + (labour_cost or 0.0), 4)

    markup_pct = None
    if quoted_unit_price and cost_total:
        markup_pct = round(quoted_unit_price / cost_total - 1, 4)

    total_quoted = None
    if quoted_unit_price is not None and quantity is not None:
        total_quoted = round(quoted_unit_price * quantity, 2)

    job_id, job_name, customer, year = _meta_from_path(
        parse.get("workbook_path", ""), parse.get("workbook_name", ""))

    search_bits = [job_name]
    search_bits += [m["description"] for m in material_lines if m["description"]]
    search_bits += [o["name"] for o in operations if o["name"]]
    search_text = " | ".join(b for b in search_bits if b)

    is_empty = (cost_total in (None, 0.0) and quoted_unit_price in (None, 0.0)
                and not material_lines and not operations)

    return {
        "schema_version": "estimate_distilled.v2",
        "job_id": job_id,
        "job_name": job_name,
        "customer": customer,
        "year": year,
        "source_path": parse.get("workbook_path"),
        "source_parse_file": source_file,
        "quantity": quantity,
        "cost_total": cost_total,            # material + labour = build cost (compare engine to THIS)
        "material_cost": material_cost,
        "labour_cost": labour_cost,
        "quoted_unit_price": quoted_unit_price,  # G6 / M105 = cost + margin (the price)
        "markup_pct": markup_pct,
        "total_quoted": total_quoted,
        "material_lines": material_lines,
        "operations": operations,
        "search_text": search_text,
        "is_empty": is_empty,
    }


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Distil formula_parse JSON(s) into compact priced records")
    ap.add_argument("--in", dest="inp", required=True, help="A formula_parse.json file OR a folder of them")
    ap.add_argument("--out", help="Output .jsonl (folder mode). If omitted, prints the single record.")
    ap.add_argument("--keep-empty", action="store_true", help="Keep hollow/empty estimates (default: skip)")
    args = ap.parse_args()

    inp = Path(args.inp)
    if inp.is_file():
        rec = distill(_load(inp), source_file=inp.name)
        if rec["is_empty"]:
            print("WARNING: this parse is empty/hollow (no values) — check the parser ran v6+", file=sys.stderr)
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        raise SystemExit(0)

    files = sorted(inp.rglob("*.formula_parse.json"))
    if not files:
        print(f"No *.formula_parse.json under {inp}")
        raise SystemExit(1)
    if not args.out:
        print("Folder mode needs --out for the JSONL")
        raise SystemExit(1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = empty = errors = 0
    with out.open("w", encoding="utf-8") as fh:
        for f in files:
            try:
                rec = distill(_load(f), source_file=f.name)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  ERROR {f.name}: {exc}")
                continue
            if rec["is_empty"] and not args.keep_empty:
                empty += 1
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    print(f"Distilled {written} record(s) -> {out}   (skipped empty: {empty}, errors: {errors})")
