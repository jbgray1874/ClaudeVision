"""
drawing_inspector.py  —  a test harness for the drawing reader.

Given any drawing PDF, report what the reader can extract per sheet:
drawing number, revision, client, project title, material, and the BOM rows
(each tagged FOLLOW = sub-drawing reference, or PRICE = bought-in commodity).

The point is to *see* what the OCR/structure reader finds across differently
formatted drawings, and to flag fields it could not read confidently — so a
human can validate coverage on the calibration set rather than trusting it blind.

    inspect_drawing(pdf_path) -> dict     # structured result
    print_report(pdf_path)                # human-readable console report
"""
from __future__ import annotations
from typing import Any, Dict, List
from pathlib import Path
import re

from bom_table_extractor import extract_bom_table_rows, _clean

# title-block labels, longest/most-specific first so 'CLIENT REF' wins over 'CLIENT'
_LABELS = [
    "DWG NO", "REVISION", "CLIENT REF", "CLIENT", "PROJECT TITLE", "DESCRIPTION",
    "MATERIAL", "SURFACE FINISH", "COLOUR", "WEIGHT", "DATE", "DRAWN BY",
    "MODIFIED BY", "SCALE", "SHEET SIZE", "SHEET",
]
_LABEL_RE = re.compile(r"(" + "|".join(re.escape(l) for l in _LABELS) + r")\s*[:.]?\s*", re.I)
_DWG_NO_RE = re.compile(r"\b(\d{3,}[-\s]*[A-Z0-9][A-Z0-9\-\s]*?)\b", re.I)


def _parse_title_block(blob: str) -> Dict[str, str]:
    """Pull label: value pairs from a title-block text blob, each value running
    up to the next recognised label."""
    fields: Dict[str, str] = {}
    matches = list(_LABEL_RE.finditer(blob))
    for i, m in enumerate(matches):
        label = m.group(1).upper().strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(blob)
        value = _clean(blob[start:end]).strip(" :.-")
        # keep the first, longest non-empty hit per label
        if value and (label not in fields or len(value) < len(fields[label])):
            fields[label] = value
    return fields


def _title_block_blob(page) -> str:
    parts: List[str] = []
    try:
        for tbl in page.extract_tables() or []:
            for row in tbl:
                for c in row:
                    if c and any(k in str(c).upper() for k in ("DWG NO", "REVISION", "CLIENT", "MATERIAL", "PROJECT TITLE")):
                        parts.append(_clean(c))
    except Exception:
        pass
    try:
        parts.append(_clean(page.extract_text(x_tolerance=2, y_tolerance=2) or ""))
    except Exception:
        pass
    return "  ".join(parts)


def inspect_drawing(pdf_path: str) -> Dict[str, Any]:
    import pdfplumber
    path = Path(pdf_path)
    file_hint = re.match(r"\s*(\d{3,}[-A-Z0-9]*)", path.stem.upper())
    result: Dict[str, Any] = {"file": path.name, "filename_job_hint": file_hint.group(1) if file_hint else "", "sheets": []}

    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            tb = _parse_title_block(_title_block_blob(page))
            dwg = tb.get("DWG NO", "")
            # on some title blocks DWG NO merges with REVISION; recover a code-shaped token
            if not re.match(r"^\d{3,}", dwg) and tb.get("REVISION"):
                mo = _DWG_NO_RE.search(tb["REVISION"])
                if mo:
                    dwg = _clean(mo.group(1))
            rows = extract_bom_table_rows(page)
            result["sheets"].append({
                "sheet": idx,
                "drawing_number": dwg,
                "revision": tb.get("REVISION", "").split()[0] if tb.get("REVISION") else "",
                "client": tb.get("CLIENT", ""),
                "project_title": tb.get("PROJECT TITLE", ""),
                "material": tb.get("MATERIAL", ""),
                "bom_rows": rows,
                "missing": [f for f, v in (("drawing_number", dwg), ("revision", tb.get("REVISION", "")), ("client", tb.get("CLIENT", ""))) if not v],
            })
    return result


def print_report(pdf_path: str) -> None:
    r = inspect_drawing(pdf_path)
    print(f"\n{'='*78}\nDRAWING READ REPORT: {r['file']}   (filename job hint: {r['filename_job_hint']})\n{'='*78}")
    for sh in r["sheets"]:
        print(f"\n  Sheet {sh['sheet']}:  DWG {sh['drawing_number'] or '??'}  Rev {sh['revision'] or '?'}"
              f"   Client {sh['client'] or '?'}   Material {sh['material'] or '?'}")
        if sh["project_title"]:
            print(f"     Project: {sh['project_title']}")
        if sh["missing"]:
            print(f"     !! could not read: {', '.join(sh['missing'])}")
        for b in sh["bom_rows"]:
            tag = "FOLLOW" if b["kind"] == "drawing_ref" else "PRICE "
            ident = b["part_number"] if b["kind"] == "drawing_ref" else b["part_ref"]
            print(f"       [{tag}] {b['item_number']:>2}  x{b['quantity']:<3} {ident[:42]:42} {b['description']}")


if __name__ == "__main__":
    import sys
    print_report(sys.argv[1])
