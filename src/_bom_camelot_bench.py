#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_bom_camelot_bench.py — Camelot as a COMPARISON-MODE BOM reader. No pipeline changes.

The reviewer's decision, verbatim in spirit: add Camelot as a complementary table
extractor (Lattice for ruled tables, Stream/Network for aligned borderless ones),
let it read WITHOUT changing the estimate, and compare cell-for-cell against the
existing deterministic reader on real packs — the M&S pack, 7332, both 11350
variants, 10975, and a scanned pack when one arrives. Promotion into production
happens only through the shared BOM schema and the reconciliation stage, only where
this benchmark demonstrates validated coverage.

TWO RULES THIS FILE ENFORCES BY CONSTRUCTION:

- ONE VOCABULARY FOR HEADER MEANING. Column families are imported from
  _bom_words_reader (_HDR_ITEM/_HDR_CODE/_HDR_DESC/_HDR_QTY/_HDR_MATERIAL/
  _HDR_WEIGHT), so Camelot cannot recognise a column the words reader has no name
  for, and a synonym learned from one pack serves every reader at once.

- NEVER CONCATENATED. The output is a REPORT — per page: rows both readers agree
  on, rows only one found, and cell-level differences (code, qty, description,
  material, weight). A screw row read twice must become a corroboration or a named
  question, never two purchases; that judgement belongs to merge_boms, which this
  tool feeds evidence, not rows.

Install (runner venv; Camelot >= 1.0 uses the pdfium backend, no Ghostscript):
    C:\ClaudeVision\.venv\Scripts\pip.exe install "camelot-py[base]"

Run (from C:\ClaudeVision\src so imports resolve):
    C:\ClaudeVision\.venv\Scripts\python.exe _bom_camelot_bench.py --pdf-dir "<folder>"
    optional: --pages 1,3,5   --out <report path>
Writes: <out> (default C:\ClaudeVision\output\camelot_bench_<folder name>.txt)
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from _bom_words_reader import (_HDR_CODE, _HDR_DESC, _HDR_ITEM, _HDR_MATERIAL,
                               _HDR_QTY, _HDR_WEIGHT, _hdr_norm,
                               _row_material_fields)

_FAMILIES: List[Tuple[str, set]] = [
    ("item", _HDR_ITEM), ("code", _HDR_CODE), ("desc", _HDR_DESC),
    ("qty", _HDR_QTY), ("material", _HDR_MATERIAL), ("weight", _HDR_WEIGHT),
]


def _family_for_header_cell(text: Any) -> Optional[str]:
    """Which column family one header CELL names, by the shared vocabulary.

    A cell is a whole header ("PART #", "WEIGHT (KG)", "DWG NO."), so the full
    normalised text is tried first, then each word, then adjacent word pairs — the
    same synonym sets the words reader anchors on, so the two readers cannot
    disagree about what a column is called."""
    raw = re.sub(r"[()#]", " ", str(text or ""))
    norm = _hdr_norm(re.sub(r"\s+", " ", raw))
    if not norm:
        return None
    toks = norm.split()
    candidates = [norm] + toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    for cand in candidates:
        for name, family in _FAMILIES:
            if cand in family:
                return name
    return None


def map_table_to_rows(grid: List[List[Any]]) -> Dict[str, Any]:
    """A Camelot table (list of cell-text rows) -> the shared BOM row schema.

    Returns {"rows": [...], "header_row": i} on success, or {"rejected": reason}
    naming exactly why not — "no table detected", "header unrecognised" and "row
    rejected" are different findings and the report must say which (the reviewer's
    rule: explain every rejection)."""
    if not grid:
        return {"rejected": "no table detected (empty grid)"}
    header_idx, columns = None, {}
    for i, row in enumerate(grid[:6]):        # a real header sits at the top
        found: Dict[str, int] = {}
        for ci, cell in enumerate(row):
            fam = _family_for_header_cell(cell)
            if fam and fam not in found:
                found[fam] = ci
        # Same acceptance strength as the words reader: the three core families,
        # or four families for an unusual table.
        if ("item" in found and "qty" in found
                and ("desc" in found or len(found) >= 4)):
            header_idx, columns = i, found
            break
    if header_idx is None:
        return {"rejected": "header unrecognised: "
                            + " | ".join(str(c) for c in grid[0])}

    rows: List[Dict[str, Any]] = []
    rejected_rows: List[str] = []
    for row in grid[header_idx + 1:]:
        def _cell(fam: str) -> str:
            ci = columns.get(fam)
            return re.sub(r"\s+", " ", str(row[ci])).strip() \
                if ci is not None and ci < len(row) else ""
        item, qty = _cell("item"), _cell("qty")
        if not (item.isdigit() and qty.isdigit()):
            if any(str(c).strip() for c in row):
                rejected_rows.append("row rejected (no integer item+qty): "
                                     + " | ".join(str(c).strip() for c in row))
            continue
        out = {"item_number": item, "part_ref": _cell("code"),
               "description": _cell("desc"), "quantity": int(qty)}
        out.update(_row_material_fields(_cell("material"), _cell("weight")))
        rows.append(out)
    return {"rows": rows, "header_row": header_idx, "rejected_rows": rejected_rows}


def compare_rows(a_rows: List[Dict[str, Any]],
                 c_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Row-level and cell-level agreement between the words reader (A) and Camelot
    (C). Keyed on the bare part code + item; a row only one reader found is a
    finding, a shared row with different cells is a finding per cell — nothing is
    merged here."""
    from part_code_conventions import bare_code

    def _key(r):
        return (str(r.get("item_number") or ""), bare_code(str(r.get("part_ref") or "")))

    a_by, c_by = {_key(r): r for r in a_rows or []}, {_key(r): r for r in c_rows or []}
    agree, diffs = [], []
    for k in sorted(set(a_by) & set(c_by)):
        a, c = a_by[k], c_by[k]
        cell_diffs = []
        for field in ("quantity", "description", "material_text",
                      "thickness_mm", "stated_weight_kg"):
            av, cv = a.get(field), c.get(field)
            if av != cv and not (av in (None, "") and cv in (None, "")):
                cell_diffs.append(f"{field}: A={av!r} C={cv!r}")
        (diffs if cell_diffs else agree).append(
            {"key": k, "cell_diffs": cell_diffs} if cell_diffs else {"key": k})
    return {
        "agree": agree,
        "cell_diffs": diffs,
        "only_a": sorted(set(a_by) - set(c_by)),
        "only_c": sorted(set(c_by) - set(a_by)),
    }


def _bench(pdf_dir: str, pages: Optional[str], out_path: str) -> None:
    try:
        import camelot
    except ImportError:
        print('Camelot is not installed in this venv. Install it with:\n'
              '    C:\\ClaudeVision\\.venv\\Scripts\\pip.exe install "camelot-py[base]"')
        sys.exit(2)
    import pdfplumber
    import _bom_words_reader as pathA

    lines: List[str] = []
    for pdf_path in sorted(glob.glob(os.path.join(pdf_dir, "*.pdf"))):
        name = os.path.basename(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            page_ids = ([int(p) for p in pages.split(",")] if pages
                        else range(1, len(pdf.pages) + 1))
            for pno in page_ids:
                a_bom = pathA.read_bom_from_page(pdf.pages[pno - 1]) or {}
                a_rows = a_bom.get("rows") or []
                best: Dict[str, Any] = {"rows": []}
                flavor_used = ""
                for flavor in ("lattice", "stream"):
                    try:
                        tables = camelot.read_pdf(pdf_path, pages=str(pno),
                                                  flavor=flavor)
                    except Exception as exc:                     # noqa: BLE001
                        lines.append(f"{name} p{pno} [{flavor}]: camelot error {exc}")
                        continue
                    for t in tables:
                        mapped = map_table_to_rows(
                            [list(r) for r in t.df.values.tolist()])
                        if mapped.get("rejected"):
                            lines.append(f"{name} p{pno} [{flavor}]: {mapped['rejected']}")
                        elif len(mapped["rows"]) > len(best["rows"]):
                            best, flavor_used = mapped, flavor
                if not a_rows and not best["rows"]:
                    continue
                cmpd = compare_rows(a_rows, best["rows"])
                lines.append(f"== {name} p{pno}: words-reader {len(a_rows)} row(s), "
                             f"camelot[{flavor_used or '-'}] {len(best['rows'])} row(s), "
                             f"agree {len(cmpd['agree'])}, "
                             f"cell-diffs {len(cmpd['cell_diffs'])}, "
                             f"A-only {len(cmpd['only_a'])}, "
                             f"C-only {len(cmpd['only_c'])}")
                for d in cmpd["cell_diffs"]:
                    lines.append(f"   diff {d['key']}: " + "; ".join(d["cell_diffs"]))
                for k in cmpd["only_a"]:
                    lines.append(f"   A-only {k}")
                for k in cmpd["only_c"]:
                    lines.append(f"   C-only {k}")
                for rr in (best.get("rejected_rows") or [])[:5]:
                    lines.append(f"   camelot {rr}")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {out_path} ({len(lines)} line(s))")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--pages", default=None, help="comma-separated 1-based page numbers")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    _default_out = os.path.join(
        r"C:\ClaudeVision\output" if os.name == "nt" else "/tmp",
        f"camelot_bench_{os.path.basename(os.path.normpath(args.pdf_dir))}.txt")
    _bench(args.pdf_dir, args.pages, args.out or _default_out)
