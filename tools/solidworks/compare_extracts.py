"""Compare a Document Manager read with the SolidWorks read of the same models (D-710, SCRUM-184).

    python tools/solidworks/compare_extracts.py <SolidWorks extract .json> <Document Manager extract .json>

SCRUM-184's acceptance: "with SolidWorks forced unavailable, a pack read by both readers gives
the same BOM, quantities, materials and properties. Any differences are listed." This lists
them, part by part:

  * parts only one reader found;
  * material, thickness, flat blank, bends, cut length and mass that disagree;
  * assembly BOM lines and quantities that disagree;
  * values the Document Manager left empty because the file did not save them. Those are
    counted as NOT SAVED, never as a disagreement: that is what the backup is expected to do.

Reads two JSON files and writes nothing. ASCII only in what it prints. Exit code 0 when the two
reads agree on everything both supplied, 1 when anything disagrees, 2 when a file cannot be read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# The route-signal fields both readers write, and how close two numbers must be to agree.
FIELDS: Tuple[Tuple[str, str], ...] = (
    ("material", "material"),
    ("thickness_mm", "thickness mm"),
    ("flat_length_mm", "flat length mm"),
    ("flat_width_mm", "flat width mm"),
    ("bend_count", "bends"),
    ("cut_length_mm", "cut length mm"),
    ("mass_kg", "mass kg"),
    ("is_sheet_metal", "sheet metal"),
)
REL_TOL, ABS_TOL = 0.005, 0.05


def _records(path: Path) -> Dict[str, Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    recs = payload.get("records") if isinstance(payload, dict) else payload
    out: Dict[str, Mapping[str, Any]] = {}
    for r in recs or []:
        if not isinstance(r, dict) or r.get("errors") or not r.get("title"):
            continue
        key = Path(str(r["title"])).stem.strip().upper()
        out.setdefault(key, r)
    return out


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _same(a: Any, b: Any) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= max(ABS_TOL, REL_TOL * max(abs(na), abs(nb)))
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return " ".join(str(a or "").upper().split()) == " ".join(str(b or "").upper().split())


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _bom(rec: Mapping[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for line in rec.get("bom") or []:
        if not isinstance(line, dict) or not line.get("part_number"):
            continue
        pn = str(line["part_number"]).strip().upper()
        out[pn] = out.get(pn, 0.0) + (_num(line.get("qty")) or 0.0)
    return out


def compare(sw: Mapping[str, Mapping[str, Any]],
            dm: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """{"only_sw", "only_dm", "both", "differ": [(part, field, sw, dm)], "not_saved":
    [(part, field)]}"""
    differ: List[Tuple[str, str, Any, Any]] = []
    not_saved: List[Tuple[str, str]] = []
    both = sorted(set(sw) & set(dm))
    for pn in both:
        a = sw[pn].get("route_signals") or {}
        b = dm[pn].get("route_signals") or {}
        for key, label in FIELDS:
            va, vb = a.get(key), b.get(key)
            if _empty(va) and _empty(vb):
                continue
            if _empty(vb):
                not_saved.append((pn, label))
            elif _empty(va) or not _same(va, vb):
                differ.append((pn, label, va, vb))
        ba, bb = _bom(sw[pn]), _bom(dm[pn])
        for child in sorted(set(ba) | set(bb)):
            qa, qb = ba.get(child), bb.get(child)
            if qa is None or qb is None or not _same(qa, qb):
                differ.append((pn, f"BOM {child} qty", qa, qb))
    return {"only_sw": sorted(set(sw) - set(dm)), "only_dm": sorted(set(dm) - set(sw)),
            "both": both, "differ": differ, "not_saved": not_saved}


def _show(v: Any) -> str:
    if v is None:
        return "-"
    n = _num(v)
    return f"{n:g}" if n is not None and not isinstance(v, bool) else str(v)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    try:
        sw, dm = _records(Path(args[0])), _records(Path(args[1]))
    except (OSError, ValueError) as exc:
        print(f"STOP: could not read the extracts ({type(exc).__name__}: {exc})")
        return 2
    r = compare(sw, dm)
    print(f"SolidWorks read {len(sw)} file(s); Document Manager read {len(dm)}; "
          f"{len(r['both'])} in both.")
    for pn in r["only_sw"]:
        print(f"  only SolidWorks:       {pn}")
    for pn in r["only_dm"]:
        print(f"  only Document Manager: {pn}")
    if r["differ"]:
        print(f"\n  {'part':24} {'what':22} {'SolidWorks':>14} {'Doc Manager':>14}")
        for pn, what, a, b in r["differ"]:
            print(f"  {pn[:24]:24} {what[:22]:22} {_show(a)[:14]:>14} {_show(b)[:14]:>14}")
    saved = {}
    for pn, what in r["not_saved"]:
        saved.setdefault(what, []).append(pn)
    for what, pns in sorted(saved.items()):
        print(f"  not saved in the file (expected): {what} on {len(pns)} part(s)")
    agree = not r["differ"] and not r["only_sw"] and not r["only_dm"]
    print("\nRESULT: " + ("the two reads agree on everything both supplied." if agree else
                          f"{len(r['differ'])} difference(s), {len(r['only_sw'])} part(s) only "
                          f"SolidWorks read, {len(r['only_dm'])} only the Document Manager "
                          f"read."))
    return 0 if agree else 1


if __name__ == "__main__":
    sys.exit(main())
