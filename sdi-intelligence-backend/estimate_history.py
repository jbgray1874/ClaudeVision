"""Restart-safe run history (D-618): every run kept on disk, and put back when the service starts.

JG and the review, 1 Nov 2026: estimates should "run unattended, reach the right people and
remain accessible without relying on you managing each job", and restart-safe history "should
preserve queued, running, completed and failed jobs, recover interrupted runner claims, and
prevent duplicate estimate emails after recovery".

WHAT A RESTART COST. Runs lived only in the service's memory, and the service restarts with
every deployment. Afterwards the page's run list was empty, the e-mail page could not find the
run, a runner mid-job was told "No such run" and stopped an engine that was working, and
Self-Running marked the job failed ("the portal no longer knows this run").

ONE FILE PER RUN, written whole and atomically (a temporary file, then a rename), at every
change of state: queued, claimed, finished, failed, released, and every few seconds while a
runner reports progress. On start the service reads them back:
  queued   stays queued, and a runner claims it as before;
  running  keeps its claim and its lease: the runner, if it is still working, keeps reporting
           and files the result; if it has gone, the lease runs out and the run fails with
           the usual reason; a runner restarted meanwhile is caught by the orphan rule;
  done and error stay in the history the page, the questions and the e-mail page read.
Finished runs are kept SDI_RUN_HISTORY_DAYS (30) and at most SDI_RUN_HISTORY_MAX (2000).
SDI_RUN_HISTORY=0 switches all of it off on one machine.

AN E-MAIL IS SENT AT MOST ONCE. The run records that its e-mail is being sent before the send
starts and what happened after, both on disk; a restart, or the runner reporting the same
finish twice, never sends it again.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, Optional

LOG_KEEP = 400                     # the last lines of a run's console kept on disk
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def enabled() -> bool:
    return os.getenv("SDI_RUN_HISTORY", "1").strip().lower() not in ("0", "false", "no", "off")


def keep_days() -> float:
    try:
        return float(os.getenv("SDI_RUN_HISTORY_DAYS", "30"))
    except ValueError:
        return 30.0


def keep_max() -> int:
    try:
        return int(os.getenv("SDI_RUN_HISTORY_MAX", "2000"))
    except ValueError:
        return 2000


def store_dir() -> Path:
    import estimate_email
    return estimate_email.state_dir() / "runs"


def _body(run: Any) -> Dict[str, Any]:
    body = asdict(run)
    log = list(body.get("log") or [])
    if len(log) > LOG_KEEP:
        body["log"] = [f"… {len(log) - LOG_KEEP} earlier line(s) are in the run's .log file"] \
            + log[-LOG_KEEP:]
    body["saved_at"] = time.time()
    return body


def save(run: Any) -> Optional[str]:
    """Write one run's file. The reason it could not be written, or None."""
    if not enabled() or not _RUN_ID.match(str(getattr(run, "run_id", "") or "")):
        return None
    folder = store_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{run.run_id}.tmp"
        tmp.write_text(json.dumps(_body(run), default=str), encoding="utf-8")
        os.replace(tmp, folder / f"{run.run_id}.json")
        return None
    except (OSError, TypeError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"


def load(run_cls: Any, now: Optional[float] = None) -> Dict[str, Any]:
    """Every saved run, rebuilt as `run_cls`, keyed by run id. Finished runs past the keep
    period, or beyond the newest SDI_RUN_HISTORY_MAX, are removed from disk."""
    if not enabled():
        return {}
    folder = store_dir()
    if not folder.is_dir():
        return {}
    now = time.time() if now is None else now
    names = {f.name for f in fields(run_cls)}
    loaded: Dict[str, Any] = {}
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run = run_cls(**{k: v for k, v in data.items() if k in names})
        except (OSError, ValueError, TypeError) as exc:
            print(f"[history] {path.name} could not be read back ({type(exc).__name__}); "
                  f"left where it is", flush=True)
            continue
        finished = getattr(run, "finished_at", None)
        if (run.status in ("done", "error") and finished
                and now - float(finished) > keep_days() * 86400):
            _remove(path)
            continue
        loaded[run.run_id] = run
    finished_runs = sorted((r for r in loaded.values() if r.status in ("done", "error")),
                           key=lambda r: r.finished_at or r.queued_at, reverse=True)
    for old in finished_runs[keep_max():]:
        _remove(folder / f"{old.run_id}.json")
        loaded.pop(old.run_id, None)
    return loaded


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def restored_note(run: Any, when: float) -> Optional[str]:
    """The line a restored run's log gains, or None for a finished one."""
    stamp = time.strftime("%H:%M:%S", time.localtime(when))
    if run.status == "queued":
        return f"The service restarted at {stamp}; this run was restored and is still queued."
    if run.status == "running":
        return (f"The service restarted at {stamp}; this run was restored with its claim. "
                f"The runner carries on and files the result; if it has stopped, the claim "
                f"runs out and the run fails with the reason.")
    return None
