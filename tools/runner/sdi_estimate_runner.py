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
import json
import os
import platform
import re
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
from typing import Any, Dict, List, Optional, Tuple

# ── things a test can reach without the network ──────────────────────────────
# requests is imported lazily inside the polling loop so that everything which
# DECIDES something — what counts as a deliverable, what this run produced — can
# be imported and tested on a machine that has neither requests nor a server.

DELIVERABLE_SUFFIXES = (".xlsx", ".html", ".json", ".log", ".csv", ".txt", ".md",
                        ".sql", ".xlsm",
                        ".wav")         # the spoken walkthrough (D-609)

# THE WORKBOOK TEMPLATE, RESOLVED THE SAME WAY THE ENGINE RESOLVES IT.
#
# Must stay identical to wb_populate.template_path(): SDI_WB_TEMPLATE wins, otherwise the copy
# on the share. A test pins this default against wb_populate's CELL_MAP, because a runner that
# checks for a different file than the engine opens is worse than no check at all — it would
# pass a run the engine then fails on, which is the exact shape of the bug it exists to prevent.
#
# The double space in the filename is real, not a typo.
WB_TEMPLATE_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                       r"\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx")


def workbook_template() -> str:
    return (os.environ.get("SDI_WB_TEMPLATE") or "").strip().strip('"') or WB_TEMPLATE_DEFAULT

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
# How often the engine's console reaches the service (D-598w): at most one post every this many
# seconds, or sooner once this many lines are waiting. Was one post per line.
_POST_EVERY_SECONDS = float(os.getenv("SDI_RUNNER_POST_SECONDS", "2"))
_POST_MAX_LINES = 500
# HOW SOON A STOP IS HEARD AND ACTED ON (D-649). A stop reaches this process only as the
# answer to a post. The engine is often silent for minutes, so the only post was the 30s
# beat, and the stop it heard was acted on at the NEXT beat: up to a minute before the
# engine was even told, then up to 30s more while it unwound Excel and SOLIDWORKS
# (3 Nov 2026: "why does stop this job take so long to shut down"). Now the runner asks
# every few seconds while the engine is quiet, and ends the engine the moment it hears.
_LISTEN_SECONDS = float(os.getenv("SDI_RUNNER_LISTEN_SECONDS", "5"))

# The engine's output tree. Deliverables land in estimates/ (workbook AND the HTML
# quote/report, which share a folder); the auditable summary lands in json/.
#
# AND IN FOUR FOLDERS, NOT TWO. The engine also writes output\text (the write-up), output\logs
# (the run log) and output\csv (part_estimate_inputs) — it prints all four paths under "Output
# files:" on every run — and this watched neither, so they were never filed. 0359342 filed two
# JSONs out of nine artefacts and the estimator's folder held no log to read and no write-up.
# James's rule is the plain one and it is right: the spreadsheet, the reports and the logs all
# belong in the estimate output folder, every run.
WATCHED_DIRS = ("estimates", "json", "text", "logs", "csv")


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


def declared_outputs(engine_root: Path, drawing_number: str = "",
                     started_at: float = 0.0) -> Tuple[List[Path], List[str]]:
    """The files the ENGINE SAYS it wrote, read from its own summary JSON.

    A DECLARATION BEATS AN INFERENCE, AND THE SNAPSHOT DIFF IS AN INFERENCE. collect() decided
    what this run produced by comparing the output tree before and after, which is sound
    reasoning and fragile in practice: it depends on the `before` snapshot having been taken
    against the same tree, on mtimes moving, and on one execution per tree. 0359342 reported
    "NO WORKBOOK" and filed two files while its own console said
    "Populated template saved: 0359342_20260910_123656.xlsx" — a workbook that existed, on
    disk, in a watched folder, and was not copied.

    The engine already publishes `saved_output_paths` into its summary JSON (json, text, log,
    csv, sql, the workbook, quote, report and covering note as each is written). Reading that
    turns "what appeared" into "what the engine says it made", and the two together cannot
    both miss the same file. Anything named but absent is returned by neither and reported by
    the caller — a declared file that is not on disk is a finding, not a silence.
    """
    out: List[Path] = []
    missing: List[str] = []
    seen: set = set()
    folder = Path(engine_root) / "output" / "json"
    if not folder.is_dir():
        return out, missing
    stem = (drawing_number or "").replace("/", "-").replace("\\", "-").strip()
    candidates: List[Path] = []
    if stem:
        # THIS JOB'S SUMMARY OR NONE. An earlier cut fell back to the NEWEST json in the folder
        # when the named one was absent, which is the worst possible default on a shared output
        # tree: a failed run would file the previous job's workbook as its own result. A missing
        # summary for the job we were asked to run is a finding, not a cue to substitute.
        exact = folder / f"{stem}.json"
        if exact.is_file():
            candidates.append(exact)
        else:
            missing.append(f"{exact} (no summary for this job was found — the engine records\n                            no generation outcome, so absence is all that is known)")
    else:
        try:                                  # no job name given: newest is the only honest pick
            candidates = sorted((f for f in folder.iterdir() if f.suffix.lower() == ".json"),
                                key=lambda f: f.stat().st_mtime, reverse=True)[:1]
        except OSError:
            return out, missing
    # AND IT MUST BELONG TO THIS EXECUTION. A summary written before this run started cannot be
    # this run's, however well it is named — so a failed rerun cannot file yesterday's estimate
    # and have it read as today's.
    if started_at:
        _fresh_candidates = []
        for doc_path in candidates:
            try:
                if doc_path.stat().st_mtime + 1.0 >= started_at:
                    _fresh_candidates.append(doc_path)
                else:
                    missing.append(f"{doc_path} (left over from an earlier run, not this one)")
            except OSError:
                continue
        candidates = _fresh_candidates
    for doc_path in candidates:
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        for holder in (doc, doc.get("estimate_summary") or {}):
            if not isinstance(holder, dict):
                continue
            for value in (holder.get("saved_output_paths") or {}).values():
                for one in (value if isinstance(value, list) else [value]):
                    if not one or not isinstance(one, str):
                        continue
                    item = Path(one)
                    key = str(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    if not item.is_file():
                        # DECLARED AND ABSENT IS THE INTERESTING CASE. The engine said it wrote
                        # this; the disk disagrees. Reported, never dropped — that is the whole
                        # point of reading a manifest rather than a directory listing.
                        missing.append(f"{item} (declared by the engine, not on disk)")
                        continue
                    if started_at:
                        try:
                            if item.stat().st_mtime + 1.0 < started_at:
                                missing.append(f"{item} (declared, but older than this run)")
                                continue
                        except OSError:
                            pass
                    out.append(item)
    return out, missing


def collect(engine_root: Path, dest: Path, before: Dict[str, float],
            log: List[str], drawing_number: str = "",
            started_at: float = 0.0) -> List[Dict[str, str]]:
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
    # NEW OR CHANGED, AND NOT BEFORE THIS RUN BEGAN. The `before` snapshot already excludes
    # untouched files; started_at also excludes anything whose mtime predates the launch, which
    # is what makes a stale tree safe to collect from.
    fresh = []
    for p, mtime in sorted(after.items()):
        if before.get(p) is not None and mtime <= before[p]:
            continue
        if started_at and mtime + 1.0 < started_at:
            continue
        fresh.append(Path(p))

    # WHAT APPEARED, PLUS WHAT THE ENGINE SAYS IT MADE. Either alone has missed a workbook
    # that was on disk the whole time; together they cannot both miss the same file.
    _declared, _absent = declared_outputs(engine_root, drawing_number, started_at)
    _seen: set = set()
    _wanted: List[Path] = []
    for item in list(fresh) + _declared:
        key = str(item).lower()
        if key not in _seen:
            _seen.add(key)
            _wanted.append(item)

    _skipped_suffix = 0
    _copy_failures: List[str] = []
    for item in _wanted:
        if item.suffix.lower() not in DELIVERABLE_SUFFIXES:
            _skipped_suffix += 1
            continue
        try:
            shutil.copy2(item, dest / item.name)
            filed.append({"name": item.name, "path": str(dest / item.name)})
        except OSError as exc:
            _copy_failures.append(item.name)
            log.append(f"[collect] could not copy {item.name} — {exc}")

    # SAY WHAT WAS LOOKED AT, NOT ONLY WHAT WAS TAKEN. When a file an estimator expects does
    # not arrive, the next question is always "did it look in the right place" — and until now
    # the log could not answer it. Each watched folder, its file count, and how the two
    # discovery routes contributed, so a miss is diagnosable from the run log alone.
    _counts = ", ".join(
        f"{name}={sum(1 for k in after if str(Path(k).parent).lower().endswith(name))}"
        for name in WATCHED_DIRS)
    log.append(f"[collect] looked in {Path(engine_root) / 'output'} ({_counts}); "
               f"{len(fresh)} new/changed, {len(_declared)} declared by the engine, "
               f"{len(_wanted)} distinct, {_skipped_suffix} skipped on suffix")
    # THREE OUTCOMES, NAMED APART. "It did not arrive" is not one fault: the engine may never
    # have written it, it may have written it and something removed it, or the copy itself may
    # have failed. Each has a different answer and they were indistinguishable in the log.
    for _m in _absent:
        log.append(f"[collect] DECLARED BUT NOT FILED — {_m}")
    log.append(f"[collect] {len(filed)} file(s) written to {dest}")
    if not filed:
        # NOTHING ARRIVED IS NOT ONE FAULT. This blamed the engine unconditionally — "exited
        # cleanly but wrote nothing new" — which is only one of three ways an empty folder
        # happens, and the least likely when a copy has just failed or a stale tree has just
        # been excluded. Each has a different answer, so each says its own thing.
        if _copy_failures:
            log.append("[collect] NOTHING was copied, and it was NOT the engine: "
                       + ", ".join(_copy_failures[:6]) + " exist on the runner and could not "
                       "be copied to the share. Check the destination is reachable and "
                       "writable — the estimate itself was produced.")
        elif _absent:
            log.append("[collect] NOTHING was copied. Every artefact this run should have "
                       "produced is accounted for above as declared-but-not-filed or left "
                       "over from an earlier run — so this run produced no new outputs of "
                       "its own, whatever is sitting in the output folder.")
        else:
            log.append("[collect] NOTHING was copied. The engine exited cleanly but wrote "
                       "nothing new into the watched output folders — check the log "
                       "above for what it did instead.")
    elif not any(f["name"].lower().endswith(".xlsx") for f in filed):
        # FILES ARE NOT AN ESTIMATE. The zero-file case was covered; this one was not, and it
        # is the one that actually happened: 10575-02 ran for sixteen minutes, exited 0, filed
        # its summary JSON and the console log, and was reported DONE with no workbook — so the
        # page said the estimate was ready and the folder held nothing an estimator opens.
        #
        # A summary with no workbook means the deliverables pass did not produce one. That is a
        # failed run whatever the exit code said, and it is named here rather than left for
        # somebody to notice by opening the folder.
        log.append("[collect] NO WORKBOOK. " + ", ".join(f["name"] for f in filed)
                   + " were filed, but no .xlsx — the engine wrote a summary and no estimate. "
                     "The deliverables pass did not produce one; the console log above says "
                     "what it did instead.")

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
                   units: int, client: str, pdf: Optional[Path] = None,
                   quantity_breaks: Optional[List[int]] = None,
                   manual_workbook: Optional[Path] = None,
                   llm_only: bool = False, fresh_read: bool = False,
                   product: str = "", deterministic_only: bool = False,
                   reader_mode: str = "", bom_routes_out: Optional[Path] = None) -> List[str]:
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
    ] + (["--pdf", str(pdf)] if pdf else ["--job", str(job)]) + (
        # THE PRODUCT. The portal's Drawing Number is the one assembly that ships; every
        # other GA in the folder counts only where the product reaches it.
        ["--product", str(product).strip()] if str(product or "").strip() else []
    ) + [
        "--order-qty", str(units),
    ] + (
        # THE OTHER QUANTITIES THE ESTIMATOR ASKED FOR. The estimate runs at the FIRST one
        # and the rest are recalculated from it — the estimator's own method, and the only
        # affordable one: a re-run per quantity is five hours for arithmetic Excel does in a
        # second, against readings that cannot change with the order size.
        ["--quantity-breaks", *[str(int(q)) for q in quantity_breaks]]
        if quantity_breaks else []
    ) + [
        "--deliverables",
        "--customer", client,
    ] + (
        # THE PARITY PARTNER, WHEN THE ESTIMATOR ATTACHED ONE. main.py builds the bundle as part
        # of the deliverables pass, so the comparison lands beside the estimate instead of being
        # a separate job somebody has to remember to run. Absent, nothing changes.
        ["--parity-workbook", str(manual_workbook)] if manual_workbook else []
    ) + (
        # THE MEASUREMENT RUN. Reads the pack with the vision model alone: the deterministic
        # BOM reader, the DXF flat patterns and the SolidWorks extract all off. It still needs
        # a runner -- it produces a workbook and a full set of deliverables like any other run
        # -- it simply reads with one source instead of four, and main.py says so on every
        # line of output it produces.
        ["--llm-only"] if llm_only else []
    ) + (
        # ASK THE MODEL AGAIN. Both LLM caches bypassed for this run only. Not a default and
        # not a tidy-up: the caches are what make two runs of one pack agree, and 2085 halved
        # its own unit cost between identical runs before they existed.
        ["--fresh-read"] if fresh_read else []
    ) + (
        # THE DRAWING READER ON ITS OWN (D-753). No language model reads the drawings and no
        # cached answer from one is replayed: the SCRUM-194 test, never an estimate to quote.
        ["--deterministic-only"] if deterministic_only else []
    ) + (
        # ONE READER MODE PER RUN, CHOSEN ON THE PAGE (run modes): never from this machine's .env.
        [READER_MODE_FLAG[reader_mode]] if reader_mode in READER_MODE_FLAG else []
    ) + (
        # A PRE-RUN: the BOMs and Routes, then stop before the workbook.
        ["--bom-routes-only", "--bom-routes-out", str(bom_routes_out)] if bom_routes_out else []
    )


READER_MODE_FLAG = {"targeted": "--targeted", "solidworks": "--solidworks-only",
                    "docmgr": "--docmgr-only"}


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
        # pythonw.exe, NOT JUST python.exe. The portal starts its own runner on
        # startup and starts it windowless, so the runner this message is about is
        # almost always a pythonw. Naming only python.exe sent the reader looking
        # for a process that was there all along under the other name, and made a
        # correct refusal look like a stale lock — which is the one wrong
        # conclusion this message must never invite, because acting on it means
        # deleting a lock a live runner is holding.
        f"      Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR "
        f"Name='pythonw.exe'\" |\n"
        f"        Where-Object CommandLine -like '*sdi_estimate_runner*' |\n"
        f"        Select-Object ProcessId, CreationDate, CommandLine\n"
        f"  Note the portal starts a runner of its own when it starts, so restarting\n"
        f"  the portal is usually why this one is refused.\n"
        f"  ONLY if nothing at all is listed, delete the stale lock and start again:\n"
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
            # A BYTE-ORDER MARK ON A NEW LOG, BECAUSE THE READER IS Get-Content.
            #
            # Windows PowerShell 5.1 reads a file as ANSI unless a BOM says otherwise, so a
            # UTF-8 log came back as "polling every 5s a??" Ctrl+C to stop". The runner prints
            # em-dashes, GBP signs and part descriptions off drawings; mojibake in the one
            # record of a failure is a record somebody has to decode before they can read it.
            #
            # Written only when the file is new. utf-8-sig in append mode emits a BOM on every
            # open, which would drop one into the middle of the log at each restart.
            _new = not path.exists() or path.stat().st_size == 0
            self._file = open(path, "a", encoding="utf-8", errors="replace")
            if _new:
                self._file.write("﻿")
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
                    help="Base URL of the SDI Intelligence service. Several, comma-separated, "
                         "and this one runner serves them all.")
    ap.add_argument("--engine-root", default=os.getenv("SDI_ENGINE_ROOT", r"C:\ClaudeVision"))
    ap.add_argument("--engine-python", default=os.getenv("SDI_ENGINE_PYTHON", ""))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    ap.add_argument("--runner-id", default=os.getenv("SDI_RUNNER_ID", ""))
    # A SLOT IS ONE MORE RUNNER ON THIS DESKTOP (D-731), in its own checkout of the same build
    # (tools\start\install-runner-slot.ps1). Slot 1 is the machine's original runner.
    ap.add_argument("--slot", type=int, default=int(os.getenv("SDI_RUNNER_SLOT", "1") or 1))
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
    if a.slot and a.slot > 1 and not a.runner_id:
        runner_id = f"{runner_id}-s{a.slot}"

    # WHICH PROCESS, AND WHICH BUILD. Both are answers this runner could never give.
    #
    # Two runners ran on SDI-DESKTOP for three days — 3668 on the venv interpreter and
    # 14796 on the user's own Python 3.10, same script, same engine root, same server —
    # and NOTHING could see it. runner_id is deliberately stable per machine so a restart
    # does not leave a graveyard of dead runners, so both processes register as the SAME
    # runner and the page shows one green tick. The single-runner lock is what was supposed
    # to make that safe, and it fails OPEN by design: when it cannot take the lock it says
    # so and carries on, which is right (a lock bug must not stop estimating) and leaves
    # the guard silently not guarding.
    #
    # So the runner now says which PROCESS it is, and the service reports when two answer
    # to one id rather than showing a confident green tick. It is the same question the
    # page already answers for the service with X-SDI-Commit — which build am I looking at
    # — asked for the half of the system that does the work.
    _process = f"pid {os.getpid()} {platform.node()} since {time.strftime('%Y-%m-%d %H:%M:%S')}"
    _build = ""
    try:
        sys.path.insert(0, str(engine_root / "src"))
        from build_stamp import build_stamp_line           # noqa: PLC0415
        _build = build_stamp_line()
    except Exception as exc:                               # noqa: BLE001
        # NEVER FATAL. A runner that will not start because it cannot name its own build is
        # worse than one that cannot name it — say so and carry on.
        _build = f"unknown ({exc.__class__.__name__})"
    # ONE RUNNER, EVERY SERVICE ON THE LIST.
    #
    # James Gray, 23 Sep 2026: "this runner going down all the time is completely
    # unacceptable." It had not gone down. On 22 and 23 September it was up, healthy and on
    # the right build, and REGISTERED WITH THE OTHER SERVICE: the installed one on 8071 and a
    # hand-started one on 8072 each keep their own queue and their own list of runners, and a
    # runner polled exactly one of them. Whichever page somebody had open said "No runner
    # connected". Five fixes to which port it should pick each moved the failure rather than
    # removing it, because the fault was the choice itself.
    #
    # So there is no choice. --server takes a list, the runner asks every service on it for
    # work in turn, and each one sees it as connected. One job still runs at a time — the
    # single-runner lock and the one-SOLIDWORKS rule are about EXECUTION, and nothing here
    # changes that — and while it runs, the other services get a heartbeat that cannot hand
    # it a second job.
    servers = [s.strip().rstrip("/") for s in str(a.server or "").split(",") if s.strip()]
    headers = {"X-SDI-Key": a.api_key} if a.api_key else {}

    print(f"SDI estimating runner")
    for _s in servers:
        print(f"  server   {_s}")
    print(f"  engine   {engine_root}")
    print(f"  python   {engine_python}{'' if engine_python.is_file() else '   (NOT FOUND — will fall back to python on PATH)'}")
    print(f"  runner   {runner_id}  ({platform.node()})")
    print(f"  process  {_process}")
    print(f"  build    {_build}")
    print(f"  polling every {a.poll_seconds:g}s — Ctrl+C to stop")
    print(f"  log      {log_path}")
    start_compute_sampler()
    _by = (compute_now() or {}).get("by")
    print(f"  compute  measured every {_COMPUTE_EVERY:g}s for the wall: "
          + ("the machine, SolidWorks, Excel and each job" if _by == "psutil"
             else "the machine's totals only (install psutil for each job's own use)") + "\n")

    complained: Dict[str, Optional[str]] = {}
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
        worked = False
        # A SECOND OR THIRD RUN ON THIS DESKTOP (D-731) is claimed only while the machine has
        # the room for it. Slot 1, the machine's own runner, is never held back.
        _ok, _measured = slot_may_claim(a.slot)
        note_gate(a.slot, _ok, _measured)
        if not _ok:
            report_gate(requests, servers, headers, runner_id, _process, _build)
            complained["__compute__"] = _say_once(
                complained.get("__compute__"), "compute",
                f"slot {a.slot}: not the room for one more run on this desktop: {_measured}",
                "   waiting for memory or CPU to free up.")
            time.sleep(a.poll_seconds)
            continue
        complained["__compute__"] = None
        for server in servers:
            job, complained[server] = _ask_for_work(
                requests, server, headers, runner_id, _process, _build,
                complained.get(server))
            if not job:
                continue
            base = server + "/api/estimate"
            others = [o for o in servers if o != server]
            with _heartbeat_while_busy(requests, others, headers, runner_id, _process,
                                       _build):
                _execute(requests, base, headers, job, engine_root, engine_python,
                         runner_id, claimed_from={"service": server,
                                              "commit": _SERVICE_COMMIT.get(server, "")})
            worked = True
            consecutive = 0
            break           # back to the top of the list: no service waits behind another
        if not worked:
            consecutive = 0
            time.sleep(a.poll_seconds)
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


# The commit each service reported on its last claim reply (D-607).
_SERVICE_COMMIT: Dict[str, str] = {}


# THE JOB TYPES THIS RUNNER EXECUTES BESIDES A FULL ESTIMATE (D-640), told to the service on
# every claim. "sw_extract": the SolidWorks analyser on the pack, organised; "xai_extract": the
# whole-document xAI read on the pack's PDFs, exactly as returned and laid out as tables.
# "dm_extract" (D-737) is added by runner_capabilities() only where the Document Manager key is.
RUNNER_CAPABILITIES = ("sw_extract", "xai_extract", "bom_routes")


# ── SEVERAL RUNS ON ONE DESKTOP (SCRUM-183 phase 2, D-731) ────────────────────────────
#
# JG, 6 Nov 2026: two estimating workers share one SolidWorks reader, waiting briefly for their
# turn, and the same job always gets the same model evidence whatever else is running. The turn
# is taken by the ENGINE around its model read (src/solidworks_turn.py), not by this runner
# around the whole run: a second run waits for one model read, never for a whole estimate, and
# reads its models exactly as it would alone. Nothing here changes how a run reads models.
#
# What a slot adds here is the compute gate: a second or third run is claimed only while the
# machine has the memory and CPU to carry it.


def compute_headroom(min_free_gb: Optional[float] = None,
                     max_cpu_pct: Optional[float] = None) -> Tuple[bool, str]:
    """(enough, what was measured). Enough when free memory and CPU leave room for one more
    run. Settings: SDI_SLOT_MIN_FREE_GB (default 3), SDI_SLOT_MAX_CPU_PCT (default 85). What
    cannot be measured is not held against the run."""
    def _num(name: str, default: float) -> float:
        try:
            return float(str(os.getenv(name, "")).strip() or default)
        except ValueError:
            return default
    min_free_gb = _num("SDI_SLOT_MIN_FREE_GB", 3.0) if min_free_gb is None else min_free_gb
    max_cpu_pct = _num("SDI_SLOT_MAX_CPU_PCT", 85.0) if max_cpu_pct is None else max_cpu_pct
    free_gb: Optional[float] = None
    cpu: Optional[float] = None
    try:
        import psutil                                              # noqa: PLC0415
        free_gb = psutil.virtual_memory().available / 1e9
        cpu = psutil.cpu_percent(interval=0.5)
    except Exception:                                              # noqa: BLE001
        try:
            import ctypes                                          # noqa: PLC0415

            class _MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _MEM()
            m.dwLength = ctypes.sizeof(_MEM)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):  # type: ignore
                free_gb = m.ullAvailPhys / 1e9
        except Exception:                                          # noqa: BLE001
            pass
    said = []
    ok = True
    if free_gb is not None:
        said.append(f"{free_gb:.1f} GB free (needs {min_free_gb:g})")
        ok = ok and free_gb >= min_free_gb
    if cpu is not None:
        said.append(f"CPU {cpu:.0f}% (limit {max_cpu_pct:g}%)")
        ok = ok and cpu <= max_cpu_pct
    return ok, ("; ".join(said) or "compute not measurable here, not held against the run")


# ── WHAT THIS MACHINE IS USING, FOR THE WALL (D-743) ─────────────────────────────────────
# JG, 7 Nov 2026: "a graphical representation of the compute resources available on the
# laptop ... what compute resource each job is taking and it updates dynamically and the
# remaining compute is also available." A thread measures every SDI_RUNNER_COMPUTE_SECONDS
# (5): the machine's CPU, memory and disk; SolidWorks and Excel, which Windows starts for the
# engine rather than the engine starting them; and this runner's own engine and its children.
# The newest reading rides on the calls the runner already makes (claim, heartbeat, console),
# so measuring never waits on the network and the network never waits on measuring. Where
# psutil is missing only the machine's totals can be read, and the reading says so.
_COMPUTE_EVERY = max(2.0, float(os.getenv("SDI_RUNNER_COMPUTE_SECONDS", "5") or 5))
_COMPUTE_APPS = {"SolidWorks": ("sldworks.exe", "sldworks"), "Excel": ("excel.exe", "excel")}
_JOB_PIDS: Dict[str, int] = {}                 # run id -> the engine process this runner started
_COMPUTE: Dict[str, Any] = {"sample": None, "procs": {}, "sys": None, "thread": None}
_GIB = float(1024 ** 3)


def _disk_root() -> str:
    try:
        return Path(__file__).resolve().anchor or os.sep
    except Exception:                                              # noqa: BLE001
        return os.sep


def _sample_with_psutil(psutil) -> Dict[str, Any]:
    threads = psutil.cpu_count(logical=True) or os.cpu_count() or 1
    vm = psutil.virtual_memory()
    out: Dict[str, Any] = {"by": "psutil", "cpu_pct": round(psutil.cpu_percent(interval=None), 1),
                           "threads": threads, "cores": psutil.cpu_count(logical=False),
                           "mem_total_gb": round(vm.total / _GIB, 2),
                           "mem_used_gb": round((vm.total - vm.available) / _GIB, 2),
                           "mem_free_gb": round(vm.available / _GIB, 2)}
    try:
        du = psutil.disk_usage(_disk_root())
        out.update(disk=_disk_root(), disk_free_gb=round(du.free / _GIB, 1),
                   disk_total_gb=round(du.total / _GIB, 1))
    except Exception:                                              # noqa: BLE001
        pass
    cache: Dict[int, Any] = _COMPUTE["procs"]
    seen: set = set()

    def use(p) -> Tuple[float, int]:
        """Share of the whole machine's CPU since the last reading, and resident memory. A
        process seen for the first time reads 0 CPU: there is nothing yet to compare with."""
        try:
            q = cache.get(p.pid)
            if q is None or q != p:
                cache[p.pid] = q = p
            seen.add(p.pid)
            return q.cpu_percent(None) / threads, q.memory_info().rss
        except Exception:                                          # noqa: BLE001
            return 0.0, 0
    app_names = {n for names in _COMPUTE_APPS.values() for n in names}
    apps: Dict[str, Dict[str, float]] = {}
    for p in psutil.process_iter(["name"]):
        name = str((p.info or {}).get("name") or "").lower()
        for label, names in _COMPUTE_APPS.items():
            if name in names:
                c, m = use(p)
                a = apps.setdefault(label, {"cpu_pct": 0.0, "mem_gb": 0.0, "count": 0})
                a["cpu_pct"] += c
                a["mem_gb"] += m / _GIB
                a["count"] += 1
    jobs: Dict[str, Dict[str, float]] = {}
    for run_id, pid in list(_JOB_PIDS.items()):
        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
        except Exception:                                          # noqa: BLE001
            continue
        cpu, mem, n = 0.0, 0, 0
        for p in tree:
            try:
                if str(p.name() or "").lower() in app_names:      # counted as itself, above
                    continue
            except Exception:                                      # noqa: BLE001
                continue
            c, m = use(p)
            cpu, mem, n = cpu + c, mem + m, n + 1
        jobs[run_id] = {"cpu_pct": round(cpu, 1), "mem_gb": round(mem / _GIB, 2), "procs": n}
    for pid in [pid for pid in cache if pid not in seen]:
        cache.pop(pid, None)
    out["apps"] = {k: {"cpu_pct": round(v["cpu_pct"], 1), "mem_gb": round(v["mem_gb"], 2),
                       "count": v["count"]} for k, v in apps.items()}
    out["jobs"] = jobs
    return out


def _sample_windows_totals() -> Dict[str, Any]:
    """The machine's totals from Windows itself, where psutil is not installed."""
    import ctypes                                                  # noqa: PLC0415

    class _MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class _FT(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]
    out: Dict[str, Any] = {"by": "windows", "threads": os.cpu_count()}
    k32 = ctypes.windll.kernel32                                   # type: ignore[attr-defined]
    m = _MEM()
    m.dwLength = ctypes.sizeof(_MEM)
    if k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        out.update(mem_total_gb=round(m.ullTotalPhys / _GIB, 2),
                   mem_used_gb=round((m.ullTotalPhys - m.ullAvailPhys) / _GIB, 2),
                   mem_free_gb=round(m.ullAvailPhys / _GIB, 2))
    idle, kernel, user = _FT(), _FT(), _FT()
    if k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        now = tuple((t.hi << 32) | t.lo for t in (idle, kernel, user))
        before = _COMPUTE["sys"]
        _COMPUTE["sys"] = now
        if before:
            d_idle, d_kernel, d_user = (a - b for a, b in zip(now, before))
            busy_total = d_kernel + d_user                         # kernel time includes idle
            if busy_total > 0:
                out["cpu_pct"] = round(100.0 * (busy_total - d_idle) / busy_total, 1)
    du = shutil.disk_usage(_disk_root())
    out.update(disk=_disk_root(), disk_free_gb=round(du.free / _GIB, 1),
               disk_total_gb=round(du.total / _GIB, 1), apps={}, jobs={})
    return out


def sample_compute() -> Dict[str, Any]:
    """One reading of this machine. Never raises: a failure is reported as the reading."""
    try:
        try:
            import psutil                                          # noqa: PLC0415
        except ImportError:
            psutil = None
        if psutil is not None:
            out = _sample_with_psutil(psutil)
        elif os.name == "nt":
            out = _sample_windows_totals()
        else:
            du = shutil.disk_usage(_disk_root())
            out = {"by": "none", "threads": os.cpu_count(), "disk": _disk_root(),
                   "disk_free_gb": round(du.free / _GIB, 1),
                   "disk_total_gb": round(du.total / _GIB, 1), "apps": {}, "jobs": {}}
    except Exception as exc:                                       # noqa: BLE001
        out = {"by": "none", "error": f"{type(exc).__name__}: {exc}"[:200]}
    out.update(at=round(time.time(), 1), host=platform.node())
    return out


def start_compute_sampler() -> None:
    """Measure in the background from now on; once per process."""
    if _COMPUTE["thread"] is not None:
        return

    def loop() -> None:
        while True:
            _COMPUTE["sample"] = sample_compute()
            time.sleep(_COMPUTE_EVERY)
    _COMPUTE["sample"] = sample_compute()        # primes the CPU counters; the next is real
    _COMPUTE["thread"] = threading.Thread(target=loop, name="compute-sampler", daemon=True)
    _COMPUTE["thread"].start()


def compute_now() -> Optional[Dict[str, Any]]:
    """The newest reading, or None before the sampler has started."""
    return _COMPUTE["sample"]


def slot_may_claim(slot: int) -> Tuple[bool, str]:
    """(may claim, what was measured). Slot 1 always may; slot 2 or more only with the room."""
    if int(slot or 1) <= 1:
        return True, "slot 1, the machine's own runner"
    return compute_headroom()


# THE LAST COMPUTE CHECK, SENT WITH EVERY CLAIM AND BEAT (JG, 10 Nov 2026): "we also need to be
# able to see that it's at least tried to check for compute resources on the second grid
# runner". A slot held back by the check used to sleep and tell nobody, so Grid Control showed
# it offline with no reason. Now each check (when, what was measured, took work or held) goes
# to every service on the list, and a held slot still checks in.
_GATE: Dict[str, Any] = {}


def note_gate(slot: int, ok: bool, measured: str, at: Optional[float] = None) -> Dict[str, Any]:
    _GATE.clear()
    _GATE.update({"slot": int(slot or 1), "ok": bool(ok), "measured": str(measured)[:300],
                  "at": round(time.time() if at is None else at, 1)})
    return dict(_GATE)


def report_gate(requests, servers: List[str], headers: Dict[str, str], runner_id: str,
                process: str, build: str) -> None:
    """A held slot's check-in: /runner/heartbeat (never a claim), carrying the check."""
    for server in servers:
        try:
            requests.post(f"{server}/api/estimate/runner/heartbeat", json={
                "runner_id": runner_id, "hostname": platform.node(), "process": process,
                "build": build, "compute": compute_now(), "gate": dict(_GATE)},
                headers=headers, timeout=10)
        except Exception:                            # noqa: BLE001 — a beat, not a job
            pass


def excel_installed() -> Optional[bool]:
    """Is a desktop Excel registered on this machine? None where it cannot be told (not Windows)."""
    if os.name != "nt":
        return None
    try:
        import winreg                                              # noqa: PLC0415
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"))
        return True
    except OSError:
        return False
    except Exception:                                              # noqa: BLE001
        return None


def extract_only() -> Tuple[bool, str]:
    """(this runner takes pack extracts only, why). JG, 10 Nov 2026: the server has no Excel, and
    every estimate is written and recalculated in Excel, so a runner there would claim estimates
    it cannot finish. SDI_RUNNER_EXTRACT_ONLY=1 says so; a Windows machine with no Excel says so
    by itself; SDI_RUNNER_EXTRACT_ONLY=0 overrides the detection."""
    v = str(os.getenv("SDI_RUNNER_EXTRACT_ONLY", "")).strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True, "SDI_RUNNER_EXTRACT_ONLY=1"
    if v in {"0", "false", "no", "off"}:
        return False, ""
    if excel_installed() is False:
        return True, "no Excel on this machine"
    return False, ""


def runner_capabilities() -> List[str]:
    """What this runner tells the service on every claim. "no_models" (D-703, SCRUM-183): it
    will not drive SolidWorks (SDI_SW_RUN_ANALYSER=0) and has no Document Manager backup
    (SDI_SW_DOCMGR unset), so the service keeps packs that need a model reader for a runner
    that has one. A runner with either says nothing extra, as before.

    The backup counts only with its licence key (SDI_SW_DOCMGR_KEY) present: the switch alone
    reads nothing (SCRUM-184), and a runner that took a model job on the switch alone would
    price it from the drawings. "On" means what the engine's docmgr_switch_on() means."""
    # "desktop_token" (D-731): this runner's engine takes the desktop's one SolidWorks in turn,
    # so the service may give it a run while another runner on this desktop has one.
    caps = list(RUNNER_CAPABILITIES) + ["desktop_token"]
    _key = bool(str(os.getenv("SDI_SW_DOCMGR_KEY", "")).strip())
    # THE DOCUMENT MANAGER EXTRACT NEEDS THE KEY, NOT THE SWITCH (D-737). The button asks for
    # that reader by name, for the SCRUM-184 comparison, so it is offered wherever the key is;
    # SDI_SW_DOCMGR still governs only whether an ESTIMATE may fall back to it.
    if _key:
        caps.append("dm_extract")
    _off = str(os.getenv("SDI_SW_RUN_ANALYSER", "")).strip().lower() in {"0", "false", "no"}
    _dm = (str(os.getenv("SDI_SW_DOCMGR", "")).strip().lower() in {"1", "true", "yes", "on"}
           and _key)
    if _off and not _dm:
        caps.append("no_models")
    # AN EXTRACT-ONLY RUNNER (the server without Excel): it says so, and offers only the pack
    # extracts that need no workbook: the xAI read, the Document Manager read where the key is,
    # and the SolidWorks read only where SolidWorks runs here.
    if extract_only()[0]:
        caps = ["extract_only", "xai_extract"] + (["dm_extract"] if _key else []) \
            + ([] if _off else ["sw_extract"]) + (["no_models"] if "no_models" in caps else [])
    return caps
PACK_EXTRACT_KIND = {"sw_extract": "sw", "xai_extract": "xai", "dm_extract": "dm"}


def pack_extract_command(engine_root: Path, engine_python: Path, job: Dict[str, Any]
                         ) -> List[str]:
    """The one command a pack-extract job runs: src/pack_extract.py, never main.py."""
    kind = PACK_EXTRACT_KIND[str(job.get("job_type"))]
    paths = [str(job["pdf_path"])] if job.get("pdf_path") else [str(job["job_folder"])]
    return [str(engine_python), "-u", str(engine_root / "src" / "pack_extract.py"), kind,
            *paths, "--out", str(job["output_path"]),
            "--name", str(job.get("drawing_number") or Path(paths[0]).name)]


def _ask_for_work(requests, server: str, headers: Dict[str, str], runner_id: str,
                  process: str, build: str,
                  complained: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Ask ONE service for work. Returns (the run or None, the complaint now standing).

    The claim is also this runner's heartbeat to that service — which is why every service
    on the list is asked every cycle, not only the one that last had work."""
    base = server + "/api/estimate"
    try:
        r = requests.post(f"{base}/runner/claim", json={
            "runner_id": runner_id, "hostname": platform.node(),
            "process": process, "build": build,
            # WHAT THIS RUNNER CAN DO BESIDES AN ESTIMATE (D-640). The service hands a
            # pack-extract job only to a runner that says it can run one: an older runner
            # would build a full main.py estimate for it.
            "capabilities": runner_capabilities(),
            # WHAT THIS MACHINE IS USING (D-743), for the wall.
            "compute": compute_now(),
            # AND THE LAST COMPUTE CHECK BEFORE THIS CLAIM (JG, 10 Nov 2026).
            "gate": dict(_GATE) or None},
            headers=headers, timeout=20)
    except Exception as exc:                       # noqa: BLE001 — keep polling
        # SAY IT ONCE. A runner that cannot reach the server prints a line a
        # second, and the one useful message scrolls away.
        return None, _say_once(complained, "unreachable",
            f"cannot reach {server} — {exc}",
            "   still trying; this will not be repeated until it changes.")

    # A REPLY IS NOT A FAILURE TO REPLY, and the difference is somebody's
    # morning. The service answers on this port; if it answers 404 it is an
    # OLDER BUILD that has no runner endpoints, and the fix is Ctrl+C on the
    # service, not an hour spent on firewalls and ports.
    if r.status_code == 404:
        return None, _say_once(complained, "old-service",
            f"the service at {server} answered 404 for the runner queue.",
            "   It is running an older build with no runner endpoints.",
            "   Restart app.py there — the page is served from disk on every",
            "   request, but the routes are imported once at start-up.")
    if r.status_code == 401:
        return None, _say_once(complained, "unauthorised",
            f"the service at {server} rejected this runner (401).",
            "   SDI_API_KEY must match on both sides. Pass --api-key, or set",
            "   SDI_API_KEY in this runner's environment.")
    try:
        r.raise_for_status()
        job = (r.json() or {}).get("run")
    except Exception as exc:                       # noqa: BLE001
        return None, _say_once(complained, "bad-reply",
            f"the service at {server} answered {r.status_code} — {exc}")
    if complained:
        print(f"[{time.strftime('%H:%M:%S')}] connected to {server}.")
    # WHICH BUILD THIS SERVICE IS ON (D-607). Two services can answer on one machine, and HPP
    # 03:18 was claimed from one that a restart of the other had not touched. The commit is
    # the one the service stamps on every reply; kept beside the job, not in it, because the
    # job is the claim's own fields.
    _SERVICE_COMMIT[server] = str(
        (getattr(r, "headers", None) or {}).get("X-SDI-Commit") or "").strip()
    return job, None


class _heartbeat_while_busy:
    """While a job runs for one service, tell the OTHERS this runner is alive and busy.

    Through /runner/heartbeat, never /runner/claim: a claim is a request for work, and a
    service that had something queued would hand this runner a second job in the middle of
    the first. An older service without the endpoint answers 404 and is simply shown
    offline for the length of the job — which is how every service looked before.

    AS OFTEN AS THE MACHINE IS MEASURED (D-746). The other services' walls get this machine's
    compute from this beat alone; at 15 s their numbers were up to 20 s old while the service
    running the job had them every few seconds."""

    _EVERY = _COMPUTE_EVERY

    def __init__(self, requests, servers: List[str], headers: Dict[str, str],
                 runner_id: str, process: str, build: str) -> None:
        self._args = (requests, servers, headers, runner_id, process, build)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _beat(self) -> None:
        requests, servers, headers, runner_id, process, build = self._args
        while not self._stop.is_set():
            for server in servers:
                try:
                    requests.post(f"{server}/api/estimate/runner/heartbeat", json={
                        "runner_id": runner_id, "hostname": platform.node(),
                        "process": process, "build": build, "compute": compute_now()},
                        headers=headers, timeout=10)
                except Exception:                    # noqa: BLE001 — a beat, not a job
                    pass
            self._stop.wait(self._EVERY)

    def __enter__(self) -> "_heartbeat_while_busy":
        if self._args[1]:
            self._thread = threading.Thread(target=self._beat, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


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
             engine_root: Path, engine_python: Path, runner_id: str,
             claimed_from: Optional[Dict[str, str]] = None) -> None:
    run_id = job["run_id"]
    dest = Path(job["output_path"])
    folder = Path(job["job_folder"])
    log: List[str] = []
    pending: List[str] = []
    last_sent = 0.0
    # WHY A STRING AND NOT A FLAG: the reason reaches the log and the operator. "Stopped from
    # the page" and "the service says this run is no longer ours" are different events, and a
    # bare True would make the second look like the first on a morning nobody pressed stop.
    stop_asked: str = ""
    # WHEN THE ENGINE LAST SPOKE. The beat used to infer this from `pending` being
    # non-empty, and flush() drains pending on the very next line -- so the beat almost
    # never saw anything there and measured silence from the START OF THE RUN. 11650
    # reported "no output for 645s" with engine output ten seconds above it. A console that
    # is wrong about how long it has been quiet is no better than one that says nothing.
    last_said = time.time()
    _post_lock = threading.Lock()       # guards `pending`, held only to take or return a batch
    _send_lock = threading.Lock()       # one post at a time, so batches arrive in order

    def say(text: str) -> None:
        nonlocal last_said
        text = text.rstrip("\n")
        log.append(text)
        with _post_lock:
            pending.append(text)
        last_said = time.time()
        print(text)

    def flush(force: bool = False) -> None:
        nonlocal last_sent, pending, stop_asked
        # BATCHED IN TIME, NOT PER LINE (D-598w). This said "batched" and was not: it returned
        # early only when nothing was pending, so every line the engine printed was its own
        # HTTP post, made from the loop that reads the engine's pipe. While each post was in
        # flight the pipe filled and the ENGINE waited. 9439-07-04, 25 Oct: printing eight
        # parts' details took 146.4 s of a 762 s run. Now a batch goes at most every
        # _POST_EVERY_SECONDS, or sooner once _POST_MAX_LINES are waiting, and the post is made
        # outside the lock `say` needs, so reading the pipe never waits on the network.
        with _post_lock:
            if not force:
                if not pending:
                    return
                if ((time.time() - last_sent) < _POST_EVERY_SECONDS
                        and len(pending) < _POST_MAX_LINES):
                    return
            batch, pending = pending, []
        with _send_lock:
            try:
                resp = requests.post(f"{base}/runner/{run_id}/progress",
                                     json={"runner_id": runner_id, "lines": batch,
                                           "compute": compute_now()},
                                     headers=headers, timeout=20)
                last_sent = time.time()
                # STOP ARRIVES ON THE HEARTBEAT, because nothing else reaches this process.
                # The runner is on another machine with no inbound port; the only moment the
                # service can tell it anything is when it calls in, which it already does
                # every few seconds to renew the lease.
                #
                # A 409 IS ALSO A STOP. Abandoning a run sets its status away from "running",
                # and the progress endpoint then refuses the post — so by the time the cancel
                # flag could be read, the request carrying it is being rejected. Either
                # answer means the same thing: this run is no longer ours, and continuing to
                # drive SOLIDWORKS and Excel for the fifteen minutes it had left is work
                # nobody will use, in front of a queue waiting for the desktop.
                if resp.status_code == 409:
                    stop_asked = "the service says this run is no longer ours"
                # AND SO IS A SERVICE THAT NO LONGER KNOWS THE RUN. Runs live in the
                # service's memory; restarting it mid-job forgot this one, so its Stop
                # button answered "No such run" and the engine drove SOLIDWORKS and Excel
                # to the end of a job whose result the service would refuse. Matched on the
                # route's own words, so a wrong address (FastAPI's bare "Not Found") is not
                # taken for it.
                elif resp.status_code == 404 and "No such run" in (resp.text or ""):
                    stop_asked = ("the service no longer knows this run — it was restarted, "
                                  "and the result would be refused")
                elif resp.ok and (resp.json() or {}).get("cancel"):
                    stop_asked = "stopped from the page"
            except Exception:                          # noqa: BLE001
                with _post_lock:
                    pending = batch + pending          # keep it for the next try

    def poster() -> None:
        """Send what the engine has said while it is quiet, so a line printed just before a
        silent Excel phase reaches the page within seconds, not at the next line or beat."""
        while proc.poll() is None:
            time.sleep(_POST_EVERY_SECONDS)
            flush()

    def until_next_beat() -> None:
        """Wait out one beat, listening for a stop every _LISTEN_SECONDS, and return the
        moment one is heard or the engine ends (D-649). A stop heard by the console poster
        is acted on within a second, not at the end of a 30s sleep."""
        end = time.time() + _BEAT_SECONDS
        listened = time.time()
        while proc.poll() is None and not stop_asked:
            now = time.time()
            if now >= end:
                return
            if now - listened >= _LISTEN_SECONDS:
                flush(force=True)
                listened = time.time()
                continue
            time.sleep(min(1.0, end - now))

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
            until_next_beat()
            if proc.poll() is not None:
                break
            if stop_asked:
                # TERMINATE, THEN KILL. The engine holds COM handles on Excel and SOLIDWORKS;
                # terminate lets it unwind them, and a desktop left with an orphaned hidden
                # Excel is how the NEXT run fails for reasons nobody can trace back to here.
                say(f"STOPPING — {stop_asked}. Ending the engine process.")
                flush(force=True)
                try:
                    proc.terminate()
                    proc.wait(timeout=30)
                except Exception:                      # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:                  # noqa: BLE001
                        pass
                break
            if last_said != spoke_at:                  # the engine spoke since the last beat
                spoke_at = last_said
                said_at = 0.0
                continue
            quiet = time.time() - last_said
            if quiet >= _SAY_QUIET_AFTER and (time.time() - said_at) >= _SAY_QUIET_AFTER:
                said_at = time.time()
                # SAY WHAT IS KNOWN, NOT A GUESS (D-477). This line used to claim the engine
                # was "driving Excel/SOLIDWORKS" — on the 21:20 K-Wellness run it printed
                # that during PDF extraction and price lookups, on a run whose own banner
                # said SolidWorks was off. The heartbeat cannot see the active stage, so it
                # names the quiet kinds without claiming one.
                say(f"Still running — no output for {int(quiet)}s. A quiet stage "
                    f"(extraction, a model call, a price lookup, or Excel/COM work) prints "
                    f"nothing; the process is alive.")
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

    # THE MANUAL ESTIMATE TO COMPARE AGAINST, IF ONE CAME WITH THE RUN. Checked here for the
    # same reason the drawing is: a path this runner cannot see must be reported as such, not
    # handed to the engine to fail forty minutes later inside the deliverables pass.
    manual_wb = Path(job["manual_workbook"]) if job.get("manual_workbook") else None
    if manual_wb is not None and not manual_wb.is_file():
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The manual estimate for the parity report is not readable from this "
                f"runner: {manual_wb}", log)
        return

    # THE TEMPLATE THE WORKBOOK IS BUILT FROM. This is the one that actually bit. 10575-02 ran
    # for sixteen minutes, and only then did wb_populate report TEMPLATE NOT FOUND on the share.
    # The canonical-route cutover deliberately forbids the legacy fallback builder, so there was
    # no second path: the run ended having written a summary and no estimate, and reported done.
    #
    # None of the reading, pricing or arbitration was wasted effort in principle -- but the one
    # fact that decided the outcome was knowable before any of it started.
    # A PACK EXTRACT IS NOT AN ESTIMATE (D-640): no template, no workbook check, nothing
    # filed to the briefs or parity areas. One command, and exactly the files it names; the
    # launch, the lease, the console and Stop are the estimate's own.
    # A PRE-RUN (job_type bom_routes) files like an extract: the files its PACK_EXTRACT_OUTPUTS
    # line names, no template, no workbook check.
    pre_run = str(job.get("job_type") or "") == "bom_routes"
    extract_job = str(job.get("job_type") or "") in PACK_EXTRACT_KIND or pre_run

    tpl = workbook_template()
    if not extract_job and not Path(tpl).is_file():
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The estimate workbook template is not readable from this runner: {tpl} — "
                f"so no workbook could be built and the run would produce a summary and no "
                f"estimate. Check the file is on the share under that exact name (the double "
                f"space is real), or point SDI_WB_TEMPLATE at a local copy.", log)
        return

    before = snapshot(engine_root)
    # WHEN THIS EXECUTION BEGAN. Everything collect() accepts must be at least this new, so a
    # failed run cannot file an earlier run's outputs and have them read as its own.
    _run_started_at = time.time()
    cmd = engine_command(engine_root, engine_python, folder, int(job["units"]),
                         job["client"], pdf=pdf, manual_workbook=manual_wb,
                         quantity_breaks=[int(q) for q in (job.get("quantity_breaks") or [])],
                         llm_only=bool(job.get("llm_only")),
                         fresh_read=bool(job.get("fresh_read")),
                         product=str(job.get("drawing_number") or ""),
                         deterministic_only=bool(job.get("deterministic_only")),
                         reader_mode=str(job.get("reader_mode") or ""),
                         bom_routes_out=Path(str(job["output_path"])) if pre_run else None)
    if extract_job and not pre_run:
        cmd = pack_extract_command(engine_root, engine_python, job)
    say("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    flush(force=True)

    try:
        # WHO CLAIMED IT, ON THE BOOK (D-601). The engine names its own machine; only the
        # runner knows its runner id and the portal's run id, so it hands them down.
        proc = subprocess.Popen(cmd, cwd=str(engine_root), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1,
                                env={**os.environ, "SDI_CLAIMED_BY_RUNNER": str(runner_id),
                                     "SDI_SERVICE_RUN_ID": str(run_id),
                                     # AND WHAT WAS SUBMITTED (D-604), so the book can say
                                     # whether what reached the engine is what was sent.
                                     # null when the service sent no scope field at all,
                                     # apart from an empty one (D-607).
                                     "SDI_SUBMITTED_SCOPE": json.dumps(
                                         job.get("submitted_scope")),
                                     # AND WHICH SERVICE, ON WHICH BUILD (D-607).
                                     "SDI_CLAIMED_FROM": json.dumps(claimed_from or {})})
    except OSError as exc:
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"Could not start the engine: {exc}", log)
        return

    assert proc.stdout is not None
    if isinstance(getattr(proc, "pid", None), int):
        _JOB_PIDS[str(run_id)] = proc.pid       # measured as this job's own use (D-743)
    threading.Thread(target=beat, name="lease-heartbeat", daemon=True).start()
    threading.Thread(target=poster, name="progress-poster", daemon=True).start()
    try:
        for text in proc.stdout:
            say(text)
            flush()
        code = proc.wait()
    finally:
        _JOB_PIDS.pop(str(run_id), None)

    # A STOPPED RUN FILES NOTHING, WHATEVER THE ENGINE'S EXIT CODE (D-588c). The beat ends the
    # engine when a stop arrives, but a stop that lands as the engine finishes cleanly found
    # the run at exit 0 and filed its book to the share — a job the person stopped, published.
    # So the service is asked once more before anything is filed, and a stop heard at any
    # point means nothing leaves the engine's own output folder. The runner then goes back to
    # the queue, so the next job runs as normal.
    flush(force=True)
    if stop_asked:
        say(f"STOPPED — {stop_asked}. Nothing was filed.")
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"Stopped — {stop_asked}. The engine was ended and nothing was filed; anything "
                f"it wrote stays in the engine's own output folder on this machine.", log)
        return

    if extract_job:
        filed = pack_extract_outputs(log)
        if code != 0 or not filed:
            _finish(requests, base, headers, run_id, runner_id, "error",
                    f"The {'pre-run' if pre_run else 'pack extract'} exited with code {code} and wrote "
                    f"{len(filed)} file(s) — the log above says why.", log, filed)
            return
        _finish(requests, base, headers, run_id, runner_id, "done", "", log, filed)
        return

    if code != 0:
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The engine exited with code {code}. Nothing was filed.", log)
        return

    try:
        filed = collect(engine_root, dest, before, log, job.get("drawing_number", ""),
                        started_at=_run_started_at)
    except Exception as exc:                           # noqa: BLE001 — surface it
        _finish(requests, base, headers, run_id, runner_id, "error",
                f"The estimate ran but could not be filed: {exc}", log)
        return

    # DONE MEANS THERE IS AN ESTIMATE. Exit code 0 says the engine did not crash; it does not
    # say it produced anything. 10575-02 ran 16 minutes, exited 0, filed a summary JSON and a
    # log, and the page reported it complete — sending an estimator to a folder with no workbook
    # in it. The deliverables are still filed and the log still says what happened, because the
    # summary and the console are exactly what is needed to work out why.
    if not any(f["name"].lower().endswith(".xlsx") for f in filed):
        _finish(requests, base, headers, run_id, runner_id, "error",
                "The engine finished without producing a workbook. "
                + (", ".join(f["name"] for f in filed) or "Nothing")
                + " was filed to the output folder — open the run log there for what the "
                  "engine did instead.", log, filed)
        return

    file_a_copy(job, filed, log)          # D-617: and in the completed AI briefs area
    file_parity(job, filed, engine_root, engine_python, log)   # D-619: and the parity folder
    _finish(requests, base, headers, run_id, runner_id, "done", "", log, filed)


# WHERE THE ENGINE PUTS ITS ANSWER. Tried in order; the first that holds a number wins.
# More than one name because the summary has grown over time and a runner that knows only
# the newest key reports nothing at all on an older record -- and reporting nothing here
# looks exactly like an estimate that produced no price.
_UNIT_COST_KEYS = (
    # THE FIGURE EXCEL ITSELF CALCULATED, and the only one that provably sums to the sheet's
    # own totals. final_estimate is written by the read-back after the workbook recalculates;
    # every other key below is the engine's own pre-workbook arithmetic, which is what the
    # sheet was BUILT from rather than what it came to.
    #
    # It was not in this list, and none of the four that were is present on a v2 record, so
    # the runner reported no price at all. 12349-02's covering email went out headed "not
    # reported/unit at 7 off" over an estimate whose workbook had a unit cost in it — the
    # exact failure the comment below was written to prevent, by a key added since.
    ("final_estimate", "totals", "unit_gbp"),
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
    for path in _UNIT_COST_KEYS:
        node: Any = summary
        for step in path[:-1]:
            node = node.get(step) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            continue
        try:
            value = float(node.get(path[-1]))
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


def quantity_prices_from(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The unit cost at every quantity the run priced (D-610), from the quantity sweep the
    engine wrote: [{"quantity": 1, "unit_gbp": 538.06}, {"quantity": 5, ...}]. Empty for a
    run priced at one quantity, which unit_cost_from already answers."""
    rows = ((summary or {}).get("quantity_sweep") or {}).get("rows") \
        if isinstance(summary, dict) else None
    out: Dict[int, float] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            q, unit = int(r.get("quantity")), float(r.get("unit"))
        except (TypeError, ValueError):
            continue
        if q >= 1 and unit > 0:
            out[q] = round(unit, 2)
    return [{"quantity": q, "unit_gbp": out[q]} for q in sorted(out)] if len(out) > 1 else []


def _quantity_prices_from_deliverables(deliverables: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    import json as _json
    for item in deliverables or []:
        if not str(item.get("name") or "").lower().endswith(".json"):
            continue
        try:
            with open(item["path"], "r", encoding="utf-8") as fh:
                found = quantity_prices_from(_json.load(fh))
        except Exception:                                # noqa: BLE001
            continue
        if found:
            return found
    return []


# ── A SECOND COPY WHERE THE ESTIMATORS FILE THEIR WORK (D-617) ────────────────────────────
# JG, 1 Nov 2026: every finished run is also saved to the completed AI briefs area, under the
# client area and the job pack number, a new sub-folder for every run "with a timestamp and some
# other identifier like a version number so that we have a record of them all". The service
# names the root and the run's own time in the claim; this machine, which holds the files,
# makes the folder and copies them. A copy that fails is said in the run log and never fails
# the estimate, which is already filed in AISheets.
_ARCHIVE_VERSION = re.compile(r"\bv(\d+)\b", re.I)
_ARCHIVE_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _archive_segment(text: Any) -> str:
    cleaned = _ARCHIVE_UNSAFE.sub("-", str(text or "")).strip()
    return re.sub(r"\s+", " ", cleaned).rstrip(". ")[:120] or "unnamed"


def _bare(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def client_area(root: Path, client: str) -> Path:
    """The client's folder under the root: one already there whose name matches with case and
    punctuation removed ("M & S" is "M&S"), so a client is never filed twice under two
    spellings; otherwise a new one in the client's name."""
    want = _bare(client)
    if want:
        try:
            for entry in sorted(root.iterdir()):
                if entry.is_dir() and _bare(entry.name) == want:
                    return entry
        except OSError:
            pass
    return root / _archive_segment(client)


def archive_folder(base: Path, stamp: str, units: Any) -> Path:
    """A new folder for this run under the job pack: "<stamp> v<N> (<units> off)", N one more
    than the highest version already there. Made exclusively, so two runs can never share one
    and an earlier run's files are never written over."""
    base.mkdir(parents=True, exist_ok=True)
    highest = 0
    for entry in base.iterdir():
        found = _ARCHIVE_VERSION.search(entry.name) if entry.is_dir() else None
        if found:
            highest = max(highest, int(found.group(1)))
    try:
        units = int(units)
    except (TypeError, ValueError):
        units = 1
    for version in range(highest + 1, highest + 200):
        folder = base / f"{_archive_segment(stamp)} v{version} ({units} off)"
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise OSError(f"no free version folder under {base}")


def file_a_copy(job: Dict[str, Any], filed: List[Dict[str, str]], log: List[str]) -> str:
    """Copy a finished run's files to the completed AI briefs area. The folder, or ""."""
    root = str(job.get("archive_root") or "").strip()
    if not root or not filed:
        return ""
    try:
        base = (client_area(Path(root), str(job.get("client") or ""))
                / _archive_segment(job.get("drawing_number")))
        folder = archive_folder(base, str(job.get("archive_stamp")
                                          or time.strftime("%Y-%m-%d %H-%M-%S")),
                                job.get("units"))
        copied, failed = 0, []
        for item in filed:
            try:
                shutil.copy2(item["path"], folder / item["name"])
                copied += 1
            except OSError as exc:
                failed.append(f"{item.get('name')} ({exc})")
        log.append(f"[archive] {copied} of {len(filed)} file(s) also filed to {folder}")
        for f in failed:
            log.append(f"[archive] NOT copied: {f}")
        return str(folder)
    except OSError as exc:
        log.append(f"[archive] NOT filed to the completed AI briefs area ({exc}). The estimate "
                   f"is filed in AISheets as usual.")
        return ""


def _engine_book(filed: List[Dict[str, str]]) -> Optional[str]:
    """The engine's workbook among the filed files: the one stamped _YYYYMMDD_HHMMSS."""
    books = [f for f in filed if f["name"].lower().endswith(".xlsx")]
    stamped = [f for f in books if re.search(r"_\d{8}_\d{6}\.xlsx$", f["name"], re.I)]
    pool = stamped or books
    return min(pool, key=lambda f: len(f["name"]))["path"] if pool else None


def file_parity(job: Dict[str, Any], filed: List[Dict[str, str]], engine_root: Path,
                engine_python: Path, log: List[str]) -> str:
    """A run that came with a manual estimate also files its comparison to the parity folder
    (D-619): both sheets, the report and the index, as a comparison by job number does, so the
    search on the page finds it beside the rest. The folder, or "".

    JG, 1 Nov 2026: "for every run we save down the two s/sheets compared and the parity reports
    that are available to be searched through in the web page and app and also at the time of
    run". The deliverables already hold the run's own parity section; this is the filed copy.
    Never fails the run: the estimate is filed whatever happens here."""
    root = str(job.get("parity_root") or "").strip()
    manual = str(job.get("manual_workbook") or "").strip()
    find = not manual and bool(job.get("compare_with_manual"))     # D-621: by job number
    book = _engine_book(filed)
    if not root or not (manual or find) or not book:
        return ""
    cli = Path(engine_root) / "src" / "parity_job.py"
    if not cli.is_file():
        log.append(f"[parity] NOT filed to the parity folder: {cli} is not on this runner yet.")
        return ""
    env = dict(os.environ, SDI_PARITY_ROOT=root)
    cmd = [str(engine_python) if Path(engine_python).is_file() else sys.executable, str(cli),
           "job", str(job.get("drawing_number") or Path(book).stem),
           *(["--manual", manual] if manual else []),
           *(["--client", str(job.get("client"))] if job.get("client") else []),
           "--ai", book, "--made-by", f"run {job.get('run_id', '')}", "--json"]
    try:
        proc = subprocess.run(cmd, cwd=str(engine_root), capture_output=True, text=True,
                              timeout=300, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.append(f"[parity] NOT filed to the parity folder ({type(exc).__name__}). The run's "
                   f"own deliverables are unaffected.")
        return ""
    line = next((ln for ln in reversed((proc.stdout or "").splitlines())
                 if ln.strip().startswith("{")), "")
    try:
        body = json.loads(line) if line else {}
    except ValueError:
        body = {}
    if proc.returncode == 3:
        log.append(f"[parity] NOT compared: the manual estimate is not a clear choice "
                   f"({str(body.get('error') or '')[:300]}). Choose it on the parity card.")
        return ""
    if proc.returncode != 0 or not body.get("folder"):
        why = body.get("error") or ((proc.stderr or "").strip().splitlines() or ["no answer"])[-1]
        log.append(f"[parity] NOT filed to the parity folder: {str(why)[:300]}")
        return ""
    log.append(f"[parity] comparison filed to {body['folder']}")
    return str(body["folder"])


def pack_extract_outputs(log: List[str]) -> List[Dict[str, str]]:
    """The files a pack extract wrote, from its own PACK_EXTRACT_OUTPUTS line; only those
    that exist. pack_extract.py writes straight into the run's output folder."""
    for text in reversed(log):
        if text.startswith("PACK_EXTRACT_OUTPUTS="):
            try:
                paths = [str(x) for x in json.loads(text.split("=", 1)[1])]
            except ValueError:
                return []
            return [{"name": Path(w).name, "path": w} for w in paths if Path(w).is_file()]
    return []


def _finish(requests, base: str, headers: Dict[str, str], run_id: str, runner_id: str,
            status: str, error: str, log: List[str],
            deliverables: Optional[List[Dict[str, str]]] = None) -> None:
    if error:
        log.append(error)
        print(error)
    body = {"runner_id": runner_id, "status": status, "error": error,
            "lines": [], "deliverables": deliverables or [],
            "unit_cost_gbp": _unit_cost_from_deliverables(deliverables or []),
            # AND THE PRICE AT EVERY QUANTITY ASKED FOR (D-610), so the page shows 1, 5 and 10
            # off, not one unit price for a run that priced three.
            "quantity_prices": _quantity_prices_from_deliverables(deliverables or [])}
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
