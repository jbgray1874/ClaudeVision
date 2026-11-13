#!/usr/bin/env python3
"""Do the prices already saved belong to their runs? Read only (reviewer, 11 Nov 2026).

"Audit existing saved results too: correcting future reads must not leave wrong historical
prices in Self-Running, TTI ledgers or tracker cells. Report mismatches before changing them."

Every saved run (the service's run history, <state>/runs/<run_id>.json) is checked against the
record pinned to its own workbook (own_record): the price at one off, and at every quantity.
Every TTI ledger entry is checked against the run it names.

    python src/price_audit.py                      the service's saved runs
    python src/price_audit.py --runs <folder>      another runs folder (a second service's)
    python src/price_audit.py --ledger <file> ...  TTI batch ledgers as well
    python src/price_audit.py --json out.json      the full result

Nothing is changed. A run whose files cannot be reached is reported "not checked", never "ok".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import own_record as orc  # noqa: E402

UNIT_COST_KEYS = (
    ("final_estimate", "totals", "unit_gbp"),
    ("workbook_equivalent_pricing", "m105_total_unit_cost_gbp"),
    ("headline_cost_price", "workbook_equivalent_total_unit_cost_gbp"),
    ("headline_cost_price", "total_unit_cost_gbp"),
    ("totals", "unit_cost_gbp"),
)


def unit_cost_from(summary: Any) -> Optional[float]:
    if not isinstance(summary, dict):
        return None
    for path in UNIT_COST_KEYS:
        node: Any = summary
        for step in path[:-1]:
            node = node.get(step) if isinstance(node, dict) else None
        if isinstance(node, dict):
            try:
                value = float(node.get(path[-1]))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return round(value, 2)
    return None


def quantity_prices_from(summary: Any) -> Dict[int, float]:
    rows = ((summary or {}).get("quantity_sweep") or {}).get("rows") if isinstance(summary, dict) else None
    out: Dict[int, float] = {}
    for r in rows or []:
        try:
            q, unit = int(r.get("quantity")), float(r.get("unit"))
        except (AttributeError, TypeError, ValueError):
            continue
        if q >= 1 and unit > 0:
            out[q] = round(unit, 2)
    return out


_NOTE = ("_covering_email.html", "_covering_note.html")


def email_evidence(run: Dict[str, Any], files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the service recorded about this run's e-mail: whether it went, to how many, the
    attachment names it listed, and which covering note was the message. The service takes
    the FIRST note among the run's files as the message, so another job's note filed with
    the run can be the e-mail itself. This is the service's record, not the mailbox."""
    res = run.get("email_result") or {}
    drawing, started = str(run.get("drawing_number") or ""), float(run.get("started_at") or 0.0)
    theirs = set(orc.other_jobs_files(files, drawing, started))
    attached = [str(a) for a in (res.get("attached") or [])]
    note = next((str(f.get("name")) for f in files
                 if any(m in str(f.get("path") or "").lower() for m in _NOTE)), None)
    # A NOTE FILED WITH THE RUN AFTERWARDS WAS NOT THE MESSAGE (12 Nov 2026). Three runs went
    # out in the service's short form because their notes were never collected; once the notes
    # were recovered this said the message "was" the covering note. The message was the note
    # only when the note went with it: it is among the attachments the service listed, or the
    # subject it recorded is not the short form's. A run recovered later says so.
    subject = str(res.get("subject") or "")
    short = subject.startswith("SDI Intelligence estimate.") or "INCOMPLETE RUN" in subject
    after = bool(note) and (short or (bool(run.get("recovered_at")) and not subject
                                      and note not in attached))
    said = (f"the service's short form; {note} was filed with the run afterwards"
            if after else note)
    return {"sent": bool(res.get("sent")), "recipients": len(res.get("recipients") or []),
            "attached": attached,
            "attached_from_another_job": sorted(a for a in attached if a in theirs),
            "message_note": said, "message_was_short_form": after,
            "message_was_another_jobs": bool(note and not after and note in theirs)}


def find_record(row: Dict[str, Any], runs: List[Dict[str, Any]],
                saved: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """A run's pinned record that was not filed with it: filed with another run, or still
    beside its workbook. {"path", "where"} or None."""
    run = saved.get(str(row.get("run_id"))) or {}
    files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
    book, _why = orc.own_book(files, str(run.get("drawing_number") or ""),
                              float(run.get("started_at") or 0.0))
    if not book:
        return None
    wanted = (book[:-len(".xlsx")] + "_record.json").lower()
    for other_id, other in saved.items():
        for d in (other.get("deliverables") or []):
            if isinstance(d, dict) and str(d.get("name") or "").lower() == wanted \
                    and Path(str(d.get("path") or "")).is_file():
                return {"path": str(d.get("path")),
                        "where": f"filed with run {other_id} ({other.get('drawing_number')})"}
    for d in files:
        if str(d.get("name") or "") == book:
            beside = Path(str(d.get("path") or "")).with_name(book[:-len(".xlsx")] + "_record.json")
            if beside.is_file():
                return {"path": str(beside), "where": "beside its workbook, not listed with the run"}
    return None


def check_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """One saved run against its own pinned record."""
    out: Dict[str, Any] = {"run_id": run.get("run_id"), "drawing": run.get("drawing_number"),
                           "client": run.get("client"), "source": run.get("source") or "",
                           "shown": run.get("engine_price_gbp"),
                           "shown_by_quantity": {int(q["quantity"]): q.get("unit_gbp")
                                                 for q in (run.get("quantity_prices") or [])
                                                 if isinstance(q, dict) and q.get("quantity")}}
    if run.get("status") != "done":
        return dict(out, verdict="not a finished run")
    files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
    item, why = orc.own_record(files, str(run.get("drawing_number") or ""),
                               float(run.get("started_at") or 0.0))
    out["record_rule"] = why
    out["email"] = email_evidence(run, files)
    out["other_jobs_files"] = orc.other_jobs_files(files, str(run.get("drawing_number") or ""),
                                                   float(run.get("started_at") or 0.0))
    if not item:
        return dict(out, verdict="not checked", why=why)
    try:
        record = json.loads(Path(str(item.get("path"))).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return dict(out, verdict="not checked", why=f"{item.get('name')} could not be read: {exc}")
    own, own_q = unit_cost_from(record), quantity_prices_from(record)
    out.update(record=item.get("name"), record_path=str(item.get("path")), own=own, own_by_quantity=own_q)
    # THE RECORD MUST SAY IT IS THIS RUN'S (reviewer, 12 Nov 2026: "positively matched to the
    # same run, drawing and quantities, not merely the same drawing's latest record"). Its
    # name ties it to the run's workbook; what it holds must agree: the drawing it declares,
    # and the quantities it priced against the quantities this run was asked for.
    declared = str(record.get("declared_product") or record.get("job_output_stem") or "")
    asked = sorted({int(q) for q in (run.get("quantity_breaks") or []) if str(q).isdigit() or isinstance(q, int)}
                   | ({int(run["units"])} if str(run.get("units") or "").isdigit() else set()))
    out.update(record_declares=declared, asked_quantities=asked, priced_quantities=sorted(own_q) or
               ([int(float(record.get("requested_order_quantity")))] if str(record.get("requested_order_quantity") or "").replace(".", "", 1).isdigit() else []))
    if declared and orc._key(declared) != orc._key(run.get("drawing_number")):
        return dict(out, verdict="not checked",
                    why=f"{item.get('name')} declares drawing {declared}, not this run's {run.get('drawing_number')}")
    out["quantities_match"] = (not asked or not out["priced_quantities"]
                               or set(asked) == set(out["priced_quantities"]))
    wrong = []
    if not out["quantities_match"]:
        wrong.append(f"this run was asked for quantities {asked}; its record priced {out['priced_quantities']}")
    if out["shown"] is not None and own is not None and abs(float(out["shown"]) - own) > 0.005:
        wrong.append(f"shows {out['shown']} at one off, its record says {own}")
    if out["shown"] is None and own is not None:
        wrong.append(f"shows no price, its record says {own}")
    for q, shown in sorted(out["shown_by_quantity"].items()):
        if q in own_q and shown is not None and abs(float(shown) - own_q[q]) > 0.005:
            wrong.append(f"shows {shown} at {q} off, its record says {own_q[q]}")
    if out["shown_by_quantity"] and own_q and set(out["shown_by_quantity"]) != set(own_q):
        wrong.append(f"shows quantities {sorted(out['shown_by_quantity'])}, its record priced {sorted(own_q)}")
    if own is None:
        return dict(out, verdict="not checked", why=f"{item.get('name')} holds no unit cost")
    return dict(out, verdict="MISMATCH" if wrong else "ok", why="; ".join(wrong))


def check_runs(folder: Path) -> List[Dict[str, Any]]:
    rows = []
    saved: Dict[str, Dict[str, Any]] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append({"run_id": path.stem, "verdict": "not checked", "why": "saved run could not be read"})
            continue
        if isinstance(run, dict):
            saved[str(run.get("run_id") or path.stem)] = run
            rows.append(check_run(run))
    # A RECORD FILED ELSEWHERE IS STILL THE RUN'S (reviewer, 12 Nov 2026: "11 not checked
    # results are not passes. Their missing pinned records need locating and reconciling").
    for i, row in enumerate(rows):
        if row.get("verdict") != "not checked" or "no pinned record" not in str(row.get("why")):
            continue
        found = find_record(row, rows, saved)
        if not found:
            continue
        run = dict(saved[str(row["run_id"])])
        run["deliverables"] = list(run.get("deliverables") or []) + [
            {"name": Path(found["path"]).name, "path": found["path"]}]
        again = check_run(run)
        again["record_found"] = found["where"]
        again["other_jobs_files"] = row.get("other_jobs_files") or []
        again["email"] = row.get("email")
        rows[i] = again
    return rows


def check_ledger(path: Path, by_run: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every ledger entry that carries a cost, against the run it names."""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [{"ledger": str(path), "verdict": "not checked", "why": str(exc)}]
    rows = []
    for key, entry in sorted((ledger or {}).items()):
        if not isinstance(entry, dict) or entry.get("unit_cost") is None:
            continue
        row = {"ledger": path.name, "row": key, "run_id": entry.get("run_id"),
               "ledger_cost": entry.get("unit_cost"), "written": entry.get("written")}
        run = by_run.get(str(entry.get("run_id") or ""))
        if not run or run.get("verdict") in (None, "not checked", "not a finished run"):
            rows.append(dict(row, verdict="not checked",
                             why="its run is not in the saved runs" if not run else run.get("why", "")))
            continue
        qty = None
        try:
            qty = int(str(key).split("|")[2])
        except (IndexError, ValueError):
            pass
        own = (run.get("own_by_quantity") or {}).get(qty) if qty and qty > 1 else None
        own = own if own is not None else run.get("own")
        bad = own is not None and abs(float(entry["unit_cost"]) - float(own)) > 0.005
        rows.append(dict(row, own=own, verdict="MISMATCH" if bad else "ok",
                         why=(f"ledger holds {entry['unit_cost']}, the run's own record says {own}"
                              + ("; this cost was WRITTEN to the tracker" if entry.get("written") else ""))
                         if bad else ""))
    return rows


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="", help="the saved runs folder (default: this service's)")
    ap.add_argument("--ledger", action="append", default=[], help="a TTI batch ledger; may repeat")
    ap.add_argument("--json", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.runs:
        folder = Path(a.runs)
    else:
        sys.path.insert(0, str(HERE.parent / "sdi-intelligence-backend"))
        import estimate_history  # noqa: PLC0415
        folder = estimate_history.store_dir()
    runs = check_runs(folder)
    print(f"Saved runs: {folder}  ({len(runs)})")
    tally: Dict[str, int] = {}
    for r in runs:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print("  " + ", ".join(f"{v}: {n}" for v, n in sorted(tally.items())))
    for r in runs:
        if r["verdict"] == "MISMATCH":
            print(f"  MISMATCH {r.get('drawing')} run {r.get('run_id')} [{r.get('source') or 'page'}]: {r['why']}")
        if r.get("other_jobs_files"):
            print(f"  FILED WITH ANOTHER JOB'S FILES {r.get('drawing')} run {r.get('run_id')}: "
                  + ", ".join(r["other_jobs_files"][:6]))
    for r in runs:
        if r.get("record_found"):
            print(f"  record located {r.get('drawing')} run {r.get('run_id')}: {r['record_found']} -> {r['verdict']}")
        e = r.get("email") or {}
        if e.get("sent") and (e.get("attached_from_another_job") or e.get("message_was_another_jobs")):
            print(f"  E-MAILED WITH ANOTHER JOB'S CONTENT {r.get('drawing')} run {r.get('run_id')} "
                  f"to {e.get('recipients')} recipient(s): "
                  + ("the message itself was " + str(e.get("message_note")) + "; "
                     if e.get("message_was_another_jobs") else "")
                  + "attached " + (", ".join(e.get("attached_from_another_job")) or "none of the other job's files"))
    for r in runs:
        if r["verdict"] == "not checked":
            print(f"  not checked {r.get('drawing')} run {r.get('run_id')}: {r.get('why')}")
    by_run = {str(r.get("run_id")): r for r in runs}
    led: List[Dict[str, Any]] = []
    for lp in a.ledger:
        rows = check_ledger(Path(lp), by_run)
        led.extend(rows)
        print(f"Ledger: {lp}  ({len(rows)} costed row(s))")
        for r in rows:
            if r["verdict"] != "ok":
                print(f"  {r['verdict']} {r.get('row')} run {r.get('run_id')}: {r.get('why')}")
    if a.json:
        Path(a.json).write_text(json.dumps({"runs": runs, "ledgers": led}, indent=1, default=str), encoding="utf-8")
        print(f"full result: {a.json}")
    return 1 if any(r["verdict"] == "MISMATCH" for r in runs + led) else 0


if __name__ == "__main__":
    raise SystemExit(main())
