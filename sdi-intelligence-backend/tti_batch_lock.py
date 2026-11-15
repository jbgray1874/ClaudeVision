"""ONE WRITER ON THE TRACKER (JG's checklist, 15 Nov 2026: "one writer / no duplicate click").

A tracker batch (src/tti_pricer.py) writes the AI Cost cells of one workbook and of the central
sheet. Two alive at once would each queue the same rows and each write the same cells. The page's
"Price the sheet" button and the "Price the changes" button both start that batch, and two
services (8071 and 8072) can be asked, so the claim is a file in the shared state folder, not a
variable in one process.

    claim(path, task_id, pid)  -> None, or raises Busy naming the batch that holds it
    holder(path)               -> {task_id, pid, started} while that process is alive, else None

A claim whose process has ended is nobody's: it is replaced, never waited on. A dry run (which
writes nothing) takes no claim.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class Busy(RuntimeError):
    pass


def pid_alive(pid: Any) -> bool:
    """Whether a process with this id is running. Never signals it: on Windows os.kill with an
    ordinary signal ENDS the process, so the question is asked through the process handle."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":                                              # pragma: no cover (laptop)
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)                        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # A finished child nobody has waited for still answers the signal: it is not running.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except OSError:
        return True


def holder(path: Path, alive: Callable[[Any], bool] = pid_alive) -> Optional[Dict[str, Any]]:
    try:
        held = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict) or not alive(held.get("pid")):
        return None
    return held


def claim(path: Path, task_id: str, pid: int, alive: Callable[[Any], bool] = pid_alive,
          now: Callable[[], float] = time.time) -> None:
    """Record that `pid` is the batch writing the tracker. Raises Busy if a live one already is."""
    path = Path(path)
    held = holder(path, alive)
    if held and int(held.get("pid") or 0) != int(pid):
        raise Busy(f"A tracker batch is already running (task {held.get('task_id')}). "
                   f"Wait for it to finish; nothing was started.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"task_id": task_id, "pid": int(pid), "started": now()}), encoding="utf-8")
    os.replace(tmp, path)
