"""Two reads of the same pack, compared fact by fact. Is the reading CONSISTENT?

WHY THIS, AND WHY NOW. "First and foremost is the quality and consistency of the reading of the
drawing packs." Quality needs somebody to say what the right answer is. Consistency does not — if
one pack read twice gives two answers, at least one is wrong, and that is visible without any
opinion about which. This is the half that can be measured today.

It compares only FACTS THAT WERE READ: part numbers, quantities, materials as printed, stock form,
thickness, blank sizes, bend counts, the operations the drawing states, and which reader produced
each BOM row. Not prices, not rates, not totals — those move for a dozen legitimate reasons and
would bury the signal.

THE DISTINCTION THAT MAKES IT USEFUL. Two runs of one pack can differ for two completely
different reasons, and confusing them wastes a day:

    a FIX       the engine changed between the runs, and the second read is deliberately
                different. estimate_summary.engine_build carries the commit of the build that
                wrote each record, so this is answerable rather than assumed.
    INSTABILITY the same build read the same bytes twice and got two answers. That is a defect
                in the reading, and the one this tool exists to surface.

It says which, at the top, before any difference is listed. A run whose build cannot be identified
is reported as UNKNOWN and never quietly treated as "same build" — that would turn every fix into
a false instability report.

    python tools/compare_two_reads.py --a output/json/7332-01_v0021.json --b output/json/7332-01.json

Exit codes:  0 identical reading   1 differences found   2 could not read an input
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

# ── WHAT COUNTS AS "THE READING" ──────────────────────────────────────────────────────
#
# Each entry is a field on a part record and what it means for it to move. The words matter as
# much as the list: a report that says "thickness_mm changed 2.5 -> 3.0" and stops leaves the
# reader to work out whether that is serious. Gauge drives the material cost AND the laser rate.
READ_FACTS: Dict[str, str] = {
    "quantity": "how many of this part the job needs — moves the material and every setup",
    "normalized_material": "the material the readers settled on, after arbitration",
    "material_text": "the material EXACTLY as printed on the drawing, before any normalising",
    "stock_form": "sheet / tube / bar / wire — decides which whole costing basis is used, and "
                  "which operations the route compiler will even consider",
    "thickness_mm": "gauge. Drives the material cost and the cutting rate together",
    "blank_length_mm": "the developed flat, long side — the nesting and the sheet yield",
    "blank_width_mm": "the developed flat, short side",
    "bend_count": "every bend is a setup; a bend gained or lost is labour gained or lost",
    "flat_pattern_detected": "whether a DXF flat pattern was found for this part at all",
    "textual_operations": "the operations the DRAWING states. The route compiler works from "
                          "these, so a change here changes what is made",
    "description": "the part's description as read",
}

# Fields that are allowed to differ without it meaning anything, and why. Named rather than
# silently skipped: a reader who cannot see what was excluded cannot trust what was included.
IGNORED: Dict[str, str] = {
    "*_gbp": "money, which is not a reading",
    "labour_estimate": "costing output",
    "material_estimate": "costing output",
    "confidence": "a score, recomputed per run by design",
}


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parts(record: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    """Parts by part number, from the writeup — the population the route and the sheet share.

    Falls back to part_estimates, because a record that never reached costing has the first and
    not the second, and one that predates the writeup has the second and not the first.
    """
    out: Dict[str, Mapping[str, Any]] = {}
    for source in ((record.get("manufacturing_writeup") or {}).get("parts") or [],
                   (record.get("estimate_summary") or {}).get("part_estimates") or []):
        for item in source:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("part_number") or item.get("item_number") or "").strip().upper()
            if key and key not in out:
                out[key] = item
    return out


def _bom_rows(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in ((record.get("document_analysis") or {}).get("bom_rows") or [])
            if isinstance(r, Mapping)]


def _build(record: Mapping[str, Any]) -> Dict[str, Any]:
    build = (record.get("estimate_summary") or {}).get("engine_build")
    return build if isinstance(build, Mapping) else {}


def _norm(value: Any) -> Any:
    """Compare like with like, without flattening a real difference into agreement.

    Lists of operations are compared as SETS — the compiler does not care about the order they
    were appended in, and reporting a reordering as a change would drown the real ones. Numbers
    are rounded to 3dp: a float that differs in the twelfth decimal is the same measurement,
    and reporting it would train people to ignore this tool.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(v).strip().lower() for v in value))
    return value


def compare_parts(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    pa, pb = _parts(a), _parts(b)
    only_a = sorted(set(pa) - set(pb))
    only_b = sorted(set(pb) - set(pa))
    changed: List[Dict[str, Any]] = []
    for key in sorted(set(pa) & set(pb)):
        for field, why in READ_FACTS.items():
            va, vb = _norm(pa[key].get(field)), _norm(pb[key].get(field))
            if va != vb:
                changed.append({"part": key, "field": field, "a": va, "b": vb, "why": why})
    return {"only_in_a": only_a, "only_in_b": only_b, "changed": changed,
            "common": len(set(pa) & set(pb))}


def compare_bom(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    """BOM rows by (part, reader, page). A row is identified by WHICH READER SAW IT WHERE,
    because the same part read by two readers is two rows by design and collapsing them would
    hide a reader that stopped working."""
    def _key(row: Mapping[str, Any]) -> Tuple[str, str, str]:
        return (str(row.get("part_number") or "").strip().upper(),
                str(row.get("source") or "").strip(),
                str(row.get("source_page") or ""))
    ka = {_key(r) for r in _bom_rows(a)}
    kb = {_key(r) for r in _bom_rows(b)}
    by_reader_a: Dict[str, int] = {}
    by_reader_b: Dict[str, int] = {}
    for row in _bom_rows(a):
        by_reader_a[str(row.get("source") or "(unnamed)")] = \
            by_reader_a.get(str(row.get("source") or "(unnamed)"), 0) + 1
    for row in _bom_rows(b):
        by_reader_b[str(row.get("source") or "(unnamed)")] = \
            by_reader_b.get(str(row.get("source") or "(unnamed)"), 0) + 1
    return {"only_in_a": sorted(ka - kb), "only_in_b": sorted(kb - ka),
            "by_reader_a": by_reader_a, "by_reader_b": by_reader_b,
            "total_a": len(_bom_rows(a)), "total_b": len(_bom_rows(b))}


def compare_route(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    """What the compiler decided, per part and operation. Read through the extract's own reader
    so this cannot disagree with the sheet an estimator is looking at."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from bom_and_route_extract import route_payloads
    except Exception as err:                                             # noqa: BLE001
        return {"unavailable": f"{type(err).__name__}: {err}"}

    def _decisions(record: Mapping[str, Any]) -> Dict[Tuple[str, str], str]:
        out: Dict[Tuple[str, str], str] = {}
        for payload in route_payloads(record):
            for decision in (payload.get("decisions") or []):
                if not isinstance(decision, Mapping):
                    continue
                key = (str(decision.get("target_id") or decision.get("part_number") or "").upper(),
                       str(decision.get("operation") or ""))
                status = str(decision.get("status") or "")
                # REQUIRED WINS when one part/operation carries several decisions. The compiler
                # emits one per piece of evidence, so the same bend can appear twice; what
                # matters for consistency is whether the job still says the work happens.
                if key not in out or status == "required":
                    out[key] = status
        return out

    da, db = _decisions(a), _decisions(b)
    changed = [{"part": k[0], "operation": k[1], "a": da.get(k), "b": db.get(k)}
               for k in sorted(set(da) | set(db)) if da.get(k) != db.get(k)]
    return {"changed": changed, "count_a": len(da), "count_b": len(db)}


def build_verdict(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    ba, bb = _build(a), _build(b)
    ca, cb = ba.get("commit"), bb.get("commit")
    if not ca or not bb or not cb:
        return {"state": "unknown",
                "says": "at least one run cannot say which build produced it, so a difference "
                        "below CANNOT be attributed. Treat nothing here as proof of instability "
                        "until both builds are known."}
    if ca == cb:
        dirty = bool(ba.get("dirty")) or bool(bb.get("dirty"))
        return {"state": "same_build", "commit": ca, "dirty": dirty,
                "says": ("SAME BUILD. Any difference below is the same code reading the same "
                         "pack twice and answering differently — that is an instability in the "
                         "reading, not a fix.")
                        + (" NOTE: a working tree was dirty, so 'same commit' does not mean "
                           "'same code'." if dirty else "")}
    return {"state": "different_builds", "a": ca, "b": cb,
            "says": f"DIFFERENT BUILDS ({ca} -> {cb}). A difference below may be a deliberate "
                    f"fix. Compare against what changed between those commits before calling "
                    f"anything a defect."}


def report(a_path: Path, b_path: Path, log=print) -> int:
    try:
        a, b = _load(a_path), _load(b_path)
    except Exception as err:                                             # noqa: BLE001
        log(f"!! could not read an input: {type(err).__name__}: {err}")
        return 2

    log("=" * 78)
    log("TWO READS OF ONE PACK")
    log("=" * 78)
    for label, path, record in (("A", a_path, a), ("B", b_path, b)):
        build = _build(record)
        log(f"  {label}  {path}")
        log(f"     job {record.get('job_number') or '(unnamed)'}   "
            f"read at {record.get('processed_at') or '(no processed_at)'}")
        log(f"     build {build.get('commit') or 'UNKNOWN'}"
            f"{' (dirty tree)' if build.get('dirty') else ''}"
            f"   {str(build.get('subject') or '')[:58]}")
    verdict = build_verdict(a, b)
    log("")
    log(f"  {verdict['says']}")
    log("")

    differences = 0

    parts = compare_parts(a, b)
    log("-" * 78)
    log(f"PARTS  ({parts['common']} read by both)")
    for key in parts["only_in_a"]:
        log(f"  ONLY IN A   {key} — the second read did not find this part")
        differences += 1
    for key in parts["only_in_b"]:
        log(f"  ONLY IN B   {key} — the first read did not find this part")
        differences += 1
    for item in parts["changed"]:
        log(f"  CHANGED     {item['part']}  {item['field']}:  {item['a']!r}  ->  {item['b']!r}")
        log(f"              {item['why']}")
        differences += 1
    if not (parts["only_in_a"] or parts["only_in_b"] or parts["changed"]):
        log("  every part read identically")

    bom = compare_bom(a, b)
    log("-" * 78)
    log(f"BOM ROWS  A {bom['total_a']}   B {bom['total_b']}")
    readers = sorted(set(bom["by_reader_a"]) | set(bom["by_reader_b"]))
    for reader in readers:
        na, nb = bom["by_reader_a"].get(reader, 0), bom["by_reader_b"].get(reader, 0)
        mark = "   " if na == nb else "  !"
        log(f"{mark} {reader:18} A {na:4}   B {nb:4}"
            + ("" if na == nb else "   <- this reader produced a different number of rows"))
    for key in bom["only_in_a"]:
        log(f"  ONLY IN A   {key[0]} read by {key[1] or '(unnamed)'} on page {key[2] or '?'}")
        differences += 1
    for key in bom["only_in_b"]:
        log(f"  ONLY IN B   {key[0]} read by {key[1] or '(unnamed)'} on page {key[2] or '?'}")
        differences += 1
    if not (bom["only_in_a"] or bom["only_in_b"]):
        log("  every BOM row matched, reader for reader and page for page")

    route = compare_route(a, b)
    log("-" * 78)
    if route.get("unavailable"):
        log(f"ROUTE  not compared: {route['unavailable']}")
    else:
        log(f"ROUTE  A {route['count_a']} decision(s)   B {route['count_b']}")
        for item in route["changed"]:
            log(f"  CHANGED     {item['part']}  {item['operation']}:  "
                f"{item['a'] or '(absent)'}  ->  {item['b'] or '(absent)'}")
            differences += 1
        if not route["changed"]:
            log("  every part/operation reached the same status")

    log("=" * 78)
    if not differences:
        log("IDENTICAL READING. Every fact these two runs read agrees.")
        log("=" * 78)
        return 0
    log(f"{differences} DIFFERENCE(S).")
    if verdict["state"] == "same_build":
        log("The build did not change, so these are the same code reading the same pack twice")
        log("and answering differently. Every one of them is a defect in the reading.")
    elif verdict["state"] == "different_builds":
        log(f"The build changed ({verdict['a']} -> {verdict['b']}). Check each against what")
        log("changed between those commits before calling it a defect.")
    else:
        log("A build could not be identified, so none of these can be attributed yet.")
    log("=" * 78)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", required=True, help="the earlier record")
    ap.add_argument("--b", required=True, help="the later record")
    args = ap.parse_args(argv)
    return report(Path(args.a), Path(args.b))


if __name__ == "__main__":
    raise SystemExit(main())
