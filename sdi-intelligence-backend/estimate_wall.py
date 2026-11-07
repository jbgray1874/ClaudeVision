"""The estimating wall (D-737): everything the wall monitor shows, worked out in one place.

JG, 7 Nov 2026: "build the full-screen page for the wall monitor ... something SUPER impressive
and techie ... runtime stats, KPIs around run times, monitoring on activity, red amber green on
running." The page polls /api/estimate/wall; this module turns the service's runs and runners
into that answer. Pure functions over plain dicts, so every figure on the wall is testable
without a service, a runner or a clock.

WHAT EACH COLOUR MEANS, said on the wall beside it, never colour alone:

  A RUN      green   on pace: under the expected time, the log still moving
             amber   slow (past the expected time), waiting for the desktop's SolidWorks, or
                     switched to the Document Manager
             red     well past the expected time, the log silent long enough to look stalled,
                     or an error line in its log
  A RUNNER   green   checked in within the last half minute
             amber   quiet but still inside the online window, or on a different build from
                     the service
             red     offline, or two processes answering to one runner
  THE FLEET  the worst of the above, so the banner never says "nominal" over a red tile

THE EXPECTED TIME is the median of this service's own finished estimates, not a figure typed
into config: the wall compares a run with the runs before it. With fewer than three to go on
there is no median, the run is green until it is silent or erring, and the wall says so.

Everything tunable is an environment setting read here, named SDI_WALL_*: the thresholds are
display judgements for the wall, not rates, and change nothing an estimate prices.
"""
from __future__ import annotations

import os
import re
import statistics
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

GREEN, AMBER, RED, GREY = "green", "amber", "red", "grey"
_ORDER = {GREY: 0, GREEN: 1, AMBER: 2, RED: 3}

# The pipeline a run's console walks through, in order, and the words that show it has got
# there. The furthest stage the log has reached is the run's stage.
STAGES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Staged", ("engine started", "[job]", "[scan]", "staged", "claimed")),
    ("Models", ("[solidworks]", "solidworks", "document manager", "[hierarchy]")),
    ("Drawings", ("[llm", "[xai", "xai", "vision", "[bom]", "dxf augmentation", "[pdf")),
    ("Route", ("[graph]", "[route", "route compiled", "[packing]")),
    ("Pricing", ("[pricing]", "parts priced", "[money]", "[invariants]")),
    ("Workbook", ("[workbook", "excel", "[qty-sweep]")),
    ("Filed", ("[deliverables]", "[record] pinned", "[walkthrough]", "filed to")),
)

_SW_WAIT = re.compile(r"Waiting for the desktop's SolidWorks|Still waiting for the desktop's "
                      r"SolidWorks", re.I)
_SW_FREE = re.compile(r"SolidWorks is free after", re.I)
_DOCMGR = re.compile(r"SWITCHING TO THE DOCUMENT MANAGER", re.I)
_ERROR = re.compile(r"\b(ERROR|FAILED|Traceback)\b")


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, "")).strip() or default)
    except ValueError:
        return default


def thresholds() -> Dict[str, float]:
    """The wall's own display thresholds (SDI_WALL_*), with what each one does."""
    return {
        "slow_over": _env_float("SDI_WALL_SLOW_OVER", 1.0),        # x expected: amber
        "late_over": _env_float("SDI_WALL_LATE_OVER", 1.6),        # x expected: red
        "silent_after_s": _env_float("SDI_WALL_SILENT_AFTER_S", 600.0),
        "runner_quiet_after_s": _env_float("SDI_WALL_RUNNER_QUIET_AFTER_S", 30.0),
        "history_days": _env_float("SDI_WALL_HISTORY_DAYS", 30.0),
    }


def fleet_plan() -> List[Dict[str, str]]:
    """The machines meant to run estimates, as SDI_WALL_FLEET names them:
    "DESKTOP-GFAAP80=Laptop,SDI-APP01=Server,NEWBOX=New box". A planned machine that has not
    checked in shows as a grey tile, so the wall shows the fleet being built, not only the
    part of it that is already up."""
    out: List[Dict[str, str]] = []
    for chunk in str(os.getenv("SDI_WALL_FLEET", "")).split(","):
        host, _, label = chunk.partition("=")
        host = host.strip()
        if host:
            out.append({"hostname": host, "label": label.strip() or host})
    return out


# ── RUNS ─────────────────────────────────────────────────────────────────────────────────
def _duration(run: Mapping[str, Any]) -> Optional[float]:
    s, f = run.get("started_at"), run.get("finished_at")
    if s and f and f >= s:
        return float(f) - float(s)
    return None


def _wait(run: Mapping[str, Any]) -> Optional[float]:
    q, s = run.get("queued_at"), run.get("started_at")
    if q and s and s >= q:
        return float(s) - float(q)
    return None


def is_estimate(run: Mapping[str, Any]) -> bool:
    return not str(run.get("job_type") or "")


def outcome(run: Mapping[str, Any]) -> str:
    """done | failed | stopped | running | queued."""
    st = str(run.get("status") or "")
    if st == "error":
        return "stopped" if re.search(r"abandon|stopped|cancel", str(run.get("error") or ""),
                                      re.I) else "failed"
    return st if st in ("done", "running", "queued") else (st or "queued")


def stage_of(log: Sequence[str]) -> Tuple[int, str]:
    """(index, name) of the furthest pipeline stage the console has reached; (-1, "") for none."""
    best = -1
    for line in log or ():
        low = str(line).lower()
        for i, (_name, words) in enumerate(STAGES):
            if i > best and any(w in low for w in words):
                best = i
    return best, (STAGES[best][0] if best >= 0 else "")


def expected_seconds(runs: Iterable[Mapping[str, Any]], now: float,
                     days: Optional[float] = None) -> Optional[float]:
    """The median of the finished estimates in the history window, or None under three."""
    days = thresholds()["history_days"] if days is None else days
    since = now - days * 86400.0
    durs = [d for r in runs if is_estimate(r) and outcome(r) == "done"
            and (r.get("finished_at") or 0) >= since
            for d in [_duration(r)] if d is not None]
    return statistics.median(durs) if len(durs) >= 3 else None


def run_rag(run: Mapping[str, Any], now: float, expected_s: Optional[float],
            th: Optional[Mapping[str, float]] = None) -> Tuple[str, str]:
    """(colour, the reason in words) for one running run."""
    th = th or thresholds()
    log = [str(x) for x in (run.get("log") or [])]
    started = float(run.get("started_at") or now)
    elapsed = max(0.0, now - started)
    last = float(run.get("last_line_at") or 0.0) or started
    silent = max(0.0, now - last)
    tail = log[-40:]
    if any(_ERROR.search(x) for x in tail):
        return RED, "an error line in its log"
    if silent >= th["silent_after_s"]:
        return RED, f"log silent for {silent / 60:.0f} min"
    if expected_s and elapsed > th["late_over"] * expected_s:
        return RED, (f"{elapsed / 60:.0f} min in, expected about {expected_s / 60:.0f}")
    waiting = None
    for x in tail:
        if _SW_WAIT.search(x):
            waiting = True
        elif _SW_FREE.search(x):
            waiting = False
    if any(_DOCMGR.search(x) for x in log):
        return AMBER, "switched to the Document Manager"
    if waiting:
        return AMBER, "waiting for the desktop's SolidWorks"
    if expected_s and elapsed > th["slow_over"] * expected_s:
        return AMBER, f"slower than usual, expected about {expected_s / 60:.0f} min"
    if expected_s:
        return GREEN, f"on pace, expected about {expected_s / 60:.0f} min"
    return GREEN, "running, no history yet to pace it against"


# ── RUNNERS ──────────────────────────────────────────────────────────────────────────────
def runner_rag(runner: Mapping[str, Any], service_commit: str = "",
               th: Optional[Mapping[str, float]] = None) -> Tuple[str, str]:
    th = th or thresholds()
    if not runner.get("online"):
        return RED, "offline"
    if runner.get("conflict"):
        return RED, "two processes answering to one runner"
    seen = float(runner.get("seconds_since_seen") or 0.0)
    build = str(runner.get("build") or "")
    if service_commit and build and not (build.startswith(service_commit[:7])
                                         or service_commit.startswith(build[:7])):
        return AMBER, f"on build {build[:7]}, the service is on {service_commit[:7]}"
    if seen > th["runner_quiet_after_s"] and not runner.get("run_id"):
        return AMBER, f"quiet for {seen:.0f} s"
    return GREEN, ("working" if runner.get("run_id") else "ready")


def worst(colours: Iterable[str]) -> str:
    out = GREY
    for c in colours:
        if _ORDER.get(c, 0) > _ORDER[out]:
            out = c
    return out


# ── KPIs ─────────────────────────────────────────────────────────────────────────────────
def _pct(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _midnight(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def kpis(runs: Sequence[Mapping[str, Any]], now: float, max_runs: int = 1) -> Dict[str, Any]:
    """The headline figures. Estimates and extracts are counted apart: an extract is minutes
    of reading, and averaging it in would flatter every run-time figure."""
    today = _midnight(now)
    week = now - 7 * 86400.0
    day = now - 86400.0
    est = [r for r in runs if is_estimate(r)]
    fin_week = [r for r in est if (r.get("finished_at") or 0) >= week]
    done_week = [r for r in fin_week if outcome(r) == "done"]
    failed_week = [r for r in fin_week if outcome(r) == "failed"]
    durs = [d for r in done_week for d in [_duration(r)] if d is not None]
    waits = [w for r in est if (r.get("started_at") or 0) >= week for w in [_wait(r)]
             if w is not None]
    running = [r for r in runs if outcome(r) == "running"]
    queued = [r for r in runs if outcome(r) == "queued"]
    judged = len(done_week) + len(failed_week)
    return {
        "runs_today": sum(1 for r in est if (r.get("queued_at") or 0) >= today),
        "done_today": sum(1 for r in est if outcome(r) == "done"
                          and (r.get("finished_at") or 0) >= today),
        "failed_today": sum(1 for r in est if outcome(r) == "failed"
                            and (r.get("finished_at") or 0) >= today),
        "extracts_today": sum(1 for r in runs if not is_estimate(r)
                              and (r.get("queued_at") or 0) >= today),
        "done_24h": sum(1 for r in est if outcome(r) == "done"
                        and (r.get("finished_at") or 0) >= day),
        "success_rate_7d": (round(100.0 * len(done_week) / judged, 1) if judged else None),
        "judged_7d": judged,
        "median_s_7d": (round(statistics.median(durs), 1) if durs else None),
        "p90_s_7d": (round(_pct(durs, 0.9), 1) if durs else None),
        "fastest_s_7d": (round(min(durs), 1) if durs else None),
        "mean_wait_s_7d": (round(sum(waits) / len(waits), 1) if waits else None),
        "running": len(running),
        "queued": len(queued),
        "max_runs": max(1, int(max_runs or 1)),
        "utilisation_pct": round(100.0 * min(len(running), max(1, int(max_runs or 1)))
                                 / max(1, int(max_runs or 1)), 0),
    }


def series(runs: Sequence[Mapping[str, Any]], now: float) -> Dict[str, Any]:
    """The two charts: the last 30 finished estimates' run times, and the last 24 hours'
    activity hour by hour (estimates done, failed, and extracts)."""
    est_done = sorted((r for r in runs if is_estimate(r) and outcome(r) in ("done", "failed")
                       and r.get("finished_at")), key=lambda r: r["finished_at"])[-30:]
    trend = [{"drawing": str(r.get("drawing_number") or ""),
              "client": str(r.get("client") or ""),
              "outcome": outcome(r),
              "seconds": (round(_duration(r), 1) if _duration(r) is not None else None),
              "finished_at": r.get("finished_at")} for r in est_done]
    start = now - 24 * 3600.0
    hours = [{"hour_start": start + h * 3600.0, "done": 0, "failed": 0, "extracts": 0}
             for h in range(24)]
    for r in runs:
        f = r.get("finished_at")
        if not f or f < start or f > now:
            continue
        slot = hours[min(23, int((f - start) // 3600))]
        if not is_estimate(r):
            slot["extracts"] += 1
        elif outcome(r) == "done":
            slot["done"] += 1
        elif outcome(r) == "failed":
            slot["failed"] += 1
    return {"run_times": trend, "activity_24h": hours}


# ── THE ONE ANSWER ───────────────────────────────────────────────────────────────────────
def _summary(r: Mapping[str, Any]) -> Dict[str, Any]:
    return {"run_id": r.get("run_id"), "drawing_number": r.get("drawing_number"),
            "client": r.get("client"), "job_type": r.get("job_type") or "",
            "status": r.get("status"), "outcome": outcome(r), "runner": r.get("runner"),
            "queued_at": r.get("queued_at"), "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
            "seconds": (round(_duration(r), 1) if _duration(r) is not None else None),
            "wait_seconds": (round(_wait(r), 1) if _wait(r) is not None else None),
            "engine_price_gbp": r.get("engine_price_gbp"),
            "error": str(r.get("error") or "")[:200]}


def snapshot(runs: Sequence[Mapping[str, Any]], runners: Sequence[Mapping[str, Any]],
             now: Optional[float] = None, max_runs: int = 1, service_commit: str = "",
             tail_lines: int = 14) -> Dict[str, Any]:
    now = time.time() if now is None else now
    th = thresholds()
    exp = expected_seconds(runs, now, th["history_days"])
    by_runner_run = {str(r.get("run_id")): r for r in runs}

    live: List[Dict[str, Any]] = []
    for r in sorted((r for r in runs if outcome(r) == "running"),
                    key=lambda r: r.get("started_at") or now):
        rag, why = run_rag(r, now, exp if is_estimate(r) else None, th)
        idx, name = stage_of(r.get("log") or [])
        started = float(r.get("started_at") or now)
        live.append({**_summary(r), "rag": rag, "rag_reason": why,
                     "elapsed_s": round(now - started, 1),
                     "expected_s": (round(exp, 1) if exp and is_estimate(r) else None),
                     "stage_index": idx, "stage": name,
                     "silent_s": round(now - (float(r.get("last_line_at") or 0) or started), 1),
                     "log_tail": [str(x) for x in (r.get("log") or [])][-tail_lines:]})

    fleet: List[Dict[str, Any]] = []
    seen_hosts = set()
    for rn in runners:
        rag, why = runner_rag(rn, service_commit, th)
        job = by_runner_run.get(str(rn.get("run_id") or ""))
        host = str(rn.get("hostname") or rn.get("runner_id") or "")
        seen_hosts.add(host.upper())
        fleet.append({"runner_id": rn.get("runner_id"), "hostname": host,
                      "label": host, "online": bool(rn.get("online")),
                      "seconds_since_seen": rn.get("seconds_since_seen"),
                      "build": str(rn.get("build") or "")[:12],
                      "capabilities": list(rn.get("capabilities") or []),
                      "rag": rag, "rag_reason": why,
                      "job": (_summary(job) if job and outcome(job) == "running" else None)})
    for plan in fleet_plan():
        matches = [f for f in fleet if f["hostname"].upper() == plan["hostname"].upper()]
        for f in matches:
            f["label"] = plan["label"]
        if not matches:
            fleet.append({"runner_id": None, "hostname": plan["hostname"],
                          "label": plan["label"], "online": False, "planned": True,
                          "rag": GREY, "rag_reason": "planned, not yet connected",
                          "job": None, "build": "", "capabilities": [],
                          "seconds_since_seen": None})

    queue = [_summary(r) for r in sorted((r for r in runs if outcome(r) == "queued"),
                                         key=lambda r: r.get("queued_at") or now)]
    recent = [_summary(r) for r in sorted(
        (r for r in runs if outcome(r) in ("done", "failed", "stopped")),
        key=lambda r: r.get("finished_at") or 0, reverse=True)[:14]]

    banner_rag = worst([x["rag"] for x in live]
                       + [x["rag"] for x in fleet if not x.get("planned")])
    banner = {GREEN: "All systems nominal", AMBER: "Attention: see the amber tiles",
              RED: "Action needed: see the red tiles", GREY: ""}[banner_rag]
    if not any(x.get("online") for x in fleet):
        banner_rag, banner = RED, "No runner connected: estimates cannot run"
    alerts = ([f"{x['drawing_number']}: {x['rag_reason']}" for x in live if x["rag"] != GREEN]
              + [f"{x['label']}: {x['rag_reason']}" for x in fleet
                 if x["rag"] in (AMBER, RED)])
    return {"now": now, "service_commit": service_commit, "banner": banner,
            "banner_rag": banner_rag, "expected_s": (round(exp, 1) if exp else None),
            "thresholds": th, "stages": [s for s, _ in STAGES],
            "kpis": kpis(runs, now, max_runs), "series": series(runs, now),
            "live": live, "fleet": fleet, "queue": queue, "recent": recent,
            "alerts": alerts}
