"""The desktop's one SolidWorks, taken in turn by every run on the machine (SCRUM-183 phase 2,
D-731).

JG, 6 Nov 2026: "We agreed that two estimating workers would share one SolidWorks reader, waiting
briefly for their turn ... the same job could receive different model evidence depending on what
else is running." So no run changes reader because another run is busy: every run reads its
models exactly as it would alone, and a run that finds SolidWorks in use WAITS for it.

JG, later the same day: "we should not fail.. we should report in the portal that [we] are
switching to document manager and provide a 5 minute update every delay due to waiting for solid
works com api." So the wait is said on the run's console, which the portal shows, when it starts
and every SDI_SW_TURN_UPDATE_MINUTES (5) after; and a wait that reaches the limit is not a
failure: the engine switches that run to the Document Manager and says so (D-732).

THE TURN IS A LOCK ON ONE FILE PER MACHINE, outside any checkout, so every slot's checkout
(C:\\ClaudeVision, C:\\ClaudeVision-s2, ...) finds the same file. It is held only while the
analyser reads models, not for the whole run, so a second run waits at most for one other run's
model read, and the rest of both runs (drawing reads, pricing, the books) go on side by side.

A WAIT THAT REACHES SDI_SW_TURN_WAIT_MINUTES (default 35, just beyond the analyser's own 30-minute
limit, so one other read normally finishes inside it) ends the wait. What the run does next is
SDI_SW_TURN_TIMEOUT: "docmgr" (the default) reads its models with the Document Manager when its
licence key is set, said on the console and on the book; "none" leaves them unread. Either way the
run goes on, and a run whose models were left unread is priced from its drawings and DXFs and
flagged not firm. Only this exceptional wait changes the reader; a normal wait never does.

A TOKEN THAT CANNOT BE USED AT ALL (no folder can be made, a filesystem with no locks) fails
open: the run reads as a lone run always has, and says so. A lone run never waits.
"""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

TOKEN_ENV = "SDI_SOLIDWORKS_TOKEN"
WAIT_ENV = "SDI_SW_TURN_WAIT_MINUTES"
UPDATE_ENV = "SDI_SW_TURN_UPDATE_MINUTES"
TIMEOUT_ENV = "SDI_SW_TURN_TIMEOUT"
TURN_WAIT_LIMIT = 35.0                     # in minutes; the analyser itself stops at 30
TURN_UPDATE_EVERY = 5.0                    # in minutes: how often a waiting run says so
POLL_SECONDS = 2.0

HELD, BUSY, UNAVAILABLE, TIMED_OUT = "held", "busy", "unavailable", "timed_out"


def token_path() -> Path:
    """The machine's one SolidWorks token. SDI_SOLIDWORKS_TOKEN names it; otherwise it sits in
    ProgramData (Windows) or the system temp folder, which every checkout on the machine shares."""
    explicit = str(os.getenv(TOKEN_ENV, "")).strip()
    if explicit:
        return Path(explicit)
    base = os.getenv("PROGRAMDATA") or tempfile.gettempdir()
    return Path(base) / "SDI" / "solidworks.token"


def _minutes(name: str, default: float) -> float:
    try:
        return max(0.0, float(str(os.getenv(name, "")).strip() or default))
    except ValueError:
        return default


def wait_minutes() -> float:
    return _minutes(WAIT_ENV, TURN_WAIT_LIMIT)


def update_minutes() -> float:
    return _minutes(UPDATE_ENV, TURN_UPDATE_EVERY) or TURN_UPDATE_EVERY


def timeout_reader() -> str:
    """What a run does when its wait reaches the limit: "docmgr" (default) or "none"."""
    v = str(os.getenv(TIMEOUT_ENV, "")).strip().lower()
    return "none" if v in {"none", "0", "off", "no", "false", "drawings"} else "docmgr"


def _take_lock(handle) -> bool:
    """True if this process now holds the lock, False if somebody else does. The runner's own
    single-instance lock asks the same two questions the same way, kept apart: which locking
    API this platform has, and whether the lock was taken."""
    handle.seek(0)
    try:
        import msvcrt                                              # Windows
    except ImportError:
        import fcntl                                               # everywhere else
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


def try_take(path: Optional[Path] = None) -> Tuple[Any, str]:
    """(handle, state) without waiting. "held": this process has the turn; "busy": another run
    on this machine has it; "unavailable": the token cannot be used at all."""
    path = Path(path) if path else token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o666)
        handle = os.fdopen(fd, "r+b")
    except Exception:                                              # noqa: BLE001
        return None, UNAVAILABLE
    try:
        if _take_lock(handle):
            return handle, HELD
    except Exception:                                              # noqa: BLE001
        handle.close()
        return None, UNAVAILABLE
    handle.close()
    return None, BUSY


def release(handle: Any) -> None:
    """Give the turn back. Closing the descriptor releases the lock."""
    try:
        if handle is not None:
            handle.close()
    except Exception:                                              # noqa: BLE001
        pass


def busy(path: Optional[Path] = None) -> bool:
    """Is another run on this machine reading models with SolidWorks right now? A probe: taken
    and given straight back."""
    handle, state = try_take(path)
    release(handle)
    return state == BUSY


def take_turn(path: Optional[Path] = None, wait_s: Optional[float] = None,
              poll_s: float = POLL_SECONDS, say: Callable[[str], Any] = print,
              sleep: Callable[[float], Any] = time.sleep,
              clock: Callable[[], float] = time.monotonic,
              update_s: Optional[float] = None) -> Tuple[Any, Dict[str, Any]]:
    """Wait for the desktop's SolidWorks. Returns (handle, turn) where turn says what happened:
    {"state": held | unavailable | timed_out, "waited_s": seconds, "token": path}. The caller
    reads models with SolidWorks only on held or unavailable, and releases the handle when the
    read ends. While it waits it says so at the start and every `update_s` seconds (D-732)."""
    path = Path(path) if path else token_path()
    wait_s = wait_minutes() * 60.0 if wait_s is None else float(wait_s)
    update_s = update_minutes() * 60.0 if update_s is None else max(0.001, float(update_s))
    started = clock()
    said_waiting = False
    next_update = update_s
    while True:
        handle, state = try_take(path)
        waited = round(clock() - started, 1)
        turn: Dict[str, Any] = {"state": state, "waited_s": waited, "token": str(path)}
        if state == HELD:
            if said_waiting:
                say(f"SolidWorks is free after {waited:.0f} s: this run reads its models now.")
            return handle, turn
        if state == UNAVAILABLE:
            say(f"The desktop's SolidWorks token ({path}) could not be used, so this run reads "
                f"its models as a lone run would, without waiting for any other run.")
            return None, turn
        if waited >= wait_s:
            turn["state"] = TIMED_OUT
            return None, turn
        if not said_waiting:
            say("Waiting for the desktop's SolidWorks: another run on this machine is reading "
                f"its models. This run waits its turn, up to {wait_s / 60:.0f} minutes, and "
                f"reads its models the same way it would alone.")
            said_waiting = True
        elif waited >= next_update:
            say(f"Still waiting for the desktop's SolidWorks: {waited / 60:.0f} min so far, up "
                f"to {wait_s / 60:.0f}. Another run on this machine is still reading its "
                f"models.")
            next_update += update_s
        sleep(poll_s)


def timed_out_reason(turn: Dict[str, Any]) -> str:
    """The run's own words for a turn that never came. What happened next is said by the
    caller, which knows whether the Document Manager read the models."""
    return (f"the desktop's SolidWorks stayed in use by another run on this machine for "
            f"{float(turn.get('waited_s') or 0) / 60:.0f} minutes ({WAIT_ENV} allows "
            f"{wait_minutes():g}), so SolidWorks did not read this run's models")


@contextmanager
def solidworks_turn(**kwargs: Any) -> Iterator[Dict[str, Any]]:
    """`with solidworks_turn() as turn:` holds the turn for the block when turn["state"] is
    held, and always gives it back."""
    handle, turn = take_turn(**kwargs)
    try:
        yield turn
    finally:
        release(handle)
