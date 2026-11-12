#!/usr/bin/env python3
"""A job's drawing pack as the resolver finds it: classed, and frozen as a regression fixture
(JG and the reviewer, 12 Nov 2026).

"Turn the independently checked packs into regression fixtures for normal estimates,
Self-Running and TTI. Report each job as scope supported, provisional with named gaps, or
incorrect pack - repair required."

THE THREE CLASSES, from the resolver's manifest and nothing else:

  scope supported               the GA is chosen without a rival, its parts list was read (from
                                the GA or its sheets), every drawing it calls for is in the pack,
                                and no sub-assembly went unread
  provisional with named gaps   the pack can be priced, with each gap named: a referenced
                                drawing with no file, a bought-in item still to price, a sub-
                                assembly with no readable drawing, files in its folders that
                                belong to no drawing, sheets that may be alternatives
  incorrect pack: repair required   no pack was found, two copies claim to be the issue, or the
                                GA's parts list was never read, so what it calls for is unknown

A FIXTURE is everything the resolver looked at for one drawing (the folder listings, the index
lookups it made, the text of each PDF it read) with what it concluded. Replaying it needs no
share. It is saved on this machine only, under tests/pack_fixtures_local (never committed: file
names and drawing text are the customer's). A fixture says who checked it; until a person has,
it guards against change but proves nothing about being right.

    python src/pack_fixture.py report 6364-01 6364-02 11896-02-01-GA      class each, now
    python src/pack_fixture.py save 11896-04-00-GA --client TTI            freeze one
    python src/pack_fixture.py checked 11896-04-00-GA --by "name" --note "..."   after a person has looked
    python src/pack_fixture.py verify                                      replay every fixture

One resolver serves normal estimates, Self-Running and the TTI tracker, so one fixture covers
all three ways in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pack_resolver as pr  # noqa: E402

SUPPORTED = "scope supported"
PROVISIONAL = "provisional with named gaps"
INCORRECT = "incorrect pack: repair required"
SCHEMA = "pack_fixture.v1"


def fixtures_dir() -> Path:
    return Path(os.environ.get("SDI_PACK_FIXTURES") or HERE.parent / "tests" / "pack_fixtures_local")


def classify(m: Dict[str, Any]) -> Tuple[str, List[str]]:
    """(class, the gaps or faults that put it there)."""
    status = str(m.get("status") or "")
    if status in ("not found", "error") or not m.get("members"):
        return INCORRECT, [m.get("question") or "no pack was found for this drawing"]
    if m.get("conflicts"):
        return INCORRECT, ["two copies claim to be the issue: " + "; ".join(m["conflicts"][:3])]
    if not m.get("references_read"):
        return INCORRECT, ["the GA's parts list was not read (no readable PDF of the GA or its sheets), "
                           "so the drawings it calls for are unknown"]
    gaps: List[str] = []
    if m.get("missing"):
        gaps.append("referenced, no drawing found: " + ", ".join(m["missing"]))
    if m.get("bought_in_unmatched"):
        gaps.append("bought-in, still to price: " + ", ".join(m["bought_in_unmatched"]))
    if m.get("unread_assemblies"):
        gaps.append("sub-assembly with no readable drawing, parts not followed: " + ", ".join(m["unread_assemblies"]))
    if m.get("unassigned_files"):
        gaps.append("files in its folders belonging to no drawing, not used: "
                    + ", ".join(Path(str(u.get("path"))).name for u in m["unassigned_files"][:8]))
    if m.get("configurations_unconfirmed"):
        gaps.append("its sheets may be alternative configurations: " + ", ".join(sorted(m.get("sheet_references") or {})))
    if m.get("identity") != "verified":
        gaps.append("the GA is matched by file name; its own title block did not confirm number and revision")
    return (PROVISIONAL if gaps else SUPPORTED), gaps


def summary(m: Dict[str, Any]) -> Dict[str, Any]:
    """What a fixture expects, and what a report prints: names only."""
    cls, gaps = classify(m)
    return {"class": cls, "gaps": gaps, "status": m.get("status"), "selected_folder": m.get("selected_folder"),
            "revision": m.get("revision") or "",
            "members": {x["drawing"]: sorted({f["format"] for f in x.get("files") or []}) for x in m.get("members") or []},
            "parents": {x["drawing"]: x.get("parent") or "" for x in m.get("members") or []},
            "missing": sorted(m.get("missing") or []), "bought_in_unmatched": sorted(m.get("bought_in_unmatched") or []),
            "sheets_read": list(m.get("sheets_read") or []), "sheet_references": m.get("sheet_references") or {},
            "unread_assemblies": list(m.get("unread_assemblies") or []),
            "unassigned_files": sorted(Path(str(u.get("path"))).name for u in m.get("unassigned_files") or []),
            "pdfs_read": m.get("pdfs_read")}


def capture(drawing: str, client: str = "", folders: Optional[List[Any]] = None,
            lookup: Optional[Callable[[str], List[Any]]] = None,
            read_text: Callable[[Path], str] = pr.read_pdf_text,
            area_rank: Optional[Callable[[Path], int]] = None, source: str = "") -> Dict[str, Any]:
    """Resolve one drawing and keep everything the resolver looked at."""
    if folders is None:
        folders, source, lookup = pr.folders_for(drawing)
    rank = area_rank or pr._default_area_rank()
    looked: Dict[str, List[Any]] = {}
    texts: Dict[str, str] = {}

    def _lookup(did: str) -> List[Any]:
        rows = list(lookup(did)) if lookup else []
        looked[str(did)] = [[str(p), int(s), float(t)] for p, s, t in rows]
        return rows

    def _read(path: Path) -> str:
        text = read_text(path)
        texts[str(path)] = text
        return text

    m = pr.resolve(drawing, folders, client=client, read_text=_read, area_rank=rank,
                   lookup=_lookup if lookup else None)
    return {"schema": SCHEMA, "drawing": drawing, "client": client, "saved_at": datetime.now().isoformat(timespec="seconds"),
            "source": source, "checked": None,
            "folders": [[str(folder), [[p.name, int(s), float(t)] for p, s, t in files], bool(archive), rank(folder)]
                        for folder, files, archive in folders],
            "lookups": looked, "has_lookup": bool(lookup), "texts": texts, "expected": summary(m)}


def replay(fx: Dict[str, Any]) -> Dict[str, Any]:
    """The resolver run again on a fixture's own data: no share, no index, no PDF reader."""
    folders, ranks = [], {}
    for folder, files, archive, rank in fx.get("folders") or []:
        f = Path(folder)
        folders.append((f, [(f / n, int(s), float(t)) for n, s, t in files], bool(archive)))
        ranks[str(f)] = int(rank)
    lookups = fx.get("lookups") or {}
    texts = fx.get("texts") or {}

    def _rank(folder: Path) -> int:
        for known in sorted(ranks, key=len, reverse=True):
            if str(folder) == known or str(folder).startswith(known):
                return ranks[known]
        return max(ranks.values(), default=0) + 1

    m = pr.resolve(fx["drawing"], folders, client=fx.get("client") or "",
                   read_text=lambda p: texts.get(str(p), ""), area_rank=_rank,
                   lookup=(lambda did: [(Path(p), int(s), float(t)) for p, s, t in lookups.get(str(did), [])])
                   if fx.get("has_lookup") else None)
    return summary(m)


def differences(expected: Dict[str, Any], got: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if expected.get("class") != got.get("class"):
        out.append(f"class was '{expected.get('class')}', now '{got.get('class')}'")
    em, gm = expected.get("members") or {}, got.get("members") or {}
    if sorted(set(em) - set(gm)):
        out.append("no longer gathered: " + ", ".join(sorted(set(em) - set(gm))))
    if sorted(set(gm) - set(em)):
        out.append("now gathered as well: " + ", ".join(sorted(set(gm) - set(em))))
    for d in sorted(set(em) & set(gm)):
        if em[d] != gm[d]:
            out.append(f"{d}: formats were {em[d]}, now {gm[d]}")
    for k, label in (("missing", "missing references"), ("bought_in_unmatched", "bought-in to price"),
                     ("sheets_read", "sheets read"), ("unread_assemblies", "unread sub-assemblies"),
                     ("unassigned_files", "unassigned files")):
        if list(expected.get(k) or []) != list(got.get(k) or []):
            out.append(f"{label} were {expected.get(k) or []}, now {got.get(k) or []}")
    if (expected.get("selected_folder") or "") != (got.get("selected_folder") or ""):
        out.append(f"chosen folder was {expected.get('selected_folder')}, now {got.get('selected_folder')}")
    return out


def _file(drawing: str) -> Path:
    return fixtures_dir() / (re.sub(r"[^0-9A-Za-z_.-]", "_", drawing.upper()) + ".json")


def verify_all() -> List[Dict[str, Any]]:
    rows = []
    for path in sorted(fixtures_dir().glob("*.json")):
        try:
            fx = json.loads(path.read_text(encoding="utf-8"))
            diff = differences(fx.get("expected") or {}, replay(fx))
        except Exception as exc:                                         # noqa: BLE001
            rows.append({"drawing": path.stem, "ok": False, "differences": [f"could not be replayed: {exc}"],
                         "checked": None, "class": ""})
            continue
        rows.append({"drawing": fx.get("drawing"), "ok": not diff, "differences": diff,
                     "checked": fx.get("checked"), "class": (fx.get("expected") or {}).get("class")})
    return rows


def _print(drawing: str, s: Dict[str, Any]) -> None:
    print(f"\n{drawing}: {s['class'].upper()}")
    print(f"  {len(s['members'])} drawing(s) gathered; {s.get('pdfs_read')} PDF(s) read"
          + (f"; parts list read from sheet(s) {', '.join(s['sheets_read'])}" if s["sheets_read"] else "")
          + (f"; revision {s['revision']}" if s.get("revision") else "; revision not read"))
    print(f"  folder: {s.get('selected_folder')}")
    for g in s["gaps"]:
        print(f"  - {g}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("drawings", nargs="+"); r.add_argument("--client", default=""); r.add_argument("--json", default="")
    s = sub.add_parser("save"); s.add_argument("drawings", nargs="+"); s.add_argument("--client", default="")
    c = sub.add_parser("checked"); c.add_argument("drawing"); c.add_argument("--by", required=True); c.add_argument("--note", default="")
    sub.add_parser("verify")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.cmd in ("report", "save"):
        out = {}
        for d in a.drawings:
            fx = capture(d, a.client)
            out[d] = fx["expected"]
            _print(d, fx["expected"])
            if a.cmd == "save":
                fixtures_dir().mkdir(parents=True, exist_ok=True)
                old = None
                if _file(d).is_file():
                    try:
                        old = json.loads(_file(d).read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        old = None
                if old and old.get("checked") and not differences(old.get("expected") or {}, fx["expected"]):
                    fx["checked"] = old["checked"]             # unchanged: the check still stands
                elif old and old.get("checked"):
                    print("  the pack differs from the checked fixture; it must be checked again")
                _file(d).write_text(json.dumps(fx, indent=1), encoding="utf-8")
                print(f"  fixture saved: {_file(d)}  ({'checked by ' + fx['checked']['by'] if fx['checked'] else 'NOT YET CHECKED by a person'})")
        if a.cmd == "report" and a.json:
            Path(a.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
        tally: Dict[str, int] = {}
        for v in out.values():
            tally[v["class"]] = tally.get(v["class"], 0) + 1
        print("\n" + "; ".join(f"{k}: {n}" for k, n in sorted(tally.items())))
        return 0
    if a.cmd == "checked":
        if not _file(a.drawing).is_file():
            print(f"no fixture for {a.drawing}; save it first")
            return 2
        fx = json.loads(_file(a.drawing).read_text(encoding="utf-8"))
        fx["checked"] = {"by": a.by, "at": datetime.now().isoformat(timespec="seconds"), "note": a.note}
        _file(a.drawing).write_text(json.dumps(fx, indent=1), encoding="utf-8")
        print(f"{a.drawing}: marked checked by {a.by}. Class: {fx['expected']['class']}")
        return 0
    rows = verify_all()
    print(f"Pack fixtures: {fixtures_dir()}  ({len(rows)})")
    for row in rows:
        who = f"checked by {row['checked']['by']}" if row.get("checked") else "NOT CHECKED by a person"
        print(f"  {'ok     ' if row['ok'] else 'CHANGED'} {row['drawing']}  [{row.get('class')}]  {who}")
        for d in row["differences"]:
            print(f"          {d}")
    return 1 if any(not r["ok"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
