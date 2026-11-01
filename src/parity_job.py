#!/usr/bin/env python3
r"""Parity by job number: find both estimates, compare them, file the comparison (D-619).

    python src\parity_job.py find   12677-01-GA          what it would compare, and the choices
    python src\parity_job.py job    12677-01-GA          compare and file
    python src\parity_job.py job    12677-01-GA --manual "<path>" --ai "<path>"
    python src\parity_job.py search [text] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    python src\parity_job.py period --from 2026-10-01 --to 2026-10-31 [--preview]
    python src\parity_job.py periods                     period comparisons already run

JG, 1 Nov 2026: "a new parity option where we can compare one job - can choose / find from file
system or name for the tool to search by job number. ... the manual estimates live at
K:\Estimating\Completed\Manual Estimates\2026\$client.. we take the most obvious s/sheet
candidate and we run a parity against it from our AI estimate with html outputs. the s/sheets
that are used are stored at K:\Estimating\Completed\AI Estimating\parity and below this for
every run we save down the two s/sheets compared and the parity reports that are available to
be searched through in the web page and app ... also, can run a search and comparison between
all manual and AI estimates ran across two time periods."

THE COMPARISON ITSELF IS parity_run.run_parity, unchanged: the engine's summary against the
manual workbook, with its bundle, CSV and HTML report. This module finds the two sides, files
what was compared, and keeps an index so a comparison can be found again.

FINDING THE MANUAL ESTIMATE. Under <Manual Estimates>\<year>\<client>\, newest year first: a job
folder whose name starts with the job number (as "1282- MILWAUKEE RED 50cm PEG" does), or a
workbook there whose name does. Inside, the most obvious workbook: the full drawing number in
its name, then the highest issue ("ISS 7", "Issue 3", "Rev B" counts as later than none), then
the newest. Copies, old and superseded versions, quotes and blank templates rank last; Excel's
own lock files are never offered. Every candidate is returned with why it ranked where it did,
so a person can choose another.

FINDING THE AI ESTIMATE. Under AISheets\<client>\<drawing>\<date time (N off)>\, the newest run
of that drawing whose folder holds the engine's workbook and its summary JSON.

FILED. Each comparison gets its own folder, <parity>\<client>\<job>\<date time>\, holding a copy
of both workbooks, the AI summary, the parity bundle, CSV and HTML report, and parity_index.json:
what was compared, from where, and the headline. Search reads those indexes. A period run files
each job the same way and writes one summary page linking them all under <parity>\_periods\.
Nothing outside the parity folder is ever written.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

MANUAL_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
AISHEETS_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"
PARITY_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\parity"
WORKBOOK_SUFFIXES = (".xls", ".xlsx", ".xlsm")
INDEX_NAME = "parity_index.json"
_RUN_FOLDER = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})-(\d{2}) \((\d+) off\)$")
_ISSUE = re.compile(r"\b(?:ISS(?:UE)?|REV(?:ISION)?|R|V)\s*\.?\s*([0-9]+|[A-Z])\b", re.I)
_SECOND_RATE = ("copy", "old", "superseded", "draft", "quote", "backup", "bak")
_NEVER = ("blank estimate", "template")


class ParityJobError(ValueError):
    """Something a person can fix: no manual estimate found, no AI run, a bad date."""


def roots() -> Dict[str, Path]:
    return {"manual": Path(os.getenv("SDI_MANUAL_ESTIMATES_ROOT", "") or MANUAL_DEFAULT),
            "aisheets": Path(os.getenv("SDI_ESTIMATE_OUTPUT_ROOT", "") or AISHEETS_DEFAULT),
            "parity": Path(os.getenv("SDI_PARITY_ROOT", "") or PARITY_DEFAULT)}


# ── job numbers ─────────────────────────────────────────────────────────────────────────

def job_digits(job: str) -> str:
    """"12677-01-GA" -> "12677": the job number every folder starts with."""
    m = re.match(r"\s*(\d{3,})", str(job or ""))
    if not m:
        raise ParityJobError(f"'{job}' does not start with a job number.")
    return m.group(1)


def _bare(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _starts_with_job(name: str, digits: str) -> bool:
    return re.match(rf"\s*{re.escape(digits)}(?!\d)", name or "") is not None


def _safe(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(text or "")).strip()
    return re.sub(r"\s+", " ", cleaned).rstrip(". ")[:120] or "unnamed"


# ── the manual estimate ─────────────────────────────────────────────────────────────────

def _issue_rank(name: str) -> int:
    found = _ISSUE.findall(Path(name).stem)
    if not found:
        return 0
    last = found[-1].upper()
    return int(last) if last.isdigit() else ord(last) - ord("A") + 1


def _manual_candidate(path: Path, job: str, client: str, year: str) -> Optional[Dict[str, Any]]:
    name = path.name
    lower = name.lower()
    if (not path.is_file() or path.suffix.lower() not in WORKBOOK_SUFFIXES
            or name.startswith("~$") or any(w in lower for w in _NEVER)):
        return None
    full = _bare(job)
    reasons = []
    names_drawing = len(full) > len(job_digits(job)) and full in _bare(path.stem)
    if names_drawing:
        reasons.append("names the drawing")
    issue = _issue_rank(name)
    if issue:
        reasons.append(f"issue {issue}")
    second = [w for w in _SECOND_RATE if re.search(rf"\b{w}\b", lower)]
    if second:
        reasons.append("looks like a " + "/".join(second))
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return {"path": str(path), "name": name, "client": client, "year": year,
            "folder": str(path.parent), "issue": issue, "modified": modified,
            "modified_text": time.strftime("%d %b %Y %H:%M", time.localtime(modified)),
            "_rank": (0 if second else 1, 1 if names_drawing else 0, issue, modified),
            "why": ", ".join(reasons) or "the job's workbook"}


def find_manual(job: str, manual_root: Optional[Path] = None,
                years: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Every manual workbook for this job, most obvious first."""
    root = Path(manual_root or roots()["manual"])
    digits = job_digits(job)
    if not root.is_dir():
        raise ParityJobError(f"The manual estimates folder is not reachable: {root}")
    year_dirs = sorted((p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"20\d\d", p.name)),
                       key=lambda p: p.name, reverse=True)
    if years:
        wanted = {str(y) for y in years}
        year_dirs = [p for p in year_dirs if p.name in wanted]
    found: List[Dict[str, Any]] = []
    for ydir in year_dirs:
        for cdir in sorted(p for p in ydir.iterdir() if p.is_dir()):
            try:
                entries = list(cdir.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not _starts_with_job(entry.name, digits):
                    continue
                if entry.is_dir():
                    inner = []
                    try:
                        inner = list(entry.iterdir())
                    except OSError:
                        pass
                    for f in inner + [g for d in inner if d.is_dir() for g in d.iterdir()]:
                        c = _manual_candidate(f, job, cdir.name, ydir.name)
                        if c:
                            found.append(c)
                else:
                    c = _manual_candidate(entry, job, cdir.name, ydir.name)
                    if c:
                        found.append(c)
        if found:
            break                                    # the newest year that has the job
    found.sort(key=lambda c: c["_rank"], reverse=True)
    for c in found:
        c.pop("_rank", None)
    return found


# ── the AI estimate ─────────────────────────────────────────────────────────────────────

def _engine_workbook(folder: Path, drawing: str) -> Optional[Path]:
    books = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".xlsx"
             and not p.name.startswith("~$")]
    stamped = [p for p in books if re.search(r"_\d{8}_\d{6}$", p.stem)]
    pool = stamped or books
    pool = [p for p in pool if _bare(p.stem).startswith(_bare(drawing)[:5])] or pool
    return min(pool, key=lambda p: len(p.name)) if pool else None


def _summary_for(workbook: Path) -> Optional[Path]:
    stem = re.sub(r"_\d{8}_\d{6}$", "", workbook.stem)
    candidate = workbook.parent / f"{stem}.json"
    return candidate if candidate.is_file() else None


def find_ai(job: str, aisheets_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every AI run of this job that holds a workbook and its summary, newest first."""
    root = Path(aisheets_root or roots()["aisheets"])
    digits = job_digits(job)
    full = _bare(job)
    if not root.is_dir():
        raise ParityJobError(f"AISheets is not reachable: {root}")
    runs: List[Dict[str, Any]] = []
    for cdir in sorted(p for p in root.iterdir() if p.is_dir()):
        for ddir in sorted(p for p in cdir.iterdir() if p.is_dir()):
            if not _starts_with_job(ddir.name, digits):
                continue
            exact = _bare(ddir.name) == full or len(full) <= len(digits)
            for rdir in sorted(p for p in ddir.iterdir() if p.is_dir()):
                m = _RUN_FOLDER.match(rdir.name)
                if not m:
                    continue
                book = _engine_workbook(rdir, ddir.name)
                summary = _summary_for(book) if book else None
                if not book or not summary:
                    continue
                runs.append({"workbook": str(book), "summary": str(summary),
                             "run_folder": str(rdir), "client": cdir.name,
                             "drawing": ddir.name, "stamp": rdir.name[:19],
                             "day": m.group(1), "units": int(m.group(5)), "exact": exact})
    runs.sort(key=lambda r: (r["exact"], r["stamp"]), reverse=True)
    return runs


# ── run one, file it ────────────────────────────────────────────────────────────────────

def _new_folder(base: Path, stamp: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        folder = base / (stamp if n == 1 else f"{stamp} ({n})")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise OSError(f"no free folder under {base}")


def _default_compare(ai: str, manual: str, out_dir: Path, read_via_excel: bool) -> Dict[str, Any]:
    from parity_run import run_parity
    return run_parity(ai, manual, out_dir=out_dir, read_via_excel=read_via_excel)


def _placed_manual(path: Path, manual_root: Path) -> Dict[str, str]:
    """A manual workbook chosen by hand: its client and year when it sits under the manual
    estimates folder as <year>\\<client>\\..., otherwise neither."""
    try:
        parts = path.resolve().relative_to(manual_root.resolve()).parts
    except (OSError, ValueError):
        parts = ()
    if len(parts) >= 3 and re.fullmatch(r"20\d\d", parts[0]):
        return {"year": parts[0], "client": parts[1]}
    return {"year": "", "client": ""}


def _placed_ai(path: Path) -> Dict[str, str]:
    """An AI workbook chosen by hand: its client, drawing and run when it sits in an AISheets
    run folder, <client>\\<drawing>\\<date time (N off)>\\, otherwise none of them."""
    run = path.parent
    if _RUN_FOLDER.match(run.name) and run.parent.parent != run.parent:
        return {"client": run.parent.parent.name, "drawing": run.parent.name,
                "stamp": run.name[:19], "run_folder": str(run)}
    return {"client": "", "drawing": "", "stamp": "", "run_folder": str(run)}


def run_job(job: str, manual: Optional[str] = None, ai: Optional[str] = None, *,
            read_via_excel: bool = False, compare: Optional[Callable[..., Dict[str, Any]]] = None,
            now: Optional[float] = None, made_by: str = "") -> Dict[str, Any]:
    """Compare one job's AI estimate with its manual one and file the comparison."""
    r = roots()
    if manual:
        if not Path(manual).is_file():
            raise ParityJobError(f"The manual estimate could not be found: {manual}")
        manual_pick = {"path": manual, "why": "chosen by hand",
                       **_placed_manual(Path(manual), r["manual"])}
    else:
        candidates = find_manual(job, r["manual"])
        if not candidates:
            raise ParityJobError(
                f"No manual estimate was found for {job_digits(job)} under {r['manual']}: no "
                f"job folder or workbook in any client folder starts with that number. Choose "
                f"the workbook by hand.")
        manual_pick = candidates[0]
    if ai:
        if not Path(ai).is_file():
            raise ParityJobError(f"The AI estimate could not be found: {ai}")
        summary = _summary_for(Path(ai)) if Path(ai).suffix.lower() != ".json" else Path(ai)
        ai_pick = {"workbook": ai, "summary": str(summary) if summary else "",
                   **_placed_ai(Path(ai))}
    else:
        runs = find_ai(job, r["aisheets"])
        if not runs:
            raise ParityJobError(
                f"No AI estimate was found for {job} in AISheets: no run folder holds both the "
                f"engine's workbook and its summary. Run the estimate first, or choose it by hand.")
        ai_pick = runs[0]
    client = ai_pick.get("client") or manual_pick.get("client") or "Unknown client"
    drawing = ai_pick.get("drawing") or job
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(now or time.time()))
    folder = _new_folder(r["parity"] / _safe(client) / _safe(drawing), stamp)

    files = []
    for label, src in (("manual", manual_pick["path"]), ("ai", ai_pick["workbook"])):
        dest = folder / f"{label} - {Path(src).name}"
        shutil.copy2(src, dest)
        files.append(dest.name)
    summary = ai_pick.get("summary") or ""
    if summary and Path(summary).is_file():
        shutil.copy2(summary, folder / f"ai - {Path(summary).name}")
        files.append(f"ai - {Path(summary).name}")

    # THE SUMMARY OF THIS RUN, NOT ANOTHER. Handed the workbook, parity_run looks for the
    # summary in the engine's own JSON folder first, which holds the NEWEST run of the drawing;
    # comparing an older run's workbook against a newer run's reading would be two estimates
    # presented as one. So the summary filed beside the workbook goes in, when there is one.
    ai_side = summary if summary and Path(summary).is_file() else ai_pick["workbook"]
    # A COMPARISON THAT FAILS IS STILL FILED, with why. The two sheets are already copied, and
    # an index that says "could not be compared: <reason>" is what lets the next person see it
    # was tried and what stopped it, rather than finding a folder of two spreadsheets.
    error = ""
    try:
        result = (compare or _default_compare)(ai_side, manual_pick["path"], folder,
                                               read_via_excel)
    except Exception as exc:                                         # noqa: BLE001
        result, error = {}, f"{type(exc).__name__}: {exc}"
    index = {
        "job": job_digits(job), "drawing": drawing, "client": client, "stamp": stamp,
        "folder": str(folder),
        "manual": {"source": manual_pick["path"], "why": manual_pick.get("why", ""),
                   "copied_as": files[0]},
        "ai": {"source": ai_pick["workbook"], "run": ai_pick.get("stamp", ""),
               "run_folder": ai_pick.get("run_folder", ""), "copied_as": files[1]},
        "report_html": Path(result["bundle_html"]).name if result.get("bundle_html") else "",
        "bundle_json": Path(result["bundle_json"]).name if result.get("bundle_json") else "",
        "bundle_csv": Path(result["bundle_csv"]).name if result.get("bundle_csv") else "",
        "headline": result.get("headline") or {},
        "read_via_excel": bool(read_via_excel),
        "made_by": made_by or "by job number",
        "files": files,
        "error": error,
    }
    (folder / INDEX_NAME).write_text(json.dumps(index, indent=2, default=str), encoding="utf-8")
    if error:
        raise ParityJobError(f"The two estimates could not be compared ({error[:300]}). Both "
                             f"sheets and this reason are filed in {folder}.")
    return index


# ── search ──────────────────────────────────────────────────────────────────────────────

def _day(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ParityJobError(f"'{text}' is not a date as YYYY-MM-DD.") from exc


def search(text: str = "", start: Optional[str] = None, end: Optional[str] = None,
           parity_root: Optional[Path] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Filed comparisons, newest first, matching the text (job, drawing or client) and dates."""
    root = Path(parity_root or roots()["parity"])
    if not root.is_dir():
        return []
    lo, hi = _day(start), _day(end)
    want = _bare(text)
    out = []
    for path in root.glob(f"*/*/*/{INDEX_NAME}"):
        try:
            idx = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        day = _day(str(idx.get("stamp", ""))[:10]) if idx.get("stamp") else None
        if lo and (not day or day < lo) or hi and (not day or day > hi):
            continue
        if want and want not in _bare(f"{idx.get('job')} {idx.get('drawing')} {idx.get('client')}"):
            continue
        idx["folder"] = str(path.parent)
        out.append(idx)
    out.sort(key=lambda i: str(i.get("stamp", "")), reverse=True)
    return out[:limit]


# ── a period ────────────────────────────────────────────────────────────────────────────

def runs_between(start: str, end: str, aisheets_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The newest AI run of each drawing whose run folder is dated within the period."""
    root = Path(aisheets_root or roots()["aisheets"])
    lo, hi = _day(start), _day(end)
    if not lo or not hi or hi < lo:
        raise ParityJobError("A period needs a start and an end date, the end not before the start.")
    if not root.is_dir():
        raise ParityJobError(f"AISheets is not reachable: {root}")
    newest: Dict[str, Dict[str, Any]] = {}
    for cdir in sorted(p for p in root.iterdir() if p.is_dir()):
        for ddir in sorted(p for p in cdir.iterdir() if p.is_dir()):
            for rdir in sorted(p for p in ddir.iterdir() if p.is_dir()):
                m = _RUN_FOLDER.match(rdir.name)
                if not m or not (lo <= _day(m.group(1)) <= hi):
                    continue
                book = _engine_workbook(rdir, ddir.name)
                if not book or not _summary_for(book):
                    continue
                key = f"{cdir.name}\\{ddir.name}"
                if key not in newest or rdir.name > newest[key]["run"]:
                    newest[key] = {"client": cdir.name, "drawing": ddir.name, "run": rdir.name,
                                   "workbook": str(book)}
    return sorted(newest.values(), key=lambda r: (r["client"], r["drawing"]))


def _write_status(paths: Iterable[Optional[Path]], body: Dict[str, Any]) -> None:
    text = json.dumps(body, default=str)
    for path in paths:
        if not path:
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass


def run_period(start: str, end: str, *, preview: bool = False, read_via_excel: bool = False,
               compare: Optional[Callable[..., Dict[str, Any]]] = None,
               say: Callable[[str], None] = print,
               status_file: Optional[Path] = None) -> Dict[str, Any]:
    """Every AI estimate in the period against its manual estimate, each filed, one summary.

    status_file: a second copy of the progress, for the service, which started this in the
    background and does not know the folder's name until the first line is written."""
    r = roots()
    try:
        runs = runs_between(start, end, r["aisheets"])
    except ParityJobError as exc:
        _write_status([status_file], {"finished": True, "error": str(exc)})
        raise
    rows: List[Dict[str, Any]] = []
    folder = None
    status_path = None
    if not preview:
        folder = _new_folder(r["parity"] / "_periods",
                             f"{start} to {end} (run {time.strftime('%Y-%m-%d %H-%M-%S')})")
        status_path = folder / "status.json"
    _write_status([status_path, status_file],
                  {"done": 0, "of": len(runs), "rows": [], "folder": str(folder or ""),
                   "start": start, "end": end, "preview": preview})
    for i, run in enumerate(runs, start=1):
        row = {"client": run["client"], "drawing": run["drawing"], "ai_run": run["run"]}
        try:
            manual = find_manual(run["drawing"], r["manual"])
        except ParityJobError as exc:
            manual = []
            row["note"] = str(exc)
        if not manual:
            row.setdefault("note", "no manual estimate found")
            row["outcome"] = "no manual"
        elif preview:
            row.update(outcome="would compare", manual=manual[0]["path"])
        else:
            try:
                idx = run_job(run["drawing"], manual=manual[0]["path"], ai=run["workbook"],
                              read_via_excel=read_via_excel, compare=compare,
                              made_by=f"period {start} to {end}")
                h = idx.get("headline") or {}
                row.update(outcome="compared", manual=manual[0]["path"],
                           folder=idx["folder"], report=idx.get("report_html", ""),
                           ai_unit=h.get("ai_unit_cost_gbp"), manual_unit=h.get("manual_unit_cost_gbp"),
                           pct=h.get("pct_variance"), status=h.get("status"))
            except Exception as exc:                                 # noqa: BLE001
                row.update(outcome="failed", note=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        say(f"  {i}/{len(runs)}  {run['drawing']}: {row['outcome']}"
            + (f" ({row.get('note')})" if row.get("note") else ""))
        _write_status([status_path, status_file],
                      {"done": i, "of": len(runs), "rows": rows, "folder": str(folder or ""),
                       "start": start, "end": end, "preview": preview})
    result = {"start": start, "end": end, "preview": preview, "rows": rows,
              "compared": sum(1 for x in rows if x["outcome"] == "compared"),
              "no_manual": sum(1 for x in rows if x["outcome"] == "no manual"),
              "failed": sum(1 for x in rows if x["outcome"] == "failed")}
    if folder:
        result["folder"] = str(folder)
        (folder / "period_summary.json").write_text(json.dumps(result, indent=2, default=str),
                                                    encoding="utf-8")
        (folder / "period_summary.html").write_text(period_page(result, r["parity"]),
                                                    encoding="utf-8")
        result["summary_html"] = str(folder / "period_summary.html")
    _write_status([status_path, status_file],
                  {**result, "done": len(runs), "of": len(runs), "finished": True})
    return result


def periods(parity_root: Optional[Path] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Period comparisons already run, newest first: their dates, counts and summary page."""
    root = Path(parity_root or roots()["parity"]) / "_periods"
    if not root.is_dir():
        return []
    out = []
    for path in root.glob("*/period_summary.json"):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"start": body.get("start"), "end": body.get("end"),
                    "folder": str(path.parent), "name": path.parent.name,
                    "compared": body.get("compared"), "no_manual": body.get("no_manual"),
                    "failed": body.get("failed"),
                    "summary_html": str(path.parent / "period_summary.html")})
    out.sort(key=lambda x: x["name"].rsplit("(run ", 1)[-1], reverse=True)
    return out[:limit]


def _gbp(v: Any) -> str:
    try:
        return f"£{float(v):,.2f}"
    except (TypeError, ValueError):
        return "not read"


def period_page(result: Dict[str, Any], parity_root: Path) -> str:
    """One page: every job in the period, the two unit costs, the gap, and its report."""
    def link(row: Dict[str, Any]) -> str:
        if not row.get("folder") or not row.get("report"):
            return ""
        rel = os.path.relpath(Path(row["folder"]) / row["report"], Path(result["folder"]))
        return f'<a href="{html.escape(rel.replace(os.sep, "/"))}">report</a>'
    body = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td class=n>{}</td><td class=n>{}</td>"
        "<td class=n>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(r["drawing"]), html.escape(r["client"]), html.escape(r["ai_run"]),
            _gbp(r.get("ai_unit")) if r["outcome"] == "compared" else "",
            _gbp(r.get("manual_unit")) if r["outcome"] == "compared" else "",
            (f"{float(r['pct']):+.1f}%" if isinstance(r.get("pct"), (int, float)) else ""),
            html.escape(str(r.get("status") or r["outcome"])),
            link(r) or html.escape(r.get("note", "")))
        for r in result["rows"])
    return f"""<!doctype html><meta charset="utf-8"><title>Parity {html.escape(result['start'])} to {html.escape(result['end'])}</title>
<style>body{{font:14px/1.5 Segoe UI,Arial,sans-serif;margin:24px;color:#1a1e1c}}
table{{border-collapse:collapse}}td,th{{padding:5px 10px;border-bottom:1px solid #d5dad7;text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}h1{{font-size:22px}}</style>
<h1>AI against manual estimates, {html.escape(result['start'])} to {html.escape(result['end'])}</h1>
<p>{result['compared']} compared, {result['no_manual']} with no manual estimate found,
{result['failed']} could not be compared. Each AI estimate is the newest run of its drawing in
the period; each manual estimate is the most obvious workbook for its job number. Internal
costing only.</p>
<table><tr><th>Drawing</th><th>Client</th><th>AI run</th><th>AI unit</th><th>Manual unit</th>
<th>Gap</th><th>Verdict</th><th>Report</th></tr>{body}</table>
"""


# ── command line ────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parity by job number (D-619).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find"); f.add_argument("job")
    j = sub.add_parser("job"); j.add_argument("job")
    j.add_argument("--manual"); j.add_argument("--ai")
    j.add_argument("--read-via-excel", action="store_true")
    j.add_argument("--made-by", default="", help="what asked for it, for the index")
    s = sub.add_parser("search"); s.add_argument("text", nargs="?", default="")
    s.add_argument("--from", dest="start"); s.add_argument("--to", dest="end")
    p = sub.add_parser("period"); p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True); p.add_argument("--preview", action="store_true")
    p.add_argument("--read-via-excel", action="store_true")
    p.add_argument("--status-file", help="a second copy of the progress, for the service")
    q = sub.add_parser("periods")
    for x in (f, j, s, p, q):
        x.add_argument("--json", action="store_true", help="one JSON line, for the service")
    a = ap.parse_args(argv)
    try:
        import config  # noqa: F401  — loads .env, so the roots set there apply
    except Exception:                                                # noqa: BLE001
        pass
    try:
        if a.cmd == "find":
            out = {"job": a.job, "manual": find_manual(a.job), "ai": find_ai(a.job)}
            if not a.json:
                print(f"Manual estimates for {job_digits(a.job)}, most obvious first:")
                for c in out["manual"] or []:
                    print(f"  {c['path']}  ({c['why']}, {c['modified_text']})")
                print("AI estimates, newest first:")
                for run in out["ai"] or []:
                    print(f"  {run['workbook']}")
        elif a.cmd == "job":
            out = run_job(a.job, a.manual, a.ai, read_via_excel=a.read_via_excel,
                          made_by=a.made_by)
            if not a.json:
                h = out["headline"]
                print(f"Filed to {out['folder']}\n  manual {out['manual']['source']}\n"
                      f"  AI     {out['ai']['source']}\n  AI {_gbp(h.get('ai_unit_cost_gbp'))} "
                      f"against manual {_gbp(h.get('manual_unit_cost_gbp'))}, "
                      f"verdict {h.get('status') or 'not read'}; report {out['report_html']}")
        elif a.cmd == "search":
            out = {"reports": search(a.text, a.start, a.end)}
            if not a.json:
                for i in out["reports"]:
                    print(f"  {i['stamp']}  {i['drawing']}  {i['client']}  {i['folder']}")
        elif a.cmd == "periods":
            out = {"periods": periods()}
            if not a.json:
                for x in out["periods"]:
                    print(f"  {x['name']}: {x['compared']} compared  {x['summary_html']}")
        else:
            out = run_period(a.start, a.end, preview=a.preview, read_via_excel=a.read_via_excel,
                             say=(lambda m: None) if a.json else print,
                             status_file=Path(a.status_file) if a.status_file else None)
            if not a.json:
                print(f"{out['compared']} compared, {out['no_manual']} with no manual, "
                      f"{out['failed']} failed" + (f"; summary in {out['folder']}"
                                                   if out.get("folder") else "; preview only"))
    except ParityJobError as exc:
        if a.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:                                         # noqa: BLE001
        # A period runs in the background; the page reads the status file, so it must say
        # the run ended, and why, rather than show "running" for ever.
        if getattr(a, "status_file", None):
            _write_status([Path(a.status_file)],
                          {"finished": True, "error": f"{type(exc).__name__}: {exc}"})
        raise
    if a.json:
        print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
