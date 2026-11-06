"""Build the index the TTi folder search reads. Reads the folders; changes nothing in them.

    python tools/tti_index_folders.py

Run it on the server from Task Scheduler, overnight and at lunchtime, say:
searches are only as current as the last build, and every answer says when that
was. The folders come from SDI_TTI_FOLDERS (default: the Design, Production and
Prototype TTi folders on W:), and W: needs its network path in SDI_DRIVE_MAP.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv                          # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import tti_files                                        # noqa: E402


def main() -> int:
    roots = tti_files.folders()
    print(f"Indexing {len(roots)} folder(s) into {tti_files.index_path()}")
    for r in roots:
        print(f"  {r['label']:<12} {r['shown']}  ->  {r['unc']}"
              + (f"\n    PROBLEM: {r['problem']}" if r["problem"] else ""))
    result = tti_files.build(roots)
    print(f"Done: {result['entries']} entries in {result['seconds']} s, built {result['built']}")
    st = tti_files.status()
    return 0 if all(not f["problem"] for f in st["folders"]) else 2


if __name__ == "__main__":
    sys.exit(main())
