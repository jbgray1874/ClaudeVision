"""The service's side of the one button (JG, 15 Nov 2026): "we want to just run that command
button whenever estimating / PMs say that the s.sheet has new rows / changes to it, so that our
process finds that s/sheet on the sharepoint, does the delta and prices any changes."

What each piece does, and what it never does:

    snapshot   runs the engine's own command (src/tti_tracker_source.py) which opens the master
               tracker read-only through desktop Excel, saves a copy, and lists its rows. The
               service never imports the engine and never opens the master itself.
    submit     starts the SAME batch the sheet button starts (src/tti_pricer.py) on that copy,
               naming the selected rows exactly, two at once, drawings only, and under the same
               one-writer claim. The task id comes from the plan id, so it is known BEFORE
               anything is sent and can be looked for afterwards.
    reconcile  reads that task's own status file once its process has ended, and releases the
               tracker only on what the file proves: completed, failed, or never submitted
               (with the batch's own words as the evidence). An unfinished file releases nothing.
    baseline   builds the first baseline from the ledgers earlier batches left, matched by
               drawing number and quantity.

No drawing number, tracker name or customer is written here; the master is whatever
SDI_TTI_CENTRAL_SHEET names, read by the engine command from the engine's .env.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tti_incremental import ReviewRequired, Store, baseline_rows  # noqa: F401 (Store re-exported)

TRACKER_ID = "master"


def run_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """OFF unless SDI_TTI_CHANGES_RUN=1: Check always works, pricing waits for the switch."""
    return str((env if env is not None else os.environ).get("SDI_TTI_CHANGES_RUN", "")).strip() == "1"


def task_id_for(plan_id: str) -> str:
    """The batch task a plan starts, fixed by the plan: known before the batch is sent."""
    return uuid.UUID(str(plan_id)).hex[:8]


def make_snapshot(engine_python: Callable[[], str], repo_root: Path, work_dir: Callable[[], Path],
                  runner: Callable[..., Any] = subprocess.run, timeout: int = 600
                  ) -> Callable[[str], Dict[str, Any]]:
    def snapshot(tracker_id: str) -> Dict[str, Any]:
        work = work_dir()
        work.mkdir(parents=True, exist_ok=True)
        out = work / f"snapshot-{uuid.uuid4().hex[:8]}.json"
        args = [engine_python(), str(repo_root / "src" / "tti_tracker_source.py"),
                "--out-dir", str(repo_root / "output" / "tti_tracker"), "--json-out", str(out)]
        try:
            proc = runner(args, capture_output=True, text=True, timeout=timeout, cwd=str(repo_root))
        except subprocess.TimeoutExpired:
            raise ReviewRequired("Reading the master tracker took longer than "
                                 f"{timeout // 60} minutes; nothing was compared.") from None
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            tail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "")[-400:]
            raise ReviewRequired("The master tracker could not be read: " + (tail or "no answer")) from None
        finally:
            try:
                out.unlink()
            except OSError:
                pass
        if not data.get("ok"):
            raise ReviewRequired("The master tracker could not be read: " + str(data.get("error"))[:400])
        return data
    return snapshot


def make_submit(spawn: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    """spawn(task_id=, sheet=, tab=, rows=, replace_costs=, server=, key=) starts the batch and
    returns {task_id, status_url}; it raises if the batch could not be started."""
    def submit(tracker_id: str, rows: List[Dict[str, Any]], *, server: str = "", key: str = "",
               request_id: str = "", at_once: int = 2) -> Dict[str, Any]:
        files = {str(r.get("snapshot_file") or "") for r in rows}
        tabs = {str(r.get("tab") or "") for r in rows}
        numbers = sorted({int(r["row"]) for r in rows})
        if len(files) != 1 or "" in files or len(tabs) != 1 or len(numbers) != len(rows):
            raise ReviewRequired("The selected rows do not come from one copy of the tracker")
        # A re-price a person approved replaces this process's own earlier cost; a batch of new
        # rows only never replaces anything.
        replace = any(r.get("cost") not in (None, "") for r in rows)
        return spawn(task_id=task_id_for(request_id), sheet=Path(files.pop()), tab=tabs.pop(),
                     rows=",".join(str(n) for n in numbers), replace_costs=replace,
                     server=server, key=key)
    return submit


def outcomes_from(status: Dict[str, Any], selected: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """What a FINISHED batch's own status proves for each selected row. A row the status does
    not list is not guessed at."""
    by_row = {int(r["row"]): r for r in status.get("rows") or [] if str(r.get("row", "")).isdigit()}
    out: Dict[str, Dict[str, Any]] = {}
    for sel in selected:
        item = by_row.get(int(sel["row"]))
        if item is None:
            raise ReviewRequired(f"The finished batch's status does not list row {sel['row']}; "
                                 f"review it before anything else is priced")
        run_id = item.get("run_id")
        said = f"batch state: {item.get('state')}" + (f"; {item.get('why')}" if item.get("why") else "")
        if str(item.get("state")) == "done" and item.get("unit_cost") is not None and run_id:
            out[sel["row_id"]] = {"state": "completed" if item.get("written") else "completed_pending_write",
                                  "run_id": run_id, "unit_cost": item.get("unit_cost"), "said": said}
        elif run_id and str(item.get("state")) in {"error", "failed", "cancelled", "abandoned"}:
            out[sel["row_id"]] = {"state": "failed", "run_id": run_id, "said": said}
        elif not run_id and str(item.get("state")) in {
                "needs drawing", "needs decision", "ask", "skipped", "has a cost",
                "held: pack not checked", "held: not the checked pack"}:
            out[sel["row_id"]] = {"state": "not_submitted", "evidence": said}
        else:
            # A POST can succeed and its reply time out. The batch currently records that as
            # 'not queued' with no run ID. That is not evidence of non-submission (row 3,
            # run e2639e873262). Keep the reservation until the services are reconciled.
            raise ReviewRequired(f"Row {sel['row']} has an uncertain/non-terminal outcome ({said}); "
                                 "check the service job history and reconcile before any retry")
    return out


def make_reconcile(store: Store, status_of: Callable[[str], Optional[Dict[str, Any]]],
                   holder: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[str], Optional[str]]:
    """RECONCILE BEFORE ANY RESEND. The tracker stays owned by its last batch until that batch's
    own record says how every selected row ended."""
    def reconcile(tracker_id: str) -> Optional[str]:
        active = store.active_plan(tracker_id)
        if not active:
            return None
        tid = task_id_for(active["plan_id"])
        held = holder()
        if held and str(held.get("task_id")) == tid:
            return f"The last batch (task {tid}) is still running; nothing new can be priced until it ends."
        status = status_of(tid)
        if status is None:
            if held:
                return f"The last batch (task {tid}) left no status and another batch is running; wait for it."
            # A missing file/dead batch does not rule out an accepted runner job.
            return (f"The last request (task {tid}) has no status file. Its reservation stays held; "
                    "check the service job history and reconcile before any retry.")
        if not status.get("finished"):
            return (f"The last batch (task {tid}) ended without finishing. Its rows stay reserved: "
                    f"review its log before anything else is priced.")
        try:
            outcomes = outcomes_from(status, active["rows"])
        except ReviewRequired as exc:
            return str(exc)
        store.finish(active["plan_id"], outcomes)
        n = sum(1 for o in outcomes.values() if o["state"].startswith("completed"))
        return f"The last batch (task {tid}) finished: {n} of {len(outcomes)} row(s) priced."
    return reconcile


def ledgers_in(folder: Path) -> List[Dict[str, Any]]:
    out = []
    for f in sorted(Path(folder).glob("*.ledger.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out
