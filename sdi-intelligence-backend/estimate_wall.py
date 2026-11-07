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

THE DESKTOP'S SOLIDWORKS (D-738). One licence per machine, taken in turn. For each machine the
wall names the run holding it and since when, and every run waiting for it with how long it has
waited of its limit (SDI_SW_TURN_WAIT_MINUTES, 30): at the limit that run reads its models with
the Document Manager and goes on; nothing is stopped.

THE ETA IS A WINDOW (D-739). History's run times are taken NET of each run's own SolidWorks
waits, so adding this run's wait does not count a delay twice; the window is the 25th to 75th
percentile of those net times from the start, plus this run's waits so far. The window each run
was given when it started is kept, and the wall measures it against the runs that finish: the
median error and how many finished inside their window. Until enough have finished it says so
instead of claiming an accuracy. A queued job starts when the soonest slot frees.

THE EVIDENCE, NOT AN ACCURACY (D-739, the 7 Nov review: "Reader type is not estimate accuracy").
The wall states what read the models, as a fact: SolidWorks measured model; Document Manager
fallback, not yet validated; or Drawing/DXF evidence. It never grades the price by it: a run with
SolidWorks evidence can still carry wrong quantities, and a dimensioned drawing can be good
evidence. What still needs a person is shown apart, once the run has finished, from the engine's
own tally: missing costing items, decisions to confirm, and provisional assumptions. The
drawing's last result is shown beside a run, so a new price can be read against the one before.

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
# WHAT READ THE MODELS, AS PLAIN LOWER-CASE PHRASES (D-745). These were case-blind regexes of
# many alternatives, each costing about 13 ms over one run's 4,000-line console. The History
# view ran up to five per run, twice, for every run of thirty days: 300 runs held the
# interpreter for 25 s, and every other request on the service waited behind it. The same
# phrases found in the console lower-cased once cost well under a millisecond each.
_EV_MODELS_UNREAD = ("goes on without its models", "not applied", "did not produce an extract",
                     "still unread by either reader", "could not look", "models were left unread")
_EV_DOCMGR = ("document manager backup reader", "switching to the document manager")
_EV_MEASURED = ("model extract applied", "native extract applied")
_EV_SW_COULD_NOT = "solidworks could not"
# What a restored run's console starts with when only its end was kept (estimate_history).
_EV_TRIMMED = "earlier line(s) are in the run's .log file"
_ENDED = ("done", "failed", "stopped")


def sw_wait_limit_s() -> float:
    """The engine's SolidWorks wait limit, as this service's environment states it."""
    return 60.0 * _env_float("SDI_SW_TURN_WAIT_MINUTES", 30.0)


def holder_from_log(log: Sequence[str]) -> str:
    """Who the latest wait line says has SolidWorks ("12677-01-GA (run 4b1c2d) has had it for
    6 min"), or ""."""
    for line in reversed([str(x) for x in (log or ())]):
        if _SW_WAIT.search(line):
            for seg in re.split(r"[:.]\s+", line):
                if "has had it" in seg:
                    return seg.strip()
            return ""
    return ""


def evidence(run: Mapping[str, Any]) -> Dict[str, Any]:
    """What read the run's models, as its own log says: {kind, label, why, caution}. A fact
    about the evidence, never a grade of the price. A finished run is read from what was kept
    when it finished (`evidence_kept`, from its whole console), else from its console."""
    if not is_estimate(run):
        return {"kind": "extract", "label": "Pack extract", "why": "prices nothing",
                "caution": False}
    ended = outcome(run) in _ENDED
    kept = run.get("evidence_kept")
    if ended and isinstance(kept, Mapping) and kept.get("kind"):
        return {"kind": str(kept.get("kind")), "label": str(kept.get("label") or ""),
                "why": str(kept.get("why") or ""), "caution": bool(kept.get("caution"))}
    return evidence_from_log(run.get("log") or [], ended=ended,
                             sw_wait_since=run.get("sw_wait_since"))


def evidence_from_log(log: Sequence[Any], ended: bool = False,
                      sw_wait_since: Any = None) -> Dict[str, Any]:
    """The evidence an estimate's console states, read once, lower-cased, by plain phrases."""
    text = "\n".join(str(x) for x in (log or ())).lower()
    if any(p in text for p in _EV_MODELS_UNREAD):
        return {"kind": "drawings", "label": "Drawing/DXF evidence",
                "why": "the models were not read; the drawings and DXFs are the evidence",
                "caution": False}
    if any(p in text for p in _EV_DOCMGR):
        return {"kind": "dm_fallback", "label": "Document Manager fallback · not yet validated",
                "why": "saved model data only, nothing measured; the Document Manager is not "
                       "yet accepted", "caution": True}
    if any(p in text for p in _EV_MEASURED):
        if _EV_SW_COULD_NOT in text:
            return {"kind": "sw_partial", "label": "SolidWorks measured model · some files by "
                    "Document Manager (not yet validated)",
                    "why": "the files SolidWorks could not open were read from saved data",
                    "caution": True}
        return {"kind": "sw", "label": "SolidWorks measured model",
                "why": "the models were opened and measured by SolidWorks", "caution": False}
    # A RUN RESTORED AFTER A RESTART KEEPS ONLY THE END OF ITS CONSOLE, where the model read is
    # not. Its evidence is not known; it is never said to be a read that was not reached.
    if ended and text[:200].find(_EV_TRIMMED) >= 0:
        return {"kind": "unknown", "label": "Not known · only the end of its log was kept",
                "why": "the service restarted after this run and kept the last lines of its "
                       "console; the full console is in the run's .log file", "caution": False}
    if sw_wait_since:
        return {"kind": "pending", "label": "Waiting for SolidWorks",
                "why": "the models are read when the licence is free", "caution": False}
    return {"kind": "pending", "label": "Model read not reached yet", "why": "",
            "caution": False}


def open_items(run: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The engine's own tally of what still needs a person, for a finished run, or None."""
    t = run.get("review") if isinstance(run.get("review"), Mapping) else None
    if not t:
        return None
    return {k: t.get(k) for k in ("total", "missing", "decisions", "quantity_checks",
                                  "provisional", "phrase")}


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
    # Read once, lower-cased: a stage's words never hold a line break, so a word found in the
    # joined console was found on one of its lines (D-745).
    low = "\n".join(str(x) for x in (log or ())).lower()
    best = -1
    for i, (_name, words) in enumerate(STAGES):
        if any(w in low for w in words):
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
        return AMBER, "switched to the Document Manager after its SolidWorks wait"
    if waiting or run.get("sw_wait_since"):
        since = float(run.get("sw_wait_since") or 0.0)
        held = holder_from_log(log)
        waited = (f", {max(0.0, now - since) / 60:.0f} of {sw_wait_limit_s() / 60:.0f} min"
                  if since else "")
        return AMBER, (f"waiting for the desktop's SolidWorks{waited}"
                       + (f"; {held}" if held else ""))
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


# ── ETA, THE QUEUE, THE LICENCE ──────────────────────────────────────────────────────────
def net_duration(run: Mapping[str, Any]) -> Optional[float]:
    """A finished run's time less its own SolidWorks waits (D-739)."""
    d = _duration(run)
    if d is None:
        return None
    return max(0.0, d - float(run.get("sw_waited_s") or 0.0))


def predict_window(runs: Iterable[Mapping[str, Any]], now: float,
                   days: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """{lo_s, mid_s, hi_s, n, basis}: the 25th, 50th and 75th percentile of the finished
    estimates' net run times in the history window, or None with fewer than three."""
    days = thresholds()["history_days"] if days is None else days
    since = now - days * 86400.0
    nets = sorted(n for r in runs if is_estimate(r) and outcome(r) == "done"
                  and (r.get("finished_at") or 0) >= since
                  for n in [net_duration(r)] if n is not None)
    if len(nets) < 3:
        return None
    return {"lo_s": round(_pct(nets, 0.25), 1), "mid_s": round(_pct(nets, 0.5), 1),
            "hi_s": round(_pct(nets, 0.75), 1), "n": len(nets),
            "basis": f"25th-75th percentile of {len(nets)} finished estimates, net of "
                     f"SolidWorks waits"}


def eta(run: Mapping[str, Any], now: float, window: Optional[Mapping[str, Any]]
        ) -> Dict[str, Any]:
    """{eta_lo_at, eta_at, eta_hi_at, overdue_s, waited_s} for a running estimate: its start,
    plus the window it was given (or today's), plus its SolidWorks waits so far."""
    win = run.get("predicted") if isinstance(run.get("predicted"), Mapping) and \
        run.get("predicted") else window
    if not win or not is_estimate(run):
        return {}
    started = float(run.get("started_at") or now)
    waited = float(run.get("sw_waited_s") or 0.0) + (
        max(0.0, now - float(run["sw_wait_since"])) if run.get("sw_wait_since") else 0.0)
    lo, mid, hi = (started + float(win[k]) + waited for k in ("lo_s", "mid_s", "hi_s"))
    return {"eta_lo_at": round(lo, 1), "eta_at": round(mid, 1), "eta_hi_at": round(hi, 1),
            "overdue_s": round(max(0.0, now - hi), 1), "waited_s": round(waited, 1)}


def eta_error(runs: Sequence[Mapping[str, Any]], now: float) -> Dict[str, Any]:
    """How good the ETAs have been: each finished estimate's net time against the window it
    was given when it started."""
    errs, inside = [], 0
    for r in runs:
        win = r.get("predicted") if isinstance(r.get("predicted"), Mapping) else None
        net = net_duration(r)
        if not win or net is None or not is_estimate(r) or outcome(r) != "done":
            continue
        errs.append(abs(net - float(win.get("mid_s") or 0.0)))
        inside += 1 if float(win.get("lo_s") or 0) <= net <= float(win.get("hi_s") or 0) else 0
    if not errs:
        return {"n": 0, "median_abs_error_s": None, "inside_pct": None}
    return {"n": len(errs), "median_abs_error_s": round(statistics.median(errs), 1),
            "inside_pct": round(100.0 * inside / len(errs), 0)}


def queue_etas(queue: Sequence[Mapping[str, Any]], live: Sequence[Mapping[str, Any]],
               now: float, max_runs: int, expected_s: Optional[float],
               extract_s: Optional[float]) -> List[Dict[str, Any]]:
    """When each queued job should start and finish: the soonest slot takes the next job."""
    slots = max(1, int(max_runs or 1))
    free = sorted(max(now, float(x.get("eta_at") or (now + (expected_s or 0.0))))
                  for x in live)[:slots]
    free += [now] * (slots - len(free))
    out = []
    for q in queue:
        dur = expected_s if is_estimate(q) else extract_s
        if not dur:
            out.append({"run_id": q.get("run_id"), "start_at": None, "finish_at": None})
            continue
        i = min(range(len(free)), key=lambda k: free[k])
        start = free[i]
        free[i] = start + dur
        out.append({"run_id": q.get("run_id"), "start_at": round(start, 1),
                    "finish_at": round(start + dur, 1)})
    return out


def solidworks_panel(running: Sequence[Mapping[str, Any]], runners: Sequence[Mapping[str, Any]],
                     now: float) -> List[Dict[str, Any]]:
    """Per machine: the run holding the desktop's SolidWorks, since when, and who waits."""
    host_of = {str(r.get("runner_id") or ""): str(r.get("hostname") or r.get("runner_id") or "")
               for r in runners}
    limit = sw_wait_limit_s()
    machines: Dict[str, Dict[str, Any]] = {}
    for rn in runners:
        if rn.get("online"):
            h = str(rn.get("hostname") or rn.get("runner_id") or "")
            machines.setdefault(h, {"host": h, "holder": None, "waiting": [], "said_holder": ""})
    for r in running:
        h = host_of.get(str(r.get("runner") or ""), str(r.get("runner") or ""))
        m = machines.setdefault(h, {"host": h, "holder": None, "waiting": [], "said_holder": ""})
        if r.get("sw_turn_at"):
            m["holder"] = {"run_id": r.get("run_id"), "drawing_number": r.get("drawing_number"),
                           "client": r.get("client"), "since": r.get("sw_turn_at"),
                           "held_s": round(max(0.0, now - float(r["sw_turn_at"])), 1)}
        if r.get("sw_wait_since"):
            waited = max(0.0, now - float(r["sw_wait_since"]))
            m["waiting"].append({"run_id": r.get("run_id"),
                                 "drawing_number": r.get("drawing_number"),
                                 "client": r.get("client"), "waited_s": round(waited, 1),
                                 "limit_s": limit, "left_s": round(max(0.0, limit - waited), 1)})
            m["said_holder"] = m["said_holder"] or holder_from_log(r.get("log") or [])
    for m in machines.values():
        m["waiting"].sort(key=lambda w: -w["waited_s"])
        m["state"] = "in_use" if m["holder"] or m["waiting"] else "free"
    return sorted(machines.values(), key=lambda m: m["host"])


def last_result(runs: Sequence[Mapping[str, Any]], drawing: Any, client: Any,
                before: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The drawing's last finished estimate with a price, for reading a new price against."""
    best = None
    for r in runs:
        if (is_estimate(r) and outcome(r) == "done" and r.get("engine_price_gbp")
                and str(r.get("drawing_number") or "") == str(drawing or "")
                and str(r.get("client") or "") == str(client or "")
                and (before is None or (r.get("finished_at") or 0) < before)):
            if best is None or (r.get("finished_at") or 0) > (best.get("finished_at") or 0):
                best = r
    return ({"engine_price_gbp": best.get("engine_price_gbp"),
             "finished_at": best.get("finished_at")} if best else None)


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


# ── COMPUTE (D-743) ─────────────────────────────────────────────────────────────────────
# JG, 7 Nov 2026: "a graphical representation of the compute resources available on the
# laptop ... what compute resource each job is taking and it updates dynamically and the
# remaining compute is also available. we can then add the server downstairs and the new
# machine." Every runner measures its machine, and its own engine's processes, every few
# seconds and sends it with the calls it already makes. Per machine the newest sample of any
# of its runners gives the totals. A job's share is its engine's own processes. SolidWorks and
# Excel are not the engine's children (Windows starts them for it), so they are shown as
# themselves, and given to a run only where it is certain: SolidWorks to the run holding the
# licence, Excel to the only run on the machine. The rest of the machine is "other".
COMPUTE_FRESH_S = 30.0
COMPUTE_STALE_S = 120.0
_PER_PROCESS_NOTE = ("Only the machine's totals are measured here: what each job and "
                     "SolidWorks use needs psutil in the runner's Python.")


def _n(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _share(segments: List[Dict[str, Any]], total: Optional[float]) -> float:
    """What is left of `total` once the named segments are taken, never below nothing. Samples
    from two runners are seconds apart, so named shares can add up past the total: they are
    scaled back to fit rather than shown as more than the machine has."""
    named = sum(x["value"] for x in segments)
    if total is None:
        return 0.0
    if named > total > 0:
        for x in segments:
            x["value"] = round(x["value"] * total / named, 2)
        return 0.0
    return round(max(0.0, total - named), 2)


def compute_view(runners: Sequence[Mapping[str, Any]], live: Sequence[Mapping[str, Any]],
                 now: float) -> Dict[str, Any]:
    """The machines (connected and planned) with what each is using and what is free; and each
    live run's own use, by run id."""
    lane = {str(r.get("run_id")): (i + 1, r) for i, r in enumerate(live)}
    host_of_runner = {str(rn.get("runner_id")): str(rn.get("hostname") or "").upper()
                      for rn in runners}
    hosts: Dict[str, Dict[str, Any]] = {}
    for rn in runners:
        c = rn.get("compute") or {}
        if not isinstance(c, dict) or not c:
            continue
        name = str(c.get("host") or rn.get("hostname") or rn.get("runner_id") or "").strip()
        key = name.upper()
        got = _n(c.get("received_at")) or _n(c.get("at")) or 0.0
        h = hosts.setdefault(key, {"host": name, "sample": {}, "got": 0.0, "jobs": {},
                                   "history": []})
        if got > h["got"]:
            h.update(sample=c, got=got, history=list(rn.get("compute_history") or []))
        if now - got <= COMPUTE_STALE_S:
            for run_id, use in (c.get("jobs") or {}).items():
                if str(run_id) in lane and isinstance(use, dict):
                    h["jobs"][str(run_id)] = use
    labels = {p["hostname"].upper(): p["label"] for p in fleet_plan()}
    machines: List[Dict[str, Any]] = []
    runs: Dict[str, Dict[str, Any]] = {}
    for key, h in hosts.items():
        c, age = h["sample"], round(now - h["got"])
        cpu, total = _n(c.get("cpu_pct")), _n(c.get("mem_total_gb"))
        used = _n(c.get("mem_used_gb"))
        apps = c.get("apps") or {}
        per_process = c.get("by") == "psutil"
        cpu_seg: List[Dict[str, Any]] = []
        mem_seg: List[Dict[str, Any]] = []
        for run_id, use in sorted(h["jobs"].items(), key=lambda kv: lane[kv[0]][0]):
            n, r = lane[run_id]
            label = f"Run {n} · {r.get('drawing_number') or run_id}"
            cpu_seg.append({"kind": "estimate", "key": run_id, "label": label,
                            "value": round(_n(use.get("cpu_pct")) or 0.0, 2)})
            mem_seg.append({"kind": "estimate", "key": run_id, "label": label,
                            "value": round(_n(use.get("mem_gb")) or 0.0, 2)})
        for app, kind in (("SolidWorks", "solidworks"), ("Excel", "excel")):
            a = apps.get(app)
            if isinstance(a, dict) and (a.get("count") or 0) > 0:
                cpu_seg.append({"kind": kind, "key": kind, "label": app,
                                "value": round(_n(a.get("cpu_pct")) or 0.0, 2)})
                mem_seg.append({"kind": kind, "key": kind, "label": app,
                                "value": round(_n(a.get("mem_gb")) or 0.0, 2)})
        cpu_other = _share(cpu_seg, cpu)
        mem_other = _share(mem_seg, used)
        machine_runs = [rid for rid, (n, r) in lane.items()
                        if host_of_runner.get(str(r.get("runner") or "")) == key]
        machines.append({
            "host": h["host"], "label": labels.get(key, h["host"]), "connected": True,
            "fresh": age <= COMPUTE_FRESH_S, "age_s": age, "measured_by": c.get("by") or "",
            "cpu_pct": cpu, "threads": _n(c.get("threads")), "cores": _n(c.get("cores")),
            "mem_total_gb": total, "mem_used_gb": used, "mem_free_gb": _n(c.get("mem_free_gb")),
            "disk": c.get("disk") or "", "disk_free_gb": _n(c.get("disk_free_gb")),
            "disk_total_gb": _n(c.get("disk_total_gb")),
            "cpu": {"segments": cpu_seg, "other": cpu_other,
                    "free": round(max(0.0, 100.0 - (cpu or 0.0)), 2) if cpu is not None else None},
            "mem": {"segments": mem_seg, "other": mem_other,
                    "free": (round(max(0.0, total - used), 2)
                             if total is not None and used is not None else None)},
            "history": [x for x in h["history"] if now - (x[0] or 0) <= 900][-180:],
            "runs_here": len(machine_runs),
            "note": "" if per_process else _PER_PROCESS_NOTE})
        for run_id in machine_runs:
            n, r = lane[run_id]
            use = h["jobs"].get(run_id)
            holds_sw = bool(r.get("sw_turn_at")) and not r.get("sw_wait_since")
            sw, xl = apps.get("SolidWorks"), apps.get("Excel")
            runs[run_id] = {
                "host": h["host"], "fresh": age <= COMPUTE_FRESH_S, "per_process": per_process,
                "cpu_pct": _n((use or {}).get("cpu_pct")), "mem_gb": _n((use or {}).get("mem_gb")),
                "procs": _n((use or {}).get("procs")),
                "solidworks": ({"cpu_pct": _n(sw.get("cpu_pct")), "mem_gb": _n(sw.get("mem_gb"))}
                               if holds_sw and isinstance(sw, dict) and sw.get("count") else None),
                "excel": ({"cpu_pct": _n(xl.get("cpu_pct")), "mem_gb": _n(xl.get("mem_gb"))}
                          if len(machine_runs) == 1 and isinstance(xl, dict) and xl.get("count")
                          else None),
                "machine_cpu_pct": cpu, "machine_mem_free_gb": _n(c.get("mem_free_gb"))}
    for plan in fleet_plan():
        if plan["hostname"].upper() not in hosts:
            machines.append({"host": plan["hostname"], "label": plan["label"],
                             "connected": False, "planned": True})
    # Connected machines first, then in the order SDI_WALL_FLEET names them.
    order = {p["hostname"].upper(): i for i, p in enumerate(fleet_plan())}
    machines.sort(key=lambda m: (not m.get("connected"), order.get(str(m["host"]).upper(), 99),
                                 str(m.get("label"))))
    return {"machines": machines, "runs": runs}


# ── HISTORY (D-744) ─────────────────────────────────────────────────────────────────────
# JG, 7 Nov 2026: "the control panel should have the entire stats / history of runs and parity
# runs, etc. and we can build vizuals around that and details." This is the service's own
# record of the runs it holds (thirty days, restart-safe: estimate_history): how each ended,
# how long it took and waited, which machine ran it, what read its models and what was left
# open. Every estimate ever filed is counted separately, from AISheets (src/run_history.py).
def _p90(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return values[0] if values else None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]


def history_view(runs: Sequence[Mapping[str, Any]], now: Optional[float] = None,
                 days: int = 30, table: int = 400) -> Dict[str, Any]:
    now = time.time() if now is None else now
    since = _midnight(now) - (days - 1) * 86400
    kept = [r for r in runs if outcome(r) in ("done", "failed", "stopped")
            and float(r.get("finished_at") or 0) >= since]
    est = [r for r in kept if is_estimate(r)]
    done = [r for r in est if outcome(r) == "done"]
    durs = [d for r in done for d in [_duration(r)] if d is not None]
    evs: Dict[int, Dict[str, Any]] = {}

    def ev_of(r: Mapping[str, Any]) -> Dict[str, Any]:
        if id(r) not in evs:
            evs[id(r)] = evidence(r)
        return evs[id(r)]
    waits = [w for r in est for w in [_wait(r)] if w is not None]
    judged = [r for r in est if outcome(r) in ("done", "failed")]
    daily = []
    for i in range(days):
        start = since + i * 86400
        inside = [r for r in kept if start <= float(r.get("finished_at") or 0) < start + 86400]
        d_est = [r for r in inside if is_estimate(r)]
        d_durs = [d for r in d_est if outcome(r) == "done" for d in [_duration(r)] if d is not None]
        daily.append({"day_start": start,
                      "done": sum(1 for r in d_est if outcome(r) == "done"),
                      "failed": sum(1 for r in d_est if outcome(r) == "failed"),
                      "stopped": sum(1 for r in d_est if outcome(r) == "stopped"),
                      "extracts": sum(1 for r in inside if not is_estimate(r)),
                      "median_s": round(statistics.median(d_durs), 1) if d_durs else None})
    clients: Dict[str, Dict[str, Any]] = {}
    machines: Dict[str, Dict[str, Any]] = {}
    evidence_mix: Dict[str, Dict[str, Any]] = {}
    for r in est:
        c = clients.setdefault(str(r.get("client") or "Unknown"), {
            "client": str(r.get("client") or "Unknown"), "estimates": 0, "done": 0, "failed": 0,
            "durations": [], "last_at": 0.0, "drawings": set()})
        c["estimates"] += 1
        c["done"] += outcome(r) == "done"
        c["failed"] += outcome(r) == "failed"
        c["drawings"].add(str(r.get("drawing_number") or "").lower())
        c["last_at"] = max(c["last_at"], float(r.get("finished_at") or 0))
        if outcome(r) == "done" and _duration(r) is not None:
            c["durations"].append(_duration(r))
        if outcome(r) == "done":
            ev = ev_of(r)
            e = evidence_mix.setdefault(ev["kind"], {"kind": ev["kind"], "label": ev["label"],
                                                     "count": 0, "caution": ev["caution"]})
            e["count"] += 1
    for r in kept:
        host = re.sub(r"-[0-9a-f]{6,}(-s\d+)?$", "", str(r.get("runner") or "unknown"))
        m = machines.setdefault(host, {"machine": host, "runs": 0, "busy_s": 0.0, "failed": 0})
        m["runs"] += 1
        m["busy_s"] += _duration(r) or 0.0
        m["failed"] += outcome(r) == "failed"
    # Only a run that carries the engine's tally counts; one without says nothing, not "none".
    reviews = [r.get("review") for r in done
               if isinstance(r.get("review"), Mapping) and r["review"].get("total") is not None]
    rows = []
    for r in sorted(kept, key=lambda r: float(r.get("finished_at") or 0), reverse=True)[:table]:
        ev = ev_of(r)
        rows.append({**_summary(r), "units": r.get("units"),
                     "quantity_prices": list(r.get("quantity_prices") or [])[:8],
                     "evidence": ev["label"], "evidence_caution": ev["caution"],
                     "open_items": open_items(r),
                     "sw_waited_s": r.get("sw_waited_s") or 0.0,
                     "walkthrough_url": r.get("walkthrough_url") or "",
                     "requested_by": r.get("requested_by") or ""})
    return {
        "days": days, "since": since,
        "totals": {"estimates": len(est), "extracts": len(kept) - len(est),
                   "done": len(done), "failed": sum(1 for r in est if outcome(r) == "failed"),
                   "stopped": sum(1 for r in est if outcome(r) == "stopped"),
                   "success_pct": (round(100.0 * len(done) / len(judged), 1) if judged else None),
                   "median_s": round(statistics.median(durs), 1) if durs else None,
                   "p90_s": round(_p90(durs), 1) if durs else None,
                   "fastest_s": round(min(durs), 1) if durs else None,
                   "engine_hours": round(sum(durs) / 3600.0, 1),
                   "mean_wait_s": round(statistics.mean(waits), 1) if waits else None,
                   "drawings": len({str(r.get('drawing_number') or '').lower() for r in est}),
                   "clients": len(clients),
                   "open_items_median": (statistics.median([float(t.get("total") or 0) for t in reviews])
                                         if reviews else None),
                   "with_review": len(reviews)},
        "daily": daily,
        "clients": sorted(({"client": c["client"], "estimates": c["estimates"], "done": c["done"],
                            "failed": c["failed"], "drawings": len(c["drawings"]),
                            "median_s": (round(statistics.median(c["durations"]), 1)
                                         if c["durations"] else None),
                            "last_at": c["last_at"]} for c in clients.values()),
                          key=lambda c: (-c["estimates"], c["client"])),
        "machines": sorted(({**m, "busy_s": round(m["busy_s"], 1)} for m in machines.values()),
                           key=lambda m: -m["runs"]),
        "evidence": sorted(evidence_mix.values(), key=lambda e: -e["count"]),
        "runs": rows, "runs_left_out": max(0, len(kept) - table)}


def snapshot(runs: Sequence[Mapping[str, Any]], runners: Sequence[Mapping[str, Any]],
             now: Optional[float] = None, max_runs: int = 1, service_commit: str = "",
             tail_lines: int = 80) -> Dict[str, Any]:
    now = time.time() if now is None else now
    th = thresholds()
    exp = expected_seconds(runs, now, th["history_days"])
    k = kpis(runs, now, max_runs)
    k["eta"] = eta_error(runs, now)
    window = predict_window(runs, now, th["history_days"])
    ext_durs = [d for r in runs if not is_estimate(r) and outcome(r) == "done"
                for d in [_duration(r)] if d is not None]
    extract_s = statistics.median(ext_durs) if len(ext_durs) >= 3 else None
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
                     **eta(r, now, window),
                     "evidence": evidence(r),
                     "last_result": last_result(runs, r.get("drawing_number"), r.get("client")),
                     "sw_turn_at": r.get("sw_turn_at") or 0.0,
                     "sw_wait_since": r.get("sw_wait_since") or 0.0,
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
    # A SECOND RUNNER ON ONE DESKTOP IS THAT DESKTOP'S SLOT (SCRUM-183): its runner id ends -sN.
    def _slot(f: Dict[str, Any]) -> str:
        m = re.search(r"-s(\d+)$", str(f.get("runner_id") or ""))
        return f" · slot {m.group(1)}" if m and int(m.group(1)) > 1 else ""
    for f in fleet:
        f["label"] = f["label"] + _slot(f)
    for plan in fleet_plan():
        matches = [f for f in fleet if f["hostname"].upper() == plan["hostname"].upper()]
        for f in matches:
            f["label"] = plan["label"] + _slot(f)
        if not matches:
            fleet.append({"runner_id": None, "hostname": plan["hostname"],
                          "label": plan["label"], "online": False, "planned": True,
                          "rag": GREY, "rag_reason": "planned, not yet connected",
                          "job": None, "build": "", "capabilities": [],
                          "seconds_since_seen": None})

    compute = compute_view(runners, live, now)
    for x in live:
        x["compute"] = compute["runs"].get(str(x.get("run_id")))

    queued = sorted((r for r in runs if outcome(r) == "queued"),
                    key=lambda r: r.get("queued_at") or now)
    when = {q["run_id"]: q for q in queue_etas(queued, live, now, max_runs,
                                               (window or {}).get("mid_s") or exp, extract_s)}
    queue = [{**_summary(r), "start_at": (when.get(r.get("run_id")) or {}).get("start_at"),
              "finish_at": (when.get(r.get("run_id")) or {}).get("finish_at")} for r in queued]
    recent = [{**_summary(r), "open_items": open_items(r)} for r in sorted(
        (r for r in runs if outcome(r) in ("done", "failed", "stopped")),
        key=lambda r: r.get("finished_at") or 0, reverse=True)[:12]]

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
            "window": window,
            "thresholds": th, "stages": [s for s, _ in STAGES],
            "kpis": k, "series": series(runs, now),
            "live": live, "fleet": fleet, "queue": queue, "recent": recent,
            "compute": compute["machines"],
            "solidworks": solidworks_panel([r for r in runs if outcome(r) == "running"],
                                           runners, now),
            "sw_wait_limit_s": sw_wait_limit_s(),
            "alerts": alerts}
