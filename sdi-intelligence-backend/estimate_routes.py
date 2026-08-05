"""
Estimating endpoints for the intranet — the SDI Estimating Intelligence page.

Mount in app.py with two lines:
    from estimate_routes import router as estimate_router
    app.include_router(estimate_router)

WHY THIS IS A QUEUE AND NOT A SUBPROCESS ANY MORE.

The engine drives SOLIDWORKS and Excel through COM. COM needs a licensed,
interactive desktop session — not a Windows service — so whatever runs an
estimate needs a SOLIDWORKS seat, an Office licence and somebody logged in.
SDI-APP01 has none of those and cannot get them: it already carries the PDM
archive service, the SolidNetWork licence manager, the TRUMPF stack and two SQL
Server instances on 32 GB, and a hung Excel on that box is a PDM outage rather
than a failed estimate.

So the work moves and the web service stays. This service holds the page, the
queue and the run history — no COM, no Excel, no seat — and can sit on SDI-APP01
today. A RUNNER on a machine that does have a seat polls for work, executes it
locally and reports back.

THE RUNNER DIALS OUT. It is never connected TO. That means no inbound firewall
rule, no fixed address, and a runner that is somebody's laptop can move desks,
go home, or join over VPN without anything being reconfigured.

A runner is a ROLE, not a machine. One laptop today, a dedicated host when one
is bought, two hosts when throughput matters — the same code, and capacity is
however many are checked in.

Endpoints (all require header  X-SDI-Key: <SDI_API_KEY> when a key is set):

    the page
      POST /api/estimate                 queue a run  -> {run_id, output_path}
      GET  /api/estimate/{run_id}        progress
      GET  /api/estimate                 every run this service knows about
      GET  /api/estimate/runners         who is checked in, and is anyone

    the runner
      POST /api/estimate/runner/claim              take the oldest queued run
      POST /api/estimate/runner/{run_id}/progress  log lines + renew the lease
      POST /api/estimate/runner/{run_id}/complete  done or failed, with results
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import config

router = APIRouter(prefix="/api/estimate", tags=["estimate"])

# Where finished estimates are filed. A DRIVE LETTER IS NOT A LOCATION: K: is the
# default mapping here and "sometimes falls off", and a service account never has
# one at all. The UNC form is the only spelling that means the same thing to a
# laptop today and to a dedicated host later.
OUTPUT_ROOT = Path(os.getenv(
    "SDI_ESTIMATE_OUTPUT_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"))

_MAX_LOG_LINES = 4000

# How long a runner's claim on a run survives without word from it. A laptop that
# sleeps mid-estimate must not leave a job "running" for ever while an estimator
# watches a spinner — the lease expires, the run is failed with a reason, and the
# queue moves on.
LEASE_SECONDS = int(os.getenv("SDI_RUNNER_LEASE_SECONDS", "180"))

# A runner that has not polled within this is treated as gone, and the page says
# so rather than quietly queueing work nobody will pick up.
RUNNER_ONLINE_SECONDS = int(os.getenv("SDI_RUNNER_ONLINE_SECONDS", "90"))


# ── access gate, identical to app.py's ───────────────────────────────────────
def _check_key(x_sdi_key: Optional[str]) -> None:
    if config.API_KEY and x_sdi_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


# ── path safety ──────────────────────────────────────────────────────────────
def _within_a_root(target: str) -> Optional[Path]:
    """The same containment rule app.py serves files under. Repeated here rather
    than imported so a change to one is a deliberate change to both."""
    t = os.path.normcase(os.path.normpath(target))
    for root in config.FILE_ROOTS:
        r = os.path.normcase(os.path.normpath(root))
        if t == r or t.startswith(r + os.sep):
            return Path(os.path.normpath(target))
    return None


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def run_folder_name(started_at: float, units: int) -> str:
    """The name of the folder ONE run files into.

    NOTHING IS EVER OVERWRITTEN. Every run of a drawing lands in its own folder,
    so a re-run cannot replace the quote belonging to an earlier workbook — which
    is what made the flat layout wrong. The engine names the workbook from the job
    NUMBER with a timestamp and the quote from the job STEM without one, so a
    second run left two spreadsheets beside a single report that described only
    the newer of them. An estimator opening the older one got a report for a
    different estimate, with nothing on screen saying so.

    Sortable-first date, so Explorer's default name order is time order. The
    quantity is in the name because a re-run at a different quantity is a
    DIFFERENT ESTIMATE, and it is the one thing you cannot tell from a timestamp.
    """
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(started_at))
    return f"{stamp} ({int(units)} off)"


def safe_segment(text: Any) -> str:
    """A client name and a drawing number become FOLDER names, and a folder name
    is not free text. Windows refuses some characters outright and silently
    truncates a trailing dot; a name that survives typing must also survive
    being a directory. Sanitised on the SERVER because the page can be bypassed."""
    cleaned = _UNSAFE.sub("-", str(text or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(". ")
    return cleaned[:120]


# ── registries ───────────────────────────────────────────────────────────────
@dataclass
class Run:
    run_id: str
    client: str
    drawing_number: str
    units: int
    job_folder: str
    output_path: str
    status: str = "queued"          # queued | running | done | error
    error: str = ""
    queued_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None      # when a runner claimed it
    finished_at: Optional[float] = None
    runner: str = ""                        # which runner is doing it
    lease_until: float = 0.0
    log: List[str] = field(default_factory=list)
    deliverables: List[Dict[str, str]] = field(default_factory=list)

    def line(self, text: str) -> None:
        if len(self.log) < _MAX_LOG_LINES:
            self.log.append(text.rstrip("\n"))
        elif len(self.log) == _MAX_LOG_LINES:
            self.log.append("… log truncated; the full console is in the run's .log file")

    def as_json(self) -> Dict[str, Any]:
        ref = self.started_at or self.queued_at
        return {
            "run_id": self.run_id, "status": self.status, "error": self.error,
            "client": self.client, "drawing_number": self.drawing_number,
            "units": self.units, "output_path": self.output_path,
            "job_folder": self.job_folder, "runner": self.runner,
            "log": self.log, "deliverables": self.deliverables,
            "queued_at": self.queued_at, "started_at": self.started_at,
            "finished_at": self.finished_at,
            "seconds": round((self.finished_at or time.time()) - ref, 1),
        }


@dataclass
class Runner:
    runner_id: str
    hostname: str = ""
    last_seen: float = field(default_factory=time.time)
    run_id: str = ""                       # what it is working on, if anything

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) <= RUNNER_ONLINE_SECONDS

    def as_json(self) -> Dict[str, Any]:
        return {"runner_id": self.runner_id, "hostname": self.hostname,
                "online": self.online, "run_id": self.run_id,
                "seconds_since_seen": round(time.time() - self.last_seen, 1)}


_RUNS: Dict[str, Run] = {}
_RUNNERS: Dict[str, Runner] = {}
_LOCK = threading.Lock()


def _expire_dead_claims() -> None:
    """A GATE NOBODY ASKS REPORTS NOTHING, so this is called on every request that
    reads or changes the queue rather than left to a timer that might not be
    running. A claim whose lease has run out means the runner stopped talking —
    lid closed, VPN dropped, process killed — and the run must be failed with a
    reason rather than left looking busy for ever."""
    now = time.time()
    for run in _RUNS.values():
        if run.status == "running" and run.lease_until and run.lease_until < now:
            run.status = "error"
            run.error = (f"The runner ({run.runner or 'unknown'}) stopped responding "
                         f"{int(now - run.lease_until) + LEASE_SECONDS}s into the run. "
                         f"Nothing was filed. If that machine went to sleep or lost the "
                         f"network, start the runner again and re-run the job.")
            run.line(run.error)
            run.finished_at = now
            r = _RUNNERS.get(run.runner)
            if r is not None and r.run_id == run.run_id:
                r.run_id = ""


def _online_runners() -> List[Runner]:
    return [r for r in _RUNNERS.values() if r.online]


def _busy_runner() -> Optional[Run]:
    """ONE ESTIMATE AT A TIME PER RUNNER. Two concurrent automations of one Excel
    instance on one desktop is not a supported thing to do, whatever folders they
    write to. Capacity comes from more runners, not from more parallel COM."""
    for run in _RUNS.values():
        if run.status == "running":
            return run
    return None


# ── request models ───────────────────────────────────────────────────────────
class EstimateRequest(BaseModel):
    client: str
    drawing_number: str
    units: int
    job_folder: Optional[str] = None
    files: List[str] = []
    output_root: Optional[str] = None
    deliverables: bool = True


class ClaimRequest(BaseModel):
    runner_id: str
    hostname: str = ""


class ProgressRequest(BaseModel):
    runner_id: str
    lines: List[str] = []


class CompleteRequest(BaseModel):
    runner_id: str
    status: str                              # done | error
    error: str = ""
    lines: List[str] = []
    deliverables: List[Dict[str, str]] = []


# ══ THE RUNNER'S ENDPOINTS ═══════════════════════════════════════════════════
# DECLARED BEFORE /{run_id}. FastAPI matches in declaration order, and a path
# parameter will happily swallow "runner" as a run id if given the chance.

@router.get("/runners")
def runners(x_sdi_key: Optional[str] = Header(default=None)):
    """Who is checked in. The page asks this so it can say "no runner is
    connected" instead of queueing work that nobody will ever pick up."""
    _check_key(x_sdi_key)
    with _LOCK:
        _expire_dead_claims()
        listed = [r.as_json() for r in sorted(_RUNNERS.values(),
                                              key=lambda r: r.last_seen, reverse=True)]
        online = [r for r in listed if r["online"]]
        queued = sum(1 for run in _RUNS.values() if run.status == "queued")
    return {"runners": listed, "online": len(online), "queued": queued}


@router.post("/runner/claim")
def claim(req: ClaimRequest, x_sdi_key: Optional[str] = Header(default=None)):
    """A runner asking for work. Returns a run to execute, or nothing."""
    _check_key(x_sdi_key)
    now = time.time()
    with _LOCK:
        _expire_dead_claims()
        runner = _RUNNERS.setdefault(req.runner_id, Runner(runner_id=req.runner_id))
        runner.hostname = req.hostname or runner.hostname
        runner.last_seen = now

        if _busy_runner() is not None:
            return {"run": None, "reason": "another run is in progress"}

        queued = sorted((r for r in _RUNS.values() if r.status == "queued"),
                        key=lambda r: r.queued_at)
        if not queued:
            return {"run": None, "reason": "nothing queued"}

        run = queued[0]
        run.status = "running"
        run.runner = req.runner_id
        run.started_at = now
        run.lease_until = now + LEASE_SECONDS
        runner.run_id = run.run_id
        run.line(f"Claimed by runner {req.hostname or req.runner_id}")

    return {"run": {
        "run_id": run.run_id, "client": run.client, "units": run.units,
        "drawing_number": run.drawing_number, "job_folder": run.job_folder,
        "output_path": run.output_path,
    }}


@router.post("/runner/{run_id}/progress")
def progress(run_id: str, req: ProgressRequest,
             x_sdi_key: Optional[str] = Header(default=None)):
    """Log lines from the engine, and the heartbeat that renews the lease."""
    _check_key(x_sdi_key)
    now = time.time()
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "No such run.")
        if run.runner != req.runner_id:
            raise HTTPException(409, "That run is claimed by a different runner.")
        if run.status != "running":
            raise HTTPException(409, f"That run is {run.status}, not running.")
        for text in req.lines:
            run.line(text)
        run.lease_until = now + LEASE_SECONDS
        r = _RUNNERS.get(req.runner_id)
        if r is not None:
            r.last_seen = now
    return {"ok": True, "lease_seconds": LEASE_SECONDS}


@router.post("/runner/{run_id}/complete")
def complete(run_id: str, req: CompleteRequest,
             x_sdi_key: Optional[str] = Header(default=None)):
    """The runner reporting the outcome. The runner files the deliverables — it
    is the machine that has them — and tells us what it wrote."""
    _check_key(x_sdi_key)
    now = time.time()
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "No such run.")
        if run.runner != req.runner_id:
            raise HTTPException(409, "That run is claimed by a different runner.")
        for text in req.lines:
            run.line(text)
        run.status = "done" if req.status == "done" else "error"
        run.error = req.error
        run.deliverables = list(req.deliverables)
        run.finished_at = now
        run.lease_until = 0.0
        r = _RUNNERS.get(req.runner_id)
        if r is not None:
            r.last_seen, r.run_id = now, ""
    return {"ok": True}


# ══ THE PAGE'S ENDPOINTS ═════════════════════════════════════════════════════
@router.post("")
def start(req: EstimateRequest, x_sdi_key: Optional[str] = Header(default=None)):
    _check_key(x_sdi_key)

    client = safe_segment(req.client)
    drawing = safe_segment(req.drawing_number)
    if not client or not drawing:
        raise HTTPException(400, "A client and a drawing number are both required.")
    if not isinstance(req.units, int) or req.units < 1:
        raise HTTPException(400, "Number of units must be a whole number of 1 or more.")

    # A JOB IS A FOLDER. The page can add loose files too, but the engine reads a
    # pack; where only files were given, their common parent is the job.
    folder = req.job_folder
    if not folder and req.files:
        try:
            folder = os.path.commonpath([str(Path(f).parent) for f in req.files])
        except ValueError:
            folder = None
    if not folder:
        raise HTTPException(400, "Add a job folder, or drawings that share one.")

    job = _within_a_root(folder)
    if job is None:
        raise HTTPException(
            403, "That folder is outside the shares this service may read. "
                 "Add it to SDI_FILE_ROOTS if it should be readable.")
    # NOTE: existence is NOT checked here. This service may not be able to see the
    # share at all — that is rather the point of a runner — so the runner checks,
    # and reports a missing folder as a failed run with a reason.

    root = Path(req.output_root) if req.output_root else OUTPUT_ROOT
    queued_at = time.time()
    drawing_folder = root / client / drawing
    out = drawing_folder / run_folder_name(queued_at, req.units)

    with _LOCK:
        _expire_dead_claims()
        if not _online_runners():
            raise HTTPException(
                503, "No estimating runner is connected, so there is nothing to run "
                     "this job. Start the runner on a machine with SOLIDWORKS and "
                     "Excel, then try again.")
        busy = _busy_runner()
        if busy is not None:
            raise HTTPException(
                409, f"An estimate is already running — {busy.drawing_number} for "
                     f"{busy.client}, started {int(time.time() - (busy.started_at or 0))}s "
                     f"ago. SOLIDWORKS and Excel are driven on one desktop, so "
                     f"estimates run one after another.")
        run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,
                  units=int(req.units), job_folder=str(job), output_path=str(out),
                  queued_at=queued_at)
        _RUNS[run.run_id] = run

    run.line(f"{drawing} · {client} · {run.units} off")
    run.line(f"Reading   {job}")
    run.line(f"Filing to {out}")
    run.line("Queued — waiting for a runner to pick it up.")
    return {"run_id": run.run_id, "output_path": str(out),
            "drawing_folder": str(drawing_folder)}


@router.get("/{run_id}")
def status(run_id: str, x_sdi_key: Optional[str] = Header(default=None)):
    _check_key(x_sdi_key)
    with _LOCK:
        _expire_dead_claims()
        run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "No such run. The service may have restarted.")
    return run.as_json()


@router.get("")
def recent(x_sdi_key: Optional[str] = Header(default=None), limit: int = 25):
    """Every run this service has queued, newest first. In memory only — a
    restart forgets them, and the estimates themselves are on the share."""
    _check_key(x_sdi_key)
    with _LOCK:
        _expire_dead_claims()
        runs = sorted(_RUNS.values(), key=lambda r: r.queued_at, reverse=True)[:limit]
        out = [{k: v for k, v in r.as_json().items() if k != "log"} for r in runs]
    return {"runs": out}
