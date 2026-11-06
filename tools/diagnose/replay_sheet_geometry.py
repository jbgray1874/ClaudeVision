"""Replay the own-sheet and cutting rules (D-591, D-592) over saved job records, read-only.

    python tools\\diagnose\\replay_sheet_geometry.py output\\json\\0351292.json
    python tools\\diagnose\\replay_sheet_geometry.py output\\archive\\json --csv replay.csv

WHAT IT IS FOR. The rules were proved on two packs. Before they are trusted on every job they
must be seen on others: small sheet parts, genuinely perforated parts, multi-view drawings and
formed strips — that the safeguards neither suppress real machining nor accept a drawing's
annotations as features. Point this at saved records of those jobs.

WHAT IT DOES. For every made part in each record (a .json file, or every .json in a folder) it
takes a COPY of the record and runs, in the engine's own order: the own-sheet re-read (weight,
feature cues, page geometry), the provisional blank from its own sheet where the drawing PDF is
still reachable, the fold settlement, and the cutting bound (which first asks whether the blank
stands for the part: an allowance, a blank lighter than the stated part, or a punched pattern
bounds nothing, and the row says "kept as read" with the reason). One row per part, before and after:

    record, part, own pages, other pages, weight, cut path, holes, blank, flange folds and their
    evidence, what happened to the cutting, and where the holes now come from

Nothing is written to the record, the pack or the output tree. Records made before D-591 show
what the rules would change; records made since show what they did.

ASCII ONLY in what it prints, like the other diagnose tools.
"""
from __future__ import annotations

import argparse
import copy
import csv
import glob
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

COLUMNS = ["record", "part", "own_pages", "other_pages", "gauge_before_mm", "gauge_after_mm",
           "weight_before_kg", "weight_after_kg",
           "cut_before_mm", "cut_after_mm", "holes_before", "holes_after", "blank_recorded",
           "blank_replayed", "flange_folds", "fold_evidence", "cutting", "holes_basis"]


def _records(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "*.json"))))
        else:
            out.extend(sorted(glob.glob(p)))
    return out


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _cut_holes(part: Dict[str, Any]):
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), dict) else {}
    return ng.get("cut_length_mm"), ng.get("hole_count")


def replay(path: str) -> List[Dict[str, str]]:
    import detail_page_geometry as g
    from fold_count import press_brake_folds
    with open(path, encoding="utf-8") as fh:
        record = json.load(fh)
    if not isinstance(record, dict) or not isinstance(record.get("manufacturing_writeup"), dict):
        return []
    summary = copy.deepcopy(record)
    parts = [p for p in (summary["manufacturing_writeup"].get("parts") or []) if isinstance(p, dict)]
    before = {}
    for p in parts:
        before[id(p)] = ((g._stated_weight_kg(p),) + _cut_holes(p) + (g._blank_pair(p),)
                         + (p.get("normalized_thickness_mm"),))
    g.revalidate_from_own_sheets(parts, summary)
    pages = g._page_index(summary)
    rows: List[Dict[str, str]] = []
    for p in parts:
        if not g._made_here(p):
            continue
        own = g.own_sheets(p, summary)
        own_pages = [s.get("page_number") for s in own]
        bound = [b for b in (p.get("pages") or []) if isinstance(b, int)]
        replayed, dims = "", (None, None)
        if own and not g._is_section_stock(p):
            probe = copy.deepcopy(p)
            blank = g.provisional_blank_from_sheets(probe, [pages[n] for n in own_pages if n in pages])
            replayed = (f"{blank['length']:g} x {blank['width']:g}" if blank
                        else f"refused: {probe.get('_provisional_blank_refused') or 'no figures'}")
            if blank and not all(g._blank_pair(p)):
                dims = (blank["length"], blank["width"])   # the blank the costing would now use
        g.settle_fold_evidence([p])
        notes = g.bound_cutting_to_blank(p, *dims)
        folds = press_brake_folds(dict(p))
        ev = g.machining_evidence(p)
        w0, c0, h0, b0, t0 = before[id(p)]
        c1, h1 = _cut_holes(p)
        rows.append({
            "record": os.path.basename(path), "part": str(p.get("part_number") or ""),
            "own_pages": " ".join(str(n) for n in own_pages),
            "other_pages": " ".join(str(b) for b in bound if b not in own_pages),
            "gauge_before_mm": _fmt(t0), "gauge_after_mm": _fmt(p.get("normalized_thickness_mm")),
            "weight_before_kg": _fmt(w0), "weight_after_kg": _fmt(g._stated_weight_kg(p)),
            "cut_before_mm": _fmt(c0), "cut_after_mm": _fmt(c1),
            "holes_before": _fmt(h0), "holes_after": "unread" if h1 is None and h0 is not None else _fmt(h1),
            "blank_recorded": f"{b0[0]:g} x {b0[1]:g}" if b0[0] and b0[1] else "",
            "blank_replayed": replayed,
            "flange_folds": _fmt(g._evidenced_fold_count(p)),
            "fold_evidence": str(folds.get("source") or ""),
            "cutting": ("; ".join(notes) if notes
                        else f"kept as read: {p['_cut_path_not_bounded']}"
                        if p.get("_cut_path_not_bounded")
                        else "measured" if ev["measured"] else "kept"),
            "holes_basis": str(ev.get("label") or ""),
        })
    return rows


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay the own-sheet and cutting rules over saved "
                                             "job records, read-only.")
    ap.add_argument("paths", nargs="+", help="record .json files, globs, or folders of them")
    ap.add_argument("--csv", default="", help="write every row to this CSV as well")
    args = ap.parse_args(argv)
    rows: List[Dict[str, str]] = []
    for path in _records(args.paths):
        try:
            got = replay(path)
        except Exception as exc:                                     # noqa: BLE001
            print(f"{os.path.basename(path)}: not replayed ({exc.__class__.__name__}: {exc})")
            continue
        changed = [r for r in got if (r["gauge_before_mm"] != r["gauge_after_mm"]
                                      or r["weight_before_kg"] != r["weight_after_kg"]
                                      or r["cut_before_mm"] != r["cut_after_mm"]
                                      or r["holes_before"] != r["holes_after"]
                                      or r["cutting"].startswith("kept as read"))]
        print(f"{os.path.basename(path)}: {len(got)} made part(s), {len(changed)} changed")
        for r in changed:
            print(f"   {r['part']}: gauge {r['gauge_before_mm'] or '-'} -> "
                  f"{r['gauge_after_mm'] or '-'} mm; weight {r['weight_before_kg'] or '-'} -> "
                  f"{r['weight_after_kg'] or '-'} kg; cut {r['cut_before_mm'] or '-'} -> "
                  f"{r['cut_after_mm'] or '-'} mm; holes {r['holes_before'] or '-'} -> "
                  f"{r['holes_after'] or '-'}; blank {r['blank_recorded'] or '-'} -> "
                  f"{r['blank_replayed'] or '-'}; {r['cutting']}".replace("\u2014", "-")
                  .replace("\u00d7", "x").encode("ascii", "replace").decode())
        rows.extend(got)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} row(s) written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
