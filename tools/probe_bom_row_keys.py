"""Why are five columns of the BOMs block empty? Ask the record what keys its BOM rows carry.

THE OUTPUT THAT PROMPTED THIS. 7332-01's 14:17 run wrote its BOMs & Routes tab with part number,
description and quantity filled on every row, and `material as printed`, `thickness mm`, `item no`,
`read from page` and `read by` EMPTY on every row — while the covering email from the same run
printed "5mm MS" and "2mm Acrylic" per part. The data is in the record. bom_sheet is asking for it
under names the record does not use.

Guessing at the right names from here would be the wrong way to fix that: a guess that happens to
work on one pack is indistinguishable from a guess that does not, and the symptom is a blank cell
either way. So this asks.

It reports, for the record's own BOM rows: how many there are, every key that appears and on how
many rows, and then key by key what bom_sheet looks for and whether it is there. It also looks at
the part records, because a column that cannot be filled from the BOM row may be fillable from the
part — and if it is, the sheet must say so rather than presenting a part-record value under a
heading that says "as printed".

    python tools/probe_bom_row_keys.py --record output/json/7332-01.json

Read-only. It opens one file and prints.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

# What bom_sheet asks each column for, in the order it tries. Kept here as data so the probe
# reports on what the code ACTUALLY reads rather than on a list that drifts from it.
WANTED: Dict[str, List[str]] = {
    "part_number": ["part_number"],
    "description": ["description"],
    "quantity": ["quantity"],
    "material_as_printed": ["material_text"],
    "thickness_mm": ["thickness_mm"],
    "item_no": ["item", "item_no"],
    "read_from_page": ["source_page", "page"],
    "read_by": ["source", "reader"],
}

# Names worth looking for when the wanted one is absent. NOT a fallback list the code will use —
# a list of candidates for a person to confirm. The difference matters: a reader silently taking
# `material` where it asked for `material_text` may be taking a normalised value and printing it
# under a heading that promises the printed one.
CANDIDATES: Dict[str, List[str]] = {
    "material_as_printed": ["material", "material_raw", "material_description", "spec",
                            "normalized_material", "material_name", "mat", "material_spec"],
    "thickness_mm": ["thickness", "gauge", "gauge_mm", "thk", "thk_mm"],
    "item_no": ["item_number", "index", "balloon", "find_no", "pos", "line_no"],
    "read_from_page": ["page_number", "pdf_page", "sheet", "source_page_number", "page_index"],
    "read_by": ["origin", "src", "read_by", "produced_by", "extractor", "method", "reader_name"],
}


def _rows(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in ((record.get("document_analysis") or {}).get("bom_rows") or [])
            if isinstance(r, Mapping)]


def _parts(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [p for p in ((record.get("manufacturing_writeup") or {}).get("parts") or [])
            if isinstance(p, Mapping)]


def probe(record: Mapping[str, Any], log=print) -> int:
    rows = _rows(record)
    log("=" * 78)
    log(f"BOM ROWS IN THIS RECORD: {len(rows)}")
    log("=" * 78)
    if not rows:
        log("  document_analysis.bom_rows is empty or absent — that is the whole answer, and it")
        log("  is a different defect from the columns being blank.")
        return 1

    present = Counter()
    for row in rows:
        for key, value in row.items():
            if value not in (None, "", [], {}):
                present[key] += 1
    log("")
    log(f"  {'KEY':32} {'ON N ROWS':>10}   sample value")
    log("  " + "-" * 74)
    for key, count in present.most_common():
        sample = next((r[key] for r in rows if r.get(key) not in (None, "", [], {})), "")
        log(f"  {key[:32]:32} {count:>10}   {str(sample)[:28]}")

    log("")
    log("=" * 78)
    log("WHAT bom_sheet ASKS FOR, COLUMN BY COLUMN")
    log("=" * 78)
    unresolved: List[str] = []
    for column, keys in WANTED.items():
        found = [k for k in keys if present.get(k)]
        if found:
            log(f"  OK        {column:22} <- {found[0]}  ({present[found[0]]}/{len(rows)} rows)")
            continue
        log(f"  EMPTY     {column:22} <- asked for {', '.join(keys)}; none present")
        near = [k for k in CANDIDATES.get(column, []) if present.get(k)]
        if near:
            for k in near:
                sample = next((r[k] for r in rows if r.get(k) not in (None, "")), "")
                log(f"            this record HAS {k!r} on {present[k]}/{len(rows)} rows, "
                    f"e.g. {str(sample)[:36]!r}")
        else:
            log(f"            and none of the usual alternatives either: "
                f"{', '.join(CANDIDATES.get(column, [])) or '(none listed)'}")
        unresolved.append(column)

    parts = _parts(record)
    log("")
    log("=" * 78)
    log(f"THE PART RECORDS ({len(parts)}) — could a blank column be filled from there instead?")
    log("=" * 78)
    if not parts:
        log("  no part records to check")
    else:
        part_keys = Counter()
        for part in parts:
            for key, value in part.items():
                if value not in (None, "", [], {}):
                    part_keys[key] += 1
        for key in ("material_text", "normalized_material", "material", "thickness_mm",
                    "stock_form", "source_page"):
            if part_keys.get(key):
                sample = next((p[key] for p in parts if p.get(key) not in (None, "")), "")
                log(f"  parts have {key!r} on {part_keys[key]}/{len(parts)} — "
                    f"e.g. {str(sample)[:34]!r}")
        log("")
        log("  IF A COLUMN IS FILLED FROM HERE IT MUST SAY SO. 'material as printed' promises")
        log("  the text on the drawing; a normalised part-record value under that heading is a")
        log("  different fact wearing the same label, and it is the arbitrated answer rather")
        log("  than the evidence the arbitration started from.")

    log("")
    log("=" * 78)
    if unresolved:
        log(f"{len(unresolved)} COLUMN(S) CANNOT BE FILLED FROM THE BOM ROW AS IT STANDS: "
            f"{', '.join(unresolved)}")
        log("Send this output back and the reader will be corrected against it, rather than")
        log("against a guess at what the keys might be called.")
        log("=" * 78)
        return 1
    log("Every column bom_sheet asks for is present on these rows.")
    log("=" * 78)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", required=True, help="a saved run record, output/json/JOB.json")
    args = ap.parse_args(argv)
    path = Path(args.record)
    if not path.is_file():
        print(f"!! {path} not found")
        return 2
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:                                             # noqa: BLE001
        print(f"!! could not read {path}: {type(err).__name__}: {err}")
        return 2
    return probe(record)


if __name__ == "__main__":
    raise SystemExit(main())
