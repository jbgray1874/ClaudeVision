"""
SameDay watch - checks SDI SameDay every 15 minutes on the server, and emails when something is wrong.

5 November 2026 (James): "this is for sales people and directors who have a very high standard ... can we get alerting
for this?" - so a problem reaches James before it reaches a director. It checks:

  * SameDay's service is running and answering, with code from the repository (not K:'s copy)
  * the phone address: SDI Intelligence carries it at /sameday/, the public address answers, and the App Proxy
    connector on this server (if it is here) is running
  * past jobs can be found, and SameDay can read W:, S: and K:
  * the OpenAI and Anthropic keys are accepted
  * today's AI spend against SameDay's daily cap (a warning at 80%)
  * OpenAI saying the account has no credit, in SameDay's log

A problem is emailed once, again every few hours while it lasts, and an "all clear" when it is fixed. A "down" result
is checked again a minute later before it counts, so a restart during an update doesn't send an email. Outside
working hours nothing is emailed; what is still wrong in the morning is.

READ-ONLY: it changes nothing in SameDay. The keys are read from SameDay's .env to test them, and never printed,
logged or emailed.

Run by the scheduled task "SDI SameDay Watch" (deploy/Install-SameDay-Watch.ps1, from the laptop):
    sameday_watch.cmd                 -> python sameday_watch.py --send >> logs\\sameday_watch.log
    python sameday_watch.py           a check now, printed, nothing sent

Configuration (SDI Intelligence's .env):
    SAMEDAY_ALERT_TO        who is emailed, comma separated. Empty = never sent (the check still runs and logs).
    SAMEDAY_ALERT_HOURS     the hours emails go out, e.g. 7-19 (the default). "0-24" = any time.
    SAMEDAY_ALERT_REMIND    hours between reminders while a problem lasts (default 3)
    SAMEDAY_URL             SameDay itself (default http://127.0.0.1:5020)
    SAMEDAY_VIA_URL         SameDay through SDI Intelligence (default http://127.0.0.1:8071/sameday)
    SAMEDAY_PUBLIC_URL      the phone address (default https://sdiintelligence-sdidisplays.msappproxy.net/sameday/)
    SAMEDAY_DIR             SameDay's folder (default C:\\SDI_Automation): its .env and its log
    SAMEDAY_SPEND_WARN      the share of the day's cap that warns (default 0.8)
Sending: as the morning review - Microsoft Graph from SDI_REVIEW_FROM when that is set, otherwise SMTP.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
STATE = HERE / "logs" / "sameday_watch_state.json"
NO_CREDIT = re.compile(r"insufficient_quota|has no credit|needs topping up|billing hard limit", re.I)


def _opt(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


# ── reading SameDay, never changing it ───────────────────────────────────────
def http_get(url: str, headers: Optional[dict] = None, timeout: float = 15, redirects: bool = True):
    """(status, parsed JSON or text, location header) - status 0 when nothing answered."""
    import httpx
    try:
        r = httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=redirects)
    except Exception as exc:                            # noqa: BLE001 - "didn't answer" is the finding
        return 0, f"{type(exc).__name__}: {str(exc)[:160]}", ""
    try:
        body = r.json()
    except ValueError:
        body = r.text[:500]
    return r.status_code, body, r.headers.get("location", "")


def service_state(name: str) -> str:
    """'RUNNING', 'STOPPED' (or another state), 'absent', or '' when it can't be told (not Windows)."""
    if os.name != "nt":
        return ""
    try:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:                                   # noqa: BLE001
        return ""
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 1060 or "does not exist" in out:
        return "absent"
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out)
    return m.group(1) if m else ""


def read_env(path: Path) -> dict:
    """KEY=VALUE lines of a .env - only to test the keys; the values never leave this process."""
    out = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m and not line.lstrip().startswith("#"):
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def new_log_text(log: Path, state: dict) -> str:
    """What SameDay has written to its log since the last check (a restart starts a new file)."""
    try:
        size = log.stat().st_size
    except OSError:
        return ""
    start = state.get("log_offset", 0)
    if not state.get("log_file"):
        start = size            # the first check starts from now - never an alarm about old lines
    elif start > size or state.get("log_file") != str(log):
        start = 0               # SameDay restarted: a new log file
    state["log_offset"], state["log_file"] = size, str(log)
    try:
        with open(log, "rb") as f:
            f.seek(start)
            return f.read(size - start).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def disk_free_gb(path: str) -> Optional[float]:
    """Free space on the server's drive, in GB - None when it can't be read (not this server)."""
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


def _problem(key: str, level: str, title: str, fix: str) -> dict:
    return {"key": key, "level": level, "title": title, "fix": fix}


def check(get: Callable = http_get, service: Callable = service_state, env: Optional[dict] = None,
          log_text: str = "", disk: Callable = disk_free_gb) -> tuple[list[dict], dict]:
    """Every check, each on its own: (problems, facts). A check that can't run is a problem, never a pass."""
    problems: list[dict] = []
    facts: dict = {}
    base = _opt("SAMEDAY_URL", "http://127.0.0.1:5020").rstrip("/")
    via = _opt("SAMEDAY_VIA_URL", "http://127.0.0.1:8071/sameday").rstrip("/")
    public = _opt("SAMEDAY_PUBLIC_URL", "https://sdiintelligence-sdidisplays.msappproxy.net/sameday/")
    env = env if env is not None else read_env(Path(_opt("SAMEDAY_DIR", r"C:\SDI_Automation")) / ".env")

    # SameDay itself
    st = service("SDISameDay")
    if st and st not in ("RUNNING", "absent"):
        problems.append(_problem("service", "down", f"SameDay's service is {st.lower()}",
                                 "On the server: Start-Service SDISameDay. If it stops again, the end of "
                                 r"C:\SDI_Automation\logs\SDISameDay.log says why."))
    code, ver, _ = get(base + "/api/version")
    if code != 200 or not isinstance(ver, dict):
        problems.append(_problem("answer", "down", "SameDay isn't answering",
                                 f"{base}/api/version gave {code or 'no answer'}. Check the service on the server "
                                 "(Get-Service SDISameDay) and the end of its log."))
        ver = {}
    else:
        facts["version"] = str(ver.get("version") or "")
        if facts["version"] and " repo " not in facts["version"]:
            problems.append(_problem("code", "warn", "SameDay is running code that didn't come from the repository",
                                     f"It reports version '{facts['version']}' - most likely K:'s copy was put on the "
                                     "server (UPDATE_SAME_DAY.bat). From the laptop: Update-SameDay.ps1 -Branch "
                                     "claude/inspiring-planck-8juriz puts the repository's code back."))
        past = ver.get("past_work") or {}
        facts["past_jobs"] = past.get("jobs")
        facts["pictures"] = "on" if past.get("pictures") else f"off ({past.get('why') or 'not reported'})"
        if past and not past.get("jobs"):
            problems.append(_problem("past_jobs", "down", "SameDay can't find past jobs",
                                     f"It says: {past.get('why') or 'no reason given'}. The job index "
                                     r"(projects.db) belongs in C:\SDI_Automation\brief_lite on the server."))
        reads = ver.get("can_read") or {}
        facts["drives"] = ", ".join(f"{d}: {'yes' if ok else 'NO'}" for d, ok in reads.items())
        bad = [d for d, ok in reads.items() if not ok]
        if bad:
            problems.append(_problem("drives", "down", "SameDay can't read " + ", ".join(d + ":" for d in bad),
                                     "Past jobs and their drawings live there. The service maps the drives at start - "
                                     "restart SDISameDay; if it still can't, the 'drive' lines of its log say why."))

    # the phone address
    if service("SDIIntelligence") not in ("RUNNING", "absent", ""):
        problems.append(_problem("intelligence", "down", "SDI Intelligence isn't running - the phone address is down",
                                 "On the server: Start-Service SDIIntelligence."))
    # 5 Nov 2026 (first run: a false alarm): SDI Intelligence asks a request addressed to the server itself
    # (127.0.0.1) to sign in, so the watch shows its own service key - the one the scheduled tasks use - and so goes the
    # way a phone's request goes. Without a key, a sign-in refusal still proves SDI Intelligence is up and carrying
    # /sameday/; it is never reported as the phone address being down.
    machine = {"X-SDI-Key": _opt("SDI_API_KEY")} if _opt("SDI_API_KEY") else {}
    code, body, _ = get(via + "/api/version", headers=machine)
    if code == 401 and not machine:
        facts["phone"] = "SDI Intelligence answering at /sameday/ (SDI_API_KEY not set, so not followed through)"
    elif code != 200 or not isinstance(body, dict):
        problems.append(_problem("phone", "down", "The phone address isn't reaching SameDay",
                                 f"SDI Intelligence at /sameday/ gave {code or 'no answer'}"
                                 + (f" ({str(body)[:100]})" if code else "") + ". Run Ship-It, then check SameDay."))
    code, _, where = get(public, redirects=False)
    if code == 0 or code >= 500:
        problems.append(_problem("public", "warn", "The phone address didn't answer from outside",
                                 f"{public} gave {code or 'no answer'}. Microsoft's App Proxy may be down, or this "
                                 "server can't reach the internet."))
    connector = service("WAPCSvc")
    if connector and connector not in ("RUNNING", "absent"):
        problems.append(_problem("connector", "down", "The App Proxy connector on this server is " + connector.lower(),
                                 "Phones can't reach SDI Intelligence or SameDay. On the server: Start-Service WAPCSvc."))

    # the keys
    k = env.get("OPENAI_API_KEY", "")
    if not k:
        problems.append(_problem("openai", "down", "No OpenAI key in SameDay's .env",
                                 "Live voice and renders can't work. Set OPENAI_API_KEY in C:\\SDI_Automation\\.env."))
    else:
        code, _, _ = get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {k}"})
        if code in (401, 403):
            problems.append(_problem("openai", "down", "OpenAI refused SameDay's key",
                                     "Live voice and renders can't work. Replace OPENAI_API_KEY in "
                                     "C:\\SDI_Automation\\.env and restart SDISameDay."))
        elif code != 200:
            problems.append(_problem("openai", "warn", f"Couldn't check the OpenAI key ({code or 'no answer'})",
                                     "OpenAI may be having a problem, or this server can't reach it."))
    k = env.get("ANTHROPIC_API_KEY", "")
    if k:
        code, _, _ = get("https://api.anthropic.com/v1/models",
                         headers={"x-api-key": k, "anthropic-version": "2023-06-01"})
        if code in (401, 403):
            problems.append(_problem("anthropic", "down", "Anthropic refused SameDay's key",
                                     "The typed chat and the design step can't work. Replace ANTHROPIC_API_KEY in "
                                     "C:\\SDI_Automation\\.env and restart SDISameDay."))
    if NO_CREDIT.search(log_text or ""):
        problems.append(_problem("credit", "down", "OpenAI says the account has no credit",
                                 "Renders and live voice stop until it is topped up: platform.openai.com > Billing.")
                        | {"sticky": True})

    # the server's own disk - 5 Nov 2026 (James: "this is a production server"): copying 269,000 thumbnails was
    # started on a guess at their size. Whatever fills C:, this says so before it is full.
    free = disk(_opt("SAMEDAY_DISK", "C:\\"))
    if free is not None:
        facts["server C: free"] = f"{free:.1f} GB"
        fix = (r"Clear space on the server's C:. SameDay's own big folders are C:\SDI_Automation\all_img_thumbs "
               r"(optional thumbnails - SameDay works without them) and C:\SDI_Automation\backups (old copies).")
        if free < 5:
            problems.append(_problem("disk", "down", f"The server's C: is almost full ({free:.1f} GB free)", fix))
        elif free < 10:
            problems.append(_problem("disk", "warn", f"The server's C: is getting full ({free:.1f} GB free)", fix))

    # today's spend
    code, status, _ = get(base + "/api/status")
    if code == 200 and isinstance(status, dict):
        spent, cap = float(status.get("spent_today") or 0), float(status.get("cap") or 0)
        facts["spend"] = f"{spent:.2f} of {cap:.2f} USD"
        warn_at = float(_opt("SAMEDAY_SPEND_WARN", "0.8") or 0.8)
        fix = ("Raise brief_lite_daily_cap_usd in C:\\SDI_Automation\\studio_data\\ai_switch.json (no restart), or set "
               "brief_lite_budget_reset_at to now to start today's count again.")
        if cap and spent >= cap:
            problems.append(_problem("spend", "down", f"Today's AI budget is used up ({facts['spend']})",
                                     "SameDay has stopped making AI calls until midnight. " + fix))
        elif cap and spent >= cap * warn_at:
            problems.append(_problem("spend", "warn", f"Today's AI budget is nearly used ({facts['spend']})",
                                     "At the cap SameDay stops, live calls included. " + fix))
    return problems, facts


# ── who is told what, and when ───────────────────────────────────────────────
def in_hours(now: datetime, spec: str) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", spec or "7-19")
    lo, hi = (int(m.group(1)), int(m.group(2))) if m else (7, 19)
    return lo <= now.hour < hi


def decide(state: dict, problems: list[dict], now: datetime, hours_ok: bool, remind_hours: float) -> dict:
    """What to email now. state['open'] is every problem seen and not yet fixed, with when it was last emailed."""
    open_ = state.setdefault("open", {})
    recovered = state.setdefault("recovered", [])
    current = {p["key"]: p for p in problems}
    for key, p in current.items():
        e = open_.setdefault(key, {"since": now.isoformat(timespec="minutes"), "sent": ""})
        e.update(title=p["title"], last_seen=now.isoformat(timespec="minutes"), sticky=bool(p.get("sticky")))
    for key in [k for k in open_ if k not in current]:
        e = open_[key]
        if e.get("sticky"):
            # seen in the log, not watched: it can only be seen to stop, never to be fixed - so it stays counted (no
            # email every 15 minutes while people keep trying), then goes quietly, with no "all clear"
            if now - datetime.fromisoformat(e.get("last_seen") or e["since"]) < timedelta(hours=remind_hours):
                continue
        elif e.get("sent"):                            # they were told it was wrong - tell them it's fixed
            recovered.append(e["title"])
        del open_[key]
    if not hours_ok:
        return {"new": [], "remind": [], "recovered": []}
    new, remind = [], []
    for key, p in current.items():
        sent = open_[key].get("sent")
        if not sent:
            new.append(p)
        elif now - datetime.fromisoformat(sent) >= timedelta(hours=remind_hours):
            remind.append(p)
    for p in new + remind:
        open_[p["key"]]["sent"] = now.isoformat(timespec="minutes")
    out = {"new": new, "remind": remind, "recovered": list(recovered)}
    recovered.clear()
    return out


def compose(todo: dict, facts: dict, now: datetime) -> Optional[dict]:
    """The email, or None when there is nothing to say."""
    bad = todo["new"] + todo["remind"]
    if not bad and not todo["recovered"]:
        return None
    if bad:
        down = [p for p in bad if p["level"] == "down"]
        subject = (f"SameDay: {'PROBLEM' if down else 'warning'} - " + "; ".join(p["title"] for p in bad[:2])
                   + (f" (+{len(bad) - 2} more)" if len(bad) > 2 else ""))
    else:
        subject = "SameDay: all clear - " + "; ".join(todo["recovered"][:2])
    lines, rows = [], []
    for p in bad:
        tag = ("Still wrong" if p in todo["remind"] else "New") + (" - DOWN" if p["level"] == "down" else " - warning")
        lines += [f"{tag}: {p['title']}", f"    What to do: {p['fix']}", ""]
        colour = "#C8102E" if p["level"] == "down" else "#B7791F"
        rows.append(f"<tr><td style='padding:8px 12px;border-left:4px solid {colour}'><b>{html.escape(p['title'])}</b>"
                    f"<br><span style='color:#555'>{html.escape(tag)}</span><br>{html.escape(p['fix'])}</td></tr>")
    for t in todo["recovered"]:
        lines += [f"Fixed: {t}", ""]
        rows.append(f"<tr><td style='padding:8px 12px;border-left:4px solid #2F855A'><b>Fixed:</b> {html.escape(t)}</td></tr>")
    about = [f"{k.replace('_', ' ')}: {v}" for k, v in facts.items() if v not in (None, "")]
    text = ("\n".join(lines) + "\nSameDay now - " + "; ".join(about) + "\n\nChecked "
            + now.strftime("%A %d %B %Y, %H:%M") + " on the server, every 15 minutes (sameday_watch.py).")
    body = ("<div style='font:14px/1.5 Segoe UI,Arial,sans-serif;color:#17181B'><table style='border-collapse:collapse'>"
            + "".join(rows) + "</table><p style='color:#555'>SameDay now: " + html.escape("; ".join(about))
            + "</p><p style='color:#888;font-size:12px'>Checked " + now.strftime("%A %d %B %Y, %H:%M")
            + " on the server, every 15 minutes (sameday_watch.py).</p></div>")
    return {"subject": subject, "text": text, "html": body}


def send(to: list[str], email: dict) -> dict:
    """As the morning review: Graph from SDI_REVIEW_FROM when set, else the service's SMTP."""
    if _opt("SDI_REVIEW_FROM"):
        import morning_review
        return morning_review.send_via_graph(to, email["subject"], email["html"])
    import estimate_email
    return estimate_email.send(to, email["subject"], email["html"], email["text"])


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check SDI SameDay and email when something is wrong.")
    ap.add_argument("--send", action="store_true", help="email SAMEDAY_ALERT_TO (otherwise print only)")
    args = ap.parse_args(argv)
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    import config  # noqa: F401 - loads SDI Intelligence's .env

    now = datetime.now()
    state = load_state()
    log = Path(_opt("SAMEDAY_DIR", r"C:\SDI_Automation")) / "logs" / "SDISameDay.log"
    log_text = new_log_text(log, state)
    problems, facts = check(log_text=log_text)
    if any(p["level"] == "down" for p in problems):
        time.sleep(60)                                  # a restart during an update: look again before it counts
        problems, facts = check(log_text=log_text)
    print(now.strftime("%Y-%m-%d %H:%M"), "OK" if not problems else
          " | ".join(f"{p['level'].upper()}: {p['title']}" for p in problems), "|", json.dumps(facts))
    if not args.send:
        return 0                # a look by hand: the scheduled check still sees the same log lines
    to = [a.strip() for a in _opt("SAMEDAY_ALERT_TO").split(",") if "@" in a]
    todo = decide(state, problems, now, in_hours(now, _opt("SAMEDAY_ALERT_HOURS", "7-19")),
                  float(_opt("SAMEDAY_ALERT_REMIND", "3") or 3))
    email = compose(todo, facts, now)
    if email and to:
        result = send(to, email)
        print("emailed" if result.get("sent") else f"NOT emailed: {result.get('reason')}", "-", email["subject"])
        if not result.get("sent"):              # not told: try again next time rather than counting it as told
            for p in todo["new"] + todo["remind"]:
                state["open"][p["key"]]["sent"] = ""
            state.setdefault("recovered", []).extend(todo["recovered"])
    elif email:
        print("SAMEDAY_ALERT_TO is empty - not emailed:", email["subject"])
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
