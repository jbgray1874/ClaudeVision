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

# ── THE RUNNER READS .env TOO ───────────────────────────────────────────────────────
# config.load_dot_env() loads C:\ClaudeVision\.env at config import, before anything reads
# os.environ, so the ENGINE's switches -- XAI_API_KEY, SDI_SW_RUN_ANALYSER, SDI_OFFLINE --
# come from a file that is the same for every run however it was started, and by whichever
# entry point. (It lived in main.py once, which meant only a run through main.py got it.)
# The runner is a separate process and imports no engine module, so it still needs its own
# read of the same file. Without it, SDI_ENGINE_ROOT, SDI_SERVER, SDI_API_KEY and
# SDI_ENGINE_PYTHON came from whichever PowerShell window happened to launch it.
#
# That is the fragility this project has already paid for twice: a run whose behaviour
# depends on the shell it was started from is a run nobody can reproduce, and the difference
# only shows up as a wrong number days later. SDI_ENGINE_ROOT is the worst of them -- point
# it at a stale checkout and the page silently estimates with code nobody has pulled.
#
# Loaded from the runner's own location, not the working directory, so it is the same file
# whatever directory the window was in. Shell variables still WIN, because load_dotenv does
# not override by default and a deliberately-set variable must keep working; what changes is
# that the default now comes from a file rather than from nothing.
def _load_engine_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return                      # same posture as main.py: not installed is not fatal
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / ".env", Path(os.getenv("SDI_ENGINE_ROOT",
                                                               r"C:\ClaudeVision")) / ".env"):
        try:
            if candidate.exists():
                load_dotenv(candidate)
                print(f"[env] runner loaded {candidate}", flush=True)
                return
        except OSError:
            continue


import sys
import threading
import time
import uuid
from pathlib import Path

_load_engine_env()          # before anything reads os.getenv for a default
from typing import Any, Dict, List, Optional

# ── things a test can reach without the network ──────────────────────────────
# requests is imported lazily inside the polling loop so that everything which
# DECIDES something — what counts as a deliverable, what this run produced — can
# be imported and tested on a machine that has neither requests nor a server.

DELIVERABLE_SUFFIXES = (".xlsx", ".html", ".json", ".log", ".csv")

# HOW OFTEN THE LEASE IS RENEWED WHILE THE ENGINE IS QUIET. Read from the same name the
# service uses, so the two cannot be configured apart -- a runner beating slower than the
# lease it renews is the original defect with different numbers, arriving silently.
#
# CAPPED AT 30s, not simply lease/6. A 900s lease would put the first renewal 150 seconds
# in -- inside the old lease's margin, and a long time to sit watching a window with no
# idea whether anything is alive. The post is a few hundred bytes; there is no reason to be
# frugal with it, and every reason to have many renewals inside one lease rather than six.
_BEAT_SECONDS = max(5, min(30, int(os.getenv("SDI_RUNNER_LEASE_SECONDS", "900")) // 6))
# How long the engine may print nothing before the page is told it is still alive. Two
# minutes, because the person watching needs to know it is working well before the lease
# would have expired -- that uncertainty is most of what made this morning expensive.
_SAY_QUIET_AFTER = 120

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
                   units: int, client: str, pdf: Optional[Path] = None) -> List[str]:
    """Exactly what a person would type. --deliverables is not optional: the page
    promises a complete set every time, so it is not a flag the caller can forget.

    TWO QUESTIONS, TWO FLAGS, AND THE CALLER DOES NOT GET TO GUESS. --job pools every
    drawing in a folder into one estimate, which is what 11650 is; --pdf reads one drawing
    as one job, which is what each drawing of a hundred-drawing M&S enquiry is. Passing the
    wrong one does not fail -- it produces a confident estimate of a different question,
    which is the worst kind of wrong this system can be.""" 
    return [
        str(engine_python) if Path(engine_python).is_file() else "python",
        # -u, BECAUSE THIS OUTPUT IS GOING DOWN A PIPE.
        # Python block-buffers stdout when it is not a terminal, so the engine's progress
        # reached the runner in multi-kilobyte bursts minutes apart: on 11650 the page sat
        # silent through the whole of the PDF extraction and then received it in one lump.
        # Estimators watching a page that does nothing for four minutes conclude it has
        # hung, and they are not wrong to — nothing there distinguishes buffering from a
        # dead run. The engine is the same; only when it speaks changes.
        "-u",
        str(Path(engine_root) / "src" / "main.py"),
    ] + (["--pdf", str(pdf)] if pdf else ["--job", str(job)]) + [
        "--order-qty", str(units),
        "--deliverables",
        "--customer", client,
    ]


# ── one runner per machine, advisory ─────────────────────────────────────────
# THIS MUST NEVER STOP THE RUNNER STARTING. It exists because six runners were
# once found polling at once; it does not exist to be clever, and it has already
# failed twice in ways that stopped the one runner somebody actually wanted:
# once by locking the byte it then wrote to, and once by failing to READ a byte
# another handle held. Both times a guard against an unlikely problem became the
# problem.
#
# So it now fails OPEN. A definite, understood "somebody else holds this" is
# reported and refused. Anything else at all - a permission oddity, a share that
# does not support locking, an exception nobody predicted - warns and carries on.
# The authoritative check lives in start-runner.ps1, where Windows can be asked
# the question directly and an answer cannot break the process asking it.
_LOCK_BYTE = 4096
_IDENTITY_BYTES = 256


def _read_identity(lock_path: Path) -> str:
    """Who the lock file says holds it, read WITHOUT touching the locked byte.

    THE LOCK WAS BREAKING THE READ IT EXISTS TO ENABLE, and only on Windows.

    The identity sits at byte 0 and the lock at byte 4096, which looks like ample
    separation and is not: a buffered read of 256 bytes fills through the raw
    layer at io.DEFAULT_BUFFER_SIZE - 8192 bytes - so it spans byte 4096 every
    time. On Linux that is harmless because flock is advisory and blocks nothing.
    On Windows a byte-range lock is MANDATORY, so the read failed, and the refusal
    fell back to "another process (it holds the lock file)" instead of naming the
    pid. The one thing an estimator needs from that message - WHICH window to
    close - was missing on the only platform this runs on.

    So the read is raw and exactly _IDENTITY_BYTES long: os.read asks for what it
    is given and no more, so it cannot reach the locked byte however the buffer
    size changes. On its own descriptor, too - reading through the handle that
    holds the lock would move that handle's file position, and _take_lock depends
    on where it is.
    """
    fd = None
    try:
        fd = os.open(str(lock_path), os.O_RDONLY)
        return os.read(fd, _IDENTITY_BYTES).decode("utf-8", "replace").strip("\x00 \r\n")
    except (OSError, ValueError):
        # A read that still fails has told us something real: somebody holds the
        # file in a way that excludes us. The caller says exactly that rather than
        # inventing a name for them.
        return ""
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def claim_the_machine(engine_root: Path):
    """Best-effort single-instance advisory. Returns a handle, or None.

    Two runners on one machine drive the same COM automation from two processes,
    and the service cannot even tell them apart: the runner id is deliberately
    stable per machine so a restart does not leave a graveyard of dead runners,
    which means every process here registers as the SAME runner.

    An OS lock rather than a pid file, because it is released when the process
    dies HOWEVER it dies - Ctrl+C, a crash, a closed window, a sleeping laptop.
    The pid written alongside is only for the message; the lock decides, so that
    text may be stale without anything behaving incorrectly."""
    lock_path = Path(engine_root) / "output" / ".runner.lock"
    handle = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        handle = os.fdopen(fd, "r+b")

        # READ BEFORE LOCKING, on a descriptor of its own. Whether anybody holds
        # the lock is _take_lock's question; this only asks what the file says.
        previous = _read_identity(lock_path)

        if not _take_lock(handle):
            handle.close()
            _refuse(previous or "another process (it holds the lock file)")

        identity = (f"pid {os.getpid()} on {platform.node()} since "
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
        handle.seek(0)
        handle.write(identity.encode("utf-8")[:_IDENTITY_BYTES].ljust(_IDENTITY_BYTES, b" "))
        handle.flush()
        return handle

    except SystemExit:
        raise                                   # a real refusal: let it through
    except Exception as exc:                    # noqa: BLE001 - fail OPEN, always
        print(f"[lock] could not take the single-runner lock ({exc.__class__.__name__}: "
              f"{exc}). Carrying on - check for other runners by hand if estimates "
              f"behave oddly.")
        try:
            if handle is not None:
                handle.close()
        except Exception:                       # noqa: BLE001
            pass
        return None


def _take_lock(handle) -> bool:
    """True if this process now holds the lock, False if somebody else does.

    TWO QUESTIONS, KEPT APART. "Which locking API does this platform have" and
    "did the lock succeed" are different, and answering them in one try/except
    got it wrong: fcntl.flock was called INSIDE the except ImportError handler,
    so the BlockingIOError it raises when another process holds the lock was not
    caught by the sibling except OSError. The refusal became a fail-open, and the
    guard silently stopped guarding — visible only because the check that proves
    it printed STARTED ANYWAY."""
    handle.seek(_LOCK_BYTE)
    try:
        import msvcrt                                       # Windows
    except ImportError:
        import fcntl                                        # everywhere else
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _refuse(who: str):
    raise SystemExit(
        f"\nA runner is already running on this machine ({who}).\n"
        f"  One runner per machine: SOLIDWORKS and Excel are driven on one\n"
        f"  desktop, and a second runner here would fight the first for them.\n"
        f"  Close that window, or find strays with:\n"
        f"      Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |\n"
        f"        Where-Object CommandLine -like '*sdi_estimate_runner*' |\n"
        f"        Select-Object ProcessId, CommandLine\n"
        f"  If nothing is listed, delete the stale lock and start again:\n"
        f"      Remove-Item C:\\ClaudeVision\\output\\.runner.lock\n")


# ── a death that leaves evidence ─────────────────────────────────────────────
class _Tee:
    """Console AND a file, because a console is not a record.

    "IT JUST SEEMS TO RANDOMLY DIE" IS WHAT NO LOG LOOKS LIKE. Every time this runner has
    gone, the only account of why went with the window: whatever it printed on the way out
    scrolled past, or the window closed, and the next question could only be answered by
    guessing. Nothing here makes the runner more reliable — it makes the NEXT failure
    answerable, which is the prerequisite for making it reliable.

    Never lets logging break the thing being logged. A full disk or a locked file costs the
    log, not the run.
    """

    # THERE MAY BE NO CONSOLE, AND THAT IS NORMAL.
    #
    # Under pythonw.exe -- which is what a windowless Scheduled Task runs, and what the
    # installer PREFERS -- sys.stdout and sys.stderr are None. `self._stream.write(text)`
    # then raises AttributeError on the very first line this runner prints, before it has
    # polled once. The task starts, the process dies in milliseconds, Windows restarts it
    # three times, and the page says "no runner connected" with nothing anywhere saying why.
    #
    # So the log file existed to make a death answerable, and the absence of a console was
    # what killed it. A record that depends on a window is the thing this class was written
    # to stop needing.

    def __init__(self, stream, path: Path):
        self._stream = stream
        self._file = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8", errors="replace")
        except OSError:
            pass

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError, AttributeError):
                # A console that has gone away mid-run costs the console, not the run.
                self._stream = None
        if self._file is not None:
            try:
                self._file.write(text)
                self._file.flush()          # a buffered crash log is no log at all
            except (OSError, ValueError):
                self._file = None
        return len(text)

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
        # NO FILE FLUSH HERE, AND THAT IS DELIBERATE. One was added on the reasoning that
        # flush() pushed the console and left the log buffered -- and no mutant could kill
        # it, because write() above already flushes the file after every line. The reasoning
        # was simply wrong: a buffered crash log has never been possible on this path. A line
        # that cannot be distinguished from its absence is not belt and braces, it is a claim
        # that something is being handled here when it is handled a dozen lines up.

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


def start_logging(engine_root: Path) -> Optional[Path]:
    """Send everything this runner says to output/logs/runner-YYYY-MM-DD.log as well.

    Works with no console at all -- see _Tee. A windowless start is the normal way this runs
    unattended, and it must not be the one way it cannot report a failure.
    """
    path = Path(engine_root) / "output" / "logs" / f"runner-{time.strftime('%Y-%m-%d')}.log"
    sys.stdout = _Tee(sys.stdout, path)
    sys.stderr = _Tee(sys.stderr, path)
    print(f"\n{'=' * 70}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] runner starting "
          f"(pid {os.getpid()})\n{'=' * 70}", flush=True)
    return path


# How many unexpected errors in a row before this gives up and lets whatever started it
# start it again. Not one -- a single blip must not end the day's runner. Not never either:
# a process that loops on the same exception for ever looks alive to the service and does
# no work, which is the worst of both.
_GIVE_UP_AFTER = 5


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

    engine_root = Path(a.engine_root)
    # BEFORE ANYTHING CAN PRINT. The missing-requests message below went to sys.stderr, which
    # under a windowless start is None -- so the one line explaining why the runner would not
    # start was itself the thing that killed it, and the page just said "no runner connected".
    log_path = start_logging(engine_root)

    try:
        import requests
    except ImportError:
        print("This runner needs 'requests'.  pip install requests", file=sys.stderr)
        return 2
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
    print(f"  polling every {a.poll_seconds:g}s — Ctrl+C to stop")
    print(f"  log      {log_path}\n")

    complained = None
    consecutive = 0
    while True:
      # AN UNEXPECTED ERROR MUST NOT END THE DAY'S RUNNER SILENTLY.
      #
      # Everything below handles the failures somebody thought of -- unreachable, 404, 401,
      # a reply that will not parse. Anything else fell out of main() and the process
      # stopped, with the reason going to a console that was about to be closed. That is
      # what "it randomly dies" is made of: not randomness, an unhandled exception and no
      # record of it.
      #
      # So: log it with the traceback, keep polling, and give up after a handful in a row.
      # Giving up is deliberate — a process looping on the same exception for ever looks
      # alive to the service and does no work, which is worse than being restarted.
      try:
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
            consecutive = 0
            time.sleep(a.poll_seconds)
            continue

        _execute(requests, base, headers, job, engine_root, engine_python, runner_id)
        consecutive = 0
      except KeyboardInterrupt:
        print("\nstopped.")
        return 0
      except Exception:                              # noqa: BLE001 — the whole point
        import traceback
        consecutive += 1
        print(f"\n[{time.strftime('%H:%M:%S')}] UNEXPECTED ERROR in the polling loop "
              f"({consecutive} in a row):", file=sys.stderr)
        traceback.print_exc()
        if consecutive >= _GIVE_UP_AFTER:
            print(f"\n{_GIVE_UP_AFTER} unexpected errors in a row — stopping so whatever "
                  f"started this runner can start it again cleanly. The traceback above is "
                  f"also in {log_path}.", file=sys.stderr)
            return 3
        time.sleep(a.poll_seconds)


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
    # WHEN THE ENGINE LAST SPOKE. The beat used to infer this from `pending` being
    # non-empty, and flush() drains pending on the very next line -- so the beat almost
    # never saw anything there and measured silence from the START OF THE RUN. 11650
    # reported "no output for 645s" with engine output ten seconds above it. A console that
    # is wrong about how long it has been quiet is no better than one that says nothing.
    last_said = time.time()
    _post_lock = threading.Lock()

    def say(text: str) -> None:
        nonlocal last_said
        text = text.rstrip("\n")
        log.append(text)
        pending.append(text)
        last_said = time.time()
        print(text)

    def flush(force: bool = False) -> None:
        nonlocal last_sent, pending
        # Batched, because a chatty engine would otherwise be one HTTP request per
        # console line.
        if not force and not pending and (time.time() - last_sent) < 20:
            return
        if not force and not pending:
            return
        with _post_lock:
            batch, pending = pending, []
            try:
                requests.post(f"{base}/runner/{run_id}/progress",
                              json={"runner_id": runner_id, "lines": batch},
                              headers=headers, timeout=20)
                last_sent = time.time()
            except Exception:                          # noqa: BLE001
                pending = batch + pending              # keep it for the next try

    def beat() -> None:
        """Renew the lease while the ENGINE PROCESS is alive, said or unsaid.

        WORKING IS NOT THE SAME AS TALKING, AND THIS COST TWO RUNS OF 11650.

        The heartbeat used to ride on the progress posts, so the lease was renewed by the
        act of printing. The reasoning was sound as far as it went -- a separate timer could
        outlive a wedged run and keep it looking alive -- but it made a silent phase
        indistinguishable from a dead machine. The engine goes quiet for minutes at a time
        driving Excel and SOLIDWORKS over COM, which is the most expensive part of the run
        and prints nothing at all. At 180 seconds of silence the service declared the runner
        dead, discarded a run that was working perfectly, and told the operator to check
        whether the machine had gone to sleep. Twice, at 180s and 181s.

        The original worry is answered without a timer that can outlive anything: this beats
        only while proc.poll() is None. When the engine dies the beat stops with it, so a
        crashed run still times out on schedule. What it cannot distinguish is a slow phase
        from a wedged one -- so it does not try to. It SAYS how long the silence has run,
        every couple of minutes, and lets the person reading the page judge. Killing a
        healthy three-minute estimate is the worse error of the two, and the quiet one is
        the one nobody could see.
        """
        said_at = 0.0
        spoke_at = last_said
        while proc.poll() is None:
            time.sleep(_BEAT_SECONDS)
            if proc.poll() is not None:
                break
            if last_said != spoke_at:                  # the engine spoke since the last beat
                spoke_at = last_said
                said_at = 0.0
                continue
            quiet = time.time() - last_said
            if quiet >= _SAY_QUIET_AFTER and (time.time() - said_at) >= _SAY_QUIET_AFTER:
                said_at = time.time()
                say(f"Still running — no output for {int(quiet)}s. The engine is driving "
                    f"Excel/SOLIDWORKS, which prints nothing; the process is alive.")
            flush(force=True)

    print(f"\n--- {job['drawing_number']} · {job['client']} · {job['units']} off")
    say(f"Runner picked up the job on {os.environ.get('COMPUTERNAME', 'this machine')}.")

    # WHAT HAS TO BE READABLE DEPENDS ON WHICH QUESTION WAS ASKED. For a pooled pack it is
    # the folder; for one drawing of an enquiry it is that drawing. Checking the folder in
    # both cases passed a run whose PDF had been moved or renamed, and the engine then
    # reported "no drawing files found" as an ordinary exit -- a failure phrased as an
    # absence, three layers away from the fact that the file simply is not there.
    pdf = Path(job["pdf_path"]) if job.get("pdf_path") else None
    if pdf is not None and not pdf.is_file():
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The drawing is not readable from this runner: {pdf}", log)
        return
    if pdf is None and not folder.is_dir():
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The job folder is not readable from this runner: {folder}", log)
        return

    before = snapshot(engine_root)
    cmd = engine_command(engine_root, engine_python, folder, int(job["units"]),
                         job["client"], pdf=pdf)
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
    threading.Thread(target=beat, name="lease-heartbeat", daemon=True).start()
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


# WHERE THE ENGINE PUTS ITS ANSWER. Tried in order; the first that holds a number wins.
# More than one name because the summary has grown over time and a runner that knows only
# the newest key reports nothing at all on an older record -- and reporting nothing here
# looks exactly like an estimate that produced no price.
_UNIT_COST_KEYS = (
    ("workbook_equivalent_pricing", "m105_total_unit_cost_gbp"),
    ("headline_cost_price", "workbook_equivalent_total_unit_cost_gbp"),
    ("headline_cost_price", "total_unit_cost_gbp"),
    ("totals", "unit_cost_gbp"),
)


def unit_cost_from(summary: Dict[str, Any]) -> Optional[float]:
    """The engine's unit cost, out of the summary it just wrote.

    READ HERE BECAUSE THE RUNNER IS THE MACHINE THAT HAS THE FILE. The service has never
    read an estimate and is not about to start; it only needs the one number so the page can
    put the engine's answer beside the LLM's. Without it, a hundred-drawing enquiry shows a
    column of AI figures and nothing to check them against, which is the opposite of the
    point of running two methods.
    """
    if not isinstance(summary, dict):
        return None
    for outer, inner in _UNIT_COST_KEYS:
        node = summary.get(outer)
        if isinstance(node, dict):
            try:
                value = float(node.get(inner))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return round(value, 2)
    return None


def _unit_cost_from_deliverables(deliverables: List[Dict[str, str]]) -> Optional[float]:
    """The summary among what was just filed. A miss is silent on purpose -- a run that
    produced no readable JSON is already reported by collect(), and saying it twice in
    different words helps nobody."""
    import json as _json
    for item in deliverables or []:
        name = str(item.get("name") or "")
        if not name.lower().endswith(".json"):
            continue
        try:
            with open(item["path"], "r", encoding="utf-8") as fh:
                found = unit_cost_from(_json.load(fh))
        except Exception:                                # noqa: BLE001
            continue
        if found is not None:
            return found
    return None


def _finish(requests, base: str, headers: Dict[str, str], run_id: str, runner_id: str,
            status: str, error: str, log: List[str],
            deliverables: Optional[List[Dict[str, str]]] = None) -> None:
    if error:
        log.append(error)
        print(error)
    body = {"runner_id": runner_id, "status": status, "error": error,
            "lines": [], "deliverables": deliverables or [],
            "unit_cost_gbp": _unit_cost_from_deliverables(deliverables or [])}
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
