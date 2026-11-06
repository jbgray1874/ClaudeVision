r"""
sw_batch_health.py — run the native extractor across MANY jobs and report health.

The operational tool for the hundreds-of-drawings reality: you cannot eyeball each
extract, so this runs sw_native_analyse.py per job folder, normalises via the
source_connectors.solidworks connector, and emits a coverage/health summary that
FLAGS the outliers a human should look at (no native models, open failures, missing
material, no BOM). Everything clean flows through; the flagged list is your triage queue.

Usage (Windows + SolidWorks, in the ClaudeVision venv):
  # discover every job folder under a customer root (folders holding .SLDPRT/.SLDASM):
  python tools\solidworks\sw_batch_health.py --root "\\sdi-dc01\CAD\Design\Customers ...\Tesco Mobile"
  # or an explicit list of job folders:
  python tools\solidworks\sw_batch_health.py --jobs "<folder1>" "<folder2>"
  # reuse existing _sw_native_extract.json instead of re-running SolidWorks:
  python tools\solidworks\sw_batch_health.py --root "<root>" --no-run

Writes _sw_batch_health.json (full per-job detail) and prints a table + a FLAGGED list.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import the connector for normalisation. Add src/ to the path so this runs from anywhere.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
try:
    from source_connectors import solidworks as swconn
except Exception as _e:  # pragma: no cover
    swconn = None
    _CONN_ERR = repr(_e)

_ANALYSER = Path(__file__).resolve().parent / "sw_native_analyse.py"
_EXTRACT = "_sw_native_extract.json"
_ARCHIVE_TOKENS = ("archive", "old versions", "superseded", "obsolete", "wip", "do not use", "backup")
_SW_EXTS = {".sldprt", ".sldasm"}


def _log(m: str) -> None:
    print(m, flush=True)


def _has_sw_files(folder: Path) -> bool:
    try:
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in _SW_EXTS and not f.name.startswith("~$"):
                return True
    except Exception:
        pass
    return False


def discover_job_folders(root: Path) -> List[Path]:
    """Every folder under root that directly contains SolidWorks models, skipping archive
    subtrees. Each such folder is treated as one job unit."""
    out: List[Path] = []
    for dirpath, dirs, _files in os.walk(root):
        low = dirpath.lower()
        if any(tok in low for tok in _ARCHIVE_TOKENS):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not any(tok in d.lower() for tok in _ARCHIVE_TOKENS)]
        p = Path(dirpath)
        if _has_sw_files(p):
            out.append(p)
    return sorted(out)


def run_analyser(folder: Path, python_exe: str) -> None:
    try:
        subprocess.run([python_exe, str(_ANALYSER), str(folder)], check=False, timeout=3600)
    except Exception as e:
        _log(f"   [analyser error] {folder}: {e!r}")


def health_for_job(folder: Path, run: bool, python_exe: str) -> Dict[str, Any]:
    jp = folder / _EXTRACT
    if run or not jp.exists():
        run_analyser(folder, python_exe)
    records = swconn.load_native_extract(jp) if swconn else []
    job = swconn.normalize_native_extract(records) if swconn else None

    opened = [r for r in records if not r.get("errors")]
    parts = [r for r in records if r.get("doctype") == swconn.SW_PART] if swconn else []
    parts_with_mat = sum(
        1 for r in parts
        if isinstance(r.get("route_signals"), dict) and (r["route_signals"].get("material"))
    )
    n_parts = len(parts)
    bom_rows = len(job.bom) if job else 0
    mat_cov = (parts_with_mat / n_parts) if n_parts else 0.0

    flags: List[str] = []
    if not records:
        flags.append("NO_NATIVE_MODELS")             # 2D-only or unreadable — falls back to PDF/DXF
    if records and bom_rows == 0:
        flags.append("NO_BOM")                        # no top assembly / empty tree
    if n_parts and mat_cov < 0.8:
        flags.append(f"LOW_MATERIAL_COVERAGE({parts_with_mat}/{n_parts})")
    _open_fail = [r for r in records if r.get("errors")]
    if _open_fail:
        flags.append(f"OPEN_FAILURES({len(_open_fail)})")

    return {
        "job": folder.name,
        "path": str(folder),
        "records": len(records),
        "opened": len(opened),
        "parts": n_parts,
        "material_coverage": round(mat_cov, 2),
        "bom_rows": bom_rows,
        "weld_candidates": (job.meta.get("counts", {}).get("weld_candidates", 0) if job else 0),
        "top_assembly": (job.meta.get("top_assembly") if job else None),
        "flags": flags,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Batch native-extract health across many jobs.")
    ap.add_argument("--root", help="Discover job folders (dirs with .SLDPRT/.SLDASM) under here.")
    ap.add_argument("--jobs", nargs="+", help="Explicit job folders instead of --root discovery.")
    ap.add_argument("--out", default="_sw_batch_health.json", help="Health report JSON path.")
    ap.add_argument("--no-run", action="store_true",
                    help="Reuse existing _sw_native_extract.json; do not launch SolidWorks.")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N jobs.")
    args = ap.parse_args(argv)

    if swconn is None:
        _log(f"[FATAL] could not import source_connectors.solidworks: {_CONN_ERR}")
        return 3
    python_exe = os.environ.get("SDI_PYTHON_EXE") or sys.executable or "python"

    if args.jobs:
        folders = [Path(j) for j in args.jobs]
    elif args.root:
        _log(f"Discovering job folders under {args.root} ...")
        folders = discover_job_folders(Path(args.root))
    else:
        _log("Provide --root or --jobs.")
        return 2
    if args.limit:
        folders = folders[: args.limit]
    if not folders:
        _log("No job folders found.")
        return 1
    _log(f"{len(folders)} job folder(s). Running extractor{' (reuse cache)' if args.no_run else ''} ...")

    results = []
    for i, folder in enumerate(folders, 1):
        _log(f"[{i}/{len(folders)}] {folder.name}")
        try:
            results.append(health_for_job(folder, run=not args.no_run, python_exe=python_exe))
        except Exception as e:
            results.append({"job": folder.name, "path": str(folder), "flags": [f"CRASH:{e!r}"]})

    flagged = [r for r in results if r.get("flags")]
    report = {
        "root": args.root,
        "jobs": len(results),
        "flagged": len(flagged),
        "summary": {
            "clean": len(results) - len(flagged),
            "no_native_models": sum(1 for r in results if "NO_NATIVE_MODELS" in r.get("flags", [])),
            "no_bom": sum(1 for r in results if "NO_BOM" in r.get("flags", [])),
            "low_material": sum(1 for r in results if any("LOW_MATERIAL" in f for f in r.get("flags", []))),
            "open_failures": sum(1 for r in results if any("OPEN_FAILURES" in f for f in r.get("flags", []))),
        },
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    _log("")
    _log(f"{'JOB':<44} {'PARTS':>5} {'MAT%':>5} {'BOM':>4}  FLAGS")
    _log("-" * 90)
    for r in results:
        _log(f"{r.get('job','?')[:44]:<44} {r.get('parts',0):>5} "
             f"{int(r.get('material_coverage',0)*100):>4}% {r.get('bom_rows',0):>4}  "
             f"{', '.join(r.get('flags') or []) or 'ok'}")
    _log("")
    _log(f"── {report['summary']['clean']}/{report['jobs']} clean · {report['flagged']} flagged for review ──")
    _log(f"   no-native:{report['summary']['no_native_models']}  no-bom:{report['summary']['no_bom']}  "
         f"low-material:{report['summary']['low_material']}  open-fail:{report['summary']['open_failures']}")
    _log(f"Full report: {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
