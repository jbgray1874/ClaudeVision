#!/usr/bin/env python3
r"""Several machine profiles, in one table you can size a server from.

    python tools/collate_machine_profiles.py <folder with the .json files>

Each developer runs tools/machine_profile.ps1 and sends back one JSON. This puts them side by
side, because the argument about what to buy is only settled by seeing the runner and the
laptops in the same table — and because a machine that never runs an estimate has nothing to
say about what an estimate needs, which is visible at a glance once the load columns are there.

Prints two tables: what each machine IS, and what a run COST it. The second is empty for
anyone who ran the spec half only, and says so rather than leaving a blank that reads as zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

_SPEC = [("Machine", "Machine"), ("Role", "Role"), ("CPU", "CPU"),
         ("Cores", "CPU_Cores"), ("Threads", "CPU_Threads"), ("RAM GB", "RAM_GB"),
         ("GPU", "GPU"), ("Disk", "Disks")]

_LOAD = [("Machine", "Machine"), ("Samples", "Load_Samples"),
         ("Peak CPU %", "Load_PeakCPU_Pct"), ("Min free RAM GB", "Load_MinFreeRAM_GB"),
         ("Peak per process", "Load_PeakProcessMB")]


def _load(folder: Path) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(folder.glob("machine_profile_*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception as exc:                                 # noqa: BLE001
            print(f"skipped {path.name}: {exc}")
    return out


def _table(rows: List[Dict[str, Any]], columns) -> str:
    header = [label for label, _ in columns]
    body = [[str(r.get(key) if r.get(key) not in (None, "") else "—")[:48]
             for _, key in columns] for r in rows]
    widths = [max(len(header[i]), *(len(b[i]) for b in body)) if body else len(header[i])
              for i in range(len(header))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    rule = "  ".join("-" * widths[i] for i in range(len(header)))
    return "\n".join([line, rule] + ["  ".join(b[i].ljust(widths[i])
                                               for i in range(len(header))) for b in body])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=Path)
    args = ap.parse_args()

    rows = _load(args.folder)
    if not rows:
        raise SystemExit(f"no machine_profile_*.json found in {args.folder}")

    print("\nWHAT EACH MACHINE IS\n")
    print(_table(rows, _SPEC))

    measured = [r for r in rows if (r.get("Load_Samples") or 0) > 0]
    print("\n\nWHAT A RUN COST IT\n")
    if measured:
        print(_table(measured, _LOAD))
    else:
        print("Nobody sampled under load. Re-run with -Watch 45 DURING an estimate — the "
              "spec half says what you own, not what you need.")
    skipped = len(rows) - len(measured)
    if measured and skipped:
        print(f"\n{skipped} machine(s) reported spec only and are not in this table.")
    print()


if __name__ == "__main__":
    main()
