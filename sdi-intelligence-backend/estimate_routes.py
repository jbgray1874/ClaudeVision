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


def _active_for(output_path: str) -> Optional[Run]:
    key = os.path.normcase(output_path)
    for run in _RUNS.values():
        if run.status == "running" and os.path.normcase(run.output_path) == key:
            return run
    return None


# ── the run itself ───────────────────────────────────────────────────────────
def _collect(run: Run, stem_hint: str) -> None:
    """Copy this run's finished artefacts to the share.

    Matched on the job folder's name, which is what main.py builds every output
    filename from, and filtered to files written DURING this run — an estimates
    folder accumulates, and yesterday's workbook for the same drawing must not
    be filed as today's result."""
    src = ENGINE_ROOT / "output" / "estimates"
    if not src.is_dir():
        run.line(f"[collect] no {src} — nothing to copy")
        return
    dest = Path(run.output_path)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        run.line(f"[collect] cannot create {dest} — {exc}")
        raise

    key = stem_hint.lower()
    found = 0
    for item in sorted(src.iterdir()):
        if not item.is_file() or item.suffix.lower() not in DELIVERABLE_SUFFIXES:
            continue
        if key and key not in item.name.lower():
            continue
        if item.stat().st_mtime < run.started_at - 5:
            continue                        # older than this run: not ours
        try:
            shutil.copy2(item, dest / item.name)
            run.deliverables.append({"name": item.name, "path": str(dest / item.name)})
            found += 1
        except OSError as exc:
            run.line(f"[collect] could not copy {item.name} — {exc}")

    # The saved JSON lives elsewhere and is the auditable record of the run.
    js = ENGINE_ROOT / "output" / "json" / f"{stem_hint}.json"
    if js.is_file() and js.stat().st_mtime >= run.started_at - 5:
        try:
            shutil.copy2(js, dest / js.name)
            run.deliverables.append({"name": js.name, "path": str(dest / js.name)})
            found += 1
        except OSError as exc:
            run.line(f"[collect] could not copy {js.name} — {exc}")

    run.line(f"[collect] {found} file(s) written to {dest}")
    if not found:
        run.line("[collect] NOTHING was copied. The run finished but produced no "
                 "artefact this service could identify — check the log above.")


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
        _collect(run, job.name)
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
    out = root / client / drawing

    # ONE RUN PER DESTINATION. Two estimates writing one folder is how a set of
    # deliverables ends up half from each; the page disables its button, and a
    # page is not a guarantee.
    with _LOCK:
        busy = _active_for(str(out))
        if busy is not None:
            raise HTTPException(
                409, f"An estimate for {client} / {drawing} is already running "
                     f"(started {int(time.time() - busy.started_at)}s ago).")
        run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,
                  units=int(req.units), job_folder=str(job), output_path=str(out))
        _RUNS[run.run_id] = run

    run.line(f"{drawing} · {client} · {run.units} off")
    run.line(f"Reading   {job}")
    run.line(f"Filing to {out}")
    threading.Thread(target=_execute, args=(run,), daemon=True,
                     name=f"estimate-{run.run_id}").start()
    return {"run_id": run.run_id, "output_path": str(out)}


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
