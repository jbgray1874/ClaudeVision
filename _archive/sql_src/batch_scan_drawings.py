"""
batch_scan_drawings.py — Batch scan all PDFs in a folder tree.

For each PDF found, automatically locates matching flat DXFs by:
  1. Checking a sibling DXF folder in the same directory
  2. Checking a global --dxf-root folder

Skips PDFs already scanned (matching JSON exists in --out).
Generates xlsx estimate output for each scan.

Usage:
    python src/batch_scan_drawings.py ^
        --root "input/drawings/M&S" ^
        --out  "output/batch" ^
        --dxf-root "input/drawings/M&S"

    # Force re-scan everything:
    python src/batch_scan_drawings.py --root ... --out ... --force

    # Dry run (show what would be scanned):
    python src/batch_scan_drawings.py --root ... --out ... --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional


def _find_matching_dxfs(pdf_path: Path, dxf_root: Optional[Path]) -> List[Path]:
    """Find flat DXFs that match this PDF — check sibling folder then dxf_root."""
    dxf_candidates: List[Path] = []

    # 1. Check same directory as PDF for DXF files
    sibling_dxfs = list(pdf_path.parent.glob("*.dxf")) + list(pdf_path.parent.glob("*.DXF"))
    dxf_candidates.extend(sibling_dxfs)

    # 2. Check dxf_root for DXFs in a folder matching the PDF parent name
    if dxf_root and dxf_root.is_dir():
        folder_match = dxf_root / pdf_path.parent.name
        if folder_match.is_dir():
            dxf_candidates.extend(
                list(folder_match.glob("*.dxf")) + list(folder_match.glob("*.DXF"))
            )

    # Deduplicate, exclude GA files from flat pattern list (GA goes as primary DXF)
    seen = set()
    result = []
    for d in dxf_candidates:
        key = d.resolve()
        if key not in seen:
            seen.add(key)
            result.append(d)

    return result


def _output_key(pdf_path: Path) -> str:
    return pdf_path.stem.replace(" ", "_")


def _already_scanned(out_dir: Path, pdf_path: Path) -> bool:
    key = _output_key(pdf_path)
    return bool(list(out_dir.glob(f"{key}*.json")))


def batch_scan(
    root: Path,
    out_dir: Path,
    dxf_root: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    estimates_dir = out_dir / "estimates"
    estimates_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(
        p for p in root.rglob("*.pdf")
        if not p.name.startswith("~") and not p.name.startswith(".")
    ) + sorted(
        p for p in root.rglob("*.PDF")
        if not p.name.startswith("~") and not p.name.startswith(".")
    )
    # Deduplicate (case-insensitive overlap on some systems)
    seen_stems = set()
    unique_pdfs = []
    for p in pdfs:
        key = str(p.resolve()).lower()
        if key not in seen_stems:
            seen_stems.add(key)
            unique_pdfs.append(p)
    pdfs = sorted(unique_pdfs)

    if not pdfs:
        print(f"No PDFs found under {root}")
        return

    print(f"Found {len(pdfs)} PDF(s) under {root}")
    print(f"Output dir: {out_dir}")
    if dry_run:
        print("DRY RUN — no scans will be executed\n")

    skipped = scanned = failed = 0

    for i, pdf_path in enumerate(pdfs, 1):
        rel = pdf_path.relative_to(root)
        dxfs = _find_matching_dxfs(pdf_path, dxf_root)

        if not force and _already_scanned(out_dir, pdf_path):
            print(f"  [{i:3d}/{len(pdfs)}] SKIP  {rel}")
            skipped += 1
            continue

        dxf_note = f"  +{len(dxfs)} DXF(s)" if dxfs else ""
        print(f"  [{i:3d}/{len(pdfs)}] SCAN  {rel}{dxf_note}")

        if dry_run:
            for d in dxfs[:3]:
                print(f"           dxf: {d.name}")
            scanned += 1
            continue

        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from file_scan import scan_pdf_file
            from pathlib import Path as _Path
            from xlsx_output import write_estimate_xlsx

            t0 = time.time()
            summary, output_paths = scan_pdf_file(
                pdf_path,
                attach_dxf_paths=dxfs if dxfs else None,
                auto_discover_dxf=False,
            )
            elapsed = round(time.time() - t0, 1)

            total = (summary.get("estimate_summary") or {}).get(
                "document_total_estimated_cost_gbp", 0.0
            )
            parts = len(
                (summary.get("estimate_summary") or {}).get("part_estimates", [])
            )
            geo_src = "DXF" if dxfs else "PDF"

            # Write xlsx
            xlsx_path = write_estimate_xlsx(summary, out_dir=estimates_dir)

            print(f"           -> {parts} parts  £{total:.2f}  [{geo_src}]  {elapsed}s")
            print(f"           -> xlsx: {xlsx_path.name}")
            scanned += 1

        except Exception as exc:
            print(f"           -> ERROR: {exc}")
            failed += 1

    print()
    print(f"Done — scanned: {scanned}  skipped: {skipped}  failed: {failed}")
    if failed:
        print("Re-run with --force to retry failed files (or remove their JSONs)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch scan drawings folder")
    parser.add_argument("--root",     required=True,  help="Folder containing PDFs to scan")
    parser.add_argument("--out",      required=True,  help="Output folder for JSON + xlsx")
    parser.add_argument("--dxf-root", default=None,   help="Root folder to search for matching DXFs")
    parser.add_argument("--force",    action="store_true", help="Re-scan even if output exists")
    parser.add_argument("--dry-run",  action="store_true", help="Show what would be scanned without running")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root not found: {root}")
        sys.exit(1)

    os.environ.setdefault("SKIP_VISION_EXTRACTION", "1")
    os.environ.setdefault("SDI_SKIP_WB_TEMPLATE", "1")

    batch_scan(
        root=root,
        out_dir=Path(args.out).resolve(),
        dxf_root=Path(args.dxf_root).resolve() if args.dxf_root else None,
        force=args.force,
        dry_run=args.dry_run,
    )
