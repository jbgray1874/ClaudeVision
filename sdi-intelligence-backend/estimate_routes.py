"""
Estimating endpoints for the intranet — the SDI Estimating Intelligence page.

Mount in app.py with two lines:
    from estimate_routes import router as estimate_router
    app.include_router(estimate_router)

Endpoints (all require header  X-SDI-Key: <SDI_API_KEY> when a key is set):
    POST /api/estimate            start a run  -> {run_id, output_path}
    GET  /api/estimate/{run_id}   progress     -> {status, log, output_path, deliverables}
    GET  /api/estimate            every run this service has started

WHY A SUBPROCESS AND NOT AN IMPORT. The engine drives SolidWorks and Excel
through COM. Importing it into the web service would put COM on the request
thread and hold the interpreter for minutes; a child process can be waited on,
logged, and killed without taking the API with it. It also means the service
survives an engine crash, which matters when an estimator is watching a page.

WHY THE OUTPUT IS COPIED RATHER THAN WRITTEN DIRECTLY. main.py writes its
deliverables under output/estimates/ with its own naming. Pointing it at the
share instead would make the estimating folder the engine's scratch space —
every partial run, every failed attempt, in the place Tim keeps real files.
The run completes locally, then its finished artefacts are copied to
<root>\\<Client>\\<DrawingNumber>. A failed run copies nothing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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

# The engine's own checkout. Override with SDI_ENGINE_ROOT if it moves.
ENGINE_ROOT = Path(os.getenv("SDI_ENGINE_ROOT", r"C:\ClaudeVision"))
ENGINE_PY = Path(os.getenv("SDI_ENGINE_PYTHON",
                           str(ENGINE_ROOT / ".venv" / "Scripts" / "python.exe")))

# Where finished estimates are filed. A DRIVE LETTER IS NOT A LOCATION: K: is the
# default mapping here and "sometimes falls off", and a service account never has
# one at all. The UNC form is the only spelling that means the same thing to a
# laptop today and to the server later.
OUTPUT_ROOT = Path(os.getenv(
    "SDI_ESTIMATE_OUTPUT_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"))

# What the page offers back for download once a run finishes.
DELIVERABLE_SUFFIXES = (".xlsx", ".html", ".json", ".log", ".csv")

# The engine's output tree. Deliverables land in estimates/ (workbook AND the HTML
# quote/report, which share a folder); the auditable summary lands in json/.
WATCHED_DIRS = ("estimates", "json")

_MAX_LOG_LINES = 4000


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


# ── run registry ─────────────────────────────────────────────────────────────
@dataclass
class Run:
    run_id: str
    client: str
    drawing_number: str
    units: int
    job_folder: str
    output_path: str
    status: str = "running"                  # running | done | error
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    log: List[str] = field(default_factory=list)
    deliverables: List[Dict[str, str]] = field(default_factory=list)
    before: Dict[str, float] = field(default_factory=dict)   # output tree at start

    def line(self, text: str) -> None:
        if len(self.log) < _MAX_LOG_LINES:
            self.log.append(text.rstrip("\n"))
        elif len(self.log) == _MAX_LOG_LINES:
            self.log.append("… log truncated; the full console is in the run's .log file")

    def as_json(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id, "status": self.status, "error": self.error,
            "client": self.client, "drawing_number": self.drawing_number,
            "units": self.units, "output_path": self.output_path,
            "log": self.log, "deliverables": self.deliverables,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "seconds": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_RUNS: Dict[str, Run] = {}
_LOCK = threading.Lock()


def _active() -> Optional[Run]:
    """ONE ESTIMATE AT A TIME, service-wide — not one per destination.

    Two reasons, and either alone would be enough. The engine drives SolidWorks
    and Excel through COM against a single interactive desktop; two concurrent
    automations of one Excel instance is not a supported thing to do, whatever
    folders they write to. And _collect identifies a run's output by what
    appeared in the output tree while it ran, which is only unambiguous if one
    run is doing the appearing."""
    for run in _RUNS.values():
        if run.status == "running":
            return run
    return None


def _snapshot() -> Dict[str, float]:
    """Every file in the watched output folders, with its modification time."""
    seen: Dict[str, float] = {}
    for name in WATCHED_DIRS:
        folder = ENGINE_ROOT / "output" / name
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            try:
                if item.is_file():
                    seen[str(item)] = item.stat().st_mtime
            except OSError:
                continue
    return seen


# ── the run itself ───────────────────────────────────────────────────────────
def _collect(run: Run) -> None:
    """Copy this run's finished artefacts to the share.

    IDENTIFIED BY WHAT APPEARED, NOT BY WHAT IT IS CALLED. This used to match
    filenames against the job folder's name, on the belief that main.py builds
    every output name from it. It does not: the HTML quote is named from the job
    STEM (12422-24-GA_End Cap_RevB_quote.html) and the workbook from the job
    NUMBER (12422-24_<timestamp>.xlsx). One matcher, two conventions — so the
    reports were filed and the spreadsheet, the thing an estimator actually
    opens, was left behind without a word.

    A name is a guess about the engine's internals; the output tree before and
    after is an observation of what this run did. Anything new, or rewritten,
    while the run was going is the run's. That holds for deliverables nobody has
    written yet, which is the point — this must not need editing every time the
    engine learns to emit another file."""
    dest = Path(run.output_path)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        run.line(f"[collect] cannot create {dest} — {exc}")
        raise

    after = _snapshot()
    fresh = [Path(p) for p, mtime in sorted(after.items())
             if run.before.get(p) is None or mtime > run.before[p]]

    found = 0
    for item in fresh:
        if item.suffix.lower() not in DELIVERABLE_SUFFIXES:
            continue
        try:
            shutil.copy2(item, dest / item.name)
            run.deliverables.append({"name": item.name, "path": str(dest / item.name)})
            found += 1
        except OSError as exc:
            run.line(f"[collect] could not copy {item.name} — {exc}")

    run.line(f"[collect] {found} file(s) written to {dest}")
    if not found:
        run.line("[collect] NOTHING was copied. The engine exited cleanly but wrote "
                 "nothing new into output\\estimates or output\\json — check the log "
                 "above for what it did instead.")

    # The console is part of the record, and is written LAST so it contains the
    # collect result too. An estimate filed on a share with no account of how it
    # was produced is a number nobody can go back and check.
    try:
        transcript = dest / f"{safe_segment(run.drawing_number)}_run.log"
        transcript.write_text("\n".join(run.log) + "\n", encoding="utf-8")
        run.deliverables.append({"name": transcript.name, "path": str(transcript)})
    except OSError as exc:
        run.line(f"[collect] could not write the run log — {exc}")


def _execute(run: Run) -> None:
    job = Path(run.job_folder)
    cmd = [
        str(ENGINE_PY) if ENGINE_PY.is_file() else "python",
        str(ENGINE_ROOT / "src" / "main.py"),
        "--job", str(job),
        "--order-qty", str(run.units),
        "--deliverables",                    # always, as the page promises
        "--customer", run.client,
    ]
    run.line("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(ENGINE_ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
        )
    except OSError as exc:
        run.status, run.error = "error", f"Could not start the engine: {exc}"
        run.line(run.error); run.finished_at = time.time()
        return

    assert proc.stdout is not None
    for text in proc.stdout:
        run.line(text)
    code = proc.wait()

    if code != 0:
        run.status = "error"
        run.error = f"The engine exited with code {code}. Nothing was filed."
        run.line(run.error)
        run.finished_at = time.time()
        return

    try:
        _collect(run)
        run.status = "done"
    except Exception as exc:                 # noqa: BLE001 — surface, never swallow
        run.status = "error"
        run.error = f"The estimate ran but could not be filed: {exc}"
        run.line(run.error)
    run.finished_at = time.time()


# ── request model ────────────────────────────────────────────────────────────
class EstimateRequest(BaseModel):
    client: str
    drawing_number: str
    units: int
    job_folder: Optional[str] = None
    files: List[str] = []
    output_root: Optional[str] = None
    deliverables: bool = True


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
    if not job.is_dir():
        raise HTTPException(404, f"No such folder: {job}")

    root = Path(req.output_root) if req.output_root else OUTPUT_ROOT
    started = time.time()
    drawing_folder = root / client / drawing
    out = drawing_folder / run_folder_name(started, req.units)

    # ONE RUN AT A TIME. The page disables its button, and a page is not a
    # guarantee — two browsers, or a refresh, and there are two.
    with _LOCK:
        busy = _active()
        if busy is not None:
            raise HTTPException(
                409, f"An estimate is already running — {busy.drawing_number} for "
                     f"{busy.client}, started {int(time.time() - busy.started_at)}s "
                     f"ago. The engine drives SolidWorks and Excel on one desktop, "
                     f"so estimates run one after another. Try again when it finishes.")
        run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,
                  units=int(req.units), job_folder=str(job), output_path=str(out),
                  started_at=started)
        # Taken INSIDE the lock and BEFORE the engine starts, so nothing the run
        # produces can land in its own "before" picture.
        run.before = _snapshot()
        _RUNS[run.run_id] = run

    run.line(f"{drawing} · {client} · {run.units} off")
    run.line(f"Reading   {job}")
    run.line(f"Filing to {out}")
    threading.Thread(target=_execute, args=(run,), daemon=True,
                     name=f"estimate-{run.run_id}").start()
    # Both paths back: the drawing's folder is what the estimator navigates to,
    # the run folder is where THIS set of deliverables will be.
    return {"run_id": run.run_id, "output_path": str(out),
            "drawing_folder": str(drawing_folder)}


@router.get("/{run_id}")
def status(run_id: str, x_sdi_key: Optional[str] = Header(default=None)):
    _check_key(x_sdi_key)
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "No such run. The service may have restarted.")
    return run.as_json()


@router.get("")
def recent(x_sdi_key: Optional[str] = Header(default=None), limit: int = 25):
    """Every run this service has started, newest first. In memory only — a
    restart forgets them, and the estimates themselves are on the share."""
    _check_key(x_sdi_key)
    runs = sorted(_RUNS.values(), key=lambda r: r.started_at, reverse=True)[:limit]
    return {"runs": [{k: v for k, v in r.as_json().items() if k != "log"} for r in runs]}
