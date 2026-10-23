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
  2. Collect the drawings for every row asked for (AI CHECK = YES) that is still WAITING for
     its pack: the Live Enquiry collector's own search of the Production share finds the
     drawings for the row's drawing number, and they are copied into
     <Live Enquiry root>\\<customer>\\<drawing> — the runner's layout, so the next read finds
     the pack. A row whose drawings are not in Production either says so and is searched again
     after LIVE_ENQUIRY_COLLECT_RETRY_HOURS.
  3. Run every ready row one after another through the portal — the same POST /api/estimate a
     person makes from the page (live_enquiry_runner.run_ready). Before each row the switch is
     asked again: switched off, the job in progress finishes and nothing more is queued.
  4. Report what it read, collected and ran, then read the sheet again after
     LIVE_ENQUIRY_POLL_MINUTES — or at once, when the button is pressed again.

NOTHING HERE PRICES ANYTHING, and the workbook is read, never written. What ran is in the
runner's ledger; this watcher shares the runner's lock, so it and `live_enquiry_runner.py
watch` can never both drive one sheet.
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
RECENT_RUNS_SHOWN = 10


# ── WHAT THE PAGE IS TOLD ────────────────────────────────────────────────────────────
def counts(decisions: Sequence[ler.Decision]) -> Dict[str, int]:
    return dict(Counter(d.status for d in decisions))


def recent_runs(ledger: Dict[str, Any], limit: int = RECENT_RUNS_SHOWN) -> List[Dict[str, Any]]:
    """The newest attempts in the ledger, newest first, as the page lists them."""
    out = []
    for job in (ledger.get("jobs") or {}).values():
        for a in job.get("attempts") or []:
            out.append({"customer": job.get("customer"), "drawing": job.get("drawing"),
                        "status": a.get("status"), "queued_at": a.get("queued_at"),
                        "finished_at": a.get("finished_at"),
                        "unit_gbp": a.get("engine_price_gbp"),
                        "quantities": a.get("quantities"),
                        "output": a.get("output_path") or "", "error": a.get("error") or ""})
    out.sort(key=lambda r: str(r.get("queued_at") or ""), reverse=True)
    return out[:limit]


def report(phase: str, message: str = "", **extra: Any) -> Dict[str, Any]:
    return {"host": socket.gethostname(), "pid": os.getpid(), "phase": phase,
            "message": message, "at": ler._now(), **extra}


class Switch:
    """The portal's answer, asked on every beat. Unreachable is OFF: a watcher that cannot
    hear the portal queues nothing."""

    def __init__(self, portal: ler.Portal, say: Callable[[str], None] = print):
        self.portal, self.say = portal, say
        self.last: Dict[str, Any] = {}

    def beat(self, rep: Dict[str, Any]) -> bool:
        try:
            self.last = self.portal.self_running(rep) or {}
        except ler.PortalError as exc:
            self.say(f"   (the portal did not answer the self-running beat: {exc.message}; "
                     f"treated as switched off)")
            self.last = {}
            return False
        return bool(self.last.get("enabled"))


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


# ── ONE CYCLE ────────────────────────────────────────────────────────────────────────
def cycle(s: Dict[str, Any], portal: ler.Portal, switch: Switch, dry_run: bool = False,
          say: Callable[[str], None] = print, collector: Any = None,
          wait: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read, collect, run. Returns what it did, for the log and the last beat."""
    ledger = ler.load_ledger(s["ledger"])
    if not dry_run:
        ler.refresh_open_runs(ledger, portal)
        ler.save_ledger(s["ledger"], ledger)
    sources = ler._sources(s["root"])
    switch.beat(report("reading the sheet", str(s["workbook"])))
    decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
    collected = collect_missing_packs(decisions, s["root"], ledger, dry_run=dry_run, say=say,
                                      collector=collector)
    if not dry_run:
        ler.save_ledger(s["ledger"], ledger)
    if any(c.get("status") == "copied" for c in collected):
        decisions = ler.plan(ler.read_sheet(s["workbook"]), sources, ledger)
    ler.write_status(decisions, s["ledger"])
    ler.print_plan(decisions, say=say)
    tally = counts(decisions)
    out = {"counts": tally, "collected": collected, "ran": []}
    if dry_run:
        return out

    current: Dict[str, Any] = {}

    def _running() -> Dict[str, Any]:
        return report("running", f"{current.get('drawing')} ({current.get('customer')})",
                      counts=tally, current=dict(current), recent=recent_runs(ledger))

    def before_each(d: ler.Decision) -> bool:
        current.clear()
        current.update(customer=d.row.customer, drawing=d.row.drawing,
                       quantities=list(d.quantities), since=ler._now())
        return switch.beat(_running())

    # A JOB IS MINUTES TO HOURS, AND THE PAGE MUST STILL SEE THE WATCHER. The runner waits on
    # each job by sleeping between status calls; here each sleep is followed by a beat, so the
    # portal shows which job is running throughout. The answer is not acted on mid-job: a
    # switch turned off lets the job in progress finish, and is obeyed before the next one.
    def sleep_and_beat(seconds: float) -> None:
        time.sleep(seconds)
        switch.beat(_running())

    out["ran"] = ler.run_ready(decisions, portal, ledger, s["ledger"], say=say,
                               before_each=before_each,
                               **(wait if wait is not None else {"sleep": sleep_and_beat}))
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
    portal = ler.Portal(args.server, args.api_key)

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
    switch = Switch(portal)
    print(f"[{ler._now()}] AI Estimate Self-Running watcher, portal {args.server}", flush=True)
    try:
        next_cycle = 0.0
        while True:
            on = switch.beat(report("idle", "waiting for the next read of the sheet"
                                    if next_cycle else "started; waiting for the switch"))
            ler._touch_lock(s["ledger"])
            pressed = bool(switch.last.get("run_now"))
            if on and (pressed or time.time() >= next_cycle):
                try:
                    done = cycle(s, portal, switch)
                    msg = (f"read the sheet: {', '.join(f'{v} {k}' for k, v in sorted(done['counts'].items()))}"
                           f"; collected {sum(1 for c in done['collected'] if c.get('status') == 'copied')}"
                           f" pack(s); ran {len(done['ran'])}")
                    print(f"\n[{ler._now()}] {msg}", flush=True)
                    nxt = datetime.now() + timedelta(minutes=config.LIVE_ENQUIRY_POLL_MINUTES)
                    switch.beat(report("waiting", msg, counts=done["counts"],
                                       recent=done.get("recent") or [],
                                       last_cycle_at=ler._now(),
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
