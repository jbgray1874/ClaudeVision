# -*- coding: utf-8 -*-
r"""PDF-GEOMETRY INSPECTION PROBE (read-only) -- v2, reads the engine's OWN output JSON.

v1 tried to re-run analyse_vector_features on pdfplumber pages and failed ('Page' object
is not iterable) -- that function is internal; file_scan calls analyse_document_geometry on
already-processed page dicts, not raw pages. Rather than reconstruct that whole chain (more
guessing), this version reads the geometry the engine ALREADY computed and wrote to the run
JSON. No re-derivation, no wrong-signature risk -- it inspects exactly what the engine produced.

For every PDF-sourced part it dumps the displayed vs _raw cut-length and the implied
calibration multiplier, plus the raw vector counts, so we can see whether the inflation is:
  (A) the calibration step multiplying UP (displayed >> raw), or
  (B) the raw extraction over-counting (raw itself too high for the part's real size).

Read-only. Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _pdf_geom_diag.py
  C:\ClaudeVision\.venv\Scripts\python.exe _pdf_geom_diag.py "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
"""
import sys, json
from pathlib import Path

DEFAULT_JSON = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"


def _f(v, nd=1):
    """Format-safe: always returns a str so f-string width specs never see None."""
    if v is None:
        return "-"
    try:
        return str(round(float(v), nd))
    except Exception:
        return str(v)


def _walk_parts(doc):
    """Yield part dicts from the scan JSON wherever they live."""
    mw = doc.get("manufacturing_writeup") or {}
    for p in (mw.get("parts") or []):
        yield p
    for p in (doc.get("parts") or []):
        yield p


def inspect(json_path: Path):
    print("=" * 80)
    print(f"Reading engine output: {json_path}")
    print("=" * 80)
    try:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  FAILED to read JSON: {e}")
        return

    seen = set()
    rows = []
    for p in _walk_parts(doc):
        pn = str(p.get("part_number") or p.get("description") or "?")
        if pn in seen:
            continue
        seen.add(pn)
        g = p.get("geometry") or p.get("geometry_rollup") or {}
        if not isinstance(g, dict):
            continue
        gsrc = str(p.get("geometry_source") or g.get("geometry_source") or "")
        disp = g.get("estimated_cut_length_mm")
        raw_blk = g.get("_raw") if isinstance(g.get("_raw"), dict) else {}
        raw = raw_blk.get("estimated_cut_length_mm")
        vpc = raw_blk.get("vector_path_count") or g.get("vector_path_count")
        lseg = raw_blk.get("line_segments") or g.get("line_segments")
        maxlen = raw_blk.get("max_line_length_points") or g.get("max_line_length_points")
        rel = (g.get("confidence") or {}).get("geometry_reliability")
        rows.append((pn, gsrc, disp, raw, vpc, lseg, maxlen, rel))

    # PDF-sourced parts first (that's where inflation lives), then DXF.
    rows.sort(key=lambda r: (0 if "pdf" in (r[1] or "").lower() else 1, str(r[0])))
    print(f"\n{'part':12} {'src':16} {'displayed':>10} {'raw':>9} {'mult':>6} "
          f"{'paths':>6} {'segs':>6} {'maxpts':>8} {'rel':>5}")
    print("-" * 88)
    for pn, gsrc, disp, raw, vpc, lseg, maxlen, rel in rows:
        mult = ""
        if disp and raw and float(raw) > 0:
            mult = f"{float(disp)/float(raw):.2f}x"
        src_short = ("PDF" if "pdf" in (gsrc or "").lower()
                     else "DXF" if "dxf" in (gsrc or "").lower() else gsrc[:14])
        print(f"{pn[:12]:12} {src_short:16} {_f(disp):>10} {_f(raw):>9} {mult:>6} "
              f"{_f(vpc,0):>6} {_f(lseg,0):>6} {_f(maxlen,0):>8} {_f(rel,2):>5}")

    print("\nHOW TO READ THIS:")
    print("  mult >1  -> calibration step is MULTIPLYING the raw cut-length up (suspect = geometry_calibration)")
    print("  mult blank but displayed huge for a small part -> raw EXTRACTION over-counts")
    print("            (section views / detail boxes / dimension lines summed as cut path; suspect = geometry_features)")
    print("  A ~1m tube reading 9000-11000mm with no _raw (no calibration) = pure over-count in extraction.")
    print("  Compare each PDF part's cut-length to its real size (e.g. 2621 half-peg ~558x497mm,")
    print("  so a sane cut path is ~3000-5000mm, not 14445mm).")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON
    p = Path(arg)
    if not p.is_file():
        print(f"JSON not found: {p}")
        print("Pass the run's output JSON path, e.g.:")
        print(r'  python _pdf_geom_diag.py "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"')
        sys.exit(0)
    inspect(p)
