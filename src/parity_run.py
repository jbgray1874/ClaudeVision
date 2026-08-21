#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""parity_run.py — run a parity report across an AI estimate and a manual one.

THE COMPARISON IS THE POINT OF THE PARALLEL RUN, AND UNTIL NOW IT NEEDED A COMMAND LINE.

estimate_full_parity_report.py has always been able to compare the engine's summary against a
workbook, but only through `main.py --estimate-full-parity-report <summary.json>`, which needs a
path to a JSON an estimator has never seen and would not know how to find. So the one artefact
that answers "is the engine right?" was reachable only by whoever knew the incantation, and the
adoption register shows the consequence: nineteen estimates issued, and not one parity bundle
produced by anybody but the engineer who wrote it.

This module is the door. It takes what an estimator actually HAS — two spreadsheets — and works
back to the JSON itself.

  AI side      an engine summary JSON, or the engine's own .xlsx (its summary is resolved from
               the filename, the same trick the override quote uses)
  Manual side  the estimator's workbook, .xlsx or .xls

Two callers:

  * the portal's "Parity report" form, comparing a previous AI job against its manual estimate;
  * a fresh run, where the estimator attaches the manual sheet up front and the runner passes it
    to main.py as --parity-workbook so the bundle lands with the rest of the deliverables.

Run:
    python src/parity_run.py --ai <summary.json|ai_estimate.xlsx> --manual <manual.xlsx> [--json]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _ensure_engine_on_path() -> None:
    """Put src/ on the path so the report module imports — APPENDED, never prepended.

    A module-level `sys.path.insert(0, src)` here was a landmine. There are two modules named
    `config` in this repo, the engine's and the portal backend's, and prepending src makes the
    engine's win for the whole process — including inside the backend's own tests, which then
    fail with "module 'config' has no attribute 'API_KEY'" for a reason that has nothing to do
    with them and depends on which file pytest happened to import first.

    Appending finds the engine's modules without displacing anybody else's, and doing it lazily
    means merely importing this module changes nothing at all.
    """
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)


# .xls is the older manual estimate format and still the common one on the share; refusing it
# would exclude most of the back catalogue, which is exactly the comparison worth having.
MANUAL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
AI_SUFFIXES = (".json", ".xlsx", ".xlsm")


class ParityInputError(ValueError):
    """A problem with what the estimator supplied, phrased for the estimator.

    Separate from every other failure because it is the only kind they can fix themselves, and
    the backend turns it into a 400 with the message shown on the form rather than a 500.
    """


def _job_stem(workbook_path: Path) -> str:
    """The job's stem, with the engine's run timestamp removed.

    The engine writes '<stem>_20260818_133037.xlsx' and its summary is '<stem>.json'."""
    return re.sub(r"_\d{8}_\d{6}$", "", Path(workbook_path).stem)


def resolve_ai_summary(ai_path: str | Path) -> Path:
    """The engine summary JSON for the AI side, from either a JSON or the engine's workbook.

    An estimator picking "the AI one" reaches for the spreadsheet, because that is the artefact
    they were sent. The JSON is what parity actually reads. Resolving one from the other is the
    difference between a form anybody can use and a form that needs the engine explained first.
    """
    p = Path(ai_path)
    if not p.exists():
        raise ParityInputError(f"The AI estimate could not be found: {p}")
    if p.suffix.lower() == ".json":
        return p
    if p.suffix.lower() not in AI_SUFFIXES:
        raise ParityInputError(
            f"The AI side must be the engine's summary JSON or its .xlsx — got '{p.suffix}'.")

    stem = _job_stem(p)
    candidates = [p.parent / f"{stem}.json"]
    try:
        import config as _cfg
        candidates.insert(0, Path(getattr(_cfg, "JSON_DIR")) / f"{stem}.json")
    except Exception:                                            # noqa: BLE001
        pass
    for c in candidates:
        if c.is_file():
            return c
    raise ParityInputError(
        f"No engine summary was found for '{p.name}'. Parity compares the engine's own reading "
        f"of the job against the manual sheet, and that reading lives in {stem}.json — looked in "
        + " and ".join(str(c.parent) for c in candidates) +
        ". If the job was run on another machine, copy its JSON across, or point at the JSON "
        "directly.")


def check_manual(manual_path: str | Path) -> Path:
    p = Path(manual_path)
    if not p.exists():
        raise ParityInputError(f"The manual estimate could not be found: {p}")
    if p.suffix.lower() not in MANUAL_SUFFIXES:
        raise ParityInputError(
            f"The manual estimate must be a workbook ({', '.join(MANUAL_SUFFIXES)}) — "
            f"got '{p.suffix}'.")
    return p


def _default_out_dir(summary: Path) -> Path:
    try:
        import config as _cfg
        return Path(getattr(_cfg, "OUTPUT_DIR")) / "csv"
    except Exception:                                            # noqa: BLE001
        return summary.parent


def run_parity(ai: str | Path,
               manual: str | Path,
               *,
               out_dir: Optional[str | Path] = None,
               read_via_excel: bool = False) -> Dict[str, Any]:
    """Compare one AI estimate against one manual estimate and write the bundle.

    read_via_excel drives the workbook through Excel COM so formulas resolve when the file's
    value cache is empty — which is the normal state of a workbook openpyxl wrote and nobody has
    opened since. It is OFF by default because it needs Excel on the box and an interactive
    session; the caller turns it on where those exist, and gets a clearer answer when it does.
    """
    summary_path = resolve_ai_summary(ai)
    manual_path = check_manual(manual)

    out = Path(out_dir) if out_dir else _default_out_dir(summary_path)
    out.mkdir(parents=True, exist_ok=True)
    stem = summary_path.stem
    out_json = out / f"{stem}.full_parity.bundle.json"
    out_csv = out / f"{stem}.full_parity.csv"

    _ensure_engine_on_path()
    from estimate_full_parity_report import generate_and_write

    bundle, written_json, written_csv = generate_and_write(
        summary_path, manual_path, out_json, out_csv, read_via_excel=read_via_excel)

    return {
        "ai_summary": str(summary_path),
        "manual_workbook": str(manual_path),
        "bundle_json": str(written_json),
        "bundle_csv": str(written_csv),
        "job_stem": stem,
        "read_via_excel": bool(read_via_excel),
        "headline": _headline(bundle),
    }


def _headline(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """What a form can show in one line, read from the bundle's own schema.

    The bundle is not reshaped here — it is the record and the portal reads it whole. This is the
    single comparison the engine already computes for exactly this purpose,
    `rollup_unit_cost_comparison`: the workbook's cached unit cost against the engine's total
    divided by the workbook's own quantity, so the two are compared at the same quantity rather
    than at whatever each happened to be run at.

    Every field returns None rather than a zero when it cannot be read. A parity headline that
    says "£0" when it means "no cached value in that cell" is worse than one that says nothing —
    it looks like an answer, and an estimator would act on it.
    """
    rollup = bundle.get("rollup_unit_cost_comparison") or {}
    counts = bundle.get("status_counts") or {}

    def num(holder, key):
        v = (holder or {}).get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    manual_unit = num(rollup, "workbook_unit_cost_cached")
    ai_unit = num(rollup, "json_implied_unit_using_workbook_qty")
    gap = round(ai_unit - manual_unit, 2) if (ai_unit is not None and manual_unit is not None) else None

    return {
        # The comparison proper.
        "ai_unit_cost_gbp": ai_unit,
        "manual_unit_cost_gbp": manual_unit,
        "gap_gbp": gap,
        "pct_variance": num(rollup, "pct_variance"),
        # match / warning / fail against the configured thresholds — the engine's own verdict,
        # not one computed here, so the form and the bundle can never disagree.
        "status": rollup.get("status"),
        "workbook_cell": rollup.get("workbook_unit_cost_cell"),
        # How much of the rest agrees. These are what turn "the totals are close" into
        # "and so is everything underneath", which is the claim parity actually has to support.
        "money_match": counts.get("money_match"),
        "money_warning": counts.get("money_warning"),
        "money_fail": counts.get("money_fail"),
        "labour_route_match": counts.get("labour_route_match"),
        "labour_route_issues": counts.get("labour_route_issues"),
        # Why a total may be missing. openpyxl cannot calculate; a workbook nobody has opened in
        # Excel has an empty value cache, and this is the field that says so rather than leaving
        # the estimator to wonder why the comparison is blank.
        "workbook_read_mode": bundle.get("workbook_read_mode"),
        "precalculation_note": bundle.get("precalculation_note"),
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Parity report across an AI estimate and a manual estimate.")
    ap.add_argument("--ai", required=True,
                    help="The engine's summary JSON, or the engine's .xlsx (its JSON is resolved)")
    ap.add_argument("--manual", required=True, help="The estimator's manual workbook (.xlsx/.xls)")
    ap.add_argument("--out-dir", help="Where to write the bundle (default: output/csv)")
    ap.add_argument("--read-via-excel", action="store_true",
                    help="Windows: resolve formulas through Excel COM when the value cache is empty")
    ap.add_argument("--json", action="store_true",
                    help="Emit the result as a single JSON line on stdout (for the backend)")
    a = ap.parse_args()

    try:
        res = run_parity(a.ai, a.manual, out_dir=a.out_dir, read_via_excel=a.read_via_excel)
    except ParityInputError as exc:
        # One line, no traceback: the backend hands the last stderr line to the estimator.
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

    if a.json:
        print(json.dumps(res))
    else:
        h = res["headline"]
        print(f"  AI summary:      {res['ai_summary']}")
        print(f"  Manual workbook: {res['manual_workbook']}")
        if h["ai_unit_cost_gbp"] is not None and h["manual_unit_cost_gbp"] is not None:
            pct = h["pct_variance"]
            print(f"  Unit cost — AI GBP {h['ai_unit_cost_gbp']:,.2f}  vs  "
                  f"manual GBP {h['manual_unit_cost_gbp']:,.2f}   gap GBP {h['gap_gbp']:,.2f}"
                  + (f" ({pct:+.1f}%)" if isinstance(pct, float) else "")
                  + (f"   {str(h['status']).upper()}" if h["status"] else ""))
        else:
            print(f"  Unit cost not comparable (workbook read via {h['workbook_read_mode']}).")
            if h["precalculation_note"]:
                print(f"    {h['precalculation_note']}")
        print(f"  Money cells:     {h['money_match']} match / {h['money_warning']} warning / "
              f"{h['money_fail']} fail")
        print(f"  Labour route:    {h['labour_route_match']} match / "
              f"{h['labour_route_issues']} issues")
        print(f"  Bundle JSON:     {res['bundle_json']}")
        print(f"  Bundle CSV:      {res['bundle_csv']}")


if __name__ == "__main__":
    main()
