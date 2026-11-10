"""THE WHOLE GRID ON EVERY GRID CONTROL (JG, 10 Nov 2026).

"whether it's on local machine and on port 8071 or 8072, the control grid still needs to see it.
we also need to start running on the server and have it all integrated."

Each service keeps its own queue, so the 8071 wall saw nothing of a job on 8072 and the server's
service saw nothing of either. Grid Control now asks the other services on the grid for their
own wall (?local=1, so they do not ask back) and shows their running jobs, their queue and their
Grid Runners beside its own, each named by the service it is on. Stop on another service's job is
sent to that service by this one, and only to a service on the list.

The list: SDI_GRID_PEERS, comma-separated service addresses (default the two on this machine,
http://localhost:8071 and http://localhost:8072; add the server's, http://10.0.0.5:8071). A
service never counts itself: each answers with an id made when it started, and its own id is
skipped. Answers are kept for a few seconds so a wall refreshing every 4 s does not make every
peer read its whole history every 4 s; a peer that does not answer in time is shown as such.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

SERVICE_ID = uuid.uuid4().hex
DEFAULT_PEERS = "http://localhost:8071,http://localhost:8072"
_CACHE_SECONDS = 3.0
_TIMEOUT = 2.5
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def peers() -> List[str]:
    raw = os.getenv("SDI_GRID_PEERS")
    raw = DEFAULT_PEERS if raw is None else raw
    out: List[str] = []
    for x in str(raw).split(","):
        x = x.strip().rstrip("/")
        if x.startswith(("http://", "https://")) and x not in out:
            out.append(x)
    return out


def _key() -> str:
    """The key the other services take: SDI_GRID_PEER_KEY where they hold a different one
    (the server's own .env), else this service's own key."""
    if os.getenv("SDI_GRID_PEER_KEY"):
        return os.environ["SDI_GRID_PEER_KEY"]
    try:
        import config                                               # noqa: PLC0415
        return str(getattr(config, "API_KEY", "") or os.getenv("SDI_API_KEY") or "")
    except Exception:                                               # noqa: BLE001
        return os.getenv("SDI_API_KEY") or ""


def _get(url: str, opener=None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"X-SDI-Key": _key()})
    with (opener or urllib.request.urlopen)(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, body: Dict[str, Any], opener=None) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"X-SDI-Key": _key(),
                                          "Content-Type": "application/json"})
    with (opener or urllib.request.urlopen)(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _label(url: str) -> str:
    return url.split("://", 1)[-1]


def _trim(peer: str, snap: Dict[str, Any]) -> Dict[str, Any]:
    keep_live = ("run_id", "drawing_number", "client", "runner", "rag", "rag_reason",
                 "elapsed_s", "expected_s", "silent_s", "stage", "job_type", "started_at")
    keep_q = ("run_id", "drawing_number", "client", "queued_at", "start_at", "finish_at",
              "job_type")
    return {
        "service": peer, "label": _label(peer), "ok": True, "error": "",
        "host": snap.get("service_host") or "", "commit": snap.get("service_commit") or "",
        "max_runs": (snap.get("kpis") or {}).get("max_runs"),
        "live": [{k: r.get(k) for k in keep_live} for r in snap.get("live") or []],
        "queue": [{k: r.get(k) for k in keep_q} for r in snap.get("queue") or []],
        "fleet": [dict(f) for f in snap.get("fleet") or [] if not f.get("planned")],
    }


def read_peer(peer: str, opener=None, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """That service's own wall, trimmed; None when it is this service."""
    now = time.time() if now is None else now
    with _lock:
        hit = _cache.get(peer)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]
    try:
        snap = _get(peer + "/api/estimate/wall?local=1", opener)
        if snap.get("grid_service_id") == SERVICE_ID:
            out: Optional[Dict[str, Any]] = None
        else:
            out = _trim(peer, snap)
    except urllib.error.HTTPError as exc:
        out = {"service": peer, "label": _label(peer), "ok": False,
               "error": f"answered {exc.code}" + (" (an older build without Grid Control)"
                                                  if exc.code == 404 else ""),
               "live": [], "queue": [], "fleet": []}
    except Exception as exc:                                        # noqa: BLE001
        out = {"service": peer, "label": _label(peer), "ok": False,
               "error": f"not answering ({type(exc).__name__})", "live": [], "queue": [],
               "fleet": []}
    with _lock:
        _cache[peer] = (now, out)
    return out


def merge(snap: Dict[str, Any], opener=None) -> Dict[str, Any]:
    """This service's wall with the rest of the grid added: `grid` (one entry per other
    service), and their Grid Runners added to `fleet` where this service has not heard from
    them itself."""
    others = [x for x in (read_peer(p, opener) for p in peers()) if x is not None]
    snap["grid"] = others
    known = {str(f.get("runner_id") or "") for f in snap.get("fleet") or []}
    for g in others:
        for f in g.get("fleet") or []:
            rid = str(f.get("runner_id") or "")
            if rid and rid in known:
                continue
            known.add(rid)
            snap.setdefault("fleet", []).append(
                {**f, "via": g["label"], "label": f"{f.get('label') or f.get('hostname')}"
                                                  f" · via {g['label']}"})
    return snap


def stop_on(service: str, run_id: str, opener=None) -> Dict[str, Any]:
    """Stop a job on another service of the grid. Only a service on the list is asked."""
    service = str(service or "").rstrip("/")
    if service not in peers():
        raise ValueError("That service is not on this grid (SDI_GRID_PEERS).")
    return _post(f"{service}/api/estimate/{run_id}/abandon", {}, opener)
