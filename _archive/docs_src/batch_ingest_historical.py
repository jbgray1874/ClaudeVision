"""
batch_ingest_historical.py — Batch RAG ingest of all historical estimate workbooks.

Scans a folder tree for .xls/.xlsx files and runs write_estimate_template_parse on
each in an isolated subprocess, writing a <key>.formula_parse.json per workbook.

Usage:
    python src/batch_ingest_historical.py --root "input/historical_estimates" \
        --out "output/formula_parse" [--timeout 120] [--retry-failed] [--force] [--no-dedupe]

Keys are derived from the file's path RELATIVE TO --root (not the bare filename),
so identically-named files in different job folders never collide.

De-duplication (on by default; disable with --no-dedupe):
    Two layers, so the RAG store never receives redundant entries:
      * source-hash  — skip files whose BYTES match an already-seen workbook
                       (exact copies scattered across folders) BEFORE parsing.
      * output-hash  — after parsing, skip any workbook whose extracted JSON is
                       identical to one already kept (template-identical books,
                       e.g. size variants that produce the same parse). This is
                       the authoritative guarantee and is seeded from existing
                       JSONs in --out, so it stays correct across resumes.
    Every drop is recorded in <out>/_dedupe_manifest.tsv for audit.

Outcomes per workbook:
    <key>.formula_parse.json   completed parse (atomic — only appears on success)
    <key>.TIMEOUT              hit the time limit
    <key>.FAILED               errored (stderr saved inside the marker)

Resume / retry:
    Default        : skip any file that already has a JSON or a failure marker.
    --retry-failed : reprocess ONLY files whose last run failed (clears their marker);
                     completed JSONs are left untouched.
    --force        : reprocess EVERYTHING, ignoring JSONs and markers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

PARSE_SUFFIX = ".formula_parse.json"
TIMEOUT_SUFFIX = ".TIMEOUT"
FAILED_SUFFIX = ".FAILED"
MANIFEST_NAME = "_dedupe_manifest.tsv"
DEFAULT_TIMEOUT_S = 120


def _workbook_key(path: Path, root: Path) -> str:
    """Collision-proof key from the path relative to root."""
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.resolve().as_posix()
    safe_stem = path.stem.replace(" ", "_")
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"{safe_stem}__{digest}"


def _json_path(out_dir: Path, key: str) -> Path:
    return out_dir / f"{key}{PARSE_SUFFIX}"


def _marker_paths(out_dir: Path, key: str):
    return out_dir / f"{key}{TIMEOUT_SUFFIX}", out_dir / f"{key}{FAILED_SUFFIX}"


def _status(out_dir: Path, key: str) -> str:
    """One of: 'done', 'failed', 'new'."""
    if _json_path(out_dir, key).exists():
        return "done"
    timeout_marker, failed_marker = _marker_paths(out_dir, key)
    if timeout_marker.exists() or failed_marker.exists():
        return "failed"
    return "new"


def _clear_markers(out_dir: Path, key: str) -> None:
    for marker in _marker_paths(out_dir, key):
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


def _valid_json(path: Path) -> bool:
    """A killed-mid-write or truncated file must NOT count as a success."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            json.load(fh)
        return True
    except Exception:
        return False


def _sha1_file(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-1 of a file's bytes, read in chunks (handles multi-MB books)."""
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _seed_output_hashes(out_dir: Path) -> dict:
    """Hash any JSONs already in out_dir so resumes don't re-admit a duplicate."""
    seen = {}
    for jp in out_dir.glob(f"*{PARSE_SUFFIX}"):
        try:
            seen[_sha1_file(jp)] = jp.name
        except OSError:
            pass
    return seen


def batch_ingest(root: Path, out_dir: Path, *, timeout_s: int,
                 retry_failed: bool, force: bool, dedupe: bool = True) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # os.walk tolerates inaccessible network folders (rglob raises on them).
    workbook_list = []
    for dirpath, dirnames, filenames in os.walk(str(root), onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if (fname.lower().endswith((".xls", ".xlsx"))
                    and not fname.startswith("~")
                    and "formula_parse" not in fname):
                workbook_list.append(Path(dirpath) / fname)
    workbooks = sorted(workbook_list)

    if not workbooks:
        print(f"No workbooks found under {root}")
        return

    # Size index: a file can only be a byte-duplicate of another with the SAME
    # size, so we only ever hash files whose size collides. Unique-size files
    # are never read for hashing.
    size_counts: Counter = Counter()
    if dedupe:
        for wb in workbooks:
            try:
                size_counts[wb.stat().st_size] += 1
            except OSError:
                pass

    mode = "force" if force else ("retry-failed" if retry_failed else "resume")
    print(f"Found {len(workbooks)} workbook(s) under {root}")
    print(f"Output dir: {out_dir}   timeout: {timeout_s}s   mode: {mode}   "
          f"dedupe: {'on' if dedupe else 'off'}")
    print()

    skipped = processed = failed = dup_src = dup_out = 0
    src_dir = str(Path(__file__).parent)

    seen_src: dict = {}                                  # source-bytes hash -> first path
    seen_out: dict = _seed_output_hashes(out_dir) if dedupe else {}
    manifest = out_dir / MANIFEST_NAME

    def _log_dup(kind: str, dropped: Path, canonical: str) -> None:
        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(f"{kind}\t{dropped}\t{canonical}\n")

    for i, wb_path in enumerate(workbooks, 1):
        rel = wb_path.relative_to(root)
        key = _workbook_key(wb_path, root)
        status = _status(out_dir, key)

        if not force:
            if status == "done":
                print(f"  [{i:5d}/{len(workbooks)}] SKIP  (done)   {rel}")
                skipped += 1
                continue
            if status == "failed" and not retry_failed:
                print(f"  [{i:5d}/{len(workbooks)}] SKIP  (failed) {rel}")
                skipped += 1
                continue

        # --- Layer 1: source-bytes dedupe (cheap pre-parse skip of exact copies)
        if dedupe:
            try:
                shared_size = size_counts.get(wb_path.stat().st_size, 0) > 1
            except OSError:
                shared_size = False
            if shared_size:
                try:
                    shash = _sha1_file(wb_path)
                except OSError:
                    shash = None
                if shash is not None:
                    if shash in seen_src:
                        print(f"  [{i:5d}/{len(workbooks)}] DUP   (src)    {rel}")
                        _log_dup("DUP-SRC", wb_path, seen_src[shash])
                        dup_src += 1
                        continue
                    seen_src[shash] = str(wb_path)

        # About to (re)process — clear any stale markers and tmp first.
        _clear_markers(out_dir, key)
        out_path = _json_path(out_dir, key)
        tmp_path = out_dir / f"{key}{PARSE_SUFFIX}.tmp"
        tmp_path.unlink(missing_ok=True)

        print(f"  [{i:5d}/{len(workbooks)}] PARSE  {rel}")
        script = (
            f"import sys; sys.path.insert(0, {src_dir!r}); "
            f"from estimate_template_parser import write_estimate_template_parse; "
            f"write_estimate_template_parse({str(wb_path)!r}, {str(tmp_path)!r})"
        )
        try:
            res = subprocess.run(
                [sys.executable, "-c", script],
                timeout=timeout_s, capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            print(f"           -> TIMEOUT ({timeout_s}s) — retryable with --retry-failed")
            (out_dir / f"{key}{TIMEOUT_SUFFIX}").write_text(str(wb_path), encoding="utf-8")
            tmp_path.unlink(missing_ok=True)
            failed += 1
            continue

        if not (res.returncode == 0 and tmp_path.exists() and _valid_json(tmp_path)):
            reason = (res.stderr or "").strip()[:300] or f"exit {res.returncode}, no/invalid output"
            last_line = reason.splitlines()[-1] if reason.strip() else "unknown"
            print(f"           -> FAILED: {last_line}")
            (out_dir / f"{key}{FAILED_SUFFIX}").write_text(
                f"{wb_path}\n\n{reason}", encoding="utf-8")
            tmp_path.unlink(missing_ok=True)
            failed += 1
            continue

        # --- Layer 2: output-JSON dedupe (authoritative; catches template-identical)
        if dedupe:
            ohash = _sha1_file(tmp_path)
            if ohash in seen_out:
                print(f"           -> DUP (output identical to {seen_out[ohash]}) — dropped")
                _log_dup("DUP-OUT", wb_path, seen_out[ohash])
                tmp_path.unlink(missing_ok=True)
                dup_out += 1
                continue
            seen_out[ohash] = out_path.name

        tmp_path.replace(out_path)  # atomic rename
        print(f"           -> {out_path.name}  ({out_path.stat().st_size:,} bytes)")
        processed += 1

    print()
    print(f"Done — processed: {processed}  skipped: {skipped}  failed: {failed}  "
          f"dup(src): {dup_src}  dup(out): {dup_out}")
    if dedupe and (dup_src or dup_out):
        print(f"  De-dupe detail written to {manifest}")
    if failed:
        print("  Re-run with --retry-failed to retry ONLY the failed files "
              "(completed JSONs are left alone).")
        print(f"  If failures are large-but-valid books, raise --timeout (currently {timeout_s}s).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Batch ingest historical estimate workbooks")
    ap.add_argument("--root", required=True, help="Folder containing .xls/.xlsx files")
    ap.add_argument("--out", required=True, help="Output folder for formula_parse.json files")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                    help=f"Per-workbook time limit in seconds (default {DEFAULT_TIMEOUT_S})")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Reprocess only previously-failed files (clears their markers)")
    ap.add_argument("--force", action="store_true",
                    help="Reprocess everything, ignoring existing JSONs and markers")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="Disable source/output de-duplication (keep every workbook)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root folder not found: {root}")
        sys.exit(1)

    batch_ingest(root, Path(args.out).resolve(),
                 timeout_s=args.timeout, retry_failed=args.retry_failed,
                 force=args.force, dedupe=not args.no_dedupe)
