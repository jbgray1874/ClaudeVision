#!/usr/bin/env python3
"""File a finished run's record, note, walkthrough and report with it. Shows the changes first (12 Nov 2026).

Three estimates from the second runner were e-mailed as "not reported/unit" over a list of
files. Each run had finished: its record, covering note, walkthrough and report were written
beside its workbook in the main checkout's estimates folder, and the collector, looking only
in its own tree, never filed them. The reviewer: "Recover the existing deliverables against
their exact run IDs, previewing changes first. No recalculation solely to repair an email,
and no automatic resend."

For every saved run that finished with a workbook and no pinned record of its own, it looks
for that workbook's files in the estimates folder(s) given and proposes:
  copy   each file into the folder the run's workbook was filed in (nothing is overwritten)
  list   each with the run, so the page, the audit and price_correct can see them
and only where the record beside the workbook says it is this portal run and this drawing.
The price is then put back from that record by price_correct.py, which shows its own changes.

What it never does: recalculate, re-send, delete, move or overwrite a file, or touch a run
whose record names another run or another drawing (listed, unchanged).

    python src/bundle_recover.py                     the proposal, nothing changed
    python src/bundle_recover.py --apply             apply it; each saved run is copied first
                                                     to <runs>/corrections/<run_id>.<time>.before.json
    python src/bundle_recover.py --only <run_id>     one run (may repeat)
    python src/bundle_recover.py --from <folder>     where the engine wrote (may repeat);
                                                     default <checkout>/output/estimates

The services read saved runs when they start, so restart them after --apply.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import own_record as orc  # noqa: E402


def _record_says(record: Dict[str, Any]) -> Dict[str, str]:
    """The portal run and drawing a pinned record names (run_provenance, main.py D-601)."""
    prov = record.get("run_provenance") if isinstance(record.get("run_provenance"), dict) else {}
    scope = prov.get("submitted_scope") if isinstance(prov.get("submitted_scope"), dict) else {}
    got = prov.get("received_scope") if isinstance(prov.get("received_scope"), dict) else {}
    return {"run_id": str(prov.get("service_run_id") or "").strip(),
            "drawing": str(scope.get("drawing_number") or got.get("drawing_number")
                           or scope.get("drawing") or got.get("drawing") or "").strip()}


def proposal(run: Dict[str, Any], sources: List[Path]) -> Optional[Dict[str, Any]]:
    """What to file with one saved run, or None when it lacks nothing (or has no workbook)."""
    if run.get("status") != "done":
        return None
    files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
    drawing, started = str(run.get("drawing_number") or ""), float(run.get("started_at") or 0.0)
    book, _why = orc.own_book(files, drawing, started)
    if not book:
        return None
    rec, _ = orc.own_record(files, drawing, started)
    if rec is not None:
        return None                                   # its record is filed: nothing was lost
    filed_book = next((Path(str(d.get("path") or "")) for d in files if str(d.get("name")) == book), None)
    if filed_book is None:
        return None
    have = {str(d.get("name") or "").lower() for d in files}
    found: List[Path] = []
    where = None
    for folder in sources:
        src_book = Path(folder) / book
        if src_book.is_file():
            where = Path(folder)
            found = [p for p in orc.beside_the_book(src_book, started) if p.name.lower() not in have]
            break
    out: Dict[str, Any] = {"run_id": run.get("run_id"), "drawing": drawing, "workbook": book,
                           "filed_in": str(filed_book.parent), "from": str(where) if where else "",
                           "add": [], "held": ""}
    if where is None:
        out["held"] = f"{book} is not in {', '.join(map(str, sources))}: nothing to recover from"
        return out
    record_path = next((p for p in found if p.name.lower() == (book[:-5] + "_record.json").lower()), None)
    if record_path is None:
        out["held"] = f"no {book[:-5]}_record.json beside the workbook in {where}"
        return out
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["held"] = f"its record could not be read: {exc}"
        return out
    says = _record_says(record)
    if says["run_id"] and says["run_id"] != str(run.get("run_id")):
        out["held"] = f"the record beside it names portal run {says['run_id']}, not this run"
        return out
    if says["drawing"] and orc._key(says["drawing"]) != orc._key(drawing):
        out["held"] = f"the record beside it is for {says['drawing']}, not {drawing}"
        return out
    out["proved_by"] = ("its record names this portal run" if says["run_id"]
                        else "its record is named for this run's workbook (it names no portal run)")
    out["add"] = [{"name": p.name, "from": str(p), "to": str(filed_book.parent / p.name),
                   "exists": (filed_book.parent / p.name).exists()} for p in found]
    out["record"] = str(record_path)
    return out


def apply_one(run: Dict[str, Any], prop: Dict[str, Any], when: str) -> Dict[str, Any]:
    out = dict(run)
    files = list(run.get("deliverables") or [])
    for a in prop["add"]:
        dest = Path(a["to"])
        if not dest.exists():                          # never overwrite
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a["from"], dest)
        files.append({"name": a["name"], "path": str(dest)})
    out["deliverables"] = files
    out["log"] = list(run.get("log") or []) + [
        f"[recovered {when}] {len(prop['add'])} file(s) this run wrote beside its workbook in "
        f"{prop['from']} were filed with it ({prop.get('proved_by')}); nothing was recalculated "
        f"or re-sent. The saved run as it was is in corrections/."]
    out["recovered_at"] = when
    return out


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="")
    ap.add_argument("--from", dest="sources", action="append", default=[])
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.runs:
        folder = Path(a.runs)
    else:
        sys.path.insert(0, str(HERE.parent / "sdi-intelligence-backend"))
        import estimate_history  # noqa: PLC0415
        folder = estimate_history.store_dir()
    sources = [Path(s) for s in a.sources] or [HERE.parent / "output" / "estimates"]
    print(f"runs    {folder}\nlooking in  {', '.join(map(str, sources))}")
    props = []
    for path in sorted(folder.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rid = str(run.get("run_id") or path.stem)
        if a.only and rid not in a.only:
            continue
        prop = proposal(run, sources)
        if not prop:
            continue
        print(f"\n{prop['drawing']}  run {rid}   workbook {prop['workbook']}")
        if prop["held"]:
            print(f"  LEFT AS IT IS: {prop['held']}")
            continue
        print(f"  proved: {prop['proved_by']}")
        print(f"  file with the run, in {prop['filed_in']}:")
        for x in prop["add"]:
            print(f"    {x['name']}" + ("   (already there: listed, not copied)" if x["exists"] else ""))
        props.append((path, run, prop))
    print(f"\n{len(props)} run(s) to recover.")
    if not a.apply:
        print("Nothing was changed. Run again with --apply to file these. Then run "
              "price_correct.py to put each run's price back from its record, and restart the services.")
        return 0
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    keep = folder / "corrections"
    keep.mkdir(parents=True, exist_ok=True)
    for path, run, prop in props:
        shutil.copy2(path, keep / f"{path.stem}.{time.strftime('%Y%m%d_%H%M%S')}.before.json")
        new = apply_one(run, prop, when)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new, indent=1), encoding="utf-8")
        tmp.replace(path)
        print(f"  recovered {prop['drawing']} run {prop['run_id']}: {len(prop['add'])} file(s)")
    print("Nothing was recalculated or re-sent. Now run price_correct.py, then restart the services.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
