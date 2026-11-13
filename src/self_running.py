#!/usr/bin/env python3
"""
AI Estimate Self-Running (D-588): the watcher behind the portal's button.

    python src\\self_running.py                  watch: obey the portal's switch, for good
    python src\\self_running.py --once           one cycle, if the portal says on
    python src\\self_running.py --dry-run        say what it would collect and run; does neither
    python src\\self_running.py --log output\\live_enquiry\\self_running.log

THE BUTTON IS A SWITCH, AND THE WORK HAPPENS HERE. The estimating page's "AI Estimate
Self-Running" button switches self-running on or off in the portal. This watcher runs on the
estimating machine — the one with the share rights, in the logged-on user's session, beside
the runner that does the estimates — and asks the portal on every beat whether it is on. It
never queues a job unless the portal has just said yes, so a portal that cannot be reached,
or a switch nobody has pressed, means nothing runs.

ONE CYCLE, WHILE THE SWITCH IS ON:
  1. Read the Live Enquiry workbook, exactly as the Live Enquiry runner reads it (one reader:
     live_enquiry_runner.read_sheet, plan, decide). Every row says what it would do and why.
  2. The drawings are found where the estimators put them (D-608): under the Live Enquiry root
     (K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry), in the folder named by the row's
     Customer and below it the folder whose name carries the row's Drawing No. A row whose
     folder is not there yet waits and is looked for again on the next read. The endpoint that
     will extract drawings replaces this when it is ready. Copying from the Production share
     (the earlier provisional search) runs only with SDI_LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION=1:
     the collector's own search finds the row's drawings and copies them into
     <Live Enquiry root>\\<customer>\\<drawing>, and a row not found there is searched again
     after LIVE_ENQUIRY_COLLECT_RETRY_HOURS.
  3. Run every ready row one after another through the portal — the same POST /api/estimate a
     person makes from the page (live_enquiry_runner.run_ready). Before each row the switch is
     asked again: switched off, the job in progress finishes and nothing more is queued.
  4. Report what it read, collected and ran, then read the sheet again after
     LIVE_ENQUIRY_POLL_MINUTES — or at once, when the button is pressed again.

NOTHING HERE PRICES ANYTHING. The workbook is read, and written in one place only (D-608a):
when a row's run finishes, its AICompleted cell is set to YES so it is not run again until a
person resets it. That write waits while the workbook is open in Excel and is tried again on
each read. What ran is in the runner's ledger; this watcher shares the runner's lock, so it and
`live_enquiry_runner.py watch` can never both drive one sheet.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import live_enquiry_runner as ler  # noqa: E402

IDLE_BEAT_SECONDS = 60          # how often an idle watcher asks the portal whether it is on
# HOW OFTEN A RUNNING JOB IS CHECKED (D-649). Was the Live Enquiry runner's 30s: a job
# stopped from the page went on showing "running" on the card for up to half a minute
# before the watcher even asked, then until the sheet had been read again. Each check is
# one status call to this machine's portal and one beat to each service.
JOB_POLL_SECONDS = 10
# THE WINDOW THE CARD SHOWS (D-626). JG, 2 Nov 2026: the price of each quantity ran, "only
# show the number ran for the past week and a max of 100, or we'll run out of space". The
# prices per quantity are D-610's and travel on each attempt; this is the window.
RECENT_RUNS_SHOWN = 100
RECENT_RUNS_DAYS = 7


# ── WHAT THE PAGE IS TOLD ────────────────────────────────────────────────────────────
def counts(decisions: Sequence[ler.Decision]) -> Dict[str, int]:
    return dict(Counter(d.status for d in decisions))


def recent_runs(ledger: Dict[str, Any], limit: int = RECENT_RUNS_SHOWN,
                days: int = RECENT_RUNS_DAYS,
                now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The attempts of the past week, newest first, at most `limit`, as the page lists them.

    An attempt still running is kept whatever its age, so a long job never vanishes from the
    card mid-run; a finished one older than the window drops off."""
    edge = (now or datetime.now()) - timedelta(days=days)
    out = []
    for job in (ledger.get("jobs") or {}).values():
        for a in job.get("attempts") or []:
            when = str(a.get("finished_at") or a.get("queued_at") or "")
            if a.get("status") not in ("queued", "running"):
                try:
                    if datetime.fromisoformat(when[:19]) < edge:
                        continue
                except ValueError:
                    pass                                 # an unreadable date is kept, not hidden
            out.append({"customer": job.get("customer"), "drawing": job.get("drawing"),
                        "status": a.get("status"), "queued_at": a.get("queued_at"),
                        "finished_at": a.get("finished_at"),
                        "unit_gbp": a.get("engine_price_gbp"),
                        "quantities": a.get("quantities"),
                        "quantity_prices": a.get("quantity_prices") or [],
                        "walkthrough_url": a.get("walkthrough_url") or "",
                        # SO THE PAGE CAN STOP ANY ONE OF THEM (JG, 10 Nov 2026), on the
                        # service it was queued on.
                        "run_id": a.get("run_id") or "", "server": a.get("server") or "",
                        "output": a.get("output_path") or "", "error": a.get("error") or ""})
    out.sort(key=lambda r: str(r.get("queued_at") or ""), reverse=True)
    return out[:limit]


def recent_from_ledger(ledger_path: Any) -> List[Dict[str, Any]]:
    """The Latest runs list straight from the ledger on disk, for a beat that ran no cycle.

    THE LIST, AND ITS RE-RUN BUTTONS, SURVIVE A RESTART AND THE SWITCH BEING OFF (JG, 12 Nov
    2026: "where have all the re-run buttons gone on the portal now?"). The list was sent only
    after a read of the sheet, and the service keeps it in memory: each publish restarted the
    service, and with Self-Running switched off no read followed, so the card showed no runs
    and no buttons. The ledger holds them; every beat carries them. Never stops a beat."""
    try:
        return recent_runs(ler.load_ledger(Path(str(ledger_path))))
    except Exception:                                                # noqa: BLE001
        return []


def report(phase: str, message: str = "", **extra: Any) -> Dict[str, Any]:
    return {"host": socket.gethostname(), "pid": os.getpid(), "phase": phase,
            "message": message, "at": ler._now(), **extra}


class Switch:
    """The portal's answer, asked on every beat. Unreachable is OFF: a watcher that cannot
    hear the portal queues nothing.

    EVERY SERVICE ON THE LIST, NOT ONE (D-644). The laptop serves 8072 and 8071, and the
    phone reaches one the watcher was not reporting to: the switch was pressed on a service
    that never heard from the watcher, and said "not connected". Each service keeps its own
    switch, so the beat goes to all of them (each then shows the watcher and its job), and
    the switch pressed MOST RECENTLY on any of them is obeyed — Off pressed anywhere still
    stops it. A service that cannot be reached is left out; none reachable is off."""

    def __init__(self, portal: Any, say: Callable[[str], None] = print):
        self.portals = list(portal) if isinstance(portal, (list, tuple)) else [portal]
        self.portal = self.portals[0]
        self.say = say
        self.last: Dict[str, Any] = {}
        self._quiet: set = set()
        self.reruns: List[Dict[str, Any]] = []          # Re-run pressed on a page, not yet taken

    def beat(self, rep: Dict[str, Any]) -> bool:
        heard: List[Any] = []
        for i, portal in enumerate(self.portals):
            try:
                heard.append((portal, portal.self_running(rep) or {}))
                self._quiet.discard(i)
            except ler.PortalError as exc:
                if i not in self._quiet:                  # said once, not every beat
                    self._quiet.add(i)
                    self.say(f"   (the portal at {getattr(portal, 'server', '') or i} did not "
                             f"answer the self-running beat: {exc.message}; left out)")
        answers = [a for _, a in heard]
        if not answers:
            self.last = {}
            return False
        for a in answers:
            self.reruns += [r for r in (a.get("rerun") or []) if isinstance(r, dict)]
        newest = max(answers, key=lambda a: float(a.get("toggled_epoch") or 0.0))
        on = bool(newest.get("enabled"))
        self.last = {**newest, "enabled": on,
                     "run_now": on and any(a.get("run_now") and a.get("enabled")
                                           for a in answers)}
        self._pass_on(rep, heard, newest)
        return on

    def take_reruns(self) -> List[Dict[str, Any]]:
        got, self.reruns = self.reruns, []
        return got

    def _pass_on(self, rep: Dict[str, Any], heard: List[Any], newest: Dict[str, Any]) -> None:
        """ONE SWITCH ON EVERY SCREEN (D-650). A service whose own press is older than the one
        obeyed is told it at once, and takes it, so its page stops saying "Switched off" while
        the watcher runs jobs on an On pressed elsewhere. Only a service that answers with a
        toggled_epoch can take it; an older one is left as it is, and not asked every beat."""
        epoch = float(newest.get("toggled_epoch") or 0.0)
        if epoch <= 0:
            return
        obeyed = {k: newest.get(k) for k in ("enabled", "toggled_epoch", "switched_by",
                                              "switched_on_at", "switched_off_at")}
        for portal, answer in heard:
            if "toggled_epoch" not in answer or float(answer.get("toggled_epoch") or 0.0) >= epoch:
                continue
            try:
                portal.self_running({**rep, "obeyed": obeyed})
            except ler.PortalError:
                pass                                      # told again on the next beat


# ── COLLECTING A PACK THAT IS NOT ON THE SHARE YET ───────────────────────────────────
def _collector():
    import live_enquiry_collector as lec
    return lec


def _due_for_collection(ledger: Dict[str, Any], key: str, now: datetime) -> bool:
    last = (ledger.get("collected") or {}).get(key) or {}
    if not last or last.get("status") == "copied":
        return True
    try:
        at = datetime.fromisoformat(str(last.get("at")))
    except ValueError:
        return True
    return now - at >= timedelta(hours=config.LIVE_ENQUIRY_COLLECT_RETRY_HOURS)


def destination(root: Path, d: ler.Decision) -> Path:
    """<root>\\<customer>\\<drawing> — the layout the runner reads. The customer's existing
    folder where the share already has one; otherwise the sheet's spelling."""
    client = (d.located.client_folder_name if d.located else "") or d.row.customer
    return Path(root) / _segment(client) / _segment(d.row.drawing)


def _segment(text: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(text or "")).strip(" .") or "UNNAMED"


def collect_missing_packs(decisions: Sequence[ler.Decision], root: Path,
                          ledger: Dict[str, Any], dry_run: bool = False,
                          say: Callable[[str], None] = print,
                          now: Optional[datetime] = None,
                          collector: Any = None) -> List[Dict[str, Any]]:
    """Copy the drawings for every row waiting on its pack from the Production share, with
    the collector's own search. Returns one result per row searched; the ledger keeps each
    under "collected" so a row not found is not searched again every cycle."""
    lec = collector or _collector()
    settings = lec.load_settings(dry_run=dry_run)
    now = now or datetime.now()
    book = ledger.setdefault("collected", {})
    results: List[Dict[str, Any]] = []
    for d in decisions:
        if d.status != "waiting":
            continue
        key = ler.job_key(d.row)
        if not _due_for_collection(ledger, key, now):
            continue
        res: Dict[str, Any] = {"at": now.isoformat(timespec="seconds"),
                               "customer": d.row.customer, "drawing": d.row.drawing}
        try:
            if not Path(settings.production_root).is_dir():
                res.update(status="not_found",
                           note=f"the Production share {settings.production_root} cannot be "
                                f"read from this machine")
            else:
                cust = lec.resolve_customer_folder(settings.production_root, d.row.customer,
                                                   settings.customer_aliases)
                if cust is None:
                    res.update(status="not_found",
                               note=f"no '{d.row.customer}' folder under "
                                    f"{settings.production_root}")
                else:
                    tokens = lec.parse_drawing_tokens(d.row.drawing) or [d.row.drawing.upper()]
                    found, missing = lec.search_drawings(cust, tokens,
                                                         settings.search_max_depth)
                    if not found:
                        res.update(status="not_found", source=str(cust),
                                   note=f"no drawing for {', '.join(tokens)} under {cust}")
                    else:
                        dest = destination(root, d)
                        copied = lec.copy_pack(found, dest, settings.copy_dxf_subfolder,
                                               dry_run)
                        res.update(status="copied", source=str(cust), dest=str(dest),
                                   copied=copied, missing=missing)
        except Exception as exc:                                      # noqa: BLE001
            res.update(status="error", note=f"{type(exc).__name__}: {exc}")
        if not dry_run:
            book[key] = res
        say(f"   collect {d.row.drawing} ({d.row.customer}): {res['status']}"
            + (f" — {len(res.get('copied') or [])} file(s) into {res.get('dest')}"
               if res["status"] == "copied" else f" — {res.get('note', '')}"))
        results.append(res)
    return results


# ── THE DRAWING EXTRACT (D-702, SCRUM-185) ───────────────────────────────────────────
# A row with no pack waited for a person to copy its drawings into the Live Enquiry folder.
# The portal already asks the Document Manager for a pack from its Extract button; this asks
# the same route the same way, for each waiting row, and stages what comes back where the
# runner looks. Nothing here runs unless config.LIVE_ENQUIRY_EXTRACT_FROM_DM is on.
#
# THE RULES IT KEEPS:
#   * The request is the page's: project = the drawing number's first part, customer = the
#     row's customer, assembly folder = the drawing number.
#   * One heavy extract at a time on the Document Manager host: while any row's extract is in
#     flight, no other row is asked; they wait for a later cycle.
#   * An extract is polled across cycles, never waited on in one held request.
#   * A failed, empty or unreadable extract leaves the row waiting with the reason, and is
#     asked again after LIVE_ENQUIRY_COLLECT_RETRY_HOURS. Nothing runs on a partial pack: the
#     files are copied into a side folder and moved into place only when every file landed.
_EXTRACT_IN_FLIGHT = {"queued", "running"}


def extract_request(d: ler.Decision) -> Dict[str, str]:
    """The extract the page's button would send for this row."""
    drawing = str(d.row.drawing or "").strip()
    return {"project_number": (drawing.split("-")[0] or "").strip(),
            "customer": str(d.row.customer or "").strip(),
            "assembly_folder": drawing}


def _due_for_extract(entry: Dict[str, Any], now: datetime) -> bool:
    if not entry or entry.get("status") in _EXTRACT_IN_FLIGHT:
        return True
    if entry.get("status") == "copied":
        return False
    try:
        at = datetime.fromisoformat(str(entry.get("at")))
    except ValueError:
        return True
    return now - at >= timedelta(hours=config.LIVE_ENQUIRY_COLLECT_RETRY_HOURS)


def _stage_pack(out_dir: Path, dest: Path) -> List[str]:
    """Copy every file the extract wrote into dest, all or nothing. Returns the files."""
    import shutil
    files = [f for f in sorted(Path(out_dir).rglob("*")) if f.is_file()]
    if not files:
        return []
    side = dest.parent / f"{dest.name}.extract-partial"
    if side.exists():
        shutil.rmtree(side)
    try:
        for f in files:
            target = side / f.relative_to(out_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        if dest.exists():
            raise FileExistsError(f"{dest} appeared while the pack was being copied")
        side.rename(dest)
    except Exception:
        shutil.rmtree(side, ignore_errors=True)
        raise
    return [str(dest / f.relative_to(out_dir)) for f in files]


def extract_missing_packs(decisions: Sequence[ler.Decision], root: Path,
                          ledger: Dict[str, Any], portal: Any, dry_run: bool = False,
                          say: Callable[[str], None] = print,
                          now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Ask for, follow and stage the drawing extract of every row waiting on its pack.
    Returns one result per row acted on; the ledger keeps each under "extracted"."""
    now = now or datetime.now()
    book = ledger.setdefault("extracted", {})
    results: List[Dict[str, Any]] = []
    asked_now: List[str] = []

    def _host_busy(but: str) -> bool:
        return bool(asked_now) or any(
            str(v.get("status")) in _EXTRACT_IN_FLIGHT for k, v in book.items()
            if k != but and isinstance(v, dict))

    for d in decisions:
        if d.status != "waiting":
            continue
        key = ler.job_key(d.row)
        entry = book.get(key) if isinstance(book.get(key), dict) else {}
        if not _due_for_extract(entry, now):
            continue
        res: Dict[str, Any] = {"at": now.isoformat(timespec="seconds"),
                               "customer": d.row.customer, "drawing": d.row.drawing}
        try:
            if entry.get("status") in _EXTRACT_IN_FLIGHT and entry.get("job_id"):
                res["job_id"] = entry["job_id"]
                res["requested"] = entry.get("requested")
                info = portal.dm_extract_status(str(entry["job_id"])) or {}
                if not info.get("finished"):
                    res.update(status="running", progress=info.get("progress"))
                elif not info.get("ok"):
                    res.update(status="failed",
                               note=str(info.get("error") or "the extract failed"))
                elif not info.get("readable_here") or not info.get("output_dir"):
                    res.update(status="unreadable",
                               note=str(info.get("note") or "the pack is not readable here"))
                else:
                    dest = destination(root, d)
                    if dry_run:
                        res.update(status="would_copy", dest=str(dest))
                    elif dest.exists():
                        res.update(status="copied", dest=str(dest), copied=[],
                                   note="the folder was already there; nothing copied over it")
                    else:
                        copied = _stage_pack(Path(str(info["output_dir"])), dest)
                        if copied:
                            res.update(status="copied", dest=str(dest), copied=copied,
                                       file_count=info.get("file_count"),
                                       source=str(info["output_dir"]))
                        else:
                            res.update(status="empty", note="the extract wrote no files")
            elif _host_busy(key):
                continue                  # one heavy extract at a time on the host
            else:
                body = extract_request(d)
                res["requested"] = body
                if not body["project_number"]:
                    res.update(status="not_asked", note="the row has no drawing number")
                elif dry_run:
                    res.update(status="would_ask")
                else:
                    started = portal.dm_extract(body) or {}
                    if started.get("job_id"):
                        res.update(status="queued", job_id=str(started["job_id"]))
                        asked_now.append(key)
                    else:
                        res.update(status="failed", note="the portal returned no job id")
        except ler.PortalError as exc:
            res.update(status="error", note=str(exc))
        except Exception as exc:                                      # noqa: BLE001
            res.update(status="error", note=f"{type(exc).__name__}: {exc}")
        if not dry_run:
            book[key] = res
        say(f"   extract {d.row.drawing} ({d.row.customer}): {res['status']}"
            + (f" - {len(res.get('copied') or [])} file(s) into {res.get('dest')}"
               if res["status"] == "copied" else
               f" - {res['note']}" if res.get("note") else ""))
        results.append(res)
    return results


# ── AICompleted, WRITTEN BACK ────────────────────────────────────────────────────────
def write_back(workbook: Path, row: ler.EnquiryRow, attempt: Dict[str, Any],
               say: Callable[[str], None] = print) -> bool:
    """Set the row's AICompleted to YES for a finished attempt (D-608a), and record on the
    attempt whether it reached the sheet. The ledger's own "done" stops a repeat meanwhile."""
    ok, note = ler.mark_completed(workbook, row)
    if ok:
        attempt["sheet_marked"] = ler._now()
        attempt.pop("sheet_mark_note", None)
    else:
        attempt["sheet_mark_note"] = note
    say(f"   {row.drawing}: {note}")
    return ok


def write_back_pending(workbook: Path, ledger: Dict[str, Any],
                       say: Callable[[str], None] = print) -> int:
    """Every finished run on the AI Live Enquiry sheet whose YES has not reached the sheet yet:
    the workbook was open, or the run finished while nobody waited on it. Returns how many
    were written."""
    written = 0
    for job in (ledger.get("jobs") or {}).values():
        attempts = job.get("attempts") or []
        last = attempts[-1] if attempts else {}
        if (last.get("marks_sheet") and last.get("status") == "done"
                and not last.get("sheet_marked")):
            row = ler.EnquiryRow(row=int(last.get("row") or 0),
                                 customer=str(job.get("customer") or ""),
                                 drawing=str(job.get("drawing") or ""))
            written += write_back(workbook, row, last, say)
    return written


# ── ONE CYCLE ────────────────────────────────────────────────────────────────────────
def apply_reruns(ledger: Dict[str, Any], asked: List[Dict[str, Any]],
                 say: Callable[[str], None] = print) -> List[str]:
    """Re-run pressed on a page: the job's row is run again on this read, whatever its last
    run's ending (failed, refused, stopped by hand), as typing `retry` does."""
    done = []
    for r in asked:
        want = str(r.get("drawing") or "").strip().upper()
        cust = str(r.get("customer") or "").strip().upper()
        for job in (ledger.get("jobs") or {}).values():
            if str(job.get("drawing") or "").strip().upper() != want:
                continue
            if cust and str(job.get("customer") or "").strip().upper() != cust:
                continue
            job["retry"] = True
            # ONCE, OUTRANKING AI CHECK AND AICompleted (JG, 11 Nov 2026): taken by the next
            # read that finds the row on the sheet, cleared when queued (or when the row has gone).
            job["page_rerun"] = r.get("at") or time.time()
            job.pop("page_rerun_refused", None)
            done.append(want)
            say(f"   {job.get('drawing')} ({job.get('customer')}): Re-run asked for on the page"
                + (f" by {r.get('by')}" if r.get("by") else ""))
    return done


def cycle(s: Dict[str, Any], portal: ler.Portal, switch: Switch, dry_run: bool = False,
          say: Callable[[str], None] = print, collector: Any = None,
          wait: Optional[Dict[str, Any]] = None,
          others: Sequence[ler.Portal] = ()) -> Dict[str, Any]:
    """Read, collect, run. Returns what it did, for the log and the last beat."""
    ledger = ler.load_ledger(s["ledger"])
    if not dry_run:
        ler.refresh_open_runs(ledger, portal, others)
        apply_reruns(ledger, getattr(switch, "take_reruns", lambda: [])(), say=say)
        # A YES THAT COULD NOT BE WRITTEN LAST TIME IS TRIED FIRST (D-608a), before the sheet
        # is read, so a row it reaches reads YES and is not asked.
        write_back_pending(Path(s["workbook"]), ledger, say=say)
        ler.save_ledger(s["ledger"], ledger)
    sources = ler._sources(s["root"])
    switch.beat(report("reading the sheet", str(s["workbook"])))
    decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
    # A PAGE RE-RUN FOR A ROW THAT HAS LEFT THE SHEET IS SAID, ONCE (JG, 11 Nov 2026: "otherwise I
    # need to manually re-run"), on the log and the page's beat, and then forgotten.
    for _job in (ledger.get("jobs") or {}).values():
        _why = _job.pop("page_rerun_refused", None)
        if _why:
            say(f"   Re-run NOT taken: {_why}")
            switch.beat(report("re-run not taken", _why))
    # WHEN AND WHERE THE SHEET WAS READ, ON EVERY BEAT OF THIS CYCLE (JG, 10 Nov): the page said
    # "read 2026-11-03" through a whole day of runs, because the time only moved when a cycle
    # finished. The counts shown are this read's, so the time and the file shown are too.
    read_at = ler._now()
    # NOT FROM PRODUCTION UNLESS ASKED (D-608): the packs are looked for under the Live
    # Enquiry root only, until the extraction endpoint is ready.
    collected = (collect_missing_packs(decisions, s["root"], ledger, dry_run=dry_run, say=say,
                                       collector=collector)
                 if config.LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION else [])
    # THE DRAWING EXTRACT (D-702, SCRUM-185): off unless switched on.
    extracted = (extract_missing_packs(decisions, s["root"], ledger, portal, dry_run=dry_run,
                                       say=say)
                 if getattr(config, "LIVE_ENQUIRY_EXTRACT_FROM_DM", False) else [])
    if not dry_run:
        ler.save_ledger(s["ledger"], ledger)
    if any(c.get("status") == "copied" for c in list(collected) + list(extracted)):
        decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
    ler.write_status(decisions, s["ledger"])
    ler.print_plan(decisions, say=say)
    tally = counts(decisions)
    out = {"counts": tally, "collected": collected, "extracted": extracted, "ran": [], "read_at": read_at}
    if dry_run:
        return out

    current: Dict[str, Any] = {}
    current_key: Dict[str, str] = {}

    def _running() -> Dict[str, Any]:
        # THE RUN ID GOES WITH THE JOB, so the page can stop it. A job this watcher queued
        # was started by no browser tab, so no tab had its id or a Stop button for it; the
        # one the ledger recorded when the portal accepted it is reported on every beat.
        _job = (ledger.get("jobs") or {}).get(current_key.get("key", "")) or {}
        _live = [a for a in (_job.get("attempts") or [])
                 if a.get("status") in {"queued", "running"} and a.get("run_id")]
        if _live:
            current["run_id"] = _live[-1]["run_id"]
            # QUEUED IS NOT RUNNING (JG, 10 Nov 2026): the card said "Running 11896-08-02-GA"
            # while it waited in the queue behind three others. The run's own state goes too.
            current["state"] = _live[-1].get("status") or ""
        else:
            current.pop("run_id", None)
            current.pop("state", None)
        return report("running", f"{current.get('drawing')} ({current.get('customer')})",
                      counts=tally, current=dict(current), recent=recent_runs(ledger),
                      last_cycle_at=read_at, workbook=str(s["workbook"]))

    switched_off: List[bool] = []

    def before_each(d: ler.Decision) -> bool:
        current.clear()
        current.update(customer=d.row.customer, drawing=d.row.drawing,
                       quantities=list(d.quantities), since=ler._now())
        current_key["key"] = ler.job_key(d.row)
        on = switch.beat(_running())
        if not on:
            switched_off.append(True)
        return on

    # A JOB IS MINUTES TO HOURS, AND THE PAGE MUST STILL SEE THE WATCHER. The runner waits on
    # each job by sleeping between status calls; here each sleep is followed by a beat, so the
    # portal shows which job is running throughout. The answer is not acted on mid-job: a
    # switch turned off lets the job in progress finish, and is obeyed before the next one.
    def sleep_and_beat(seconds: float) -> None:
        time.sleep(seconds)
        switch.beat(_running())

    # WHO HEARS ABOUT EACH FINISHED ESTIMATE (D-609): the page's saved "Email the finished
    # estimate to" list, asked once a cycle, so a change saved on the page applies to the next
    # job. SDI_LIVE_ENQUIRY_EMAIL_TO, where set, wins. Unreachable or empty: sent to nobody.
    email_to: List[str] = []
    if not config.LIVE_ENQUIRY_EMAIL_TO:
        try:
            email_to = list(portal.recipients())
        except Exception as exc:                                      # noqa: BLE001
            say(f"   (the saved e-mail list could not be read: "
                f"{getattr(exc, 'message', exc)}; finished estimates are filed and sent to "
                f"nobody this cycle)")
        say(f"   finished estimates are e-mailed to {', '.join(email_to)}" if email_to else
            "   no saved e-mail list: finished estimates are filed and sent to nobody")
    if config.LIVE_ENQUIRY_EMAIL_ESTIMATOR:
        say(f"   and to the estimator each row names, at "
            f"{', '.join(config.LIVE_ENQUIRY_EMAIL_DOMAINS)} addresses only (D-614)")

    def after_each(d: ler.Decision, attempt: Dict[str, Any]) -> None:
        if attempt.get("status") == "done" and d.row.completed_column:
            write_back(Path(s["workbook"]), d.row, attempt, say=say)
            ler.save_ledger(s["ledger"], ledger)
        # THE CARD LETS GO OF A JOB THE MOMENT IT ENDS (D-649), not after the sheet and the
        # Live Enquiry folders have been read again for the next one: a stopped job went on
        # reading "running" (and its Stop button "Stopping") for all of that read.
        if attempt.get("status") in {"done", "error"}:
            current.clear()
            current_key["key"] = ""
            ended = "finished" if attempt.get("status") == "done" else "ended without an estimate"
            switch.beat(report("between jobs",
                               f"{d.row.drawing} ({d.row.customer}) {ended}; reading the "
                               f"sheet for the next job", counts=tally,
                               recent=recent_runs(ledger)))

    # ONE JOB AT A TIME, AND THE SHEET IS READ AGAIN AFTER EACH (D-639). The cycle used to
    # read the sheet once and run only the rows ready at that moment, so a row made ready
    # while a job ran (a new line on the sheet, a pack dropped into its folder) waited for
    # the whole cycle to end and then LIVE_ENQUIRY_POLL_MINUTES more. Now each finished job
    # is followed by a fresh read of the sheet and the folders, and whatever is ready then
    # is next. A row is tried at most once a cycle, so a failure cannot loop; a switch
    # turned off, a portal that stops answering, or a job still running at its time limit
    # ends the cycle exactly as before.
    _wait = wait if wait is not None else {"sleep": sleep_and_beat,
                                           "poll_seconds": JOB_POLL_SECONDS}
    tried: set = set()
    ran: List[Dict[str, Any]] = []
    at_once = max(1, int(getattr(config, "SELF_RUNNING_AT_ONCE", 1) or 1))
    # ITS OWN JOBS STILL ON THE PORTAL COUNT AGAINST THE LIMIT (JG, 10 Nov 2026). A watcher
    # restarted by a task reinstall or a service restart saw its queued job as "running",
    # passed over it, and queued the next ready row: four of its jobs sat in the queue at
    # once, one per restart. Each one still open is picked up here and waited on like a job
    # this process queued, so the limit holds across restarts.
    by_key = {ler.job_key(d.row): d for d in decisions}
    adopted: List[Any] = []
    for _key, _job in (ledger.get("jobs") or {}).items():
        _open = [_a for _a in _job.get("attempts") or []
                 if _a.get("status") in {"queued", "running"} and _a.get("run_id")]
        # ONE COPY OF A JOB ON THE GRID (JG, 10 Nov 2026): 11896-04-00-GA ran on 8071 while a
        # second copy, queued by an earlier watcher on 8072, waited to run it again. The
        # newest copy is kept; an older one still only QUEUED is withdrawn from its service.
        # One already running is left to finish: stopping it is a person's call.
        for _old in _open[:-1]:
            if _old.get("status") != "queued":
                continue
            try:
                ler._asked_in_turn(_old, portal, others)[0].abandon(_old["run_id"])
                _old.update(status="error", finished_at=ler._now(), withdrawn=True,
                            error=f"withdrawn: a second copy of this job was queued as run "
                                  f"{_open[-1].get('run_id')}")
                say(f"   {_job.get('drawing')}: withdrew queued copy {_old['run_id']}; run "
                    f"{_open[-1].get('run_id')} is the one kept")
            except Exception as exc:                              # noqa: BLE001
                say(f"   {_job.get('drawing')}: could not withdraw queued copy "
                    f"{_old['run_id']}: {getattr(exc, 'message', exc)}")
        _open = [_a for _a in _open if _a.get("status") in {"queued", "running"}]
        if _open and _key in by_key:
            adopted += [(by_key[_key], _a) for _a in _open]
    if any(a.get("withdrawn") for _j in (ledger.get("jobs") or {}).values()
           for a in _j.get("attempts") or []):
        ler.save_ledger(s["ledger"], ledger)
    use_flight = at_once > 1 or bool(adopted)

    def _home(attempt: Dict[str, Any]) -> ler.Portal:
        return ler._asked_in_turn(attempt, portal, others)[0]

    while use_flight:
        # MORE THAN ONE AT ONCE (SDI_SELF_RUNNING_AT_ONCE): the same rules as one at a time
        # (the switch asked before each is queued, each row tried once a cycle, the sheet read
        # again after each finishes), with up to `at_once` jobs queued together.
        sleep_fn = _wait.get("sleep", time.sleep)
        poll_s = _wait.get("poll_seconds", JOB_POLL_SECONDS)
        clock = _wait.get("clock", time.time)
        in_flight: List[List[Any]] = []          # [decision, attempt, deadline]
        stop_filling = False
        for d, a in adopted:
            tried.add(ler.job_key(d.row))
            in_flight.append([d, a, clock() + config.LIVE_ENQUIRY_RUN_TIMEOUT_MINUTES * 60])
            say(f"   {d.row.drawing}: still {a.get('status')} on the portal as run "
                f"{a.get('run_id')} (queued {a.get('queued_at')}); waiting for it before "
                f"queueing more")

        def _show(d: ler.Decision) -> None:
            current.clear()
            current.update(customer=d.row.customer, drawing=d.row.drawing,
                           quantities=list(d.quantities), since=ler._now(),
                           also=[f"{x[0].row.drawing} ({x[0].row.customer}, "
                                 f"{x[1].get('status') or 'queued'})"
                                 for x in in_flight if x[0] is not d])
            current_key["key"] = ler.job_key(d.row)

        while True:
            while len(in_flight) < at_once and not stop_filling and not switched_off:
                ready = [d for d in decisions
                         if d.status == "ready" and ler.job_key(d.row) not in tried]
                if not ready:
                    break
                nxt = ready[0]
                tried.add(ler.job_key(nxt.row))
                if not before_each(nxt):
                    say("   stopped: AI Estimate Self-Running was switched off on the portal")
                    break
                try:
                    attempt = ler.queue_one(nxt, portal, ledger, s["ledger"], say=say,
                                            email_to=email_to)
                except ler.PortalError as exc:
                    if exc.status in (0, 503):
                        say(f"   stopped: {exc.message}")
                        stop_filling = True
                        break
                    if exc.status == 409:
                        say(f"   {nxt.row.drawing}: already queued or running on the portal "
                            f"— left to it")
                        continue
                    job = ledger["jobs"].setdefault(ler.job_key(nxt.row), {
                        "customer": nxt.row.customer, "drawing": nxt.row.drawing,
                        "attempts": []})
                    job["attempts"].append({
                        "queued_at": ler._now(), "finished_at": ler._now(), "status": "error",
                        "row": nxt.row.row, "folder": str(nxt.located.folder),
                        "fingerprint": nxt.fingerprint, "quantities": list(nxt.quantities),
                        "error": f"the portal refused it: {exc.message}"})
                    ler.save_ledger(s["ledger"], ledger)
                    say(f"   {nxt.row.drawing}: the portal refused it — {exc.message}")
                    continue
                in_flight.append([nxt, attempt,
                                  clock() + config.LIVE_ENQUIRY_RUN_TIMEOUT_MINUTES * 60])
                _show(nxt)
                switch.beat(_running())
            if not in_flight:
                break
            sleep_fn(poll_s)
            ended = False
            for item in list(in_flight):
                d, attempt, deadline = item
                if ler.poll_once(attempt, _home(attempt), ledger, s["ledger"], say=say):
                    in_flight.remove(item)
                    ran.append(attempt)
                    price = attempt.get("engine_price_gbp")
                    say(f"   {d.row.drawing}: {attempt['status']}"
                        + (f" — £{price:,.2f} a unit at {d.quantities[0]} off" if price else "")
                        + (f" — {attempt.get('error')}" if attempt.get("error") else ""))
                    after_each(d, attempt)
                    ended = True
                elif clock() > deadline:
                    in_flight.remove(item)
                    ran.append(attempt)
                    say(f"   {d.row.drawing} has run past "
                        f"{config.LIVE_ENQUIRY_RUN_TIMEOUT_MINUTES} min; not waiting on it any "
                        f"longer this cycle (the portal keeps it)")
                    stop_filling = True
            ler._touch_lock(s["ledger"])
            if in_flight:
                _show(in_flight[0][0])
            if ended and not stop_filling and not switched_off:
                try:
                    sources = ler._sources(s["root"])
                    decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
                except Exception as exc:                              # noqa: BLE001
                    say(f"   (the sheet could not be read again: {type(exc).__name__}: {exc}; "
                        f"carrying on with the last read)")
        break
    while not use_flight:
        ready = [d for d in decisions
                 if d.status == "ready" and ler.job_key(d.row) not in tried]
        if not ready:
            break
        nxt = ready[0]
        tried.add(ler.job_key(nxt.row))
        batch = ler.run_ready([nxt], portal, ledger, s["ledger"], say=say,
                              before_each=before_each, after_each=after_each,
                              email_to=email_to, **_wait)
        ran += batch
        if batch and batch[-1].get("status") not in {"done", "error"}:
            break                                    # still running at its time limit
        if switched_off:
            break                                    # switched off before it was queued
        if not batch and not any(d.status == "ready" and ler.job_key(d.row) not in tried
                                 for d in decisions):
            break
        try:
            sources = ler._sources(s["root"])
            decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
        except Exception as exc:                                      # noqa: BLE001
            say(f"   (the sheet could not be read again after {nxt.row.drawing}: "
                f"{type(exc).__name__}: {exc}; carrying on with the last read)")
    out["ran"] = ran
    after = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
    ler.write_status(after, s["ledger"])
    out["counts"] = counts(after)
    out["recent"] = recent_runs(ledger)
    return out


def _settings(args: argparse.Namespace) -> Dict[str, Any]:
    return ler._settings(args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AI Estimate Self-Running: obey the portal's "
                                             "switch and work through the Live Enquiry sheet.")
    ap.add_argument("--workbook", default="")
    ap.add_argument("--root", default="")
    ap.add_argument("--ledger", default="")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://10.0.0.5:8071"))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--once", action="store_true", help="one cycle, then stop")
    ap.add_argument("--dry-run", action="store_true",
                    help="read the sheet and say what it would collect and run; copies and "
                         "queues nothing, and does not ask the portal")
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    if args.log:
        ler._log_to(args.log)
    s = _settings(args)
    if not s["workbook"]:
        raise SystemExit("Set SDI_LIVE_ENQUIRY_WORKBOOK (in .env) to the Live Enquiry workbook.")
    # A LIST, LIKE THE RUNNER'S (D-644): jobs go to the first service, the beat to all.
    servers = [x.strip().rstrip("/") for x in str(args.server or "").split(",") if x.strip()]
    portals = [ler.Portal(x, args.api_key) for x in servers] or [ler.Portal(args.server,
                                                                            args.api_key)]
    portal = portals[0]

    if args.dry_run:
        class _Silent(Switch):
            def beat(self, rep: Dict[str, Any]) -> bool:
                return True
        cycle(s, portal, _Silent(portal), dry_run=True)
        return 0

    if not ler.take_lock(s["ledger"]):
        raise SystemExit(f"Another Live Enquiry runner holds {ler._lock_path(s['ledger'])}. "
                         f"Stop it first (the SDI Live Enquiry Runner task); two would queue "
                         f"every job twice.")
    switch = Switch(portals)
    print(f"[{ler._now()}] AI Estimate Self-Running watcher, reporting to "
          f"{', '.join(servers) or args.server}; jobs queued on {servers[0] if servers else args.server}",
          flush=True)
    try:
        next_cycle = 0.0
        while True:
            on = switch.beat(report("idle", "waiting for the next read of the sheet"
                                    if next_cycle else "started; waiting for the switch",
                                    recent=recent_from_ledger(s["ledger"])))
            ler._touch_lock(s["ledger"])
            pressed = bool(switch.last.get("run_now")) or bool(getattr(switch, "reruns", []))
            if on and (pressed or time.time() >= next_cycle):
                try:
                    done = cycle(s, portal, switch, others=portals)
                    msg = (f"read the sheet: {', '.join(f'{v} {k}' for k, v in sorted(done['counts'].items()))}"
                           f"; collected {sum(1 for c in done['collected'] if c.get('status') == 'copied')}"
                           f" pack(s); ran {len(done['ran'])}")
                    print(f"\n[{ler._now()}] {msg}", flush=True)
                    nxt = datetime.now() + timedelta(minutes=config.LIVE_ENQUIRY_POLL_MINUTES)
                    switch.beat(report("waiting", msg, counts=done["counts"],
                                       recent=done.get("recent") or [],
                                       last_cycle_at=done.get("read_at") or ler._now(),
                                       workbook=str(s["workbook"]),
                                       next_cycle_at=nxt.isoformat(timespec="seconds")))
                except SystemExit:
                    raise
                except Exception as exc:                              # noqa: BLE001
                    msg = f"cycle failed: {type(exc).__name__}: {exc}"
                    print(f"\n[{ler._now()}] {msg}", flush=True)
                    switch.beat(report("error", msg))
                next_cycle = time.time() + config.LIVE_ENQUIRY_POLL_MINUTES * 60
                if args.once:
                    return 0
            elif args.once:
                print("Switched off on the portal: nothing run.", flush=True)
                return 0
            time.sleep(IDLE_BEAT_SECONDS)
    finally:
        ler.release_lock(s["ledger"])


if __name__ == "__main__":
    sys.exit(main())
