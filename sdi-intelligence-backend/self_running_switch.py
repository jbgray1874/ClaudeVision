"""self_running_switch.py — the portal's half of AI Estimate Self-Running (D-588).

THE BUTTON IS A SWITCH. The estimating page's "AI Estimate Self-Running" button turns it on;
"Stop self-running" turns it off. The work — reading the Live Enquiry sheet, collecting each
waiting row's drawings from Production, running every ready job one after another through this
portal — is done by a watcher on the estimating machine (src/self_running.py), which asks this
module on every beat whether it is on and reports what it is doing.

WHY THE SERVICE DOES NOT RUN IT. This page is served by the laptop on 8072 and by SDI-APP01 on
8071. The server has no share rights in the logged-on estimator's session, no SOLIDWORKS and no
runner; a process started there would read nothing and run nothing. The estimating runner
already works this way — the service holds the queue, the machine that can do the work claims
it — so self-running does too.

WHAT IS KEPT, OUTSIDE THE REPOSITORY. One small file beside the saved e-mail recipients
(estimate_email.state_dir): the switch, who pressed it and when, whether a press is waiting to
be acted on at once, and the watcher's last report with the time it arrived. The service never
reads the sheet or the ledger itself; what the page shows is what the watcher said.

STALE IS NOT CONNECTED. A watcher that has not reported within STALE_SECONDS is shown as not
connected, with the time it was last heard from — never as idle, which would read as "nothing
to do" when the truth is "nothing is listening".
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_STATE_FILENAME = "self_running.json"
STALE_SECONDS = int(os.getenv("SDI_SELF_RUNNING_STALE_SECONDS", "180"))
_LOCK = threading.Lock()


def _state_dir() -> Path:
    try:
        from estimate_email import state_dir
        return state_dir()
    except Exception:                                                # noqa: BLE001
        explicit = os.getenv("SDI_STATE_DIR", "").strip()
        if explicit:
            return Path(explicit)
        program_data = os.getenv("PROGRAMDATA", "").strip()
        return (Path(program_data) / "SDI Intelligence") if program_data \
            else Path.home() / ".sdi-intelligence"


def _path() -> Path:
    return _state_dir() / _STATE_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def view(now: Optional[float] = None) -> Dict[str, Any]:
    """What the page shows: the switch, and the watcher as last heard from."""
    now = time.time() if now is None else now
    with _LOCK:
        state = _load()
    watcher = dict(state.get("watcher") or {})
    seen = watcher.get("seen_epoch")
    age = (now - float(seen)) if isinstance(seen, (int, float)) else None
    watcher["connected"] = age is not None and age <= STALE_SECONDS
    watcher["seconds_since"] = round(age) if age is not None else None
    return {
        "enabled": bool(state.get("enabled")),
        "switched_on_at": state.get("switched_on_at"),
        "switched_off_at": state.get("switched_off_at"),
        "switched_by": state.get("switched_by") or "",
        "run_now_pending": bool(state.get("run_now")),
        "watcher": watcher,
        "stale_after_seconds": STALE_SECONDS,
    }


def switch(on: bool, by: str = "") -> Dict[str, Any]:
    """Turn self-running on or off. ON also asks the watcher to read the sheet at once rather
    than at its next scheduled read; OFF lets the job in progress finish and queues nothing
    more."""
    with _LOCK:
        state = _load()
        state["enabled"] = bool(on)
        state["switched_by"] = by or state.get("switched_by") or ""
        if on:
            state["switched_on_at"] = _now_iso()
            state["run_now"] = True
        else:
            state["switched_off_at"] = _now_iso()
            state["run_now"] = False
        _save(state)
    return view()


def heartbeat(report: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """The watcher's beat: keep what it said, answer whether it is on. A pending press is
    delivered once and then cleared, so one press means one immediate read."""
    now = time.time() if now is None else now
    with _LOCK:
        state = _load()
        watcher = {k: v for k, v in (report or {}).items() if k not in ("seen_epoch",)}
        # Keep the last cycle's tallies and runs across the short beats that do not carry them.
        previous = state.get("watcher") or {}
        for keep in ("counts", "recent", "last_cycle_at", "next_cycle_at"):
            if keep not in watcher and keep in previous:
                watcher[keep] = previous[keep]
        watcher["seen_epoch"] = now
        watcher["seen_at"] = datetime.fromtimestamp(now, timezone.utc).astimezone() \
            .isoformat(timespec="seconds")
        state["watcher"] = watcher
        run_now = bool(state.get("run_now")) and bool(state.get("enabled"))
        state["run_now"] = False
        _save(state)
        enabled = bool(state.get("enabled"))
    return {"enabled": enabled, "run_now": run_now}
