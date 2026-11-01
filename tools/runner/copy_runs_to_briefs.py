#!/usr/bin/env python3
r"""Copy finished runs already filed in AISheets to the completed AI briefs area (D-617a).

    python tools\runner\copy_runs_to_briefs.py --client "M&S" --from 2026-10-31 --to 2026-10-31
    python tools\runner\copy_runs_to_briefs.py --client "M&S" --from 2026-10-31 --to 2026-10-31 --apply

D-617 files every run that finishes from now on to completed AI briefs\<client area>\<job pack>\
<date time> v<N> (<units> off). JG, 1 Nov 2026: "yes, copy the six from 31 Oct." This does the
same for runs already in AISheets\<client>\<drawing>\<date time (N off)>, with the runner's own
rules (runner.file_a_copy): the same stamp, the next version, the client area matched without
case or punctuation, nothing ever written over.

PREVIEW UNLESS --apply. It lists every run it would copy and why any is skipped: not in the
date range, another client, no workbook in the folder (a run that failed), or already copied
(a folder under the pack starting with the same stamp). Running it twice copies nothing twice.
It only reads AISheets.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sdi_estimate_runner as runner  # noqa: E402  — loads .env, and owns the folder rules

AISHEETS_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"
BRIEFS_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries"
                  r"\completed AI briefs")
_RUN_FOLDER = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}) \((\d+) off\)$")


def _day(text: Optional[str]) -> Optional[date]:
    return datetime.strptime(text, "%Y-%m-%d").date() if text else None


def finished_runs(aisheets: Path) -> List[Dict[str, Any]]:
    """Every run folder under AISheets\\<client>\\<drawing>\\, with what it holds."""
    out: List[Dict[str, Any]] = []
    for client in sorted(p for p in aisheets.iterdir() if p.is_dir()):
        for drawing in sorted(p for p in client.iterdir() if p.is_dir()):
            for folder in sorted(p for p in drawing.iterdir() if p.is_dir()):
                m = _RUN_FOLDER.match(folder.name)
                if not m:
                    continue
                files = sorted(p for p in folder.iterdir() if p.is_file())
                out.append({"client": client.name, "drawing": drawing.name, "folder": folder,
                            "stamp": m.group(1), "units": int(m.group(2)), "files": files,
                            "day": datetime.strptime(m.group(1)[:10], "%Y-%m-%d").date(),
                            "has_workbook": any(f.suffix.lower() == ".xlsx" for f in files)})
    return out


def already_copied(briefs: Path, run: Dict[str, Any]) -> Optional[Path]:
    pack = runner.client_area(briefs, run["client"]) / runner._archive_segment(run["drawing"])
    if not pack.is_dir():
        return None
    return next((p for p in pack.iterdir()
                 if p.is_dir() and p.name.startswith(run["stamp"] + " v")), None)


def plan(aisheets: Path, briefs: Path, client: str = "", start: Optional[date] = None,
         end: Optional[date] = None, drawings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Each run with `action`: copy, or skip and why."""
    want_client = runner._bare(client)
    want_drawings = {runner._bare(d) for d in drawings or [] if d.strip()}
    out = []
    for run in finished_runs(aisheets):
        why = ""
        if start and run["day"] < start or end and run["day"] > end:
            why = "outside the dates asked for"
        elif want_client and runner._bare(run["client"]) != want_client:
            why = "another client"
        elif want_drawings and runner._bare(run["drawing"]) not in want_drawings:
            why = "another drawing"
        elif not run["has_workbook"]:
            why = "no workbook in the folder: the run did not finish with an estimate"
        else:
            done = already_copied(briefs, run)
            if done is not None:
                why = f"already copied to {done}"
        out.append(dict(run, action="skip" if why else "copy", why=why))
    return out


def apply(briefs: Path, run: Dict[str, Any]) -> str:
    log: List[str] = []
    folder = runner.file_a_copy(
        {"archive_root": str(briefs), "client": run["client"], "drawing_number": run["drawing"],
         "units": run["units"], "archive_stamp": run["stamp"]},
        [{"name": f.name, "path": str(f)} for f in run["files"]], log)
    for line in log:
        print("      " + line)
    return folder


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--client", default="", help="only this client's folder, e.g. \"M&S\"")
    ap.add_argument("--from", dest="start", default="", help="first day, YYYY-MM-DD")
    ap.add_argument("--to", dest="end", default="", help="last day, YYYY-MM-DD")
    ap.add_argument("--drawing", action="append", default=[], help="only this drawing (repeat)")
    ap.add_argument("--aisheets", default=os.getenv("SDI_ESTIMATE_OUTPUT_ROOT", "")
                    or AISHEETS_DEFAULT)
    ap.add_argument("--briefs", default=os.getenv("SDI_COMPLETED_AI_BRIEFS_ROOT", "")
                    or BRIEFS_DEFAULT)
    ap.add_argument("--apply", action="store_true", help="copy; without it, only preview")
    a = ap.parse_args(argv)
    aisheets, briefs = Path(a.aisheets), Path(a.briefs)
    if not aisheets.is_dir():
        print(f"AISheets is not reachable: {aisheets}")
        return 2
    runs = plan(aisheets, briefs, a.client, _day(a.start), _day(a.end), a.drawing)
    to_copy = [r for r in runs if r["action"] == "copy"]
    shown = [r for r in runs if r["action"] == "copy" or not r["why"].startswith(
        ("outside the dates", "another client", "another drawing"))]
    print(f"From  {aisheets}\nTo    {briefs}\n")
    for r in shown:
        where = f"{r['client']}\\{r['drawing']}\\{r['folder'].name}"
        print(f"  {'COPY' if r['action'] == 'copy' else 'skip'}  {where}"
              + (f"  ({r['why']})" if r["why"] else f"  {len(r['files'])} files"))
        if a.apply and r["action"] == "copy":
            apply(briefs, r)
    print(f"\n{len(to_copy)} run(s) to copy" + ("" if a.apply else
          ". Nothing was copied: add --apply to copy them."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
