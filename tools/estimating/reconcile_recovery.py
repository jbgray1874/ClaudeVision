"""Is a recovered estimate COMPLETE against the run it was recovered from?

A replayed record can produce a workbook that opens, recalculates and totals with no formula
error while lines the original run priced have quietly gone to zero: an offline replay does
not ask the price sources the original run asked. A positive total proves nothing about that.
So the original saved record and the recovered record are compared line by line, on the
engine's own costed-line view (costed_facts.costed_job), and the recovery passes only when:

  * every line the original carried is still there, at the same quantity;
  * every line the original priced is still priced (no LOST PRICE);
  * every money change is on a line named as an intended correction (--changed), or within
    tolerance; anything else is listed for explanation, never assumed correct;
  * the corrected part shows what it must (--part with its expectations);
  * where workbook totals are given, both are reported with the engine's line sums beside them.

Reads only. Writes one report JSON beside the recovery (--report). Generic: no job, part or
figure is known here; the caller names them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def unit_money(line: Dict[str, Any]) -> Optional[float]:
    for k in ("engine_unit_gbp", "charged_unit_gbp"):
        v = _num(line.get(k))
        if v is not None:
            return v
    return None


def lines_of(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    import costed_facts as cf
    return [l for l in (cf.costed_job(summary).get("lines") or []) if isinstance(l, dict)]


def _index(lines: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        k = key(line.get("part_number") or line.get("identity"))
        if k:
            out.setdefault(k, line)
    return out


def compare_lines(before: List[Dict[str, Any]], after: List[Dict[str, Any]], changed: Iterable[str] = (),
                  tol_abs: float = 0.5, tol_rel: float = 0.01) -> Dict[str, Any]:
    """Line-by-line completeness of `after` against `before`."""
    allowed = {key(c) for c in changed}
    b, a = _index(before), _index(after)
    out: Dict[str, Any] = {"missing": [], "lost_price": [], "quantity_changed": [], "money_changed": [],
                           "added": [], "intended": [], "unchanged": 0}
    for k in sorted(set(b) | set(a)):
        lb, la = b.get(k), a.get(k)
        name = (lb or la).get("part_number") or k
        if lb and not la:
            out["missing"].append({"line": name, "unit_gbp": unit_money(lb), "kind": lb.get("kind")})
            continue
        if la and not lb:
            out["added"].append({"line": name, "unit_gbp": unit_money(la), "kind": la.get("kind"),
                                 "intended": k in allowed})
            continue
        mb, ma = unit_money(lb), unit_money(la)
        qb, qa = _num(lb.get("qty_per_unit")), _num(la.get("qty_per_unit"))
        row = {"line": name, "kind": la.get("kind"), "qty_before": qb, "qty_after": qa,
               "unit_before_gbp": mb, "unit_after_gbp": ma}
        if k in allowed:
            out["intended"].append(row)
            continue
        if (mb or 0) > 0 and not (ma or 0) > 0:
            out["lost_price"].append(row)
        elif qb != qa:
            out["quantity_changed"].append(row)
        elif abs((ma or 0) - (mb or 0)) > max(tol_abs, tol_rel * abs(mb or 0)):
            out["money_changed"].append(row)
        else:
            out["unchanged"] += 1

    def ext(lines: Dict[str, Dict[str, Any]]) -> float:
        return round(sum((unit_money(l) or 0) * (_num(l.get("qty_per_unit")) or 0) for l in lines.values()), 2)

    out["engine_line_sum_before_gbp"] = ext(b)
    out["engine_line_sum_after_gbp"] = ext(a)
    out["unexplained"] = (len(out["missing"]) + len(out["lost_price"]) + len(out["quantity_changed"])
                          + len(out["money_changed"]) + sum(1 for x in out["added"] if not x["intended"]))
    return out


def check_part(prepared: Dict[str, Any], replay: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """The corrected part, as the replayed record holds it, against what the caller expects."""
    want = key(spec["part"])
    bad: List[str] = []
    seen: Dict[str, Any] = {}
    if spec.get("pdf") or spec.get("axes"):
        pages = [p for p in prepared.get("pages") or []
                 if str(p.get("source_pdf_name") or "").lower() == str(spec.get("pdf") or "").lower()]
        ax = (pages[0].get("printed_dimension_axes") or {}) if pages else {}
        seen["printed_axes_mm"] = ax.get("axes_mm")
        seen["pdf_sha256"] = ax.get("pdf_sha256")
        if spec.get("axes") and ax.get("axes_mm") != spec["axes"]:
            bad.append(f"printed axes {ax.get('axes_mm')} are not {spec['axes']}")
        if spec.get("pdf_sha256") and ax.get("pdf_sha256") != spec["pdf_sha256"]:
            bad.append("the PDF read is not the file the evidence was checked against")
    parts = [p for p in ((replay.get("manufacturing_writeup") or {}).get("parts") or [])
             if key(p.get("part_number")) == want]
    if len(parts) != 1:
        bad.append(f"{len(parts)} records for {spec['part']} in the replay")
        return {"part": spec["part"], "seen": seen, "problems": bad}
    p = parts[0]
    ops = sorted(set((p.get("inferred_operations") or []) + (p.get("textual_operations") or [])))
    seen.update({"material": p.get("normalized_material"), "thickness_mm": p.get("normalized_thickness_mm"),
                 "blank_mm": [p.get("blank_length_mm"), p.get("blank_width_mm")],
                 "finish": p.get("normalized_finish"), "operations": ops,
                 "review": (p.get("owned_thickness_conflict") or {}).get("basis")})
    if spec.get("material") and str(p.get("normalized_material") or "").upper() != spec["material"].upper():
        bad.append(f"material {p.get('normalized_material')} is not {spec['material']}")
    if spec.get("thickness") is not None and _num(p.get("normalized_thickness_mm")) != spec["thickness"]:
        bad.append(f"thickness {p.get('normalized_thickness_mm')} is not {spec['thickness']}")
    if spec.get("blank") and [_num(p.get("blank_length_mm")), _num(p.get("blank_width_mm"))] != spec["blank"]:
        bad.append(f"blank {seen['blank_mm']} is not {spec['blank']}")
    missing_ops = [o for o in spec.get("ops") or [] if o not in ops]
    if missing_ops:
        bad.append(f"operations missing: {', '.join(missing_ops)}")
    present = [o for o in spec.get("absent_ops") or [] if o in ops]
    if present:
        bad.append(f"operations that must not be charged: {', '.join(present)}")
    if spec.get("conflict_printed") is not None and \
            (p.get("owned_thickness_conflict") or {}).get("printed_mm") != spec["conflict_printed"]:
        bad.append("the thickness-conflict review item is missing")
    return {"part": spec["part"], "seen": seen, "problems": bad}


def _floats(text: Optional[str]) -> Optional[List[float]]:
    return [float(x) for x in re.split(r"[x,]", text)] if text else None


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("original", type=Path, help="the original run's saved record (read only)")
    ap.add_argument("prepared", type=Path, help="the prepared copy the replay started from")
    ap.add_argument("replay", type=Path, help="the replayed record")
    ap.add_argument("--changed", action="append", default=[], help="a line the correction is meant to change")
    ap.add_argument("--part", help="the corrected part to check")
    ap.add_argument("--pdf", help="its own PDF's file name")
    ap.add_argument("--pdf-sha256")
    ap.add_argument("--axes", help="printed axes expected, e.g. 1866x770")
    ap.add_argument("--blank", help="blank expected, e.g. 1866x770")
    ap.add_argument("--material")
    ap.add_argument("--thickness", type=float)
    ap.add_argument("--ops", default="", help="operations that must be present, comma-separated")
    ap.add_argument("--absent-ops", default="", help="operations that must not be charged")
    ap.add_argument("--conflict-printed", help="printed thickness(es) the review item must name, e.g. 6")
    ap.add_argument("--original-book-total", type=float)
    ap.add_argument("--recovered-book-total", type=float)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.report.exists():
        ap.error("the report must be a new file")
    load = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    original, prepared, replay = load(a.original), load(a.prepared), load(a.replay)
    report: Dict[str, Any] = {"schema": "recovery_reconciliation.v1", "original": str(a.original),
                              "lines": compare_lines(lines_of(original), lines_of(replay), a.changed)}
    if a.part:
        report["part"] = check_part(prepared, replay, {
            "part": a.part, "pdf": a.pdf, "pdf_sha256": a.pdf_sha256, "axes": _floats(a.axes),
            "blank": _floats(a.blank), "material": a.material, "thickness": a.thickness,
            "ops": [o for o in a.ops.split(",") if o], "absent_ops": [o for o in a.absent_ops.split(",") if o],
            "conflict_printed": [int(x) if float(x).is_integer() else float(x) for x in a.conflict_printed.split(",")]
            if a.conflict_printed else None})
    report["workbook_totals_gbp"] = {"original": a.original_book_total, "recovered": a.recovered_book_total}
    lines = report["lines"]
    print(f"LINES: {lines['unchanged']} unchanged, {len(lines['intended'])} intended correction(s), "
          f"{lines['unexplained']} unexplained")
    for label in ("missing", "lost_price", "quantity_changed", "money_changed"):
        for row in lines[label]:
            print(f"  {label.upper():17} {json.dumps(row, default=str)}")
    for row in lines["added"]:
        if not row["intended"]:
            print(f"  ADDED             {json.dumps(row, default=str)}")
    for row in lines["intended"]:
        print(f"  INTENDED          {json.dumps(row, default=str)}")
    print(f"engine line sums: before GBP {lines['engine_line_sum_before_gbp']}, "
          f"after GBP {lines['engine_line_sum_after_gbp']}")
    print(f"workbook totals: original GBP {a.original_book_total}, recovered GBP {a.recovered_book_total}")
    part_ok = True
    if a.part:
        part = report["part"]
        print(f"PART {part['part']}: {json.dumps(part['seen'], default=str)}")
        for problem in part["problems"]:
            print(f"  PART PROBLEM: {problem}")
        part_ok = not part["problems"]
    complete = lines["unexplained"] == 0 and part_ok and a.recovered_book_total is not None \
        and a.recovered_book_total > 0
    report["complete"] = complete
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print("RECONCILIATION: " + ("COMPLETE - every original line accounted for"
                                if complete else "NOT COMPLETE - see the lines above"))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
