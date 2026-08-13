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
#
# THREE MINUTES WAS A BET THAT LOST FOUR TIMES IN ONE MORNING, ALL OF THEM WRONGLY.
# 11650 was killed at 180s, 181s, 180s and 180s while the engine was working perfectly:
# it goes quiet for minutes driving Excel and SOLIDWORKS over COM, and _execute runs
# INLINE in the poll loop, so during a run the runner does not poll either. Nothing spoke,
# so the service concluded the machine had died and destroyed a completed piece of work.
#
# The two errors are not symmetric. Expiring too early throws away real work and tells the
# operator to go and check a laptop that was never asleep. Expiring too late leaves a queue
# blocked — annoying, recoverable, and now recoverable ON PURPOSE: the short lease was
# compensating for having no way to release a stuck claim, and POST /{run_id}/abandon is
# that way. The compensation can go.
#
# The runner also heartbeats now, every LEASE/6 while the engine process is alive, so a
# genuinely dead machine is still noticed within a few beats of the truth.
LEASE_SECONDS = int(os.getenv("SDI_RUNNER_LEASE_SECONDS", "900"))

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
    # ONE PDF, NOT A PACK. An M&S-style enquiry is a hundred unrelated drawings that each
    # want their own estimate, which is main.py's --pdf mode; a job FOLDER is the 11650
    # case, where every drawing in it contributes to one BOM. The two are different
    # questions about the same files, and the runner has to be told which was asked.
    pdf_path: str = ""
    batch_id: str = ""                      # which enquiry this drawing came in with
    # THE SECOND OPINION, KEPT BESIDE THE FIRST AND NEVER MIXED INTO IT. An LLM read of the
    # drawing arrives in seconds; the engine's estimate takes tens of minutes and runs one
    # at a time. Holding both on the run means the page can show the fast answer now and
    # the real one when it lands -- and can show where they disagree, which is the entire
    # reason for having two methods rather than a faster one.
    llm_price_gbp: Optional[float] = None
    llm: Dict[str, Any] = field(default_factory=dict)
    engine_price_gbp: Optional[float] = None
    # WHETHER A RUNNER SHOULD EVER PICK THIS UP. An LLM-only enquiry needs no SOLIDWORKS
    # seat and no Excel; queued as an ordinary run it would sit in front of real work for
    # ever, waiting for a machine that has nothing to do with it.
    wants_engine: bool = True
    # STOP MEANS STOP, NOT "LOOK STOPPED". Abandoning a run frees the queue and leaves the
    # engine running -- SOLIDWORKS and Excel carry on driving a desktop nobody is watching,
    # for the fifteen minutes the job had left, and the next run queues behind work that has
    # already been given up on. The runner cannot be interrupted from here, so it is TOLD, on
    # the heartbeat it already sends, and it does the killing at its end.
    cancel_requested: bool = False
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
            "pdf_path": self.pdf_path, "batch_id": self.batch_id,
            "llm_price_gbp": self.llm_price_gbp, "llm": self.llm,
            "engine_price_gbp": self.engine_price_gbp,
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


class BatchRequest(BaseModel):
    """A hundred drawings that are a hundred enquiries, not one pack."""
    client: str
    units: int
    files: List[str] = []
    output_root: Optional[str] = None
    # "both" runs the fast LLM read AND queues the full estimate. "llm" scans only, which is
    # the only method that finishes a hundred drawings the same day. "engine" is the full
    # estimate alone. Default both, because the point of two methods is the comparison.
    method: str = "both"


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
    # THE ENGINE'S OWN ANSWER, so the page can put it beside the LLM's. Reported by the
    # runner because the runner is the machine that has the summary JSON; this service has
    # never read an estimate and is not about to start.
    unit_cost_gbp: Optional[float] = None


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
        # WHAT IT IS BUSY WITH, not merely that it holds a run id. The page has to be able
        # to say "busy — 11650-00 for Boots, 67s in" in the same words the 409 uses when it
        # refuses a second estimate, or the two disagree about one fact and the operator is
        # left to guess which is right.
        for entry in listed:
            run = _RUNS.get(entry.get("run_id") or "")
            entry["running"] = None if run is None or run.status != "running" else {
                "drawing_number": run.drawing_number, "client": run.client,
                "seconds": round(time.time() - (run.started_at or time.time())),
            }
        online = [r for r in listed if r["online"]]
        queued = sum(1 for run in _RUNS.values() if run.status == "queued")
    return {"runners": listed, "online": len(online), "queued": queued,
            "busy": sum(1 for r in online if r.get("running"))}


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

        queued = sorted((r for r in _RUNS.values()
                         if r.status == "queued" and r.wants_engine),
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
        # WHICH QUESTION WAS ASKED OF THESE FILES. Empty means the job folder is the job
        # and every drawing in it pools into one estimate; set means this one drawing is
        # the job. The runner cannot infer it -- both arrive as paths under the same share.
        "pdf_path": run.pdf_path,
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
        _cancel = run.cancel_requested
    # THE ANSWER TO A HEARTBEAT IS WHERE A CANCELLATION FITS. The runner is a separate
    # process on another machine and cannot be reached; it can only be told something the
    # next time it speaks, and it already speaks every few seconds to renew the lease.
    return {"ok": True, "lease_seconds": LEASE_SECONDS, "cancel": _cancel}


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
        if req.unit_cost_gbp is not None:
            try:
                run.engine_price_gbp = round(float(req.unit_cost_gbp), 2)
            except (TypeError, ValueError):
                pass
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
        # A QUEUE THAT REFUSES WORK WHILE IT IS WORKING IS NOT A QUEUE.
        #
        # This raised 409 whenever anything was RUNNING, which made a hundred-drawing M&S
        # enquiry impossible to submit: the first drawing would be claimed within five
        # seconds and the other ninety-nine would all be refused. It also refused a second
        # ordinary job that could perfectly well have waited.
        #
        # The one-at-a-time rule is real -- two concurrent COM automations against one
        # desktop is not a supported thing to do -- but it is a rule about EXECUTION, and
        # claim() is where it is enforced: a runner is handed nothing while another run is
        # in progress. Queueing is not executing. The guard was in the wrong place, and the
        # cost of it being there was that the queue could only ever hold one thing.
        busy = _busy_runner()
        run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,
                  units=int(req.units), job_folder=str(job), output_path=str(out),
                  queued_at=queued_at)
        _RUNS[run.run_id] = run

    run.line(f"{drawing} · {client} · {run.units} off")
    run.line(f"Reading   {job}")
    run.line(f"Filing to {out}")
    if busy is not None:
        run.line(f"Queued behind {busy.drawing_number} for {busy.client}, which has been "
                 f"running {int(time.time() - (busy.started_at or 0))}s. SOLIDWORKS and "
                 f"Excel are driven on one desktop, so estimates run one after another.")
    else:
        run.line("Queued — waiting for a runner to pick it up.")
    return {"run_id": run.run_id, "output_path": str(out),
            "drawing_folder": str(drawing_folder),
            "waiting_behind": busy.run_id if busy is not None else None}


@router.post("/batch")
def batch(req: BatchRequest, x_sdi_key: Optional[str] = Header(default=None)):
    """An enquiry that is many drawings, each wanting its own estimate.

    THE M&S SHAPE. A customer sends a hundred PDFs and asks what each one costs. That is a
    hundred estimates, not one: the drawings are unrelated, they do not share a BOM, and
    pooling them would produce a single meaningless total. It is the opposite of the 11650
    shape, where four drawings ARE one cabinet and pooling them is the whole point.

    Both shapes already exist in the engine -- main.py --pdf reads one drawing as one job,
    main.py --job pools a folder -- and both already exist in this queue. So this adds no
    execution path and no new way for an estimate to be produced. It queues one ordinary
    run per drawing and lets the queue do what a queue does: one at a time, in order,
    each filing into its own folder under the client.

    Filed as  <root>/<client>/<drawing>/<dated run>  which is the existing convention with
    the drawing taken from the PDF's own filename. The filename is used deliberately: it is
    knowable BEFORE the run, so a drawing that fails still has a named folder and the
    estimator can match it to the file they were sent. The title-block number is read
    during the run and appears in the outputs.
    """
    _check_key(x_sdi_key)
    client = safe_segment(req.client)
    if not client:
        raise HTTPException(400, "A client is required — it names the folder every one of "
                                 "these estimates is filed under.")
    if not isinstance(req.units, int) or req.units < 1:
        raise HTTPException(400, "Number of units must be a whole number of 1 or more.")
    if not req.files:
        raise HTTPException(400, "Add the drawings to estimate.")

    method = str(req.method or "both").strip().lower()
    if method not in {"both", "llm", "engine"}:
        raise HTTPException(400, f"Unknown pricing method {req.method!r}. Use both, llm or "
                                 f"engine.")
    root = Path(req.output_root) if req.output_root else OUTPUT_ROOT
    batch_id = uuid.uuid4().hex[:12]
    queued_at = time.time()
    accepted, refused = [], []

    with _LOCK:
        _expire_dead_claims()
        # ONLY THE METHOD THAT NEEDS A RUNNER IS REFUSED WITHOUT ONE. An LLM scan runs on
        # this service and needs no seat, so refusing it because a laptop is closed would
        # withhold the one method that can answer a hundred drawings today.
        if method != "llm" and not _online_runners():
            raise HTTPException(
                503, "No estimating runner is connected, so there is nothing to run these "
                     "jobs. Start the runner on a machine with SOLIDWORKS and Excel, then "
                     "try again — or run this enquiry as an LLM scan, which needs neither.")
        # ORDER IS THE ORDER THEY WERE GIVEN IN. An estimator working down a customer's
        # list wants the answers to arrive in that list's order, not in whatever order a
        # file dialog happened to hand them over.
        for raw in req.files:
            path = _within_a_root(raw)
            if path is None:
                refused.append({"file": raw, "why": "outside the shares this service may read"})
                continue
            drawing = safe_segment(Path(raw).stem)
            if not drawing:
                refused.append({"file": raw, "why": "its name leaves nothing to call a folder"})
                continue
            out = root / client / drawing / run_folder_name(queued_at, req.units)
            run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,
                      units=int(req.units), job_folder=str(Path(raw).parent),
                      output_path=str(out), queued_at=queued_at,
                      pdf_path=str(path), batch_id=batch_id,
                      wants_engine=(method != "llm"))
            _RUNS[run.run_id] = run
            accepted.append(run)
            queued_at += 0.001          # keeps the queue order stable and the sort total

    for i, run in enumerate(accepted, start=1):
        run.line(f"{run.drawing_number} · {client} · {run.units} off")
        run.line(f"Reading   {run.pdf_path}")
        run.line(f"Filing to {run.output_path}")
        run.line(f"Queued — drawing {i} of {len(accepted)} in this enquiry.")

    # THE SCAN RUNS IN THE BACKGROUND AND THE REQUEST RETURNS NOW. A hundred drawings at a
    # few seconds each is minutes; holding the HTTP request open for that would time out in
    # the browser and leave the estimator with no batch id for work that is running anyway.
    if method in {"both", "llm"}:
        threading.Thread(target=_scan_batch, args=(list(accepted),),
                         name=f"llm-scan-{batch_id}", daemon=True).start()

    if not accepted:
        # AN ENQUIRY THAT QUEUED NOTHING IS NOT AN ENQUIRY THAT WAS ACCEPTED. Returning 200
        # with an empty list would read on the page as "submitted", and the estimator would
        # wait for a hundred answers that nobody is producing.
        raise HTTPException(400, "None of those drawings could be queued: "
                            + "; ".join(f"{Path(r['file']).name} — {r['why']}"
                                        for r in refused[:6]))
    return {"batch_id": batch_id, "client": client, "units": int(req.units),
            "method": method, "client_folder": str(root / client),
            "queued": [r.run_id for r in accepted], "refused": refused}


def _scan_one(run: "Run") -> None:
    """The fast read, on the service, for one drawing.

    NOT ON THE RUNNER, DELIBERATELY. The runner exists because SOLIDWORKS and Excel need an
    interactive desktop and can only do one thing at a time; an LLM read needs neither. Put
    it in that queue and a hundred scans would file in behind a forty-minute estimate and
    arrive tomorrow, which is the exact problem this method exists to solve.

    Never raises. A hundred-drawing enquiry runs this a hundred times and drawing seven
    failing must not cost the other ninety-three -- the failure goes on the row.
    """
    try:
        import sys
        _src = str(Path(__file__).resolve().parents[1] / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
        from llm_scan_price import scan_price
        out = scan_price(run.pdf_path, run.units)
    except Exception as exc:                                 # noqa: BLE001
        out = {"found": False,
               "why": f"the scan could not run ({type(exc).__name__}: {str(exc)[:160]})"}
    with _LOCK:
        run.llm = out
        run.llm_price_gbp = out.get("price_gbp") if out.get("found") else None
        # AN LLM-ONLY DRAWING IS FINISHED WHEN THE SCAN IS. Left "queued" it would count
        # for ever against the enquiry's total and the page would never say it was done --
        # a progress bar that cannot reach the end is worse than none.
        if not run.wants_engine and run.status == "queued":
            run.status = "done"
            run.finished_at = time.time()
    run.line("LLM scan: " + (
        f"£{out['price_gbp']:.2f} — {out.get('basis') or 'no basis given'}"
        if out.get("found") else f"no figure — {out.get('why') or 'no reason given'}"))


def _scan_batch(runs: List["Run"]) -> None:
    """One at a time, in the enquiry's order.

    SEQUENTIAL ON PURPOSE. Firing a hundred concurrent requests at an account is how a key
    gets rate-limited, and this project has already watched SerpAPI answer 429 seven times
    in one run. Seconds each, in order, is fast enough to be useful and slow enough to be
    allowed.
    """
    for run in runs:
        if run.status in {"done", "error"}:
            continue                     # released or already finished while we worked
        _scan_one(run)


@router.get("/batch/{batch_id}")
def batch_status(batch_id: str, x_sdi_key: Optional[str] = Header(default=None)):
    """Every drawing in one enquiry, in the order it was queued.

    ONE REQUEST, NOT A HUNDRED. The page polls this every couple of seconds; asking after
    each run separately would be a hundred requests per tick, and the log lines that make a
    single run readable are noise when what you want is a list of a hundred answers.
    """
    _check_key(x_sdi_key)
    with _LOCK:
        _expire_dead_claims()
        runs = sorted((r for r in _RUNS.values() if r.batch_id == batch_id),
                      key=lambda r: r.queued_at)
    if not runs:
        raise HTTPException(404, "No such enquiry. The service may have restarted.")
    done = [r for r in runs if r.status in {"done", "error"}]
    return {
        "batch_id": batch_id, "client": runs[0].client, "units": runs[0].units,
        "total": len(runs), "finished": len(done),
        "failed": sum(1 for r in done if r.status == "error"),
        "runs": [{"run_id": r.run_id, "drawing_number": r.drawing_number,
                  "status": r.status, "error": r.error,
                  "llm_price_gbp": r.llm_price_gbp,
                  "engine_price_gbp": r.engine_price_gbp,
                  "llm_basis": (r.llm or {}).get("basis") or (r.llm or {}).get("why") or "",
                  "llm_confidence": (r.llm or {}).get("confidence"),
                  "seconds": round((r.finished_at or time.time())
                                   - (r.started_at or r.queued_at), 1),
                  "output_path": r.output_path,
                  "deliverables": r.deliverables} for r in runs],
    }


@router.post("/batch/{batch_id}/abandon")
def batch_abandon(batch_id: str, x_sdi_key: Optional[str] = Header(default=None)):
    """Stop the rest of an enquiry. Finished drawings keep their estimates.

    A hundred queued drawings is the one case where changing your mind is expensive to act
    on one row at a time, and an estimator who has spotted that the wrong folder was picked
    should not have to click ninety-nine times to say so.
    """
    _check_key(x_sdi_key)
    released = 0
    with _LOCK:
        runs = [r for r in _RUNS.values() if r.batch_id == batch_id]
        if not runs:
            raise HTTPException(404, "No such enquiry. The service may have restarted.")
        for run in runs:
            if run.status not in {"queued", "running"}:
                continue
            was = run.status
            # STOPPING A HUNDRED DRAWINGS MEANS THE SAME AS STOPPING ONE. A batch was the
            # one place where "stop" still only freed the queue: the drawing being worked on
            # carried on driving SOLIDWORKS and Excel for the fifteen minutes it had left,
            # on an enquiry the estimator had already given up on. The single-run stop
            # learned to end the engine; this is the same act, ninety-nine times over, and
            # it had no reason to mean less.
            run.cancel_requested = True
            run.status = "error"
            run.error = ("Released with the rest of this enquiry. "
                         + ("It had not started." if was == "queued" else
                            "It was running; the runner ends the engine on its next "
                            "heartbeat."))
            run.line(run.error)
            run.finished_at = time.time()
            run.lease_until = 0.0
            r = _RUNNERS.get(run.runner)
            if r is not None and r.run_id == run.run_id:
                r.run_id = ""
            released += 1
    return {"ok": True, "released": released}


@router.post("/{run_id}/abandon")
def abandon(run_id: str, x_sdi_key: Optional[str] = Header(default=None)):
    """Release a claim a HUMAN knows is dead, without waiting out the lease.

    WHY THIS EXISTS AT ALL. The lease was three minutes because there was no other way to
    unstick a queue, and three minutes is far too short for a job whose expensive phase
    prints nothing — so it killed four healthy runs of 11650 in one morning. The lease is
    now generous, which it can be precisely because this exists: the operator standing in
    front of the machine knows whether it is working, and the service does not.

    It does NOT stop the engine. The runner is a separate process on another machine and
    may still be working; if it finishes it will try to report and be told the run is no
    longer its own. That is why this says so plainly rather than pretending to cancel.
    """
    _check_key(x_sdi_key)
    with _LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "No such run. The service may have restarted.")
        if run.status not in {"queued", "running"}:
            raise HTTPException(409, f"That run is already {run.status}.")
        was = run.status
        # SET BEFORE THE STATUS CHANGES. Once the run is no longer "running", the heartbeat
        # endpoint refuses it with a 409 and the runner never gets to read this flag -- so the
        # 409 is what actually carries the message, and this records the INTENT for anything
        # that reads the run afterwards. Both halves matter: the 409 says "not yours any more",
        # which is also true of a run this runner genuinely lost, and only this says a person
        # asked for it to stop.
        run.cancel_requested = True
        run.status = "error"
        run.error = ("Released by hand from the page. The queue is free; if the runner was "
                     "in fact still working, its result will be refused when it reports.")
        run.line(run.error)
        run.finished_at = time.time()
        run.lease_until = 0.0
        r = _RUNNERS.get(run.runner)
        if r is not None and r.run_id == run.run_id:
            r.run_id = ""
    return {"ok": True, "was": was, "run_id": run_id}


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
