"""Replay a saved job through the current code — re-costing, the workbook's line list, the
commercial lines and the report — and check it, in minutes, before another long run.

    python tools/replay_saved_job.py output/json/8188-08.json
    python tools/replay_saved_job.py output/json/8188-08.json --facts docs/briefs/8188-08.facts.json
    python tools/replay_saved_job.py output/json/8188-08.json --offline

WHY. Fixes passed narrow tests and then missed the stage that built the finished workbook:
the doubled insert was minted in the workbook's own canonicalisation, downstream of every
part-record fix, and that was found only by a full run, five times. A run is twenty minutes of
extraction and vision reads that cannot change with a costing fix. This takes the record the
last run SAVED (its drawing reads, BOM rows and part records) and drives the current code from
the first costing pass to the report:

    pre-costing passes  (file_scan.pre_costing_passes — the same function the run calls)
    estimate_document   (every part re-costed)
    late records        (the BOM-table reconcile's additions, re-costed by the run's own routine)
    canonical route     (recompiled from the final population)
    workbook line list  (wb_populate.canonicalise_part_estimates_for_workbook — where lines are minted)
    commercial lines    (packaging and delivery, priced on the chosen basis at every break)
    the record          (costed_facts.costed_job — what every surface reads)
    the report          (job_report_html.build_report_html)

WHAT IT DOES NOT DO. It does not re-read the drawings (a fix to a reader needs a run), and it
does not open the Excel template, so the sheet's own formulas — nest yields, the totals, the
quantity-break recalculation — are not evaluated: money printed here is the engine's figure,
not the workbook's. The book is still the proof; this says whether a run is worth starting.

NOTHING IS OVERWRITTEN. Output goes to output/replay/<job>_replay.json and
output/replay/<job>_replay_report.html; the saved record is only read.

GENERIC BY CONSTRUCTION: no job, code or figure is known here. What a job must show lives in
its facts file (docs/briefs/<job>.facts.json), checked by tools/check_book_against_brief.py.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))


def _sq(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


# Fields a late record keeps when it is re-costed: who it is and where it was listed, never
# the price the old code gave it.
_LATE_KEEP = ("part_number", "description", "quantity", "bom_parent", "bom_parents",
              "printed_code", "is_bought_in", "page_roles", "source", "owning_assembly",
              "supplied_by_third_party", "raw_aliases", "supplier")


def _line_money(line: Dict[str, Any]) -> Optional[float]:
    for key in ("charged_unit_gbp", "engine_unit_gbp"):
        v = _num(line.get(key))
        if v is not None:
            return v
    return None


def _lines(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    import costed_facts as cf
    return [l for l in (cf.costed_job(summary).get("lines") or []) if isinstance(l, dict)]


def replay(summary: Dict[str, Any], log=print) -> Dict[str, Any]:
    """The saved record driven through the current code, in place. Returns the summary."""
    import estimator
    import file_scan

    wu = summary.get("manufacturing_writeup") if isinstance(summary.get("manufacturing_writeup"), dict) else None
    if not wu or not isinstance(wu.get("parts"), list):
        raise SystemExit("the saved record has no manufacturing_writeup.parts — nothing to replay")
    parts = wu["parts"]
    saved_pes = list(((summary.get("estimate_summary") or {}).get("part_estimates")) or [])

    # The identities the writeup already holds (codes and their aliases): a saved estimate
    # outside them was added after costing, by the BOM-table reconcile.
    held = set()
    for p in parts:
        if isinstance(p, dict):
            held.add(_sq(p.get("part_number")))
            held.update(_sq(a) for a in (p.get("raw_aliases") or []))
    late = []
    for pe in saved_pes:
        if isinstance(pe, dict) and pe.get("part_number") and _sq(pe["part_number"]) not in held:
            late.append({k: copy.deepcopy(pe[k]) for k in _LATE_KEEP if k in pe})

    log("[replay] pre-costing passes (the run's own function)")
    file_scan.pre_costing_passes(summary)
    log(f"[replay] estimate_document over {len(parts)} part record(s)")
    summary["estimate_summary"] = estimator.estimate_document(parts, summary=summary)
    if late:
        log(f"[replay] {len(late)} late record(s) re-costed: {', '.join(str(r['part_number']) for r in late[:8])}")
        summary["estimate_summary"].setdefault("part_estimates", []).extend(late)
        estimator.cost_uncosted_bought_in_records(summary)
    try:
        from route_compiler import refresh_canonical_route_after_reconciliation
        refresh_canonical_route_after_reconciliation(summary)
    except Exception as exc:                                         # noqa: BLE001
        log(f"[replay] canonical route not refreshed ({type(exc).__name__}: {exc})")
    try:
        import wb_populate
        pes = list(summary["estimate_summary"].get("part_estimates") or [])
        if wb_populate.canonical_route_cutover_enabled(summary):
            summary["estimate_summary"]["canonical_part_estimates"] = \
                wb_populate.canonicalise_part_estimates_for_workbook(summary, pes)
            log("[replay] workbook line list built by the workbook's own canonicalisation")
        else:
            log("[replay] canonical cutover is off for this record — the sheet would be built "
                "from part_estimates as they stand")
    except Exception as exc:                                         # noqa: BLE001
        log(f"[replay] workbook line list NOT built ({type(exc).__name__}: {exc})")
    try:
        from commercial_lines import collect_lines
        summary["commercial_lines"] = collect_lines(summary)
    except Exception as exc:                                         # noqa: BLE001
        log(f"[replay] commercial lines not collected ({type(exc).__name__}: {exc})")
    summary["replayed_by"] = "tools/replay_saved_job.py"
    return summary


def _print_changes(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> None:
    b = {_sq(l.get("part_number")): l for l in before}
    a = {_sq(l.get("part_number")): l for l in after}
    print("\nLINES — the saved record against the replay (engine unit £, not the workbook's)")
    for k in sorted(set(b) | set(a)):
        lb, la = b.get(k), a.get(k)
        if lb and not la:
            print(f"  REMOVED  {lb.get('part_number')}  (£{_line_money(lb)})")
        elif la and not lb:
            print(f"  ADDED    {la.get('part_number')} x{la.get('qty_per_unit')}  £{_line_money(la)}")
        else:
            mb, ma = _line_money(lb), _line_money(la)
            if (mb or 0) != (ma or 0) or lb.get("qty_per_unit") != la.get("qty_per_unit"):
                print(f"  CHANGED  {la.get('part_number')}: x{lb.get('qty_per_unit')} £{mb} -> "
                      f"x{la.get('qty_per_unit')} £{ma}")


def _print_evidence(summary: Dict[str, Any]) -> None:
    import costed_facts as cf
    from detail_page_geometry import not_cut_from_a_blank
    pes = list(((summary.get("estimate_summary") or {}).get("part_estimates")) or [])
    parts = list(((summary.get("manufacturing_writeup") or {}).get("parts")) or [])
    print("\nPROVISIONAL BLANKS — measured and inferred dimensions told apart")
    seen = False
    for p in parts:
        rec = p.get("_blank_provisional") if isinstance(p, dict) else None
        if not isinstance(rec, dict):
            continue
        seen = True
        pe = next((e for e in pes if _sq(e.get("part_number")) == _sq(p.get("part_number"))), {})
        me = pe.get("material_estimate") or {}
        print(f"  {p.get('part_number')}: basis {rec.get('basis')}; measured {rec.get('measured_mm')}; "
              f"inferred {rec.get('inferred_mm')}; priced on {rec.get('provisional_mm')}"
              + (f"; net area {rec.get('net_area_m2')} m² (range {rec.get('area_range_m2')})"
                 if rec.get("net_area_m2") else "")
              + f"; material £{me.get('unit_material_cost_gbp')}")
    if not seen:
        print("  none")
    declined = [(p.get("part_number"), p.get("_allowance_declined")) for p in parts
                if isinstance(p, dict) and p.get("_allowance_declined")]
    if declined:
        print("\nALLOWANCE DECLINED — each candidate's own reason")
        for pn, why in declined:
            print(f"  {pn}: {why}")
    print("\nCOMMERCIAL LINES — the basis chosen and the unit at every break")
    try:
        import pyodbc                                            # noqa: F401
    except Exception:                                            # noqa: BLE001
        print("  (SDI Live unreachable in this python — figures below that cite SDI Live "
              "history are the saved record's, not a fresh lookup)")
    lines = summary.get("commercial_lines") or []
    for cl in lines:
        if not isinstance(cl, dict):
            continue
        breaks = cl.get("order_gbp_at_breaks") or {}
        per_unit = ", ".join(f"{q}: £{float(v) / max(int(q), 1):.2f}/unit (£{float(v):.2f} order)"
                             for q, v in sorted(breaks.items(), key=lambda kv: int(kv[0])))
        klass = ("RESEARCHED SHIPMENT" if cl.get("shipment_working") else
                 "JUSTIFIED FALLBACK" if cl.get("shipment_refusal")
                 and "recorded no reason" not in str(cl.get("shipment_refusal"))
                 else "FALLBACK — REASON NOT RECORDED" if "weak" in str(cl.get("basis_chosen") or "").lower()
                 else "HOUSE/HISTORY BASIS")
        print(f"  {cl.get('code')} [{klass}]: {cl.get('basis_chosen') or 'basis not named'}; "
              f"order £{cl.get('order_gbp')}" + (f"; {per_unit}" if per_unit else "; no breaks held"))
        if cl.get("shipment_refusal"):
            print(f"      shipment_refusal: {cl['shipment_refusal']}")
        for key in ("shipment_working", "history_working", "cross_check"):
            if cl.get(key):
                print(f"      {key}: {str(cl[key])[:300]}")
    if not lines:
        print("  none collected")
    print("\nASSEMBLIES — none may carry a gauge decision")
    guilty = [p.get("part_number") for p in parts if isinstance(p, dict)
              and not_cut_from_a_blank(p) and cf.thickness_conflict(p)]
    print(f"  {'gauge decision on ' + ', '.join(map(str, guilty)) if guilty else 'none'}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("summary", type=Path, help="the saved record, e.g. output/json/<job>.json")
    ap.add_argument("--facts", type=Path, default=None, help="docs/briefs/<job>.facts.json")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "replay")
    ap.add_argument("--offline", action="store_true",
                    help="do not ask SDI Live or the researcher (SDI_OFFLINE=1)")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.offline:
        os.environ["SDI_OFFLINE"] = "1"
    # THE ENVIRONMENT IS PART OF THE RESULT (D-456). The first replay ran on a python without
    # pyodbc: SDI Live was unreachable, so every history figure it printed was the SAVED
    # record's, and nothing said so. The runner's interpreter is .venv\Scripts\python.exe.
    print(f"interpreter: {sys.executable}")
    env_caveats: List[str] = []
    try:
        import pyodbc                                            # noqa: F401
    except Exception:                                            # noqa: BLE001
        env_caveats.append(
            "pyodbc is MISSING in this python: SDI Live cannot be re-queried, so any history "
            "or catalogue figure shown is the SAVED record's, carried, not fresh. Run the "
            "replay with the runner's interpreter (.venv\\Scripts\\python.exe) for live rungs.")
    if a.offline:
        env_caveats.append("--offline: SDI Live and the market researcher were not asked by design.")
    for _c in env_caveats:
        print(f"ENVIRONMENT: {_c}")
    saved = json.loads(a.summary.read_text(encoding="utf-8"))
    job = str(saved.get("job_number") or saved.get("job_folder_name") or a.summary.stem)
    before_lines = _lines(copy.deepcopy(saved))
    summary = replay(copy.deepcopy(saved))
    after_lines = _lines(summary)
    _print_changes(before_lines, after_lines)
    _print_evidence(summary)

    a.out.mkdir(parents=True, exist_ok=True)
    out_json = a.out / f"{job}_replay.json"
    out_json.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    try:
        from job_report_html import build_report_html
        out_html = a.out / f"{job}_replay_report.html"
        out_html.write_text(build_report_html(summary), encoding="utf-8")
        print(f"\nreport: {out_html}")
    except Exception as exc:                                         # noqa: BLE001
        print(f"\nreport NOT built ({type(exc).__name__}: {exc})")
    print(f"record: {out_json}")
    print("note: the final workbook charge (the sheet's nest and formulas) is verified only "
          "on the book — a passing replay is the ticket to run it, not a substitute for it")

    if a.facts:
        from check_book_against_brief import check
        res = check(summary, json.loads(a.facts.read_text(encoding="utf-8")))
        width = max((len(r[1]) for r in res.rows), default=10)
        print("\nGATES")
        for name, item, ok, detail in res.rows:
            print(f"{'PASS' if ok else 'FAIL'}  {name:<20} {item:<{width}}  {detail}")
        n_fail = len(res.failed)
        print(f"\n{len(res.rows) - n_fail} held, {n_fail} failed")
        return 1 if n_fail else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
