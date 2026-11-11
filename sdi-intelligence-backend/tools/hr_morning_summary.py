"""The weekday morning summary for HR: who is in, what needs attention, and the
roll calls since the last summary, emailed with a link to HRInventry Anywhere.

    python tools/hr_morning_summary.py                    # print it
    python tools/hr_morning_summary.py --send             # and email it to SDI_HR_MORNING_TO
    python tools/hr_morning_summary.py --send --update    # update InVentry first
    python tools/hr_morning_summary.py --send --to me@wearesdi.com   # a test, to one person

Runs a fresh BrightHR check. Without --update it changes nothing in BrightHR
or InVentry. With it, InVentry is updated exactly as the app's Update InVentry
button does, with the same safety checks, and the summary says what changed.

Meant to run from Task Scheduler on SDI-App01 at 09:00, Monday to Friday:
deploy/install_hr_morning_task.ps1. Every run is in the app's History tab.
"""
import datetime
import html
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hr_config as cfg          # noqa: E402

BY = "Morning summary (scheduled)"
FRESH_MINUTES = 10           # a check this recent is used as it is, not run again
BUSY_RETRIES = 20            # a check already running is waited for, up to 10 minutes
BUSY_WAIT_SECONDS = 30
STALE_UPDATE_HOURS = 24
MAX_NAMES = 20               # past this the email gives the count and points to the app


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def _local(ts, fmt="%a %d %b %H:%M") -> str:
    t = _parse(ts) if ts else None
    return t.astimezone().strftime(fmt) if t else "?"


def _state_path() -> Path:
    return Path(cfg.HR_SNAPSHOT_DIR) / "hr_morning_summary.json"


def last_sent():
    try:
        return _parse(json.loads(_state_path().read_text(encoding="utf-8")).get("last_sent"))
    except (OSError, ValueError, AttributeError):
        return None


def _mark_sent(when) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_sent": when.isoformat()}), encoding="utf-8")


def app_url() -> str:
    if cfg.HR_APP_URL:
        return cfg.HR_APP_URL
    hosts = sorted(h.strip().lower() for h in os.getenv("SDI_PUBLIC_HOSTS", "").split(",") if h.strip())
    return f"https://{hosts[0]}/app/hr-inventry.html" if hosts else ""


# ── what it reads ────────────────────────────────────────────────────────────

def _snapshot():
    try:
        return json.loads((Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _check(now, sleep=time.sleep):
    """(ran, note). Uses a check from the last few minutes as it is; otherwise
    runs one, waiting for one already running (the 5-minute sync, or a press
    in the app) rather than reporting from nothing."""
    import hr_blip
    t = _parse(((_snapshot() or {}).get("summary") or {}).get("timestamp"))
    if t and (now - t).total_seconds() < FRESH_MINUTES * 60:
        return False, None
    for attempt in range(BUSY_RETRIES + 1):
        if hr_blip.run_blip().get("status") != "busy":
            return True, None
        if attempt < BUSY_RETRIES:
            sleep(BUSY_WAIT_SECONDS)
    return False, (f"BrightHR was busy with another check for {BUSY_RETRIES * BUSY_WAIT_SECONDS // 60} "
                   "minutes, so these figures are from the last check that finished.")


def gather(update=False, now=None, sleep=time.sleep) -> dict:
    import forgotten_clockouts
    import hr_history
    import hr_rollcall
    now = now or _now()
    ran, busy = _check(now, sleep)
    snap = _snapshot()
    summary = (snap or {}).get("summary") or {}
    notes = ([busy] if busy else []) + list(summary.get("warnings") or [])
    push = None
    if update and not busy:
        import hr_onsite_push
        push = hr_onsite_push.run_push(apply=True, by=BY)      # writes its own History line
    elif ran:
        hr_history.record({"time": now.isoformat(), "kind": "check", "by": BY,
                           "status": summary.get("status"), "brighthr_on_site": summary.get("on_site"),
                           "staff_checked": summary.get("employees_checked")})
    on_site, inventry_problem = hr_rollcall.inventry_on_site()        # read after any update
    people, _ = hr_rollcall.build(on_site, snap, now=now)
    since = last_sent() or now - datetime.timedelta(hours=24)
    calls = []
    for r in hr_rollcall.runs():
        started = _parse(r.get("started"))
        if started and started >= since:
            calls.append(dict(r, absent=[p["name"] for p in (hr_rollcall.saved(r["id"]) or {}).get("absent", [])]))
    last_update = next((e for e in hr_history.recent(hr_history.KEEP_LINES)
                        if e.get("kind") == "update" and e.get("status") == "ok"), None)
    # With InVentry not answering there is nothing to compare: everyone would
    # look missing from it.
    compared = [] if on_site is None else people
    # Who is clocked in, by name. A clocking open past the limit is a forgotten
    # clock-out, listed on its own, not someone in the building.
    clocked = []
    for r in (snap or {}).get("on_site") or []:
        t = _parse((r.get("clocking") or {}).get("start"))
        if t and (now - t).total_seconds() / 3600 <= cfg.BLIP_MAX_CLOCKIN_AGE_HOURS:
            clocked.append({"name": f"{r.get('first_name', '')} {r.get('surname', '')}".strip() or "?",
                            "manager": r.get("manager") or "", "since": t.isoformat()})
    clocked.sort(key=lambda p: p["name"].lower())
    return {
        "time": now.isoformat(), "checked": summary.get("timestamp"),
        "status": summary.get("status"), "clocked_in": len(clocked) if snap else None, "people_in": clocked,
        "staff_checked": summary.get("employees_checked"), "notes": notes, "push": push,
        "inventry_problem": inventry_problem,
        "on_inventry": None if on_site is None else len(on_site),
        "at_reception": sum(1 for p in on_site or [] if p.get("by") == "reception"),
        "not_on_inventry": [p["name"] for p in compared if p.get("brighthr") and not p.get("inventry")],
        "not_clocked_in": [p["name"] for p in compared
                           if (p.get("inventry") or {}).get("by") == "sync" and not p.get("brighthr")],
        "forgotten": forgotten_clockouts.forgotten(snap or {}, now=now),
        "roll_calls": calls, "since": since.isoformat(), "last_update": last_update,
    }


# ── what it says ─────────────────────────────────────────────────────────────

def _people(n) -> str:
    return f"{n} {'person' if n == 1 else 'people'}"


def attention(d: dict) -> list:
    """(heading, explanation, names) for each thing someone should look at."""
    out = []
    push = d.get("push")
    if d.get("inventry_problem"):
        out.append(("InVentry did not answer", d["inventry_problem"], []))
    if push and push.get("status") != "ok":
        out.append(("InVentry was not updated", (push.get("warnings") or ["A safety check stopped it."])[0], []))
    if d["not_on_inventry"]:
        out.append((f"Missing from InVentry's fire list: {_people(len(d['not_on_inventry']))}",
                    "Clocked in on BrightHR, but not matched to an InVentry record, so the update could not "
                    "sign them in. The Roll call in the app includes them. See Data issues in the app."
                    if push and push.get("status") == "ok" else
                    "Clocked in on BrightHR, but not signed in on InVentry, so InVentry's own list (the one "
                    "reception would use in a fire) does not include them. The Roll call in the app does. "
                    "To fix it, press Update InVentry in the app: it signs them in.",
                    d["not_on_inventry"]))
    if d["not_clocked_in"]:
        out.append((f"On InVentry, no longer clocked in: {_people(len(d['not_clocked_in']))}",
                    "Signed in by the sync earlier and clocked out since. Update InVentry signs them out.",
                    d["not_clocked_in"]))
    if d["forgotten"]:
        out.append((f"Forgotten clock-outs: {_people(len(d['forgotten']))}",
                    "Still clocked in on BrightHR from an earlier shift. Their hours are wrong until the "
                    "clocking is closed in BrightHR with the time they left.",
                    [f"{r['name']} ({r['days']:.0f} day{'' if round(r['days']) == 1 else 's'})"
                     for r in d["forgotten"]]))
    last = d.get("last_update")
    if not push:
        t = _parse((last or {}).get("time"))
        if t is None or (_parse(d["time"]) - t).total_seconds() > STALE_UPDATE_HOURS * 3600:
            out.append(("InVentry has not been updated in the last day",
                        f"Last update: {_local(last['time']) + ' by ' + str(last.get('by') or '?') if last else 'none recorded'}. "
                        "Press Update InVentry in the app so the fire list matches BrightHR.", []))
    for n in d["notes"]:
        out.append(("Note", n, []))
    return out


def compose(d: dict, link: str) -> tuple:
    todo = attention(d)
    push = d.get("push")
    things = sum(1 for h, _, _ in todo if h != "Note")
    subject = (f"HR morning summary: {d['clocked_in'] if d['clocked_in'] is not None else '?'} clocked in, "
               + (f"{things} to check" if things else "nothing to check"))
    forgot = len(d.get("forgotten") or [])
    figures = [("Clocked in on BrightHR", f"{d['clocked_in']} of {d['staff_checked']} staff checked"
                + (f" (not counting {forgot} forgotten clock-out{'' if forgot == 1 else 's'})" if forgot else "")),
               ("On InVentry's fire list", "InVentry did not answer" if d["on_inventry"] is None else
                f"{d['on_inventry']}" + (f" ({d['at_reception']} signed in at reception)" if d["at_reception"] else ""))]
    if d["on_inventry"] is not None and d["clocked_in"]:
        # The evidence the two are in step: of everyone clocked in, how many
        # InVentry's list has.
        both = max(0, d["clocked_in"] - len(d["not_on_inventry"]))
        figures.append(("In step", f"{both} of {d['clocked_in']} clocked in are on InVentry's list "
                                   f"({round(both / d['clocked_in'] * 100)}%)"))
    if push and push.get("status") == "ok":
        figures.append(("InVentry updated", f"{len(push.get('signed_in_names') or [])} signed in, "
                                             f"{len(push.get('signed_out_names') or [])} signed out"))
    head = f"Checked {_local(d['checked'])}."

    text = [head, ""] + [f"{k}: {v}" for k, v in figures] + [""]
    page = [f"<p>{html.escape(head)}</p><table cellpadding='4' cellspacing='0'>"
            + "".join(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(v)}</td></tr>" for k, v in figures)
            + "</table>"]

    text.append("NEEDS ATTENTION" if todo else "Nothing needs attention.")
    page.append("<h3>Needs attention</h3>" if todo else "<p><b>Nothing needs attention.</b></p>")
    for heading, why, names in todo:
        more = len(names) - MAX_NAMES
        names = names[:MAX_NAMES] + ([f"and {more} more: see the app"] if more > 0 else [])
        text += [f"- {heading}", f"  {why}"] + [f"    {n}" for n in names]
        page.append(f"<p><b>{html.escape(heading)}</b><br>{html.escape(why)}"
                    + (f"<br>{html.escape(', '.join(names))}" if names else "") + "</p>")

    text += ["", "ROLL CALLS SINCE THE LAST SUMMARY"]
    page.append("<h3>Roll calls since the last summary</h3>")
    if not d["roll_calls"]:
        text.append("None.")
        page.append("<p>None.</p>")
    for r in d["roll_calls"]:
        line = (f"{_local(r['started'])}: {r['present_count']} present, {r['absent_count']} absent"
                + (f", started by {r['started_by']}" if r.get("started_by") else ""))
        absent = f"Absent: {', '.join(r['absent'])}" if r["absent"] else "Nobody absent."
        text += [f"- {line}", f"  {absent}"]
        page.append(f"<p><b>{html.escape(line)}</b><br>{html.escape(absent)}</p>")
    if d["roll_calls"]:
        import hr_rollcall
        where = f"Each is in Saved roll calls in the app, and as a spreadsheet in {hr_rollcall.folder()}."
        text.append(where)
        page.append(f"<p>{html.escape(where)}</p>")

    # Last, so what needs doing stays at the top: everyone clocked in, by
    # manager where the HR managers list says who that is.
    people_in = d.get("people_in") or []
    text += ["", f"WHO IS CLOCKED IN ON BRIGHTHR ({len(people_in)})"]
    page.append(f"<h3>Who is clocked in on BrightHR ({len(people_in)})</h3>")
    if not people_in:
        text.append("Nobody.")
        page.append("<p>Nobody.</p>")
    groups = {}
    for p in people_in:
        groups.setdefault(p["manager"].strip() or "No manager listed", []).append(p)
    named = any(k != "No manager listed" for k in groups)
    for mgr in sorted(groups, key=lambda k: (k == "No manager listed", k.lower())):
        rows = groups[mgr]
        entries = [f"{p['name']} {_local(p['since'], '%H:%M')}" for p in rows]
        if named:
            text.append(f"{mgr} ({len(rows)})")
            page.append(f"<p><b>{html.escape(mgr)} ({len(rows)})</b><br>")
        else:
            page.append("<p>")
        text += [f"  {e}" for e in entries]
        page.append(html.escape(", ".join(entries)) + "</p>")

    if link:
        text += ["", f"Open HRInventry Anywhere: {link}", f"The roll call: {link}#roll"]
        page.append(f"<p><a href='{html.escape(link)}'>Open HRInventry Anywhere</a> &nbsp;·&nbsp; "
                    f"<a href='{html.escape(link)}#roll'>The roll call</a></p>")
    foot = ("This summary is sent each weekday morning by SDI Intelligence. Names and figures are as at "
            "the check above.")
    text += ["", foot]
    page.append(f"<p style='color:#666'>{html.escape(foot)}</p>")
    return subject, "".join(page), "\n".join(text)


def send(to, subject, page, text) -> dict:
    """From the sdi-intelligence mailbox through Microsoft Graph, as the AM CRM
    morning review is: Office 365 refuses the server's SMTP login (530 5.7.57).
    SMTP only where no mailbox is set."""
    if os.getenv("SDI_REVIEW_FROM", "").strip():
        import morning_review
        return morning_review.send_via_graph(to, subject, page)
    import estimate_email
    return estimate_email.send(to, subject, page, text)


def main(argv, sleep=time.sleep, today=None) -> int:
    if "--weekdays-only" in argv and (today or datetime.date.today()).weekday() >= 5:
        print("Weekend - no summary sent.")
        return 0
    os.chdir(BACKEND)
    import config  # noqa: F401  - the service's settings, as the other scheduled emails load them
    d = gather(update="--update" in argv, sleep=sleep)
    subject, page, text = compose(d, app_url())
    print(subject)
    print(text)
    if "--send" not in argv:
        return 0
    # --to sends a test to someone else instead; a test is not "the last summary",
    # so the real one still carries the roll calls.
    test = "--to" in argv
    to = (sorted(a.strip() for a in (argv[argv.index("--to") + 1:] or [""])[0].split(",") if a.strip())
          if test else sorted(cfg.HR_MORNING_TO))
    if not to:
        print("SDI_HR_MORNING_TO is not set in .env; nothing sent." if not test else "--to needs an address.")
        return 2
    result = send(to, subject, page, text)
    if result.get("sent"):
        if not test:
            _mark_sent(_parse(d["time"]))
        print(f"sent to {', '.join(to)}")
        return 0
    print(f"NOT sent: {result.get('reason')}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
