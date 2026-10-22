"""
hr_blip.py — BrightHR Blip attendance: who is currently clocked in.
Queries the Blip clockings endpoint per employee (employeeId is required).
Uses a thread pool to run requests concurrently — 192 employees in ~20s
instead of ~170s sequential.

Writes output to:
  HR_SNAPSHOT_DIR:  blip_<UTC>.json (audit) + blip_latest.json (pointer)
  HR_OUTPUT_DIR:    blip_onsite_<UTC>.json (browsable by COO in portal)
"""
import json
import os
import sys
import datetime
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import hr_config as cfg

BLIP_URL = "https://api.bright.hr/blip/v1/clockings/query"
MAX_WORKERS = 5   # concurrent requests — stays well under BrightHR rate limit
MAX_ATTEMPTS = 6  # per employee, counting rate-limited tries
MAX_PAUSE = 60    # seconds, the longest single rate-limit pause
LOCK_STALE_MINUTES = 30   # a lock older than this was left by a run that died


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp():
    return _now().strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str):
    line = f"{_now().isoformat()}  {msg}"
    print(line)
    try:
        Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
        with open(Path(cfg.HR_SNAPSHOT_DIR) / "hr_pipeline.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _atomic_write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _get_token() -> str:
    import hr_brighthr as bh
    return bh.get_access_token()


def _load_active_employees() -> list:
    p = Path(cfg.HR_SNAPSHOT_DIR) / "latest.json"
    if not p.exists():
        raise RuntimeError("No employee snapshot — run hr_pull.py first.")
    return json.loads(p.read_text(encoding="utf-8")).get("records") or []


def _current_staff(token: str) -> tuple:
    """Everyone BrightHR lists as employed, read fresh on every run.

    Only these people are asked about, so anyone missing here is missing from
    the on-site list however long they have been clocked in. The saved list
    (latest.json) was the source and failed twice over: only hr_pull.py writes
    it and nothing runs that on a schedule, so a new starter was never asked
    about; and it keeps only staff with an email address, which leaves out
    warehouse staff who have none. The clockings lookup needs only the
    BrightHR id, so that is all this requires.

    Returns (staff, warning). If BrightHR's staff list cannot be read, the saved
    list is used and the warning says so, rather than the run failing.
    """
    try:
        import hr_brighthr as bh
        staff = [e for e in (bh.normalise_employee(r) for r in bh.fetch_employees(token))
                 if e["id"] and not e["terminated"]]
        if staff:
            return staff, None
        reason = "BrightHR returned an empty staff list"
    except Exception as exc:              # fall back, and say so
        reason = f"BrightHR's staff list could not be read ({exc})"
    saved = _load_active_employees()
    return saved, (f"{reason}; checked the saved list of {len(saved)} instead, which can "
                   f"miss new starters and staff without an email address.")


class _Throttle:
    """One rate-limit pause shared by every worker.

    When BrightHR answers 429, every worker waits, not just the one that was
    refused. Workers backing off one at a time kept the other four hammering,
    so on a busy afternoon nearly every query was refused three times and the
    run came back degraded.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._resume_at = 0.0

    def wait(self):
        while True:
            with self._lock:
                delay = self._resume_at - time.monotonic()
            if delay <= 0:
                return
            time.sleep(delay)

    def pause(self, seconds: float) -> bool:
        """Hold every worker for seconds. True if this extended the pause."""
        with self._lock:
            until = time.monotonic() + seconds
            if until <= self._resume_at:
                return False
            self._resume_at = until
            return True


def _retry_after(response, attempt: int) -> float:
    """BrightHR's Retry-After if it gives one, else 10s, 20s, 30s... capped."""
    try:
        wait = float(response.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        wait = 10 * (attempt + 1)
    return max(1.0, min(wait, MAX_PAUSE))


def _acquire_lock():
    """One Blip run at a time. Two at once double the request rate and both
    get rate-limited: the portal button pressed during a scheduled run, or
    twice. Returns the lock path, or None if another run holds it."""
    path = Path(cfg.HR_SNAPSHOT_DIR) / "blip.lock"
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue                     # released as we looked: try again
            if age < LOCK_STALE_MINUTES * 60:
                return None
            _log(f"  removing a Blip lock left {age / 60:.0f} min ago by a run that did not finish")
            try:
                path.unlink()
            except OSError:
                return None
            continue
        os.write(fd, f"{os.getpid()} {_now().isoformat()}".encode())
        os.close(fd)
        return path
    return None


def _query_one(token: str, employee_id: str, from_dt: str, throttle=None) -> tuple:
    """
    Query clockings for one employee at a point in time.
    Returns (clockings, ok) where clockings are active at that moment (i.e.
    still clocked in) and ok is False if the query itself failed.

    The distinction matters: a failed query looks identical to "not clocked in"
    if you only return a list, so a bad token or a BrightHR outage would report
    an empty building instead of an error — and anything downstream would
    publish that as the fire roll call.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"filters": {"employeeId": employee_id, "from": from_dt}}
    throttle = throttle or _Throttle()
    for attempt in range(MAX_ATTEMPTS):
        throttle.wait()
        try:
            r = requests.post(BLIP_URL, json=body, headers=headers,
                              timeout=cfg.BH_TIMEOUT)
            if r.status_code == 404:
                return [], True          # no clockings for this employee
            if r.status_code == 429:
                wait = _retry_after(r, attempt)
                if throttle.pause(wait):
                    _log(f"  [429] BrightHR rate limit - all workers pausing {wait:.0f}s")
                continue
            if r.status_code != 200:
                _log(f"  [{r.status_code}] employee {employee_id} — query failed")
                return [], False
            return r.json().get("items") or [], True
        except requests.RequestException as exc:
            _log(f"  [error] employee {employee_id} — {exc}")
            return [], False
    return [], False                     # rate limited on every attempt


def _write_output_file(on_site: list, summary: dict):
    """
    Write a clean, dated, browsable output file to HR_OUTPUT_DIR
    so the COO can view who is on site in the portal Files view.
    Email stripped — names only.

    NON-FATAL, but never silent: returns (path, error). The snapshot is already
    saved by the time this runs, so a failure here loses nothing - but it used
    to vanish from the response entirely, leaving a run that said OK with no
    file to show for it. The caller now surfaces the reason.
    """
    out_dir = getattr(cfg, "HR_OUTPUT_DIR", "").strip()
    if not out_dir:
        _log("HR_OUTPUT_DIR not set — skipping browsable output file.")
        return None, "HR_OUTPUT_DIR is not set."
    # Built before any I/O so the fallback copy below still has it if the
    # share turns out to be unreachable.
    payload = {
        "generated": summary["timestamp"],
        "query_type": "point_in_time",
        "employees_checked": summary["employees_checked"],
        "on_site": summary["on_site"],
        "status": summary["status"],
        "staff_on_site": [
            {
                "first_name": e.get("first_name", ""),
                "surname": e.get("surname", ""),
                "clocked_in": e.get("clocking", {}).get("start", ""),
            }
            for e in on_site
        ],
    }
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(out_dir) / f"blip_onsite_{_stamp()}.json"
        _atomic_write_json(out_path, payload)
        _log(f"Output file written -> {out_path}")
        return str(out_path), None
    except OSError as exc:
        reason = f"Could not write to HR_OUTPUT_DIR ({out_dir}): {exc}"
        # A drive letter is the usual culprit: a Windows service runs under an
        # account that has no user drive mappings, so K:\ simply does not exist
        # for it even though it works interactively.
        if _looks_like_mapped_drive(out_dir):
            reason += (
                f". {out_dir[:2]} is a mapped drive - a Windows service cannot see user "
                f"drive mappings. Set HR_OUTPUT_DIR to the UNC path instead "
                f"(e.g. \\\\sdi-dc01\\shareddata$\\Shared\\IT\\HRSystemsOutput)."
            )
        _log(f"OUTPUT FILE FAILED: {reason}")
        fallback = _write_fallback_copy(payload)
        if fallback:
            reason += f" A local copy was written to {fallback} instead."
        return None, reason


def _looks_like_mapped_drive(path: str) -> bool:
    r"""True for a drive-letter path like K:\..., false for a UNC \\server\share."""
    return len(path) > 1 and path[1] == ":" and path[0].isalpha()


def _write_fallback_copy(payload: dict):
    """Keep a copy beside the snapshot when the output share is unreachable."""
    try:
        path = Path(cfg.HR_SNAPSHOT_DIR) / f"blip_onsite_{_stamp()}.json"
        _atomic_write_json(path, payload)
        return str(path)
    except OSError:
        return None


def run_blip() -> dict:
    Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock()
    if lock is None:
        reason = ("A BrightHR Blip query is already running (the scheduled task or "
                  "another press). Wait for it to finish, then try again.")
        _log(f"BLIP busy: {reason}")
        return {"timestamp": _now().isoformat(), "status": "busy", "on_site": 0,
                "employees_checked": 0, "query_failures": 0, "warnings": [reason]}
    try:
        return _run_blip()
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _run_blip() -> dict:
    _log("BLIP start — querying current clockings (concurrent)")

    token = _get_token()
    employees, staff_warning = _current_staff(token)
    if staff_warning:
        _log(f"  {staff_warning}")
    emp_index = {e["id"]: e for e in employees if e.get("id")}
    _log(f"  {len(employees)} active employees to check")

    # BrightHR: 'from' without 'to' is a POINT-IN-TIME filter — returns clockings
    # active at exactly that moment. Use NOW to get who is currently on site.
    from_dt = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _log(f"  Querying at point-in-time {from_dt} with {MAX_WORKERS} workers")

    on_site = []
    # Whose query failed, not just how many. A failed lookup is "unknown", and
    # the push must not read it as "clocked out" - with sign-out live, that
    # would take someone in the building off the fire roll for a cycle.
    query_failed = []
    checked = 0
    failures = 0
    emp_list = [e for e in employees if e.get("id")]

    # ── concurrent queries ──
    throttle = _Throttle()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_query_one, token, emp["id"], from_dt, throttle): emp
            for emp in emp_list
        }
        for future in as_completed(futures):
            emp = futures[future]
            checked += 1
            try:
                clockings, ok = future.result()
            except Exception:
                clockings, ok = [], False
            if not ok:
                failures += 1
                query_failed.append({
                    "id": emp.get("id"),
                    "first_name": emp.get("first_name", ""),
                    "surname": emp.get("surname", ""),
                    "email": emp.get("email", ""),
                })
            if clockings:
                on_site.append({
                    "id": emp.get("id"),
                    "first_name": emp.get("first_name", ""),
                    "surname": emp.get("surname", ""),
                    "email": emp.get("email", ""),
                    "clocking": clockings[0],
                })
            if checked % 40 == 0:
                _log(f"  Progress: {checked}/{len(emp_list)} checked, {len(on_site)} on site")

    on_site.sort(key=lambda x: x.get("first_name", "").lower())

    fail_pct = (failures / len(emp_list) * 100) if emp_list else 0.0
    summary = {
        "timestamp": _now().isoformat(),
        "employees_checked": len(emp_list),
        "on_site": len(on_site),
        "query_failures": failures,
        "fail_pct": round(fail_pct, 2),
        "status": "ok",
        "warnings": [staff_warning] if staff_warning else [],
    }

    # A snapshot built from failed queries under-reports who is in the building.
    # Mark it degraded so the InVentry load refuses it rather than publishing an
    # incomplete evacuation list.
    if failures and fail_pct > cfg.BLIP_MAX_FAIL_PCT:
        summary["status"] = "degraded"
        summary["warnings"].append(
            f"{failures} of {len(emp_list)} employee queries failed ({fail_pct:.1f}% > "
            f"BLIP_MAX_FAIL_PCT {cfg.BLIP_MAX_FAIL_PCT}%); on-site list may be incomplete."
        )
        _log(f"BLIP DEGRADED: {summary['warnings'][-1]}")
    elif failures:
        summary["warnings"].append(f"{failures} employee query(s) failed but within tolerance.")

    # ── audit snapshot ──
    snap_path = Path(cfg.HR_SNAPSHOT_DIR) / f"blip_{_stamp()}.json"
    snapshot = {"summary": summary, "on_site": on_site, "query_failed": query_failed}
    _atomic_write_json(snap_path, snapshot)
    _atomic_write_json(Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json", snapshot)

    # ── browsable output for the COO ──
    out_file, out_error = _write_output_file(on_site, summary)
    if out_file:
        summary["output_file"] = out_file
    if out_error:
        # Visible in the portal and in hr_status.json, rather than a run that
        # claims success with no file to show for it.
        summary["warnings"].append(out_error)
        summary["output_file_error"] = out_error

    _log(f"BLIP {summary['status']}: {len(on_site)} on site of {len(emp_list)} "
         f"({failures} query failure(s)) -> {snap_path}")
    return summary


if __name__ == "__main__":
    try:
        s = run_blip()
        sys.exit(0 if s["status"] in ("ok", "busy") else 2)
    except Exception as exc:
        _log(f"BLIP CRITICAL: {exc}")
        sys.exit(1)
