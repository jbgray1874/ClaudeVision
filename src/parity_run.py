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

    # TWO COMPARISONS, EACH FAILURE-ISOLATED (D-623, SCRUM-157).
    #
    # The money-cell bundle is the long-standing record, and the only one that can drive Excel
    # to resolve an empty value cache. The line-by-line detail (parity_compare) is the one a
    # person reads: cost apart from sell, the commercial lines, scope part by part, quantities
    # and revisions, each difference linked to its lines and cells. Either may fail on a sheet
    # the other reads, so each runs on its own; only when both fail is there nothing to file.
    bundle: Dict[str, Any] = {}
    written_json = written_csv = None
    legacy_error = ""
    try:
        from estimate_full_parity_report import generate_and_write
        bundle, written_json, written_csv = generate_and_write(
            summary_path, manual_path, out_json, out_csv, read_via_excel=read_via_excel)
    except Exception as exc:                                     # noqa: BLE001
        legacy_error = f"{type(exc).__name__}: {exc}"
        print(f"   [parity] the money-cell bundle could not be written ({legacy_error}); the "
              f"line-by-line comparison carries on.", flush=True)

    # THE ONE OF THE THREE A PERSON CAN ACTUALLY READ.
    #
    # parity_report_html has existed all along and renders this bundle properly — the job report
    # already imports its tables. But nothing ever wrote the standalone page, so this route
    # produced a JSON nobody reads and a CSV that needs Excel, and the answer to "why did these
    # two estimates differ" was a 2,000-line file. The renderer was there; the call was not.
    #
    # Failure-isolated on purpose: the bundle is the record, and a template fault in the report
    # must not cost the comparison that was just computed successfully.
    written_html = None
    if written_json:
        try:
            from parity_report_html import generate_report_files
            written_html = generate_report_files(written_json, out_dir=out, job_stem=stem)
        except Exception as exc:                                 # noqa: BLE001
            print(f"   [parity] the HTML report could not be written ({exc}) — the bundle JSON "
                  f"and CSV are complete and unaffected.", flush=True)

    detail, detail_json, detail_html, detail_error = None, None, None, ""
    try:
        import parity_compare
        detail = parity_compare.compare(summary_path, manual_path)
        detail_json, detail_html = parity_compare.write(detail, out, stem)
    except Exception as exc:                                     # noqa: BLE001
        detail_error = f"{type(exc).__name__}: {exc}"
        print(f"   [parity] the line-by-line comparison could not be written ({detail_error}).",
              flush=True)

    # THE COMPARISON, SPOKEN (D-627). JG: "Does the parity run also create a .wav file with
    # an explanation. this would be superb." The words come from the detail's own figures and
    # the voice is the same Windows one the estimate walkthrough uses; a machine with no
    # voice writes the words and keeps the comparison. Failure-isolated like everything here.
    walkthrough_wav = walkthrough_txt = None
    walkthrough_note = ""
    if detail is not None and detail_html:
        try:
            import parity_compare
            from walkthrough_audio import paths_for, write_walkthrough
            # Named here, not via the report: paths_for treats a dotted stem's last piece as
            # an extension, and "12677.parity" would come out as "12677.txt".
            base = out / (str(stem).replace(".", "_") + "_parity.tmp")
            ok, walkthrough_note = write_walkthrough(parity_compare.spoken(detail), base)
            txt, wav = paths_for(base)
            walkthrough_txt = str(txt) if txt.is_file() else None
            walkthrough_wav = str(wav) if ok else None
            print(f"   [parity] spoken comparison: {walkthrough_note}", flush=True)
        except Exception as exc:                                 # noqa: BLE001
            walkthrough_note = f"not spoken ({type(exc).__name__}: {exc})"
            print(f"   [parity] {walkthrough_note} — the comparison itself is unaffected.",
                  flush=True)

    if not written_json and not detail_json:
        raise RuntimeError(f"Neither comparison could be made. Money cells: {legacy_error}. "
                           f"Line by line: {detail_error}.")

    return {
        "ai_summary": str(summary_path),
        "manual_workbook": str(manual_path),
        "bundle_json": str(written_json) if written_json else None,
        "bundle_csv": str(written_csv) if written_csv else None,
        # The page a person opens: the line-by-line report, or the money-cell page without it.
        "bundle_html": detail_html or written_html,
        "legacy_html": written_html,
        "detail_json": detail_json,
        "detail_html": detail_html,
        "detail_headline": (detail or {}).get("headline"),
        "walkthrough_wav": walkthrough_wav,
        "walkthrough_txt": walkthrough_txt,
        "walkthrough_note": walkthrough_note,
        "errors": {"money_cells": legacy_error, "line_by_line": detail_error},
        "job_stem": stem,
        "read_via_excel": bool(read_via_excel),
        "headline": _merged_headline(_headline(bundle), detail),
    }


def _merged_headline(legacy: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The one-line answer, from the line-by-line comparison when it read both unit costs.

    The detail reads the same price chain at the same quantity, and when the quantities differ it
    takes the AI figure from the run's own sweep or says the two are not comparable, which the
    money-cell rollup never did. Where the detail could not read both figures (an empty value
    cache that only Excel can fill), the money-cell answer stands. The percentage stays unsigned,
    as every caller has always read it; the signed figure travels beside it.
    """
    h = dict(legacy)
    d = (detail or {}).get("headline") or {}
    if d.get("ai_unit_cost_gbp") is None or d.get("manual_unit_cost_gbp") is None:
        h["unit_cost_source"] = "money cells"
        return h
    pct = d.get("pct")
    h.update({
        "ai_unit_cost_gbp": d["ai_unit_cost_gbp"],
        "manual_unit_cost_gbp": d["manual_unit_cost_gbp"],
        "gap_gbp": d.get("gap_gbp"),
        "pct_variance": abs(pct) if isinstance(pct, (int, float)) else None,
        "pct_signed": pct,
        "status": d.get("status"),
        "workbook_cell": next((r.get("manual_cell") for r in detail.get("cost_build") or []
                               if r.get("key") == "unit"), legacy.get("workbook_cell")),
        "compared_at_qty": d.get("compared_at_qty"),
        "comparable": d.get("comparable", True),
        "ai_sell_gbp": d.get("ai_sell_gbp"),
        "manual_sell_gbp": d.get("manual_sell_gbp"),
        "scope_counts": d.get("scope_counts"),
        "revision_differs": d.get("revision_differs"),
        "unit_cost_source": "line by line",
    })
    return h


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

    # THE ROLLUP IS NOT THE ONLY PLACE A UNIT COST IS READ, AND SAYING IT IS MISLEADS BADLY.
    #
    # 10575-02 produced no rollup comparison, so the card announced "Unit costs could not both be
    # read" and told the estimator to tick "Resolve formulas through Excel". Both halves were
    # wrong. The money-cell row for M117 had ALREADY read both sides -- AI £168.03 against manual
    # £832.80, a 396% gap and a status of `fail` -- and the .xls had been read by xlrd, which
    # returns computed values, so the Excel box would have changed nothing.
    #
    # A parity report that finds a four-hundred-percent gap and reports itself as unreadable is
    # worse than one that fails outright: the estimator closes the card believing there is nothing
    # to see. So where the rollup is silent, the money cells answer instead.
    if ai_unit is None or manual_unit is None:
        for row in bundle.get("money_cell_comparisons") or []:
            if "unit manufacturing cost" not in str(row.get("label", "")).lower():
                continue
            a, m = num(row, "json_numeric"), num(row, "workbook_cached_numeric")
            if a is not None and m is not None:
                ai_unit, manual_unit = a, m
                rollup = {**rollup,
                          "status": row.get("status"),
                          "pct_variance": row.get("pct_variance"),
                          "workbook_unit_cost_cell": row.get("cell"),
                          "unit_cost_source": "money_cell"}
                break

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
        if res.get("detail_html"):
            print(f"  Line by line:    {res['detail_html']}")


if __name__ == "__main__":
    main()
