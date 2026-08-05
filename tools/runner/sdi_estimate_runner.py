"""
SDI Estimating Intelligence — the runner.

Runs on a machine that HAS what an estimate needs: a SOLIDWORKS seat, an Office
licence, and somebody logged in. Polls the SDI Intelligence service for queued
jobs, executes them locally, streams the console back, and files the finished
deliverables to the share.

    python tools\\runner\\sdi_estimate_runner.py --server http://10.0.0.5:8071

WHY IT DIALS OUT AND IS NEVER CONNECTED TO. A runner may be a laptop. It moves
desks, goes home, joins over VPN and gets a different address every time. Polling
outward means none of that needs configuring, no inbound firewall rule exists to
be asked for, and the machine is reachable by exactly nobody.

WHY THE RUNNER FILES THE OUTPUT. It is the machine that HAS the files. Sending
hundreds of megabytes of workbook and report to a web service so that the web
service can write them to a share the runner can already see would be slower,
more fragile, and would put the share rights on the wrong account.

The engine is driven exactly as a person would drive it from a terminal:
    main.py --job <folder> --order-qty <n> --deliverables --customer <client>

Nothing here decides anything about an estimate. If this file has an opinion
about costing, that is a bug.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── things a test can reach without the network ──────────────────────────────
# requests is imported lazily inside the polling loop so that everything which
# DECIDES something — what counts as a deliverable, what this run produced — can
# be imported and tested on a machine that has neither requests nor a server.

DELIVERABLE_SUFFIXES = (".xlsx", ".html", ".json", ".log", ".csv")

# The engine's output tree. Deliverables land in estimates/ (workbook AND the HTML
# quote/report, which share a folder); the auditable summary lands in json/.
WATCHED_DIRS = ("estimates", "json")


def snapshot(engine_root: Path) -> Dict[str, float]:
    """Every file in the watched output folders, with its modification time."""
    seen: Dict[str, float] = {}
    for name in WATCHED_DIRS:
        folder = Path(engine_root) / "output" / name
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            try:
                if item.is_file():
                    seen[str(item)] = item.stat().st_mtime
            except OSError:
                continue
    return seen


def collect(engine_root: Path, dest: Path, before: Dict[str, float],
            log: List[str], drawing_number: str = "") -> List[Dict[str, str]]:
    """Copy this run's finished artefacts to the share.

    IDENTIFIED BY WHAT APPEARED, NOT BY WHAT IT IS CALLED. Matching filenames
    against the job folder's name looks obvious and is wrong: the HTML quote is
    named from the job STEM and the workbook from the job NUMBER, so one matcher
    against two conventions files the reports and silently leaves the spreadsheet
    behind — a folder on the Estimating share that looks finished, missing the one
    file an estimator actually opens.

    A name is a guess about the engine's internals; the output tree before and
    after is an observation of what this run did. That also keeps working when the
    engine learns to emit a deliverable nobody has thought of yet."""
    filed: List[Dict[str, str]] = []
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.append(f"[collect] cannot create {dest} — {exc}")
        raise

    after = snapshot(engine_root)
    fresh = [Path(p) for p, mtime in sorted(after.items())
             if before.get(p) is None or mtime > before[p]]

    for item in fresh:
        if item.suffix.lower() not in DELIVERABLE_SUFFIXES:
            continue
        try:
            shutil.copy2(item, dest / item.name)
            filed.append({"name": item.name, "path": str(dest / item.name)})
        except OSError as exc:
            log.append(f"[collect] could not copy {item.name} — {exc}")

    log.append(f"[collect] {len(filed)} file(s) written to {dest}")
    if not filed:
        log.append("[collect] NOTHING was copied. The engine exited cleanly but wrote "
                   "nothing new into output\\estimates or output\\json — check the log "
                   "above for what it did instead.")

    # The console is part of the record, and is written LAST so it contains the
    # filing result too. An estimate on a share with no account of how it was
    # produced is a number nobody can go back and check.
    try:
        name = (drawing_number or "run").replace("/", "-").replace("\\", "-")
        transcript = dest / f"{name}_run.log"
        transcript.write_text("\n".join(log) + "\n", encoding="utf-8")
        filed.append({"name": transcript.name, "path": str(transcript)})
    except OSError as exc:
        log.append(f"[collect] could not write the run log — {exc}")

    return filed


def engine_command(engine_root: Path, engine_python: Path, job: Path,
                   units: int, client: str) -> List[str]:
    """Exactly what a person would type. --deliverables is not optional: the page
    promises a complete set every time, so it is not a flag the caller can forget."""
    return [
        str(engine_python) if Path(engine_python).is_file() else "python",
        str(Path(engine_root) / "src" / "main.py"),
        "--job", str(job),
        "--order-qty", str(units),
        "--deliverables",
        "--customer", client,
    ]


# ── one runner per machine ───────────────────────────────────────────────────
# The lock is taken on a byte FAR PAST anything we write. msvcrt.locking locks at
# the file's current position, so locking byte 0 and then writing the holder's
# identity there means the process fights its own lock — which is exactly what
# the first version did, and it failed with "Permission denied" on the flush.
# Separating the two regions means the lock is a lock and the text is text.
_LOCK_BYTE = 4096
_IDENTITY_BYTES = 256


def claim_the_machine(engine_root: Path):
    """Refuse to start if a runner is already running here, and say which one.

    ONE DESKTOP, ONE EXCEL, ONE SOLIDWORKS SESSION. Two runners on one machine
    would drive the same COM automation from two processes, and they cannot even
    tell each other apart: the runner id is deliberately stable per machine so a
    restart does not leave the service listing a graveyard of dead runners, which
    means every process on this box registers as the SAME runner.

    It is also how a window opened on Tuesday is still polling on Friday. Six of
    them were found running at once, three under the wrong interpreter.

    An OS-level lock rather than a pid file, because it is released when the
    process dies HOWEVER it dies: Ctrl+C, a crash, a closed window, a laptop that
    slept and never came back. A pid file survives all of those and then refuses
    to start the runner you actually want. The pid we write is only for the
    message — the lock decides, so the text can be stale without harming anything.
    """
    lock_path = Path(engine_root) / "output" / ".runner.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    handle = os.fdopen(fd, "r+b")          # binary: no newline translation to trip on

    handle.seek(0)
    previous = handle.read(_IDENTITY_BYTES).decode("utf-8", "replace").strip("\x00 \r\n")

    handle.seek(_LOCK_BYTE)
    try:
        try:
            import msvcrt                                   # Windows
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl                                    # everywhere else
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(
            f"\nA runner is already running on this machine "
            f"({previous or 'process unknown'}).\n"
            f"  One runner per machine: SOLIDWORKS and Excel are driven on one\n"
            f"  desktop, and a second runner here would fight the first for them.\n"
            f"  Close that window, or find strays with:\n"
            f"      Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |\n"
            f"        Where-Object CommandLine -like '*sdi_estimate_runner*' |\n"
            f"        Select-Object ProcessId, CommandLine\n")

    # Written at offset 0, padded to a fixed width and never truncated, so it can
    # never reach the locked byte.
    identity = (f"pid {os.getpid()} on {platform.node()} since "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    handle.seek(0)
    handle.write(identity.encode("utf-8")[:_IDENTITY_BYTES].ljust(_IDENTITY_BYTES, b" "))
    handle.flush()
    return handle          # held open for the life of the process; do not close


# ── the polling loop ─────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="SDI Estimating Intelligence runner")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://10.0.0.5:8071"),
                    help="Base URL of the SDI Intelligence service.")
    ap.add_argument("--engine-root", default=os.getenv("SDI_ENGINE_ROOT", r"C:\ClaudeVision"))
    ap.add_argument("--engine-python", default=os.getenv("SDI_ENGINE_PYTHON", ""))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    ap.add_argument("--runner-id", default=os.getenv("SDI_RUNNER_ID", ""))
    a = ap.parse_args()

    try:
        import requests
    except ImportError:
        print("This runner needs 'requests'.  pip install requests", file=sys.stderr)
        return 2

    engine_root = Path(a.engine_root)
    _lock = claim_the_machine(engine_root)          # noqa: F841 — held, not used
    engine_python = Path(a.engine_python) if a.engine_python else \
        engine_root / ".venv" / "Scripts" / "python.exe"

    # STABLE ACROSS RESTARTS, per machine. A fresh id on every start would leave
    # the service listing a graveyard of runners that were all the same one.
    runner_id = a.runner_id or f"{platform.node()}-{uuid.getnode():x}"
    base = a.server.rstrip("/") + "/api/estimate"
    headers = {"X-SDI-Key": a.api_key} if a.api_key else {}

    print(f"SDI estimating runner")
    print(f"  server   {a.server}")
    print(f"  engine   {engine_root}")
    print(f"  python   {engine_python}{'' if engine_python.is_file() else '   (NOT FOUND — will fall back to python on PATH)'}")
    print(f"  runner   {runner_id}  ({platform.node()})")
    print(f"  polling every {a.poll_seconds:g}s — Ctrl+C to stop\n")

    complained = None
    while True:
        try:
            r = requests.post(f"{base}/runner/claim", json={
                "runner_id": runner_id, "hostname": platform.node()},
                headers=headers, timeout=20)
        except Exception as exc:                       # noqa: BLE001 — keep polling
            # SAY IT ONCE. A runner that cannot reach the server prints a line a
            # second, and the one useful message scrolls away.
            complained = _say_once(complained, "unreachable",
                f"cannot reach {a.server} — {exc}",
                "   still trying; this will not be repeated until it changes.")
            time.sleep(a.poll_seconds)
            continue

        # A REPLY IS NOT A FAILURE TO REPLY, and the difference is somebody's
        # morning. The service answers on this port; if it answers 404 it is an
        # OLDER BUILD that has no runner endpoints, and the fix is Ctrl+C on the
        # service, not an hour spent on firewalls and ports.
        if r.status_code == 404:
            complained = _say_once(complained, "old-service",
                f"the service at {a.server} answered 404 for the runner queue.",
                "   It is running an older build with no runner endpoints.",
                "   Restart app.py there — the page is served from disk on every",
                "   request, but the routes are imported once at start-up.")
            time.sleep(a.poll_seconds)
            continue
        if r.status_code == 401:
            complained = _say_once(complained, "unauthorised",
                f"the service at {a.server} rejected this runner (401).",
                "   SDI_API_KEY must match on both sides. Pass --api-key, or set",
                "   SDI_API_KEY in this runner's environment.")
            time.sleep(a.poll_seconds)
            continue
        try:
            r.raise_for_status()
            job = (r.json() or {}).get("run")
        except Exception as exc:                       # noqa: BLE001
            complained = _say_once(complained, "bad-reply",
                f"the service answered {r.status_code} — {exc}")
            time.sleep(a.poll_seconds)
            continue
        if complained:
            print(f"[{time.strftime('%H:%M:%S')}] connected to {a.server}.")
        complained = None

        if not job:
            time.sleep(a.poll_seconds)
            continue

        _execute(requests, base, headers, job, engine_root, engine_python, runner_id)


def _say_once(current: Optional[str], kind: str, *lines: str) -> Optional[str]:
    """Print a complaint the first time, and stay quiet until the COMPLAINT changes.

    A runner that cannot get work prints once every poll, and the one line that
    would have told somebody what to do scrolls away inside a minute. Keyed on the
    KIND of problem rather than a flag, so a service that goes from unreachable to
    404 says so instead of staying silent because it already complained once."""
    if current == kind:
        return current
    print(f"[{time.strftime('%H:%M:%S')}] {lines[0]}")
    for extra in lines[1:]:
        print(extra)
    return kind


def _execute(requests, base: str, headers: Dict[str, str], job: Dict[str, Any],
             engine_root: Path, engine_python: Path, runner_id: str) -> None:
    run_id = job["run_id"]
    dest = Path(job["output_path"])
    folder = Path(job["job_folder"])
    log: List[str] = []
    pending: List[str] = []
    last_sent = 0.0

    def say(text: str) -> None:
        text = text.rstrip("\n")
        log.append(text)
        pending.append(text)
        print(text)

    def flush(force: bool = False) -> None:
        nonlocal last_sent, pending
        # Batched, because a chatty engine would otherwise be one HTTP request per
        # console line. The heartbeat rides along, so the lease is renewed by the
        # act of working rather than by a separate timer that could outlive a
        # wedged run and keep it looking alive.
        if not force and not pending and (time.time() - last_sent) < 20:
            return
        if not force and not pending:
            return
        batch, pending = pending, []
        try:
            requests.post(f"{base}/runner/{run_id}/progress",
                          json={"runner_id": runner_id, "lines": batch},
                          headers=headers, timeout=20)
            last_sent = time.time()
        except Exception:                              # noqa: BLE001
            pending = batch + pending                  # keep it for the next try

    print(f"\n--- {job['drawing_number']} · {job['client']} · {job['units']} off")
    say(f"Runner picked up the job on {os.environ.get('COMPUTERNAME', 'this machine')}.")

    if not folder.is_dir():
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The job folder is not readable from this runner: {folder}", log)
        return

    before = snapshot(engine_root)
    cmd = engine_command(engine_root, engine_python, folder, int(job["units"]), job["client"])
    say("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    flush(force=True)

    try:
        proc = subprocess.Popen(cmd, cwd=str(engine_root), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
    except OSError as exc:
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"Could not start the engine: {exc}", log)
        return

    assert proc.stdout is not None
    for text in proc.stdout:
        say(text)
        flush()
    code = proc.wait()

    if code != 0:
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The engine exited with code {code}. Nothing was filed.", log)
        return

    try:
        filed = collect(engine_root, dest, before, log, job.get("drawing_number", ""))
    except Exception as exc:                           # noqa: BLE001 — surface it
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The estimate ran but could not be filed: {exc}", log)
        return

    _finish(requests, base, headers, run_id, runner_id, "done", "", log, filed)


def _finish(requests, base: str, headers: Dict[str, str], run_id: str, runner_id: str,
            status: str, error: str, log: List[str],
            deliverables: Optional[List[Dict[str, str]]] = None) -> None:
    if error:
        log.append(error)
        print(error)
    body = {"runner_id": runner_id, "status": status, "error": error,
            "lines": [], "deliverables": deliverables or []}
    # The whole log goes with the completion, so a run whose progress posts were
    # lost to a blip still arrives complete rather than half-reported.
    body["lines"] = log
    for attempt in range(4):
        try:
            requests.post(f"{base}/runner/{run_id}/complete", json=body,
                          headers=headers, timeout=30).raise_for_status()
            print(f"--- reported {status}\n")
            return
        except Exception as exc:                       # noqa: BLE001
            if attempt == 3:
                print(f"could not report the result to the server — {exc}", file=sys.stderr)
                print("The estimate itself is filed; the page will show it as timed out.",
                      file=sys.stderr)
                return
            time.sleep(2 ** attempt)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nrunner stopped.")
