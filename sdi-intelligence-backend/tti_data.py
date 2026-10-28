"""One reading of the Despatch Plan, shared by every TTI view and tool.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────
Phase one had one question and fetched the workbook to answer it. There are
now six, on a screen with tabs and in a voice assistant that will ask two or
three in a row. Fetching and re-parsing seventeen sheets for each of them
would make the chase list slow enough that people would stop opening it, and
slow enough that a voice answer would time out.

── WHY A CACHE HERE IS NOT A PERMISSION HOLE ────────────────────────────────
The workbook is read as the person asking, and that must not change. So every
call still asks SharePoint about the file with THAT person's token: if their
access has gone, the metadata request refuses and they get nothing, cache or
no cache. What the cache saves is the download and the parse, and only when
SharePoint's own eTag says the file has not been saved since. Nobody is
admitted by a cached copy; the copy only spares the second person in a minute
from waiting for the same parse.

Nothing is written to disk. The parsed rows live in this process and go when
it restarts, which is the right lifetime for somebody else's commercial
tracker.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import tti_plan_source as plan
from sue_despatch import SourceRow
from tracker_snapshot import load_schedule_snapshot, read_schedule_bytes


# How long a parse may be reused without asking SharePoint again at all. Kept
# deliberately short: a despatch plan is edited through the day, and a stale
# answer is the failure this app cannot afford. Zero means always ask.
TTL_SECONDS = int((os.getenv("SDI_TTI_PLAN_TTL", "") or "0").strip() or 0)

MAX_ROWS_IN_MEMORY = 20000


class Unavailable(Exception):
    """Said plainly to the person, never a guess about why."""


@dataclass(frozen=True)
class Plan:
    rows: list[SourceRow]
    saved: datetime
    version: str
    digest: str
    reused: bool

    def provenance(self) -> dict:
        """What every answer carries, so none of them can be read as live."""
        return {"plan_saved": self.saved.isoformat(),
                "plan_version": (self.version or self.digest)[:16],
                "rows_read": len(self.rows),
                "plan_reused_from_cache": self.reused}


_lock = threading.Lock()
_held: dict = {}            # {key: (version, when, digest, rows, saved)}


def _key() -> tuple:
    return (plan.site(), plan.file_path())


def snapshot_path() -> str:
    """A local copy, for a machine with no Graph access. Never the default: a
    file of unknown freshness answering a despatch question is worse than no
    answer, so SharePoint wins whenever it is configured."""
    return (os.getenv("SDI_TTI_DESPATCH_PLAN", "") or "").strip()


def configured() -> bool:
    return bool(plan.configured() or snapshot_path())


def rows_for(token: str, *, client=None) -> Plan:
    """The plan's rows, read as the holder of `token`.

    Raises Unavailable with a sentence fit to show somebody. The sentence comes
    from tti_plan_source, which distinguishes a 403 (your access), a 404 (the
    file moved) and a 400 (this app's address for it) - a distinction that cost
    an afternoon of checking permissions that were fine.
    """
    if not plan.configured():
        return _from_snapshot()
    key = _key()
    with _lock:
        known = _held.get(key)
    version_held = known[0] if known else ""
    if known and TTL_SECONDS and time.monotonic() - known[1] < TTL_SECONDS:
        return Plan(known[3], known[4], known[0], known[2], True)
    try:
        data, saved, version = plan.fetch_plan(token, client=client,
                                               known_version=version_held)
    except plan.PlanUnavailable as exc:
        raise Unavailable(str(exc)) from exc
    if data is None and known:
        # SharePoint says the file has not been saved since this parse. Its own
        # save time is taken afresh all the same, so the screen's "last saved"
        # is never older than SharePoint's answer.
        with _lock:
            _held[key] = (version, time.monotonic(), known[2], known[3], saved)
        return Plan(known[3], saved, version, known[2], True)
    if data is None:
        # Only reachable if a caller passed a version nothing was held for.
        raise Unavailable("The Despatch Plan could not be read just now. Try again.")
    try:
        digest, rows = read_schedule_bytes(data)
    except ValueError as exc:
        raise Unavailable(f"The Despatch Plan could not be read: {exc}") from exc
    if len(rows) > MAX_ROWS_IN_MEMORY:
        raise Unavailable("The Despatch Plan has grown beyond what this view reads.")
    with _lock:
        _held[key] = (version, time.monotonic(), digest, rows, saved)
    return Plan(rows, saved, version, digest, False)


def _from_snapshot() -> Plan:
    """The local .xlsx fallback, with the FILE's own save time - not this hour.

    An answer stamped "now" about a workbook saved last Tuesday is the lie that
    matters in a despatch question, so the mtime is used and shown.
    """
    where = snapshot_path()
    if not where:
        raise Unavailable(
            "The Despatch Plan has not been configured. Set SDI_TTI_PLAN_SITE and "
            "SDI_TTI_PLAN_PATH for the SharePoint workbook.")
    try:
        digest, rows = load_schedule_snapshot(where)
    except ValueError as exc:
        raise Unavailable(f"The Despatch Plan could not be read: {exc}") from exc
    except OSError as exc:
        raise Unavailable("The Despatch Plan is not reachable from this service "
                          "just now.") from exc
    try:
        saved = datetime.fromtimestamp(Path(where).stat().st_mtime, timezone.utc)
    except OSError:
        saved = datetime.now(timezone.utc)
    return Plan(rows, saved, "", digest, False)


def forget() -> None:
    """Drop what is held. For tests, and for a restart-free way to clear it."""
    with _lock:
        _held.clear()
