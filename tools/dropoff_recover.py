#!/usr/bin/env python3
"""Recover a review copy of a pack that was kept without every file found for it.

PREVIEW FIRST. With no --apply it only reads and prints what it would do:

    .\\.venv\\Scripts\\python.exe tools\\dropoff_recover.py "chatgptdropoff\\<client>\\<pack folder>"

With --apply it writes a NEW version beside the pack ("<name> v2"), holding the kept files
and each absent file whose source still carries the fingerprint recorded when the pack was
gathered. The original folder, its manifest and its runs' evidence are not written to. No
estimate is rerun. A file whose source has gone or changed is listed and left out.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
import pack_dropoff  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+", help="kept pack folder(s) under the drop-off")
    ap.add_argument("--apply", action="store_true", help="write the new version (default: preview)")
    args = ap.parse_args(argv)
    bad = 0
    for folder in args.folders:
        plan = pack_dropoff.recover(folder) if args.apply else pack_dropoff.recovery_plan(folder)
        print(f"\n{plan['folder']}")
        print(f"  kept files verified against their checksums: {plan['kept']}")
        for a in plan["add"]:
            print(f"  recoverable   {a['name']}  <-  {a['source_path']}")
        for c in plan["cannot"]:
            print(f"  NOT recovered {c['name']}: {c['why']}")
        if not plan["ok"]:
            print(f"  nothing to do: {plan['why']}")
            bad += bool(plan["cannot"])
        elif plan.get("created"):
            print(f"  CREATED {plan['created']}  (the original folder was not changed)")
        else:
            print(f"  PREVIEW ONLY. --apply would create {plan['would_create']} and leave the original as it is.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
