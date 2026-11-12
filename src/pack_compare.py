#!/usr/bin/env python3
"""Is the resolver's drawing pack the pack the job needed? Checked against Live Enquiry (JG, 11 Nov 2026).

"we have an issue with other jobs ran today and yesterday not having the full drawing packs?
all of them have live enquiry for us to train our extract on ... the ones in the
K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry folders for the 9 / 10 ran yesterday. we
need to be able to re create that extraction."

Each job's folder under Live Enquiry\\<client>\\<drawing> is compared with what the resolver
finds for that drawing NOW, file by file:

  found by both        the resolver would gather it
  missed               in the folder, not gathered: the extraction to fix
  added                gathered, not in the folder: a part the folder lacks, or one it should not take
  different copy       same name, different file

WHO MADE THE FOLDER DECIDES WHAT IT PROVES. A folder with no pack_manifest.json of ours was put
together by a person (or the old collector): it is the reference, and every file it holds that
the resolver misses is a fault. A folder with our manifest was made by the resolver itself: it
shows what an earlier run was given, and "added" there is what the resolver now finds beyond it.
Several versions ("<drawing> v2") are all compared; the latest is the one a rerun would use.

    python src/pack_compare.py                       every job folder under Live Enquiry
    python src/pack_compare.py --since 2026-11-10    folders changed since a date
    python src/pack_compare.py --drawing 11896-04-00-GA
    python src/pack_compare.py --json out.json       the full comparison as JSON

Reads only; nothing is copied, moved or written except the JSON asked for.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pack_resolver as pr  # noqa: E402
import pack_store as ps     # noqa: E402

# eDrawings files are drawings too, saved beside the CAD in some packs.
COMPARED_EXT = set(pr.DRAWING_EXT) | {".easm", ".eprt", ".edrw", ".eprtx", ".easmx", ".edrwx"}
_VERSION = re.compile(r"^(?P<base>.+?) v(?P<n>\d+)$")


def folder_files(folder: Path) -> Dict[str, Tuple[int, float]]:
    """name (lower case) -> (size, modified) for the drawing files in a job folder and below."""
    out: Dict[str, Tuple[int, float]] = {}
    for p in sorted(folder.rglob("*")):
        try:
            if p.is_file() and p.suffix.lower() in COMPARED_EXT:
                st = p.stat()
                out.setdefault(p.name.lower(), (int(st.st_size), float(st.st_mtime)))
        except OSError:
            continue
    return out


def made_by(folder: Path) -> Dict[str, Any]:
    """Whether the resolver made this folder, and when; a folder without its manifest is a person's."""
    m = folder / ps.MANIFEST
    if not m.is_file():
        return {"by": "person", "at": None}
    try:
        data = json.loads(m.read_text(encoding="utf-8"))
        stored = data.get("stored") or {}
        return {"by": "resolver", "at": stored.get("at") or data.get("resolved_at"),
                "status": data.get("status")}
    except (OSError, ValueError):
        return {"by": "resolver", "at": None}


def resolver_files(manifest: Dict[str, Any]) -> Dict[str, Tuple[int, str]]:
    """name (lower case) -> (size, path) for every file the resolver's pack holds."""
    out: Dict[str, Tuple[int, str]] = {}
    for m in manifest.get("members") or []:
        for f in m.get("files") or []:
            p = Path(str(f.get("path") or ""))
            out.setdefault(p.name.lower(), (int(f.get("size") or 0), str(p)))
    return out


def compare(folder: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    have = folder_files(folder)
    got = resolver_files(manifest)
    both = sorted(set(have) & set(got))
    different = sorted(n for n in both if got[n][0] and have[n][0] != got[n][0])
    who = made_by(folder)
    return {"folder": str(folder), "made_by": who["by"], "made_at": who.get("at"),
            "in_folder": len(have), "resolver": len(got),
            "found_by_both": len(both), "missed": sorted(set(have) - set(got)),
            "added": sorted(set(got) - set(have)), "different_copy": different,
            "resolver_status": manifest.get("status"), "resolver_missing": list(manifest.get("missing") or []),
            "parts_list_read": bool(manifest.get("references_read")),
            "pdfs_read": manifest.get("pdfs_read"),
            "unread_assemblies": list(manifest.get("unread_assemblies") or []),
            "configurations_unconfirmed": bool(manifest.get("configurations_unconfirmed")),
            "selected_folder": manifest.get("selected_folder"), "question": manifest.get("question") or ""}


def job_folders(root: Path, since: Optional[datetime] = None, drawing: str = "",
                client: str = "") -> List[Tuple[str, str, Path]]:
    """(client, drawing, folder) for every job folder under the store, every version."""
    out: List[Tuple[str, str, Path]] = []
    try:
        clients = [c for c in root.iterdir() if c.is_dir()]
    except OSError:
        return out
    for c in sorted(clients):
        if client and c.name.lower() != client.lower():
            continue
        try:
            jobs = [j for j in c.iterdir() if j.is_dir()]
        except OSError:
            continue
        for j in sorted(jobs):
            m = _VERSION.match(j.name)
            base = m.group("base") if m else j.name
            if drawing and not pr._same(base, drawing):
                continue
            if since is not None:
                # THE FOLDER'S OWN DATE, NOT ITS FILES' (11 Nov 2026): a copied drawing keeps the
                # date it had on W:, so a pack filled by hand yesterday looked months old and was
                # skipped. The folder's created and changed dates say when it was filled.
                try:
                    st = j.stat()
                    when = max(st.st_mtime, st.st_ctime)
                    for sub in j.iterdir():
                        sst = sub.stat()
                        when = max(when, sst.st_ctime)
                except OSError:
                    continue
                if datetime.fromtimestamp(when) < since:
                    continue
            out.append((c.name, base, j))
    return out


def run(root: Path, since: Optional[datetime] = None, drawing: str = "", client: str = "",
        resolve: Optional[Callable[[str, str], Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The comparison for every job folder found; `resolve(drawing, client)` gives the manifest."""
    if resolve is None:
        def resolve(d: str, cl: str) -> Dict[str, Any]:
            rows, _src, lookup = pr.folders_for(d)
            return pr.resolve(d, rows, client=cl, lookup=lookup)
    cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    out = []
    for cl, base, folder in job_folders(root, since, drawing, client):
        key = (base.upper(), cl.upper())
        if key not in cache:
            try:
                cache[key] = resolve(base, cl)
            except Exception as exc:                                     # noqa: BLE001
                cache[key] = {"status": "error", "question": f"{type(exc).__name__}: {exc}", "members": []}
        row = compare(folder, cache[key])
        row.update(client=cl, drawing=base)
        out.append(row)
    return out


def verdict(row: Dict[str, Any]) -> str:
    if row.get("resolver_status") in ("error", "not found"):
        return "resolver found no pack"
    if row["made_by"] == "person" and row["missed"]:
        return f"MISSES {len(row['missed'])} file(s) the estimator's pack holds"
    if row["made_by"] == "resolver" and row["added"]:
        return f"now finds {len(row['added'])} more than this folder was given"
    if row["missed"]:
        return f"{len(row['missed'])} file(s) here not found now"
    # THE SAME FILES IS NOT A COMPLETE PACK (reviewer, 12 Nov 2026): 11896-04-00-GA "matched" the
    # folder an earlier run of the resolver had made, on zero drawings read. Agreement with our
    # own earlier pack proves nothing, and neither folder is complete unless the GA's parts
    # list was read and nothing it calls for is missing.
    if not row.get("parts_list_read"):
        return "same files; COMPLETENESS NOT PROVED: the GA's parts list was not read"
    if row.get("resolver_missing"):
        return f"same files; INCOMPLETE: {len(row['resolver_missing'])} referenced drawing(s) not found"
    if row["made_by"] == "resolver":
        return "same files as the earlier resolver pack; parts list read, nothing missing"
    return "matches the estimator's pack; parts list read, nothing missing"


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default="", help="the Live Enquiry folder (default the pack store)")
    ap.add_argument("--since", default="", help="only folders changed on or after this date, e.g. 2026-11-10")
    ap.add_argument("--drawing", default="")
    ap.add_argument("--client", default="")
    ap.add_argument("--json", default="", help="write the full comparison here")
    ap.add_argument("--list", type=int, default=8, help="file names listed per job for missed and added")
    a = ap.parse_args(list(argv) if argv is not None else None)
    root = Path(a.root) if a.root else ps.store_root()
    since = datetime.fromisoformat(a.since) if a.since else None
    rows = run(root, since, a.drawing, a.client)
    print(f"Live Enquiry: {root}  ({len(rows)} job folder(s))")
    for r in rows:
        print(f"\n{r['client']} / {Path(r['folder']).name}   made by {r['made_by']}"
              + (f" at {r['made_at']}" if r.get("made_at") else ""))
        print(f"  folder {r['in_folder']} file(s); resolver {r['resolver']} ({r['resolver_status']}); "
              f"both {r['found_by_both']}  ->  {verdict(r)}")
        for label, names in (("missed", r["missed"]), ("added", r["added"]), ("different copy", r["different_copy"])):
            if names:
                more = f" ... +{len(names) - a.list} more" if len(names) > a.list else ""
                print(f"  {label}: " + ", ".join(names[:a.list]) + more)
        if r.get("unread_assemblies"):
            print("  sub-assemblies with no readable drawing: " + ", ".join(r["unread_assemblies"][:a.list]))
        if r.get("configurations_unconfirmed"):
            print("  its sheets may be alternative configurations: confirm before parts are added together")
        if r.get("resolver_missing"):
            print("  referenced, no drawing anywhere: " + ", ".join(r["resolver_missing"][:a.list]))
        if r.get("question"):
            print(f"  asks: {r['question']}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nfull comparison: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
