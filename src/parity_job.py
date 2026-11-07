#!/usr/bin/env python3
r"""Parity by job number: find both estimates, compare the filed copies, keep the evidence.

    python src\parity_job.py find   12677-01-GA [--client Acme]     both sides, and whether it is clear
    python src\parity_job.py job    12677-01-GA [--client Acme]     compare and file (only when clear)
    python src\parity_job.py job    12677-01-GA --manual "<path>" --ai "<path>"
    python src\parity_job.py search [text] [--from D] [--to D] [--outcome match|warning|fail|...]
    python src\parity_job.py period --from 2026-10-01 --to 2026-10-31 [--client X] [--preview]
    python src\parity_job.py periods --a-from D --a-to D --b-from D --b-to D [--client X] [--job N]
    python src\parity_job.py history                                period comparisons already run
    python src\parity_job.py wall                                   the control panel's parity view (D-741)

JG, 1 Nov 2026 (D-619): compare one job by job number, "we take the most obvious s/sheet
candidate and we run a parity against it from our AI estimate with html outputs", save both
sheets and the reports under AI Estimating\parity, searchable, and "a search and comparison
between all manual and AI estimates ran across two time periods".

THE REVIEW, 1 Nov 2026 (D-621), and what changed because of it:
  * MATCHING RESPECTS THE CLIENT AND THE DRAWING. A sheet is chosen for you only when the choice
    is clear: under a client folder matching the AI run's client, naming the full drawing number
    when one is given, in one job folder, and better than the next by issue. Otherwise every
    candidate is returned with the reason it could not be decided, and a person chooses.
  * THE FILED COPIES ARE WHAT IS COMPARED. Both workbooks, the run's summary and its record are
    copied, unchanged and under their own names, into ai\ and manual\ in the comparison's folder,
    each with its SHA-256; the comparison then reads those copies, so the report always
    describes exactly what is kept.
  * THE RUN'S OWN SUMMARY, NEVER ANOTHER. A workbook with no summary filed beside it is refused:
    looking elsewhere could find a newer run's reading of the same drawing.
  * QUANTITIES MUST MATCH. The comparator divides the engine's total by the manual sheet's
    quantity; when the run priced a different quantity that unit cost is wrong. The run's own
    quantity sweep is used at the manual's quantity where it priced it; otherwise the comparison
    is marked "quantities differ" and is not counted as a match or a miss.
  * A SINGLE COMPARISON CAN RUN IN THE BACKGROUND with a status file the service polls.
  * TWO PERIODS: Period A against Period B, filtered by client and job. Within each period every
    drawing is counted once (its newest run, the others collapsed and counted); pairs with no
    manual estimate, ambiguous pairs and quantity mismatches are listed apart from the
    comparable ones; a pair already compared with the same manual sheet is reused, not redone.
    The date is the AI estimate's (its run folder); the manual sheet's date is its file date and
    says so.

THE COMPARISON ITSELF IS parity_run.run_parity (the engine's summary against the manual
workbook, with its bundle, CSV and HTML report), unchanged. Nothing outside the parity folder is
ever written, and the original sheets are only ever read.

FILED: <parity>\<client>\<drawing>\<date time>_<comparison id>\
    ai\<the engine's workbook>  ai\<its summary .json>  ai\<its record .json>
    manual\<the manual workbook>
    <the parity report .html, bundle .json, .csv>
    parity_index.json            the manifest: sources, copies, fingerprints, dates, quantities,
                                 how the manual sheet was chosen, the headline and the outcome
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import statistics
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

MANUAL_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
AISHEETS_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"
PARITY_DEFAULT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\parity"
SCHEMA = "sdi_parity_comparison.v2"
WORKBOOK_SUFFIXES = (".xls", ".xlsx", ".xlsm")
INDEX_NAME = "parity_index.json"
COMPARABLE = ("match", "warning", "fail")
_RUN_FOLDER = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2})-(\d{2})-(\d{2}) \((\d+) off\)$")
_ISSUE = re.compile(r"\b(?:ISS(?:UE)?|REV(?:ISION)?|R|V)\s*\.?\s*([0-9]+|[A-Z])\b", re.I)
_SECOND_RATE = ("copy", "old", "superseded", "draft", "quote", "backup", "bak")
_NEVER = ("blank estimate", "template")


class ParityJobError(ValueError):
    """Something a person can fix: no manual estimate found, no AI run, a bad date."""


class ParityChoiceNeeded(ParityJobError):
    """More than one manual sheet could be the one, or the likeliest does not match the client
    or the drawing: a person chooses. Carries every candidate and the reason."""

    def __init__(self, reason: str, candidates: List[Dict[str, Any]]):
        super().__init__(reason)
        self.candidates = candidates


def roots() -> Dict[str, Path]:
    return {"manual": Path(os.getenv("SDI_MANUAL_ESTIMATES_ROOT", "") or MANUAL_DEFAULT),
            "aisheets": Path(os.getenv("SDI_ESTIMATE_OUTPUT_ROOT", "") or AISHEETS_DEFAULT),
            "parity": Path(os.getenv("SDI_PARITY_ROOT", "") or PARITY_DEFAULT)}


# ── names ───────────────────────────────────────────────────────────────────────────────

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


def client_matches(folder: str, client: str) -> bool:
    """The same client, with case, spaces and punctuation set aside: "ACME" is "Acme Ltd"."""
    a, b = _bare(folder), _bare(client)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


# ── the manual estimate ─────────────────────────────────────────────────────────────────

def _issue_rank(name: str) -> int:
    found = _ISSUE.findall(Path(name).stem)
    if not found:
        return 0
    last = found[-1].upper()
    return int(last) if last.isdigit() else ord(last) - ord("A") + 1


def _manual_candidate(path: Path, job: str, client_folder: str, year: str,
                      wanted_client: str = "") -> Optional[Dict[str, Any]]:
    name = path.name
    lower = name.lower()
    if (not path.is_file() or path.suffix.lower() not in WORKBOOK_SUFFIXES
            or name.startswith("~$") or any(w in lower for w in _NEVER)):
        return None
    full = _bare(job)
    names_drawing = len(full) > len(job_digits(job)) and full in _bare(path.stem)
    issue = _issue_rank(name)
    second = [w for w in _SECOND_RATE if re.search(rf"\b{w}\b", lower)]
    if wanted_client:
        client_match = "same" if client_matches(client_folder, wanted_client) else "other"
    else:
        client_match = "unknown"
    reasons = []
    if client_match == "same":
        reasons.append("the run's client")
    elif client_match == "other":
        reasons.append(f"a different client ({client_folder})")
    if names_drawing:
        reasons.append("names the drawing")
    if issue:
        reasons.append(f"issue {issue}")
    if second:
        reasons.append("looks like a " + "/".join(second))
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return {"path": str(path), "name": name, "client": client_folder, "year": year,
            "folder": str(path.parent), "issue": issue, "modified": modified,
            "modified_text": time.strftime("%d %b %Y %H:%M", time.localtime(modified)),
            "names_drawing": names_drawing, "second_rate": bool(second),
            "client_match": client_match,
            "_rank": (1 if client_match != "other" else 0, 0 if second else 1,
                      1 if names_drawing else 0, issue, modified),
            "why": ", ".join(reasons) or "the job's workbook"}


def find_manual(job: str, manual_root: Optional[Path] = None,
                years: Optional[Iterable[str]] = None,
                client: str = "") -> List[Dict[str, Any]]:
    """Every manual workbook for this job number, likeliest first, each saying why. Every client
    folder is looked in, so a sheet filed under another client is shown as that, not missed;
    whether one may be chosen without asking is decide()'s question."""
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
                files = [entry]
                if entry.is_dir():
                    try:
                        inner = list(entry.iterdir())
                    except OSError:
                        inner = []
                    files = inner + [g for d in inner if d.is_dir() for g in d.iterdir()]
                for f in files:
                    c = _manual_candidate(f, job, cdir.name, ydir.name, client)
                    if c:
                        found.append(c)
        if found:
            break                                    # the newest year that has the job
    found.sort(key=lambda c: c["_rank"], reverse=True)
    for c in found:
        c.pop("_rank", None)
    return found


def decide(candidates: List[Dict[str, Any]], job: str, client: str = "") -> Dict[str, Any]:
    """Whether the likeliest sheet may be used without asking, and why.

    Clear only when: it is under a client folder matching the run's client (when the client is
    known); it names the full drawing number (when one is given, e.g. 12677-01-GA rather than
    12677); the sheets left are in one job folder; and it is a higher issue than the next. A
    date alone never decides between two sheets."""
    if not candidates:
        return {"pick": None, "clear": False, "reason": "No manual estimate was found."}
    pool = list(candidates)
    if client:
        same = [c for c in pool if c["client_match"] == "same"]
        if not same:
            return {"pick": pool[0], "clear": False, "reason": (
                f"No sheet is under a client folder matching '{client}'. The likeliest is "
                f"under '{pool[0]['client']}': choose it if it is right.")}
        pool = same
    digits = job_digits(job)
    if len(_bare(job)) > len(digits):
        named = [c for c in pool if c["names_drawing"]]
        if not named:
            return {"pick": pool[0], "clear": False, "reason": (
                f"No sheet names {job}; the ones found start with {digits} only, and a job "
                f"number can cover several drawings. Choose the right one.")}
        pool = named
    good = [c for c in pool if not c["second_rate"]] or pool
    folders = sorted({c["folder"] for c in good})
    if len(folders) > 1:
        return {"pick": good[0], "clear": False, "reason": (
            f"Sheets for this job are in {len(folders)} folders "
            f"({'; '.join(Path(f).name for f in folders[:4])}). Choose the right one.")}
    if len(good) == 1:
        return {"pick": good[0], "clear": True, "reason": good[0]["why"]}
    top, nxt = good[0], good[1]
    if top["issue"] > nxt["issue"]:
        return {"pick": top, "clear": True,
                "reason": f"{top['why']}; the highest issue of {len(good)} sheets"}
    return {"pick": top, "clear": False, "reason": (
        f"{len(good)} sheets are equally likely ({', '.join(c['name'] for c in good[:4])}): "
        f"no issue number tells them apart, and a date alone does not decide. Choose one.")}


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


def _record_for(folder: Path) -> Optional[Path]:
    """The run's record (D-616), when its folder holds exactly one."""
    try:
        records = [p for p in folder.glob("*_record.json") if p.is_file()]
    except OSError:
        return None
    return records[0] if len(records) == 1 else None


def find_ai(job: str, aisheets_root: Optional[Path] = None,
            client: str = "") -> List[Dict[str, Any]]:
    """Every AI run of this job that holds a workbook and its summary, the exact drawing and
    the client's own runs first, then newest first."""
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
                record = _record_for(rdir)
                runs.append({"workbook": str(book), "summary": str(summary),
                             "record": str(record) if record else "",
                             "run_folder": str(rdir), "client": cdir.name,
                             "drawing": ddir.name, "stamp": rdir.name[:19],
                             "day": m.group(1), "units": int(m.group(5)), "exact": exact,
                             "client_match": bool(client) and client_matches(cdir.name, client)})
    runs.sort(key=lambda r: (r["exact"], r["client_match"], r["stamp"]), reverse=True)
    return runs


def _placed_manual(path: Path, manual_root: Path) -> Dict[str, str]:
    try:
        parts = path.resolve().relative_to(manual_root.resolve()).parts
    except (OSError, ValueError):
        parts = ()
    if len(parts) >= 3 and re.fullmatch(r"20\d\d", parts[0]):
        return {"year": parts[0], "client": parts[1]}
    return {"year": "", "client": ""}


def _placed_ai(path: Path) -> Dict[str, Any]:
    run = path.parent
    m = _RUN_FOLDER.match(run.name)
    if m and run.parent.parent != run.parent:
        return {"client": run.parent.parent.name, "drawing": run.parent.name,
                "stamp": run.name[:19], "run_folder": str(run), "units": int(m.group(5))}
    return {"client": "", "drawing": "", "stamp": "", "run_folder": str(run), "units": None}


def _ai_side(ai: str) -> Dict[str, Any]:
    """The AI side chosen by hand: its workbook, its own summary and record. A workbook with
    no summary beside it is refused rather than matched to a summary found elsewhere."""
    p = Path(ai)
    if not p.is_file():
        raise ParityJobError(f"The AI estimate could not be found: {ai}")
    if p.suffix.lower() == ".json":
        summary, book = p, _engine_workbook(p.parent, p.stem)
    else:
        book, summary = p, _summary_for(p)
        if summary is None:
            raise ParityJobError(
                f"No summary is filed beside {p.name}. The comparison reads that run's own "
                f"summary, and one found anywhere else could be a different run of the same "
                f"drawing. Choose the run's .json, or a run folder that holds one.")
    record = _record_for(p.parent)
    return {"workbook": str(book) if book else "", "summary": str(summary),
            "record": str(record) if record else "", **_placed_ai(p)}


# ── fingerprints, snapshots, quantities ─────────────────────────────────────────────────

def fingerprint(path: Path) -> Dict[str, Any]:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    st = path.stat()
    return {"sha256": h.hexdigest(), "bytes": st.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}


def _snapshot(src: str, into: Path) -> Dict[str, Any]:
    """Copy one source, unchanged and under its own name, and fingerprint both ends. A source
    that changed while it was being copied is refused, so a kept copy is never half of two."""
    source = Path(src)
    before = fingerprint(source)
    into.mkdir(parents=True, exist_ok=True)
    dest = into / source.name
    shutil.copy2(source, dest)
    after = fingerprint(dest)
    if after["sha256"] != before["sha256"]:
        raise ParityJobError(f"{source.name} changed while it was being copied; try again when "
                             f"nobody is saving it.")
    return {"source": str(source), "copied_as": f"{into.name}/{dest.name}", "path": str(dest),
            **after}


def _new_folder(base: Path, name: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        folder = base / (name if n == 1 else f"{name} ({n})")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise OSError(f"no free folder under {base}")


def _thresholds() -> tuple:
    """The comparator's own verdict thresholds, so a quantity-corrected verdict means the same."""
    try:
        import config
        t = (getattr(config, "WORKBOOK_EQUIVALENT_PRICING", {}) or {}).get(
            "variance_thresholds_pct") or {}
        return float(t.get("match", 3.0)), float(t.get("warning", 10.0))
    except Exception:                                                # noqa: BLE001
        return 3.0, 10.0


def _verdict(pct: Optional[float]) -> str:
    if pct is None:
        return "review"
    match, warn = _thresholds()
    return "match" if pct <= match else "warning" if pct <= warn else "fail"


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def quantities(summary: Dict[str, Any], bundle: Dict[str, Any], run_units: Optional[int],
               headline: Dict[str, Any]) -> Dict[str, Any]:
    """The quantity each side priced, whether their unit costs can be compared, and the AI unit
    cost at the manual's quantity when the run's quantity sweep priced it."""
    est = summary.get("estimate_summary") if isinstance(summary.get("estimate_summary"), dict) else {}
    ai_qty = _num(((est or {}).get("estimate_workbook_inputs") or {}).get("assumed_job_quantity"))
    if ai_qty is None and run_units:
        ai_qty = float(run_units)
    manual_qty = None
    for row in bundle.get("money_cell_comparisons") or []:
        if str(row.get("label", "")).lower().startswith("reference order quantity"):
            manual_qty = _num(row.get("workbook_cached_numeric"))
            break
    sweep = {}
    for r in ((summary.get("quantity_sweep") or {}).get("rows") or []):
        q, u = _num((r or {}).get("quantity")), _num((r or {}).get("unit"))
        if q and u:
            sweep[q] = u
    out: Dict[str, Any] = {"ai": ai_qty, "manual": manual_qty, "comparable": True, "note": ""}
    if ai_qty is None or manual_qty is None:
        out["note"] = "One side's quantity could not be read; check the report before relying on the unit costs."
        return out
    if abs(ai_qty - manual_qty) < 1e-9:
        return out
    manual_unit = _num(headline.get("manual_unit_cost_gbp"))
    if manual_qty in sweep and manual_unit:
        ai_unit = round(sweep[manual_qty], 2)
        # A percentage of the manual figure, as the line-by-line comparison states every one.
        pct = round(abs(ai_unit - manual_unit) / abs(manual_unit) * 100.0, 4)
        out.update(note=(f"The AI run priced {ai_qty:g} off and the manual sheet {manual_qty:g} off; "
                         f"compared at {manual_qty:g} off from the run's own quantity sweep."),
                   ai_unit_at_manual_qty=ai_unit, pct_at_manual_qty=pct,
                   status_at_manual_qty=_verdict(pct),
                   gap_at_manual_qty=round(ai_unit - manual_unit, 2))
        return out
    out.update(comparable=False, note=(
        f"Quantities differ: the AI run priced {ai_qty:g} off and the manual sheet is "
        f"{manual_qty:g} off, which the run did not price. The unit costs are not comparable; "
        f"re-run the estimate at {manual_qty:g} off, or compare another run."))
    return out


def outcome_of(index: Dict[str, Any]) -> str:
    if index.get("error"):
        return "not compared"
    q = index.get("quantity") or {}
    if q and not q.get("comparable", True):
        return "quantities differ"
    if q.get("status_at_manual_qty"):
        return str(q["status_at_manual_qty"])
    return str((index.get("headline") or {}).get("status") or "review")


def unit_pct(index: Dict[str, Any]) -> Optional[float]:
    q = index.get("quantity") or {}
    if q.get("pct_at_manual_qty") is not None:
        return _num(q["pct_at_manual_qty"])
    return _num((index.get("headline") or {}).get("pct_variance"))


def _money_lines(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The money rows the comparator read, cost kept apart from selling price, each with its
    cell on the manual sheet."""
    out = []
    for row in bundle.get("money_cell_comparisons") or []:
        out.append({"label": row.get("label"), "ai": _num(row.get("json_numeric")),
                    "manual": _num(row.get("workbook_cached_numeric")),
                    "pct": _num(row.get("pct_variance")), "status": row.get("status"),
                    "cell": row.get("cell")})
    return out


def _detail_quantity(detail: Dict[str, Any], headline: Dict[str, Any]) -> Dict[str, Any]:
    """The line-by-line comparison's quantities, in the shape the index has always carried."""
    q = dict(detail.get("quantity") or {})
    out: Dict[str, Any] = {"ai": q.get("ai"), "manual": q.get("manual"),
                           "comparable": q.get("comparable", True), "note": q.get("note", ""),
                           "compared_at": q.get("compared_at"), "manual_cell": q.get("manual_cell")}
    if q.get("ai_unit_at_manual_qty") is not None:
        out.update(ai_unit_at_manual_qty=q["ai_unit_at_manual_qty"],
                   pct_at_manual_qty=headline.get("pct_variance"),
                   status_at_manual_qty=headline.get("status"),
                   gap_at_manual_qty=headline.get("gap_gbp"))
    return out


def _detail_lines(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The cost build-up, the selling side and the commercial lines, each with its cell: cost
    and sell never in one line."""
    out = []
    for kind in ("cost_build", "selling"):
        for r in detail.get(kind) or []:
            out.append({"kind": "cost" if kind == "cost_build" else "selling",
                        "label": r.get("label"), "ai": r.get("ai"), "manual": r.get("manual"),
                        "pct": r.get("pct"), "status": r.get("status"),
                        "cell": r.get("manual_cell"), "fraction": bool(r.get("fraction"))})
    for c in (detail.get("commercial") or {}).get("categories") or []:
        out.append({"kind": "commercial", "label": c.get("label"), "ai": c.get("ai"),
                    "manual": c.get("manual"), "pct": c.get("pct"),
                    "status": c.get("status") if c.get("presence") == "both" else c.get("presence"),
                    "cell": ", ".join(str(x.get("cell")) for x in (c.get("manual_lines") or [])
                                      if x.get("cell"))})
    return out


# ── one comparison ──────────────────────────────────────────────────────────────────────

def _default_compare(ai: str, manual: str, out_dir: Path, read_via_excel: bool) -> Dict[str, Any]:
    from parity_run import run_parity
    return run_parity(ai, manual, out_dir=out_dir, read_via_excel=read_via_excel)


def _status(path: Optional[Path], body: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def run_job(job: str, manual: Optional[str] = None, ai: Optional[str] = None, *,
            client: str = "", read_via_excel: bool = False,
            compare: Optional[Callable[..., Dict[str, Any]]] = None,
            now: Optional[float] = None, made_by: str = "", comparison_id: str = "",
            say: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    """Compare one job's AI estimate with its manual one, from filed copies, and keep them."""
    r = roots()
    say("Finding the AI estimate…")
    if ai:
        ai_pick = _ai_side(ai)
    else:
        runs = find_ai(job, r["aisheets"], client=client)
        if not runs:
            raise ParityJobError(
                f"No AI estimate was found for {job} in AISheets: no run folder holds both the "
                f"engine's workbook and its summary. Run the estimate first, or choose it by hand.")
        ai_pick = runs[0]
    client = client or ai_pick.get("client") or ""
    say("Finding the manual estimate…")
    if manual:
        if not Path(manual).is_file():
            raise ParityJobError(f"The manual estimate could not be found: {manual}")
        manual_pick = {"path": manual, "why": "chosen by hand",
                       **_placed_manual(Path(manual), r["manual"])}
        how, match_reason = "chosen by hand", "chosen by hand"
    else:
        candidates = find_manual(job, r["manual"], client=client)
        if not candidates:
            raise ParityJobError(
                f"No manual estimate was found for {job_digits(job)} under {r['manual']}: no "
                f"job folder or workbook in any client folder starts with that number. Choose "
                f"the workbook by hand.")
        d = decide(candidates, job, client)
        if not d["clear"]:
            raise ParityChoiceNeeded(d["reason"], candidates)
        manual_pick, how, match_reason = d["pick"], "found by job number", d["reason"]

    folder_client = client or manual_pick.get("client") or "Unknown client"
    drawing = ai_pick.get("drawing") or job
    cid = comparison_id or uuid.uuid4().hex[:8]
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(now or time.time()))
    folder = _new_folder(r["parity"] / _safe(folder_client) / _safe(drawing), f"{stamp}_{cid}")

    say("Copying both estimates into the parity folder…")
    manual_copy = _snapshot(manual_pick["path"], folder / "manual")
    ai_copy = _snapshot(ai_pick["summary"], folder / "ai")
    book_copy = _snapshot(ai_pick["workbook"], folder / "ai") if ai_pick.get("workbook") else {}
    record_copy = _snapshot(ai_pick["record"], folder / "ai") if ai_pick.get("record") else {}

    say("Comparing the copies…")
    error, result = "", {}
    try:
        result = (compare or _default_compare)(ai_copy["path"], manual_copy["path"], folder,
                                               read_via_excel)
    except Exception as exc:                                         # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    headline = result.get("headline") or {}
    bundle = _load(result["bundle_json"]) if result.get("bundle_json") else {}
    # D-623: the line-by-line record answers quantity, lines, scope and revision when it was
    # made and read both unit costs; the money-cell bundle answers otherwise.
    detail = _load(result["detail_json"]) if result.get("detail_json") else {}
    use_detail = bool(detail) and headline.get("unit_cost_source") == "line by line"
    if error:
        quantity = {}
    elif use_detail:
        quantity = _detail_quantity(detail, headline)
    else:
        quantity = quantities(_load(ai_copy["path"]), bundle, ai_pick.get("units"), headline)

    for c in (manual_copy, ai_copy, book_copy, record_copy):
        c.pop("path", None)
    index = {
        "schema": SCHEMA, "comparison_id": cid, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "job": job_digits(job), "drawing": drawing, "client": folder_client, "stamp": stamp,
        "folder": str(folder), "made_by": made_by or "by job number",
        "match": {"how": how, "reason": match_reason,
                  "client_matched": bool(client) and client_matches(manual_pick.get("client", ""), client)},
        "manual": {**manual_copy, "client_folder": manual_pick.get("client", ""),
                   "year": manual_pick.get("year", ""),
                   "date": manual_copy.get("modified"), "date_basis": "the sheet's file date"},
        "ai": {**{k: v for k, v in book_copy.items()},
               "source": ai_pick.get("workbook") or ai_pick["summary"],
               "copied_as": book_copy.get("copied_as") or ai_copy["copied_as"],
               "summary": ai_copy, "record": record_copy or None,
               "run": ai_pick.get("stamp", ""), "run_folder": ai_pick.get("run_folder", ""),
               "units": ai_pick.get("units"),
               "date": ai_pick.get("stamp", ""), "date_basis": "the AI run folder's date and time"},
        "quantity": quantity,
        "report_html": Path(result["bundle_html"]).name if result.get("bundle_html") else "",
        "legacy_html": (Path(result["legacy_html"]).name if result.get("legacy_html")
                        and result.get("legacy_html") != result.get("bundle_html") else ""),
        "detail_json": Path(result["detail_json"]).name if result.get("detail_json") else "",
        "bundle_json": Path(result["bundle_json"]).name if result.get("bundle_json") else "",
        "bundle_csv": Path(result["bundle_csv"]).name if result.get("bundle_csv") else "",
        # The spoken comparison (D-627): the .wav where the machine has a voice, its words
        # always, both filed with the report.
        "walkthrough_wav": Path(result["walkthrough_wav"]).name if result.get("walkthrough_wav") else "",
        "walkthrough_txt": Path(result["walkthrough_txt"]).name if result.get("walkthrough_txt") else "",
        # An audio failure never costs the comparison; it is said here, explicitly, instead.
        "walkthrough_note": str(result.get("walkthrough_note") or ""),
        "headline": headline,
        "lines": _detail_lines(detail) if use_detail else _money_lines(bundle),
        "lines_from": "line by line" if use_detail else "money cells",
        "scope_counts": ((detail.get("scope") or {}).get("counts") if detail else None),
        "revision": ({k: (detail.get("revision") or {}).get(k) for k in ("manual", "ai", "differs")}
                     if detail else None),
        "differences": (detail.get("differences") or [])[:10] if detail else [],
        "read_via_excel": bool(read_via_excel), "error": error,
    }
    index["outcome"] = outcome_of(index)
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


# A date, optionally with a time: 2026-10-31, 2026-10-31 09:30, 2026-10-31T09:30:15. The time's
# separators may be ':' or '-', because that is how the run folders themselves spell it.
_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2})[:\-](\d{2})(?:[:\-](\d{2}))?)?$")


def _moment(text: Optional[str], *, late: bool = False) -> Optional[datetime]:
    """The boundary a person typed, as an exact moment (D-625).

    A bare date has always meant the whole day, and keeps meaning it: its first second, or
    with `late` its last, so one day is a valid period on its own. A time narrows it — two
    runs of the same drawing on the same day can be compared morning against afternoon — and
    an end given to the minute includes that whole minute."""
    if not text or not str(text).strip():
        return None
    m = _WHEN.match(str(text).strip())
    if not m:
        raise ParityJobError(f"'{text}' is not a date as YYYY-MM-DD, or a date and time as "
                             f"YYYY-MM-DD HH:MM.")
    day = datetime.strptime(m.group(1), "%Y-%m-%d")
    if m.group(2) is None:
        return day.replace(hour=23, minute=59, second=59) if late else day
    hour, minute = int(m.group(2)), int(m.group(3))
    second = int(m.group(4)) if m.group(4) is not None else (59 if late else 0)
    if hour > 23 or minute > 59 or second > 59:
        raise ParityJobError(f"'{text}' is not a time of day.")
    return day.replace(hour=hour, minute=minute, second=second)


def _stamp_dt(stamp: str) -> Optional[datetime]:
    """A run folder's or comparison's stamp, '2026-10-31 14-30-00', as a datetime."""
    try:
        return datetime.strptime(str(stamp or "")[:19], "%Y-%m-%d %H-%M-%S")
    except ValueError:
        try:
            return datetime.strptime(str(stamp or "")[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _indexes(root: Path) -> List[Dict[str, Any]]:
    out = []
    for path in root.glob(f"*/*/*/{INDEX_NAME}"):
        idx = _load(str(path))
        if idx:
            idx["folder"] = str(path.parent)
            idx.setdefault("outcome", outcome_of(idx))
            out.append(idx)
    return out


def search(text: str = "", start: Optional[str] = None, end: Optional[str] = None,
           parity_root: Optional[Path] = None, limit: int = 200,
           outcome: str = "") -> List[Dict[str, Any]]:
    """Filed comparisons, newest first, by job, drawing or client, date and outcome."""
    root = Path(parity_root or roots()["parity"])
    if not root.is_dir():
        return []
    lo, hi = _moment(start), _moment(end, late=True)
    want = _bare(text)
    out = []
    for idx in _indexes(root):
        when = _stamp_dt(str(idx.get("stamp", ""))) if idx.get("stamp") else None
        if lo and (not when or when < lo) or hi and (not when or when > hi):
            continue
        if want and want not in _bare(f"{idx.get('job')} {idx.get('drawing')} {idx.get('client')}"):
            continue
        if outcome and idx["outcome"] != outcome:
            continue
        out.append(idx)
    out.sort(key=lambda i: str(i.get("stamp", "")), reverse=True)
    return out[:limit]


# ── periods ─────────────────────────────────────────────────────────────────────────────

def runs_between(start: str, end: str, aisheets_root: Optional[Path] = None,
                 client: str = "", job: str = "") -> List[Dict[str, Any]]:
    """Each drawing estimated in the period, once: its newest run there, with how many runs it
    had. The date is the AI run folder's."""
    root = Path(aisheets_root or roots()["aisheets"])
    lo, hi = _moment(start), _moment(end, late=True)
    if not lo or not hi or hi < lo:
        raise ParityJobError("A period needs a start and an end, as dates or dates with times, "
                             "the end not before the start. One day, or part of one, is fine.")
    if not root.is_dir():
        raise ParityJobError(f"AISheets is not reachable: {root}")
    digits = job_digits(job) if job else ""
    newest: Dict[str, Dict[str, Any]] = {}
    for cdir in sorted(p for p in root.iterdir() if p.is_dir()):
        if client and not client_matches(cdir.name, client):
            continue
        for ddir in sorted(p for p in cdir.iterdir() if p.is_dir()):
            if digits and not _starts_with_job(ddir.name, digits):
                continue
            for rdir in sorted(p for p in ddir.iterdir() if p.is_dir()):
                m = _RUN_FOLDER.match(rdir.name)
                if not m:
                    continue
                ran = _stamp_dt(rdir.name)
                if not ran or not (lo <= ran <= hi):
                    continue
                book = _engine_workbook(rdir, ddir.name)
                if not book or not _summary_for(book):
                    continue
                key = f"{cdir.name}\\{ddir.name}"
                seen = newest.get(key)
                runs = (seen["runs_in_period"] if seen else 0) + 1
                if not seen or rdir.name > seen["run"]:
                    newest[key] = {"client": cdir.name, "drawing": ddir.name, "run": rdir.name,
                                   "run_folder": str(rdir), "workbook": str(book),
                                   "units": int(m.group(5)), "estimate_date": m.group(1)}
                newest[key]["runs_in_period"] = runs
    return sorted(newest.values(), key=lambda r: (r["client"], r["drawing"]))


def _reusable(archive: List[Dict[str, Any]], run_folder: str, manual_sha: str) -> Optional[Dict[str, Any]]:
    """An earlier comparison of the same run against the same sheet, made by the comparator in
    use now. One filed before the line-by-line comparison (D-623) carries no `lines_from`; it
    stays in the archive and in search, but a period compares that pair again rather than
    linking a report that has no cost, scope or commercial lines in it."""
    for idx in sorted(archive, key=lambda i: str(i.get("stamp", "")), reverse=True):
        if (not idx.get("error") and idx.get("lines_from")
                and (idx.get("ai") or {}).get("run_folder") == run_folder
                and (idx.get("manual") or {}).get("sha256") == manual_sha):
            return idx
    return None


def _pair(run: Dict[str, Any], r: Dict[str, Path], archive: List[Dict[str, Any]], *,
          preview: bool, read_via_excel: bool, compare, made_by: str) -> Dict[str, Any]:
    row = {"client": run["client"], "drawing": run["drawing"], "ai_run": run["run"],
           "estimate_date": run["estimate_date"], "runs_in_period": run["runs_in_period"]}
    try:
        candidates = find_manual(run["drawing"], r["manual"], client=run["client"])
    except ParityJobError as exc:
        return {**row, "outcome": "no manual", "note": str(exc)}
    if not candidates:
        return {**row, "outcome": "no manual", "note": "no manual estimate found"}
    d = decide(candidates, run["drawing"], run["client"])
    if not d["clear"]:
        return {**row, "outcome": "ambiguous", "note": d["reason"],
                "candidates": [c["path"] for c in candidates[:6]]}
    manual = d["pick"]["path"]
    if preview:
        return {**row, "outcome": "would compare", "manual": manual, "why": d["reason"]}
    try:
        idx = _reusable(archive, run["run_folder"], fingerprint(Path(manual))["sha256"])
        reused = idx is not None
        if not idx:
            idx = run_job(run["drawing"], manual=manual, ai=run["workbook"], client=run["client"],
                          read_via_excel=read_via_excel, compare=compare, made_by=made_by)
            archive.append(idx)
    except Exception as exc:                                         # noqa: BLE001
        return {**row, "outcome": "failed", "note": f"{type(exc).__name__}: {exc}", "manual": manual}
    h, q = idx.get("headline") or {}, idx.get("quantity") or {}
    return {**row, "outcome": idx.get("outcome") or outcome_of(idx), "manual": manual,
            "folder": idx["folder"], "report": idx.get("report_html", ""), "reused": reused,
            "ai_unit": q.get("ai_unit_at_manual_qty") or h.get("ai_unit_cost_gbp"),
            "manual_unit": h.get("manual_unit_cost_gbp"), "pct": unit_pct(idx),
            "quantity_note": q.get("note", ""), "status": idx.get("outcome")}


def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparable = [x for x in rows if x["outcome"] in COMPARABLE]
    pcts = [abs(float(x["pct"])) for x in comparable if isinstance(x.get("pct"), (int, float))]
    count = {k: sum(1 for x in rows if x["outcome"] == k)
             for k in ("match", "warning", "fail", "quantities differ", "no manual", "ambiguous",
                       "failed", "not compared", "would compare")}
    return {"drawings": len(rows), "compared": len(comparable), **count,
            "runs_collapsed": sum(max(0, int(x.get("runs_in_period") or 1) - 1) for x in rows),
            "median_abs_pct": round(statistics.median(pcts), 2) if pcts else None,
            "mean_abs_pct": round(statistics.mean(pcts), 2) if pcts else None,
            "within_warning_pct": (round(100.0 * sum(1 for x in comparable
                                                     if x["outcome"] in ("match", "warning"))
                                         / len(comparable), 1) if comparable else None)}


def _period_rows(start, end, r, archive, *, client, job, preview, read_via_excel, compare,
                 made_by, progress) -> List[Dict[str, Any]]:
    runs = runs_between(start, end, r["aisheets"], client=client, job=job)
    rows = []
    for i, run in enumerate(runs, start=1):
        rows.append(_pair(run, r, archive, preview=preview, read_via_excel=read_via_excel,
                          compare=compare, made_by=made_by))
        progress(i, len(runs), rows)
    return rows


def run_period(start: str, end: str, *, preview: bool = False, read_via_excel: bool = False,
               client: str = "", job: str = "",
               compare: Optional[Callable[..., Dict[str, Any]]] = None,
               say: Callable[[str], None] = print,
               status_file: Optional[Path] = None) -> Dict[str, Any]:
    """Every drawing estimated in one period against its manual estimate, each filed."""
    r = roots()
    if not _moment(start) or not _moment(end, late=True):
        raise ParityJobError("A period needs a start and an end, as dates or dates with times.")
    folder = None
    if not preview:
        # _safe, because a boundary with a time carries ':' and Windows refuses it in a name.
        folder = _new_folder(r["parity"] / "_periods",
                             _safe(f"{start} to {end} (run {time.strftime('%Y-%m-%d %H-%M-%S')})"))
    base = {"kind": "period", "start": start, "end": end, "client": client, "job": job,
            "preview": preview, "folder": str(folder or "")}

    def progress(i, n, rows):
        say(f"  {i}/{n}  {rows[-1]['drawing']}: {rows[-1]['outcome']}")
        _status(status_file, {**base, "done": i, "of": n, "rows": rows})
        if folder:
            _status(folder / "status.json", {**base, "done": i, "of": n, "rows": rows})

    _status(status_file, {**base, "done": 0, "of": None, "rows": []})
    archive = _indexes(r["parity"]) if r["parity"].is_dir() else []
    rows = _period_rows(start, end, r, archive, client=client, job=job, preview=preview,
                        read_via_excel=read_via_excel, compare=compare,
                        made_by=f"period {start} to {end}", progress=progress)
    result = {**base, "rows": rows, "stats": stats(rows), "date_basis": DATE_BASIS,
              "compared": stats(rows)["compared"], "no_manual": stats(rows)["no manual"],
              "failed": stats(rows)["failed"]}
    if folder:
        _write_pages(folder, "period_summary", result, period_page)
        result["summary_html"] = str(folder / "period_summary.html")
        result["summary_portal_html"] = str(folder / "period_summary.portal.html")
    _status(status_file, {**result, "done": len(rows), "of": len(rows), "finished": True})
    if folder:
        _status(folder / "status.json", {**result, "done": len(rows), "of": len(rows), "finished": True})
    return result


DATE_BASIS = ("Each AI estimate is dated by its run folder. Each manual estimate's date is its "
              "file's modified date, labelled as such: the sheet holds no reliable estimate date.")


def compare_periods(a: tuple, b: tuple, *, client: str = "", job: str = "",
                    preview: bool = False, read_via_excel: bool = False,
                    compare: Optional[Callable[..., Dict[str, Any]]] = None,
                    say: Callable[[str], None] = print,
                    status_file: Optional[Path] = None) -> Dict[str, Any]:
    """Period A against Period B: the comparable pairs in each, how the variance moved, the
    drawings estimated in both, and everything that could not be compared, listed apart."""
    r = roots()
    for s, e in (a, b):
        if not _moment(s) or not _moment(e, late=True) or _moment(e, late=True) < _moment(s):
            raise ParityJobError("Each period needs a start and an end, as dates or dates with "
                                 "times, the end not before the start.")
    name = _safe(f"A {a[0]} to {a[1]} vs B {b[0]} to {b[1]} "
                 f"(run {time.strftime('%Y-%m-%d %H-%M-%S')})")
    folder = None if preview else _new_folder(r["parity"] / "_periods", name)
    base = {"kind": "two periods", "a": list(a), "b": list(b), "client": client, "job": job,
            "preview": preview, "folder": str(folder or "")}
    archive = _indexes(r["parity"]) if r["parity"].is_dir() else []
    sides: Dict[str, List[Dict[str, Any]]] = {}
    for label, (s, e) in (("A", a), ("B", b)):
        def progress(i, n, rows, label=label):
            say(f"  {label} {i}/{n}  {rows[-1]['drawing']}: {rows[-1]['outcome']}")
            _status(status_file, {**base, "period": label, "done": i, "of": n,
                                  "rows_a": sides.get("A", rows if label == "A" else []),
                                  "rows_b": rows if label == "B" else []})
        sides[label] = _period_rows(s, e, r, archive, client=client, job=job, preview=preview,
                                    read_via_excel=read_via_excel, compare=compare,
                                    made_by=f"period {s} to {e}", progress=progress)
    sa, sb = stats(sides["A"]), stats(sides["B"])
    by_a = {x["drawing"]: x for x in sides["A"] if x["outcome"] in COMPARABLE}
    both = []
    for x in sides["B"]:
        y = by_a.get(x["drawing"])
        if y and x["outcome"] in COMPARABLE:
            both.append({"drawing": x["drawing"], "client": x["client"],
                         "pct_a": y.get("pct"), "pct_b": x.get("pct"),
                         "change": (round(x["pct"] - y["pct"], 2)
                                    if isinstance(x.get("pct"), (int, float))
                                    and isinstance(y.get("pct"), (int, float)) else None)})

    def delta(k):
        return (round(sb[k] - sa[k], 2) if isinstance(sa.get(k), (int, float))
                and isinstance(sb.get(k), (int, float)) else None)
    result = {**base, "rows_a": sides["A"], "rows_b": sides["B"], "stats_a": sa, "stats_b": sb,
              "change": {"median_abs_pct": delta("median_abs_pct"),
                         "mean_abs_pct": delta("mean_abs_pct"),
                         "within_warning_pct": delta("within_warning_pct")},
              "in_both": both, "date_basis": DATE_BASIS}
    if folder:
        _write_pages(folder, "comparison", result, two_period_page)
        result["summary_html"] = str(folder / "comparison.html")
        result["summary_portal_html"] = str(folder / "comparison.portal.html")
    _status(status_file, {**result, "finished": True})
    if folder:
        _status(folder / "status.json", {**result, "finished": True})
    return result


def history(parity_root: Optional[Path] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Period comparisons already run, newest first."""
    root = Path(parity_root or roots()["parity"]) / "_periods"
    if not root.is_dir():
        return []
    out = []
    for name in ("period_summary.json", "comparison.json"):
        for path in root.glob(f"*/{name}"):
            body = _load(str(path))
            if not body:
                continue
            stem = Path(name).stem
            s = body.get("stats") or body.get("stats_b") or {}
            out.append({"kind": body.get("kind") or "period", "name": path.parent.name,
                        "folder": str(path.parent),
                        "start": body.get("start") or (body.get("a") or [None])[0],
                        "end": body.get("end") or (body.get("b") or [None, None])[-1],
                        "a": body.get("a"), "b": body.get("b"),
                        "compared": s.get("compared", body.get("compared")),
                        "no_manual": s.get("no manual", body.get("no_manual")),
                        "failed": s.get("failed", body.get("failed")),
                        "median_abs_pct": s.get("median_abs_pct"),
                        "within_warning_pct": s.get("within_warning_pct"),
                        "summary_html": str(path.parent / f"{stem}.html"),
                        "summary_portal_html": str(path.parent / f"{stem}.portal.html")})
    out.sort(key=lambda x: x["name"].rsplit("(run ", 1)[-1], reverse=True)
    return out[:limit]


# ── the control panel's parity view (D-741) ─────────────────────────────────────────────
# JG, 7 Nov 2026: "we should see the parity runs and all kpis/ vizualizations built into this".
#
# ONE READ OF THE FILED COMPARISONS, SUMMED FOR THE WALL. Every figure is a count of filed
# comparisons, or a percentage of the manual sheet's figure as the comparator states every one,
# and each says what it counts:
#   * WHERE PARITY STANDS is each drawing's newest comparison that could be made. A later one
#     that failed to compare does not hide it; a drawing that never compared counts as such.
#   * HOW IT HAS MOVED is every comparison, week by week, each drawing once a week.
#   * WHETHER RE-ESTIMATING CLOSED THE GAP is the drawings compared from more than one AI run:
#     the first run's variance against the latest run's. Comparing the same run again with a
#     newer comparator is not a new estimate and does not count as one.
#   * Quantities that differ, and comparisons that could not be made, are counted apart and
#     never as a match or a miss.

def signed_pct(index: Dict[str, Any]) -> Optional[float]:
    """AI against manual as a signed percentage of the manual unit cost, positive when the AI
    is dearer; at the manual's quantity when the run's quantity sweep priced it. None when
    either unit cost was not read."""
    h, q = index.get("headline") or {}, index.get("quantity") or {}
    manual = _num(h.get("manual_unit_cost_gbp"))
    ai = _num(q.get("ai_unit_at_manual_qty"))
    if ai is None:
        ai = _num(h.get("ai_unit_cost_gbp"))
    if ai is None or not manual:
        return None
    return round((ai - manual) / abs(manual) * 100.0, 2)


def _abs_pct(index: Dict[str, Any]) -> Optional[float]:
    """The comparator's own unit-cost variance, the figure its verdict was made on."""
    p = unit_pct(index)
    if p is None:
        s = signed_pct(index)
        return abs(s) if s is not None else None
    return abs(p)


def _drawing_key(index: Dict[str, Any]) -> tuple:
    return (str(index.get("client") or "").strip().lower(),
            str(index.get("drawing") or "").strip().lower())


def _median(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 2) if values else None


def _newest_per_drawing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each drawing's newest comparison, one that compared preferred over a later failure."""
    keep: Dict[tuple, Dict[str, Any]] = {}
    for idx in sorted(rows, key=lambda i: str(i.get("stamp", ""))):
        k = _drawing_key(idx)
        if idx.get("error") and k in keep and not keep[k].get("error"):
            continue
        keep[k] = idx
    return list(keep.values())


def _standing(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts and variances over comparisons already reduced to one per drawing."""
    comparable = [i for i in rows if i.get("outcome") in COMPARABLE]
    absolute = [p for p in (_abs_pct(i) for i in comparable) if p is not None]
    signed = [p for p in (signed_pct(i) for i in comparable) if p is not None]
    n = len(comparable)
    count = {k: sum(1 for i in rows if i.get("outcome") == k) for k in COMPARABLE}
    return {"drawings": len(rows), "compared": n, **count,
            "quantities_differ": sum(1 for i in rows if i.get("outcome") == "quantities differ"),
            "not_compared": sum(1 for i in rows if i.get("outcome") == "not compared"),
            "review": sum(1 for i in rows if i.get("outcome") == "review"),
            "within_match_pct": round(100.0 * count["match"] / n, 1) if n else None,
            "within_warning_pct": (round(100.0 * (count["match"] + count["warning"]) / n, 1)
                                   if n else None),
            "median_abs_pct": _median(absolute),
            "mean_abs_pct": round(statistics.mean(absolute), 2) if absolute else None,
            "median_signed_pct": _median(signed),
            "ai_dearer": sum(1 for p in signed if p > 0),
            "ai_cheaper": sum(1 for p in signed if p < 0)}


def _bins(comparable: List[Dict[str, Any]], match: float, warn: float) -> List[Dict[str, Any]]:
    """The signed variance of each drawing's standing comparison, in bands either side of
    level: the comparator's match and warning thresholds, and twice the warning one."""
    far = 2.0 * warn
    edges = [(None, -far, "fail"), (-far, -warn, "fail"), (-warn, -match, "warning"),
             (-match, match, "match"), (match, warn, "warning"), (warn, far, "fail"),
             (far, None, "fail")]

    def name(lo, hi):
        if lo is None:
            return f"AI under by more than {far:g}%"
        if hi is None:
            return f"AI over by more than {far:g}%"
        if lo < 0 < hi:
            return f"within ±{hi:g}%"
        return f"{lo:+g}% to {hi:+g}%"
    out = [{"label": name(lo, hi), "lo": lo, "hi": hi, "band": band, "count": 0, "drawings": []}
           for lo, hi, band in edges]
    for idx in comparable:
        p = signed_pct(idx)
        if p is None:
            continue
        # Each threshold belongs to the band inside it, as the comparator's verdict has it.
        a = abs(p)
        step = 0 if a <= match else 1 if a <= warn else 2 if a <= far else 3
        b = out[3 + step] if p >= 0 else out[3 - step]
        b["count"] += 1
        if len(b["drawings"]) < 8:
            b["drawings"].append(f"{idx.get('drawing')} {p:+.1f}%")
    return out


def _weekly(rows: List[Dict[str, Any]], today: date, weeks: int) -> List[Dict[str, Any]]:
    """Each of the last `weeks` weeks, Monday to Sunday: the comparisons filed in it, each
    drawing once (its newest that week)."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for back in range(weeks - 1, -1, -1):
        start = monday - timedelta(days=7 * back)
        end = start + timedelta(days=7)
        inside = [i for i in rows if i["_when"] and start <= i["_when"].date() < end]
        s = _standing(_newest_per_drawing(inside))
        out.append({"week": start.isoformat(), "label": f"{start.day} {start.strftime('%b')}",
                    "comparisons": len(inside), "drawings": s["drawings"],
                    "compared": s["compared"], "match": s["match"], "warning": s["warning"],
                    "fail": s["fail"], "not_comparable": s["drawings"] - s["compared"],
                    "median_abs_pct": s["median_abs_pct"],
                    "within_warning_pct": s["within_warning_pct"]})
    return out


def _line_pct(line: Dict[str, Any]) -> Optional[float]:
    a, m = _num(line.get("ai")), _num(line.get("manual"))
    if a is None or not m:
        return None
    return round((a - m) / abs(m) * 100.0, 2)


_COST_ORDER = ("Total material cost", "Total labour cost", "Rebate and overhead absorption",
               "Total unit cost", "Sell price")


def _cost_areas(standing: List[Dict[str, Any]], warn: float, limit: int = 10) -> Dict[str, Any]:
    """Each cost line and commercial category across the standing comparisons made line by
    line: how many read both sides, the median signed and absolute variance, and how many
    were outside the warning threshold. Fractions (rebate, margin, divisor) are left out:
    a percentage of a fraction is not a cost."""
    from_lines = [i for i in standing if i.get("outcome") in COMPARABLE
                  and i.get("lines_from") == "line by line"]
    areas: Dict[tuple, List[float]] = {}
    for idx in from_lines:
        for line in idx.get("lines") or []:
            if line.get("fraction") or line.get("kind") not in ("cost", "selling", "commercial"):
                continue
            p = _line_pct(line)
            if p is None:
                continue
            areas.setdefault((line["kind"], str(line.get("label") or "")), []).append(p)
    rows = []
    for (kind, label), pcts in areas.items():
        absolute = [abs(p) for p in pcts]
        rows.append({"kind": kind, "label": label, "count": len(pcts),
                     "median_signed_pct": _median(pcts), "median_abs_pct": _median(absolute),
                     "outside_warning": sum(1 for p in absolute if p > warn)})
    order = {name: n for n, name in enumerate(_COST_ORDER)}
    rows.sort(key=lambda r: (0, order[r["label"]]) if r["label"] in order
              else (1, -r["count"], r["label"]))
    return {"from_comparisons": len(from_lines), "areas": rows[:limit],
            "left_out": max(0, len(rows) - limit)}


def _movers(rows: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    """Drawings compared from more than one AI run: the first run's variance against the
    latest's. Each run counts once, by its newest comparison."""
    runs: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for idx in sorted(rows, key=lambda i: str(i.get("stamp", ""))):
        if idx.get("outcome") not in COMPARABLE or _abs_pct(idx) is None:
            continue
        ai = idx.get("ai") or {}
        run = str(ai.get("run_folder") or ai.get("run") or ai.get("source") or "")
        if run:
            runs.setdefault(_drawing_key(idx), {})[run] = idx
    out = []
    for by_run in runs.values():
        if len(by_run) < 2:
            continue
        ordered = sorted(by_run.values(), key=lambda i: str((i.get("ai") or {}).get("run")
                                                           or i.get("stamp", "")))
        first, last = ordered[0], ordered[-1]
        fa, la = _abs_pct(first), _abs_pct(last)
        out.append({"drawing": last.get("drawing"), "client": last.get("client"),
                    "runs": len(ordered), "first_stamp": first.get("stamp"),
                    "last_stamp": last.get("stamp"), "first_pct": signed_pct(first),
                    "last_pct": signed_pct(last), "first_abs_pct": fa, "last_abs_pct": la,
                    "first_outcome": first.get("outcome"), "last_outcome": last.get("outcome"),
                    "change_abs_pct": round(la - fa, 2)})
    out.sort(key=lambda r: str(r["last_stamp"]), reverse=True)
    return {"drawings": len(out),
            "closer": sum(1 for r in out if r["change_abs_pct"] < -0.5),
            "further": sum(1 for r in out if r["change_abs_pct"] > 0.5),
            "rows": out[:limit]}


def _recent_row(idx: Dict[str, Any]) -> Dict[str, Any]:
    h, q = idx.get("headline") or {}, idx.get("quantity") or {}
    return {"stamp": idx.get("stamp"), "job": idx.get("job"), "drawing": idx.get("drawing"),
            "client": idx.get("client"), "outcome": idx.get("outcome"),
            "abs_pct": _abs_pct(idx), "signed_pct": signed_pct(idx),
            "ai_unit": _num(q.get("ai_unit_at_manual_qty")) or _num(h.get("ai_unit_cost_gbp")),
            "manual_unit": _num(h.get("manual_unit_cost_gbp")),
            "quantity_note": q.get("note", "") if not q.get("comparable", True) else "",
            "made_by": idx.get("made_by"), "ai_run": (idx.get("ai") or {}).get("run"),
            "lines_from": idx.get("lines_from"), "error": str(idx.get("error") or "")[:200],
            "folder": idx.get("folder"), "report_html": idx.get("report_html"),
            "walkthrough_wav": idx.get("walkthrough_wav"),
            "walkthrough_txt": idx.get("walkthrough_txt")}


def wall_summary(parity_root: Optional[Path] = None, now: Optional[float] = None,
                 weeks: int = 12, recent: int = 12) -> Dict[str, Any]:
    """The parity view on the control panel: where parity stands, how it has moved, by client
    and by cost line, re-estimated drawings, the newest comparisons and the period runs."""
    root = Path(parity_root or roots()["parity"])
    at = datetime.fromtimestamp(now) if now else datetime.now()
    match, warn = _thresholds()
    base = {"schema": "sdi_parity_wall.v1", "root": str(root),
            "as_of": at.strftime("%Y-%m-%d %H:%M:%S"),
            "thresholds": {"match": match, "warning": warn}}
    if not root.is_dir():
        return {**base, "reachable": False,
                "note": f"The parity folder could not be read from this machine: {root}"}
    every = _indexes(root)
    for idx in every:
        idx["_when"] = _stamp_dt(str(idx.get("stamp", "")))
    standing = _newest_per_drawing(every)
    now_s = _standing(standing)
    comparable = [i for i in standing if i.get("outcome") in COMPARABLE]
    today = at.date()

    def window(lo_days: int, hi_days: int) -> Dict[str, Any]:
        lo, hi = today - timedelta(days=lo_days), today - timedelta(days=hi_days)
        inside = [i for i in every if i["_when"] and lo < i["_when"].date() <= hi]
        return {**_standing(_newest_per_drawing(inside)), "comparisons": len(inside)}
    last30, prior30 = window(30, 0), window(60, 30)
    monday = today - timedelta(days=today.weekday())
    movers = _movers(every, limit=8)
    clients: Dict[str, List[Dict[str, Any]]] = {}
    for idx in standing:
        clients.setdefault(str(idx.get("client") or "Unknown client"), []).append(idx)
    by_client = sorted(({"client": c, **_standing(rows)} for c, rows in clients.items()),
                       key=lambda r: (-r["drawings"], r["client"]))
    newest = sorted(every, key=lambda i: str(i.get("stamp", "")), reverse=True)
    out = {**base, "reachable": True,
           "kpis": {**now_s, "comparisons": len(every),
                    "this_week": sum(1 for i in every if i["_when"]
                                     and i["_when"].date() >= monday),
                    "last_30_days": last30, "prior_30_days": prior30,
                    "median_abs_change_30d": (round(last30["median_abs_pct"]
                                                    - prior30["median_abs_pct"], 2)
                                              if last30["median_abs_pct"] is not None
                                              and prior30["median_abs_pct"] is not None else None),
                    "re_estimated": movers["drawings"], "closer": movers["closer"],
                    "further": movers["further"],
                    "newest_stamp": newest[0].get("stamp") if newest else None},
           "distribution": _bins(comparable, match, warn),
           "trend": _weekly(every, today, weeks),
           "by_client": by_client[:8], "clients_left_out": max(0, len(by_client) - 8),
           "cost_areas": _cost_areas(standing, warn),
           "movers": movers,
           "recent": [_recent_row(i) for i in newest[:recent]],
           "periods": history(root, limit=6)}
    for idx in every:
        idx.pop("_when", None)
    return out


# ── pages ───────────────────────────────────────────────────────────────────────────────
# WRITTEN TWICE, BECAUSE THEY ARE OPENED FROM TWO PLACES. From the share, links are relative
# so the folder can be opened in Explorer or moved. Through the portal a page is served from
# /api/file in a sandbox, where a relative link resolves to nothing, so the .portal copy links
# each report through /api/file by its full path.

def _gbp(v: Any) -> str:
    try:
        return f"£{float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def _pct(v: Any) -> str:
    return f"{float(v):.1f}%" if isinstance(v, (int, float)) else ""


def _link(row: Dict[str, Any], here: Path, portal: bool, text: str = "report") -> str:
    if not row.get("folder") or not row.get("report"):
        return html.escape(str(row.get("note") or ""))[:240]
    target = Path(row["folder"]) / row["report"]
    href = ("/api/file?path=" + quote(str(target))) if portal \
        else os.path.relpath(target, here).replace(os.sep, "/")
    return f'<a href="{html.escape(href)}">{text}</a>'


_STYLE = """<style>body{font:14px/1.5 Segoe UI,Arial,sans-serif;margin:24px;color:#1a1e1c}
table{border-collapse:collapse;margin:8px 0 18px}td,th{padding:5px 10px;border-bottom:1px solid #d5dad7;text-align:left;vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums}h1{font-size:22px}h2{font-size:17px;margin-top:22px}
.note{color:#5b625e}</style>"""


def _rows_table(rows: List[Dict[str, Any]], here: Path, portal: bool, outcomes: Iterable[str]) -> str:
    keep = [x for x in rows if x["outcome"] in set(outcomes)]
    if not keep:
        return '<p class="note">None.</p>'
    body = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td class=n>{}</td><td class=n>{}</td><td class=n>{}</td>"
        "<td>{}</td><td>{}</td></tr>".format(
            html.escape(x["drawing"]), html.escape(x["client"]),
            html.escape(x["ai_run"]) + (f" ({x['runs_in_period']} runs, newest used)"
                                        if x.get("runs_in_period", 1) > 1 else ""),
            _gbp(x.get("ai_unit")), _gbp(x.get("manual_unit")), _pct(x.get("pct")),
            html.escape(str(x.get("outcome"))), _link(x, here, portal)
            + (f'<br><span class="note">{html.escape(x["quantity_note"])}</span>' if x.get("quantity_note") else ""))
        for x in keep)
    return ("<table><tr><th>Drawing</th><th>Client</th><th>AI run</th><th>AI unit</th>"
            "<th>Manual unit</th><th>Variance</th><th>Outcome</th><th>Evidence</th></tr>"
            + body + "</table>")


def _stats_line(s: Dict[str, Any]) -> str:
    return (f"{s['compared']} comparable ({s['match']} match, {s['warning']} warning, "
            f"{s['fail']} fail); median variance {_pct(s['median_abs_pct']) or 'n/a'}, "
            f"mean {_pct(s['mean_abs_pct']) or 'n/a'}, within warning "
            f"{_pct(s['within_warning_pct']) or 'n/a'}. Apart: {s['quantities differ']} with "
            f"quantities that differ, {s['ambiguous']} ambiguous, {s['no manual']} with no manual "
            f"estimate, {s['failed']} that failed. {s['runs_collapsed']} repeat run(s) collapsed.")


def period_page(result: Dict[str, Any], here: Path, portal: bool) -> str:
    rows = result["rows"]
    s = result["stats"]
    return (f"<!doctype html><meta charset=utf-8><title>Parity {html.escape(result['start'])} to "
            f"{html.escape(result['end'])}</title>{_STYLE}"
            f"<h1>AI against manual estimates, {html.escape(result['start'])} to {html.escape(result['end'])}</h1>"
            f"<p>{html.escape(_stats_line(s))}</p><p class=note>{html.escape(result['date_basis'])} "
            f"Internal costing only.</p>"
            f"<h2>Comparable</h2>{_rows_table(rows, here, portal, COMPARABLE)}"
            f"<h2>Quantities differ</h2>{_rows_table(rows, here, portal, ['quantities differ'])}"
            f"<h2>Ambiguous: choose the manual sheet</h2>{_rows_table(rows, here, portal, ['ambiguous'])}"
            f"<h2>No manual estimate found</h2>{_rows_table(rows, here, portal, ['no manual'])}"
            f"<h2>Could not be compared</h2>{_rows_table(rows, here, portal, ['failed', 'not compared'])}")


def two_period_page(result: Dict[str, Any], here: Path, portal: bool) -> str:
    a, b, sa, sb, ch = result["a"], result["b"], result["stats_a"], result["stats_b"], result["change"]
    def pts(v):
        return "" if v is None else f"{v:+.1f} pts"
    both = "".join(f"<tr><td>{html.escape(x['drawing'])}</td><td>{html.escape(x['client'])}</td>"
                   f"<td class=n>{_pct(x['pct_a'])}</td><td class=n>{_pct(x['pct_b'])}</td>"
                   f"<td class=n>{pts(x['change'])}</td></tr>"
                   for x in result["in_both"]) or '<tr><td colspan=5 class=note>None estimated in both periods.</td></tr>'

    def moved(k):
        v = ch.get(k)
        return "n/a" if v is None else f"{v:+.1f} pts"
    parts = [f"<!doctype html><meta charset=utf-8><title>Parity A against B</title>{_STYLE}",
             f"<h1>Period A {html.escape(a[0])} to {html.escape(a[1])} against Period B "
             f"{html.escape(b[0])} to {html.escape(b[1])}</h1>",
             f"<p class=note>{html.escape(result['date_basis'])}"
             + (f" Client: {html.escape(result['client'])}." if result.get("client") else "")
             + (f" Job: {html.escape(result['job'])}." if result.get("job") else "")
             + " Internal costing only.</p>",
             "<table><tr><th></th><th>Period A</th><th>Period B</th><th>Change</th></tr>"
             f"<tr><td>Comparable pairs</td><td class=n>{sa['compared']}</td><td class=n>{sb['compared']}</td><td></td></tr>"
             f"<tr><td>Median variance</td><td class=n>{_pct(sa['median_abs_pct'])}</td><td class=n>{_pct(sb['median_abs_pct'])}</td><td class=n>{moved('median_abs_pct')}</td></tr>"
             f"<tr><td>Mean variance</td><td class=n>{_pct(sa['mean_abs_pct'])}</td><td class=n>{_pct(sb['mean_abs_pct'])}</td><td class=n>{moved('mean_abs_pct')}</td></tr>"
             f"<tr><td>Within warning</td><td class=n>{_pct(sa['within_warning_pct'])}</td><td class=n>{_pct(sb['within_warning_pct'])}</td><td class=n>{moved('within_warning_pct')}</td></tr>"
             f"<tr><td>Quantities differ</td><td class=n>{sa['quantities differ']}</td><td class=n>{sb['quantities differ']}</td><td></td></tr>"
             f"<tr><td>Ambiguous</td><td class=n>{sa['ambiguous']}</td><td class=n>{sb['ambiguous']}</td><td></td></tr>"
             f"<tr><td>No manual estimate</td><td class=n>{sa['no manual']}</td><td class=n>{sb['no manual']}</td><td></td></tr>"
             f"<tr><td>Failed</td><td class=n>{sa['failed']}</td><td class=n>{sb['failed']}</td><td></td></tr>"
             f"<tr><td>Repeat runs collapsed</td><td class=n>{sa['runs_collapsed']}</td><td class=n>{sb['runs_collapsed']}</td><td></td></tr>"
             "</table>",
             "<h2>Drawings estimated in both periods</h2><table><tr><th>Drawing</th><th>Client</th>"
             f"<th>Variance A</th><th>Variance B</th><th>Change</th></tr>{both}</table>"]
    for label, rows in (("A", result["rows_a"]), ("B", result["rows_b"])):
        parts.append(f"<h2>Period {label}: comparable</h2>{_rows_table(rows, here, portal, COMPARABLE)}")
        parts.append(f"<h2>Period {label}: apart from the figures</h2>"
                     f"{_rows_table(rows, here, portal, ['quantities differ', 'ambiguous', 'no manual', 'failed', 'not compared'])}")
    return "".join(parts)


def _write_pages(folder: Path, stem: str, result: Dict[str, Any], page) -> None:
    (folder / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (folder / f"{stem}.html").write_text(page(result, folder, False), encoding="utf-8")
    (folder / f"{stem}.portal.html").write_text(page(result, folder, True), encoding="utf-8")


# ── command line ────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parity by job number (D-619, D-621).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find"); f.add_argument("job"); f.add_argument("--client", default="")
    j = sub.add_parser("job"); j.add_argument("job"); j.add_argument("--client", default="")
    j.add_argument("--manual"); j.add_argument("--ai")
    j.add_argument("--read-via-excel", action="store_true")
    j.add_argument("--made-by", default="", help="what asked for it, for the manifest")
    j.add_argument("--id", default="", help="the comparison id, when the service chose it")
    s = sub.add_parser("search"); s.add_argument("text", nargs="?", default="")
    s.add_argument("--from", dest="start"); s.add_argument("--to", dest="end")
    s.add_argument("--outcome", default="")
    p = sub.add_parser("period", help="one period: dates, or dates with times (D-625), "
                                      "e.g. --from \"2026-10-31 09:00\" --to \"2026-10-31 12:00\"")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True); p.add_argument("--preview", action="store_true")
    p.add_argument("--client", default=""); p.add_argument("--job", default="")
    p.add_argument("--read-via-excel", action="store_true")
    q = sub.add_parser("periods")
    for k in ("a-from", "a-to", "b-from", "b-to"):
        q.add_argument(f"--{k}", required=True)
    q.add_argument("--client", default=""); q.add_argument("--job", default="")
    q.add_argument("--preview", action="store_true"); q.add_argument("--read-via-excel", action="store_true")
    hst = sub.add_parser("history")
    w = sub.add_parser("wall", help="the control panel's parity view (D-741)")
    w.add_argument("--weeks", type=int, default=12); w.add_argument("--recent", type=int, default=12)
    for x in (f, j, s, p, q, hst, w):
        x.add_argument("--json", action="store_true", help="one JSON line, for the service")
        x.add_argument("--status-file", help="progress for the service, which runs this in the background")
    a = ap.parse_args(argv)
    status = Path(a.status_file) if getattr(a, "status_file", None) else None
    try:
        import config  # noqa: F401  — loads .env, so the roots set there apply
    except Exception:                                                # noqa: BLE001
        pass
    quiet = (lambda m: None) if a.json else print
    try:
        if a.cmd == "find":
            ai_runs = find_ai(a.job)
            client = a.client or (ai_runs[0]["client"] if ai_runs else "")
            manual = find_manual(a.job, client=client)
            d = decide(manual, a.job, client)
            out = {"job": a.job, "client": client, "manual": manual, "ai": ai_runs,
                   "decision": {"clear": d["clear"], "reason": d["reason"],
                                "path": (d["pick"] or {}).get("path")}}
            if not a.json:
                print(f"Manual estimates for {job_digits(a.job)} ({client or 'client unknown'}), likeliest first:")
                for c in manual:
                    print(f"  {c['path']}  ({c['why']}, {c['modified_text']})")
                print(("Clear: " if d["clear"] else "Choose by hand: ") + d["reason"])
                print("AI estimates, newest first:")
                for run in ai_runs:
                    print(f"  {run['workbook']}")
        elif a.cmd == "job":
            def step(m):
                quiet(m)
                _status(status, {"state": "running", "step": m, "job": a.job})
            _status(status, {"state": "running", "step": "Starting…", "job": a.job})
            out = run_job(a.job, a.manual, a.ai, client=a.client, read_via_excel=a.read_via_excel,
                          made_by=a.made_by, comparison_id=a.id, say=step)
            _status(status, {"state": "done", "finished": True, "result": out})
            if not a.json:
                h = out["headline"]
                print(f"Filed to {out['folder']}\n  manual {out['manual']['source']}\n"
                      f"  AI     {out['ai']['source']}\n  outcome {out['outcome']}: AI "
                      f"{_gbp(h.get('ai_unit_cost_gbp')) or 'not read'} against manual "
                      f"{_gbp(h.get('manual_unit_cost_gbp')) or 'not read'}; "
                      f"{(out.get('quantity') or {}).get('note', '')}")
        elif a.cmd == "search":
            out = {"reports": search(a.text, a.start, a.end, outcome=a.outcome)}
            if not a.json:
                for i in out["reports"]:
                    print(f"  {i['stamp']}  {i['drawing']}  {i['client']}  {i['outcome']}  {i['folder']}")
        elif a.cmd == "history":
            out = {"periods": history()}
            if not a.json:
                for x in out["periods"]:
                    print(f"  {x['name']}: {x['compared']} comparable  {x['summary_html']}")
        elif a.cmd == "wall":
            out = wall_summary(weeks=max(1, min(a.weeks, 52)), recent=max(1, min(a.recent, 50)))
            if not a.json:
                k = out.get("kpis") or {}
                print(out.get("note") or (
                    f"{k.get('drawings')} drawings, {k.get('compared')} comparable, "
                    f"{k.get('within_warning_pct')}% within the warning threshold, median "
                    f"variance {k.get('median_abs_pct')}%"))
        elif a.cmd == "periods":
            out = compare_periods((getattr(a, "a_from"), getattr(a, "a_to")),
                                  (getattr(a, "b_from"), getattr(a, "b_to")),
                                  client=a.client, job=a.job, preview=a.preview,
                                  read_via_excel=a.read_via_excel, say=quiet, status_file=status)
            if not a.json:
                print(f"A: {_stats_line(out['stats_a'])}\nB: {_stats_line(out['stats_b'])}"
                      + (f"\nFiled in {out['folder']}" if out.get("folder") else "\nPreview only"))
        else:
            out = run_period(a.start, a.end, preview=a.preview, read_via_excel=a.read_via_excel,
                             client=a.client, job=a.job, say=quiet, status_file=status)
            if not a.json:
                print(_stats_line(out["stats"]) + (f"\nFiled in {out['folder']}"
                                                   if out.get("folder") else "\nPreview only"))
    except ParityChoiceNeeded as exc:
        body = {"error": str(exc), "choose": True, "candidates": exc.candidates}
        _status(status, {"state": "choose", "finished": True, **body})
        print(json.dumps(body, default=str) if a.json else str(exc), file=sys.stdout if a.json else sys.stderr)
        return 3
    except ParityJobError as exc:
        _status(status, {"state": "failed", "finished": True, "error": str(exc)})
        if a.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:                                         # noqa: BLE001
        # In the background the page reads the status file, so it must say the run ended, and
        # why, rather than show "running" for ever.
        _status(status, {"state": "failed", "finished": True,
                         "error": f"{type(exc).__name__}: {exc}"})
        raise
    if a.json:
        print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
