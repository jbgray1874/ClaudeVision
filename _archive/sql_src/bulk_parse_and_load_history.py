from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def _parse_all(history_root: Path, src_dir: Path, exts: List[str]) -> int:
    files = []
    for ext in exts:
        files.extend(history_root.rglob(f"*{ext}"))
    files = sorted({p.resolve() for p in files if p.is_file()})
    ok = 0
    for wb in files:
        cmd = [sys.executable, str(src_dir / "main.py"), "--parse-estimate-template", str(wb)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            ok += 1
        else:
            sys.stderr.write(f"PARSE_FAIL\t{wb}\t{proc.stderr.strip()}\n")
    return ok


def _load_all(history_root: Path, src_dir: Path, write_sidecar: bool) -> int:
    cmd = [sys.executable, str(src_dir / "load_historical_quotes.py"), "--root", str(history_root)]
    if write_sidecar:
        cmd.append("--write-sidecar-reconciliation")
    proc = subprocess.run(cmd, text=True)
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk parse historical spreadsheets then load parse JSON into SQL.")
    parser.add_argument("--root", required=True, help="History folder containing spreadsheet files")
    parser.add_argument("--src-dir", default=str(Path(__file__).resolve().parent), help="src folder containing main.py/load_historical_quotes.py")
    parser.add_argument("--extensions", default=".xlsx,.xlsm,.xls", help="Comma-separated spreadsheet extensions")
    parser.add_argument("--skip-parse", action="store_true", help="Skip parse stage and only run load")
    parser.add_argument("--write-sidecar-reconciliation", action="store_true", help="Write sidecar reconciliation JSON files during load")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    src_dir = Path(args.src_dir).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")
    exts = [e.strip().lower() for e in args.extensions.split(",") if e.strip()]

    parsed_ok = 0
    if not args.skip_parse:
        parsed_ok = _parse_all(root, src_dir, exts)
        print(f"Parsed spreadsheets: {parsed_ok}")

    rc = _load_all(root, src_dir, write_sidecar=args.write_sidecar_reconciliation)
    if rc != 0:
        raise SystemExit(rc)
    print("Bulk parse + load completed.")


if __name__ == "__main__":
    main()

