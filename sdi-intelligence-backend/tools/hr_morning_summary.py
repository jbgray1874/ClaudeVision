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
AUTO_MINUTES = 15            # an update this recent means the 5-minute update is running
JUST_MINUTES = 10            # clocked in or out this recently: the next update handles them
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


def _console_label(p, now) -> str:
    """'Name (signed in 07:41)', or the day too when it was an earlier day.

    InVentry writes local time with no offset, so the text is read as it
    stands rather than converted.
    """
    import hr_inventry_api as api
    since = str((p.get("inventry") or {}).get("since") or "")
    try:
        day = datetime.date.fromisoformat(since[:10])
    except ValueError:
        return p["name"]
    if day >= (api.inventry_day(now) or day):
        return f"{p['name']} (signed in {since[11:16]})"
    return f"{p['name']} (signed in {day.strftime('%a')} {day.day} {day.strftime('%b')}, not signed out since)"


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
    # With the 5-minute update running, someone who clocked in or out in the
    # last few minutes is not a problem: the next update handles them. Only
    # those it has had time to sign in, and has not, need looking at.
    lt = _parse((last_update or {}).get("time"))
    automatic = bool(lt) and (now - lt).total_seconds() <= AUTO_MINUTES * 60
    missing = [p for p in compared if p.get("brighthr") and not p.get("inventry")]

    def just_in(p):
        t = _parse((p.get("brighthr") or {}).get("since"))
        return automatic and t is not None and (now - t).total_seconds() < JUST_MINUTES * 60
    left = [p["name"] for p in compared if (p.get("inventry") or {}).get("by") == "sync" and not p.get("brighthr")]
    # The other direction: on InVentry from a console sign-in, with no BrightHR
    # clocking. The fire list has them; BrightHR has no hours for them, and the
    # update never signs a console sign-in out. A forgotten clock-out is listed
    # on its own instead.
    forgot = forgotten_clockouts.forgotten(snap or {}, now=now)
    forgot_names = {f.get("name") for f in forgot}
    no_clocking = [_console_label(p, now) for p in compared
                   if p.get("inventry") and (p["inventry"].get("by") != "sync")
                   and not p.get("brighthr") and p["name"] not in forgot_names]
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
        "automatic": automatic,
        "not_on_inventry": [p["name"] for p in missing if not just_in(p)],
        "just_arrived": [p["name"] for p in missing if just_in(p)],
        "not_clocked_in": [] if automatic else left,
        "just_left": left if automatic else [],
        "forgotten": forgot,
        "no_clocking": no_clocking,
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
                    f"Clocked in on BrightHR more than {JUST_MINUTES} minutes ago, but still not on InVentry's "
                    "list, although it updates every 5 minutes. Their InVentry record most likely needs fixing: "
                    "the Data issues tab in the app says what's wrong. The Roll call in the app includes them."
                    if d.get("automatic") else
                    "Clocked in on BrightHR, but not signed in on InVentry, so InVentry's own list (the one "
                    "used in a fire) does not include them. The Roll call in the app does. "
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
    if d.get("no_clocking"):
        out.append((f"On InVentry, not clocked in on BrightHR: {_people(len(d['no_clocking']))}",
                    "Signed in on the console, but BrightHR has no clocking for them. They are on InVentry's "
                    "fire list, but their hours are missing from BrightHR. Ask them to clock in on Blip. "
                    "The update never signs out a console sign-in.",
                    d["no_clocking"]))
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


def information(d: dict) -> list:
    """What the next 5-minute update will handle: worth knowing, not a problem."""
    out = []
    if d.get("just_arrived"):
        out.append((f"Just clocked in: {_people(len(d['just_arrived']))}",
                    f"Clocked in within the last {JUST_MINUTES} minutes. The next automatic update, within 5 "
                    "minutes, signs them in on InVentry.", d["just_arrived"]))
    if d.get("just_left"):
        out.append((f"Just clocked out: {_people(len(d['just_left']))}",
                    "Clocked out since the last update. The next automatic update, within 5 minutes, signs them "
                    "out of InVentry.", d["just_left"]))
    return out


def compose(d: dict, link: str) -> tuple:
    todo = attention(d)
    info = information(d)
    push = d.get("push")
    things = sum(1 for h, _, _ in todo if h != "Note")
    subject = (f"HR morning summary: {d['clocked_in'] if d['clocked_in'] is not None else '?'} clocked in, "
               + (f"{things} to check" if things else "nothing to check"))
    forgot = len(d.get("forgotten") or [])
    no_clock = len(d.get("no_clocking") or [])
    figures = [("Clocked in on BrightHR", f"{d['clocked_in']} of {d['staff_checked']} staff checked"
                + (f" (not counting {forgot} forgotten clock-out{'' if forgot == 1 else 's'})" if forgot else "")),
               ("On InVentry's fire list", "InVentry did not answer" if d["on_inventry"] is None else
                f"{d['on_inventry']}" + (f" ({d['at_reception']} signed in on the console)" if d["at_reception"] else ""))]
    both = None
    if d["on_inventry"] is not None and d["clocked_in"]:
        # The evidence the two are in step: of everyone clocked in, how many
        # InVentry's list has.
        both = max(0, d["clocked_in"] - len(d["not_on_inventry"]) - len(d.get("just_arrived") or []))
        figures.append(("In step", f"{both} of {d['clocked_in']} clocked in are on InVentry's list "
                                   f"({round(both / d['clocked_in'] * 100)}%)"))
    if d["on_inventry"] is not None:
        # The other direction, always shown so a 0 says it was checked.
        figures.append(("On InVentry, not clocked in on BrightHR", str(no_clock)))
    last = d.get("last_update")
    updates = (f"automatic, every 5 minutes (last at {_local(last['time'], '%H:%M')})" if d.get("automatic")
               else f"not automatic: last update {_local(last['time'])}" if last
               else "not automatic: no update recorded")
    figures.append(("InVentry updates", updates))
    if push and push.get("status") == "ok":
        figures.append(("InVentry updated", f"{len(push.get('signed_in_names') or [])} signed in, "
                                             f"{len(push.get('signed_out_names') or [])} signed out"))
    head = (f"Checked {_local(d['checked'])}."
            + (" InVentry is updated from BrightHR automatically every 5 minutes." if d.get("automatic") else ""))

    def trimmed(names):
        more = len(names) - MAX_NAMES
        return names[:MAX_NAMES] + ([f"and {more} more: see the app"] if more > 0 else [])

    text = [head, ""] + [f"{k}: {v}" for k, v in figures] + [""]
    text.append("NEEDS ATTENTION" if todo else "Nothing needs attention.")
    for heading, why, names in todo:
        text += [f"- {heading}", f"  {why}"] + [f"    {n}" for n in trimmed(names)]
    if info:
        text += ["", "FOR INFORMATION"]
    for heading, why, names in info:
        text += [f"- {heading}", f"  {why}"] + [f"    {n}" for n in trimmed(names)]

    text += ["", "ROLL CALLS SINCE THE LAST SUMMARY"]
    if not d["roll_calls"]:
        text.append("None.")
    calls = []
    for r in d["roll_calls"]:
        line = (f"{_local(r['started'])}: {r['present_count']} present, {r['absent_count']} absent"
                + (f", started by {r['started_by']}" if r.get("started_by") else ""))
        absent = f"Absent: {', '.join(r['absent'])}" if r["absent"] else "Nobody absent."
        text += [f"- {line}", f"  {absent}"]
        calls.append((line, absent))
    where = None
    if d["roll_calls"]:
        import hr_rollcall
        where = f"Each is in Saved roll calls in the app, and as a spreadsheet in {hr_rollcall.folder()}."
        text.append(where)

    # Last, so what needs doing stays at the top: everyone clocked in, by
    # manager where the HR managers list says who that is.
    people_in = d.get("people_in") or []
    text += ["", f"WHO IS CLOCKED IN ON BRIGHTHR ({len(people_in)})"]
    if not people_in:
        text.append("Nobody.")
    groups = {}
    for p in people_in:
        groups.setdefault(p["manager"].strip() or "No manager listed", []).append(p)
    named = any(k != "No manager listed" for k in groups)
    ordered = []
    for mgr in sorted(groups, key=lambda k: (k == "No manager listed", k.lower())):
        rows = [(p["name"], _local(p["since"], "%H:%M")) for p in groups[mgr]]
        if named:
            text.append(f"{mgr} ({len(rows)})")
        text += [f"  {n} {t}" for n, t in rows]
        ordered.append((mgr if named else None, rows))

    if link:
        text += ["", f"Open HRInventry Anywhere: {link}", f"The roll call: {link}#roll"]
    foot = ("This summary is sent each weekday morning by SDI Intelligence. Names and figures are as at "
            "the check above.")
    text += ["", foot]

    pct = round(both / d["clocked_in"] * 100) if both is not None else None
    tiles = [
        ("Clocked in on BrightHR", "?" if d["clocked_in"] is None else str(d["clocked_in"]),
         f"of {d['staff_checked']} staff" + (f", {forgot} forgotten left out" if forgot else ""), None),
        ("On InVentry's fire list", "?" if d["on_inventry"] is None else str(d["on_inventry"]),
         "InVentry did not answer" if d["on_inventry"] is None
         else f"{d['at_reception']} signed in on the console" if d["at_reception"] else "all signed in by the update",
         None),
        ("In step", "?" if pct is None else f"{pct}%",
         "" if both is None else f"{both} of {d['clocked_in']} clocked in", "ok" if pct == 100 else "warn"),
        ("No BrightHR clocking", "?" if d["on_inventry"] is None else str(no_clock),
         "on InVentry, not clocked in", "warn" if no_clock else "ok"),
    ]
    page = _email_html(d, subject, things, tiles, updates, todo, info, calls, where, ordered,
                       len(people_in), link, foot, trimmed)
    return subject, page, "\n".join(text)


# ── the email's look ─────────────────────────────────────────────────────────
# Tables and inline styles only: Outlook draws mail with Word's engine, which
# ignores most modern CSS. Colours are the SDI brand (near-black and yellow)
# around a white body, so it reads the same in light or dark mail clients.
_INK, _MUTED, _LINE, _PAPER = "#1b1b18", "#5d5d55", "#e3e3dc", "#f3f3ef"
_BRAND_DARK, _BRAND = "#141412", "#F6D946"
_OK, _OK_BG, _WARN, _WARN_BG, _INFO, _INFO_BG = "#1d7a45", "#e9f6ee", "#b45d09", "#fdf3e3", "#2457a6", "#edf3fc"
_FONT = "Segoe UI, Arial, Helvetica, sans-serif"   # unquoted: the styles sit in single-quoted attributes


def _e(x) -> str:
    return html.escape(str(x))


def _email_html(d, subject, things, tiles, updates, todo, info, calls, where, groups, n_in,
                link, foot, trimmed) -> str:
    t = _parse(d.get("checked"))
    lt = t.astimezone() if t else None
    when = f"{lt.strftime('%A')} {lt.day} {lt.strftime('%B')} · checked {lt.strftime('%H:%M')}" if lt else "Not checked"

    def section(title):
        return (f"<tr><td style='padding:22px 28px 8px;font-family:{_FONT};font-size:12px;font-weight:600;"
                f"letter-spacing:1px;text-transform:uppercase;color:{_MUTED}'>{_e(title)}</td></tr>")

    def card(heading, why, names, colour, bg):
        names = trimmed(names)
        return (f"<tr><td style='padding:0 28px 10px'><table role='presentation' width='100%' cellpadding='0' "
                f"cellspacing='0'><tr><td bgcolor='{bg}' style='background:{bg};border-left:4px solid {colour};"
                f"padding:12px 14px;font-family:{_FONT}'>"
                f"<div style='font-size:15px;font-weight:600;color:{_INK}'>{_e(heading)}</div>"
                f"<div style='font-size:13px;line-height:19px;color:{_MUTED};padding-top:4px'>{_e(why)}</div>"
                + (f"<div style='font-size:14px;line-height:21px;color:{_INK};padding-top:8px'>"
                   + "<br>".join(_e(n) for n in names) + "</div>" if names else "")
                + "</td></tr></table></td></tr>")

    out = [f"<div style='margin:0;padding:0;background:{_PAPER}'>"
           f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' bgcolor='{_PAPER}' "
           f"style='background:{_PAPER}'><tr><td align='center' style='padding:24px 12px'>"
           f"<table role='presentation' width='640' cellpadding='0' cellspacing='0' bgcolor='#ffffff' "
           f"style='width:100%;max-width:640px;background:#ffffff;border:1px solid {_LINE}'>"]
    # header
    out.append(f"<tr><td bgcolor='{_BRAND_DARK}' style='background:{_BRAND_DARK};padding:22px 28px;font-family:{_FONT}'>"
               f"<div style='font-size:12px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;"
               f"color:{_BRAND}'>SDI Intelligence · HRInventry</div>"
               f"<div style='font-size:24px;font-weight:600;color:#ffffff;padding-top:6px'>HR morning summary</div>"
               f"<div style='font-size:14px;color:#c8c8bf;padding-top:4px'>{_e(when)}</div></td></tr>")
    # status
    if things:
        status, colour, bg = (f"{things} thing{'' if things == 1 else 's'} to check below", _WARN, _WARN_BG)
    else:
        status, colour, bg = ("Everything is in step. Nothing needs attention.", _OK, _OK_BG)
    out.append(f"<tr><td style='padding:20px 28px 4px'><table role='presentation' width='100%' cellpadding='0' "
               f"cellspacing='0'><tr><td bgcolor='{bg}' style='background:{bg};border-left:4px solid {colour};"
               f"padding:12px 14px;font-family:{_FONT};font-size:15px;font-weight:600;color:{colour}'>"
               f"{_e(status)}</td></tr></table></td></tr>")
    # figure tiles
    cells = []
    for label, value, sub, tone in tiles:
        vc = _OK if tone == "ok" else _WARN if tone == "warn" else _INK
        # One cell per tile in a single row, so all four share the tallest one's height.
        cells.append(f"<td width='25%' valign='top' style='border:1px solid {_LINE};padding:12px;"
                     f"font-family:{_FONT}'>"
                     f"<div style='font-size:11px;line-height:14px;font-weight:600;color:{_MUTED};"
                     f"text-transform:uppercase;letter-spacing:.5px'>{_e(label)}</div>"
                     f"<div style='font-size:28px;line-height:34px;font-weight:600;color:{vc};padding-top:6px'>{_e(value)}</div>"
                     f"<div style='font-size:12px;line-height:16px;color:{_MUTED}'>{_e(sub)}</div></td>")
    out.append(f"<tr><td style='padding:12px 20px 0'><table role='presentation' width='100%' cellpadding='0' "
               f"cellspacing='8' style='border-collapse:separate'><tr>{''.join(cells)}</tr></table></td></tr>")
    out.append(f"<tr><td style='padding:8px 28px 0;font-family:{_FONT};font-size:13px;color:{_MUTED}'>"
               f"InVentry updates: {_e(updates)}</td></tr>")
    # needs attention, for information
    if todo:
        out.append(section("Needs attention"))
        for heading, why, names in todo:
            out.append(card(heading, why, names, _WARN, _WARN_BG))
    if info:
        out.append(section("For information"))
        for heading, why, names in info:
            out.append(card(heading, why, names, _INFO, _INFO_BG))
    # roll calls
    out.append(section("Roll calls since the last summary"))
    if not calls:
        out.append(f"<tr><td style='padding:0 28px;font-family:{_FONT};font-size:14px;color:{_MUTED}'>None.</td></tr>")
    for line, absent in calls:
        out.append(card(line, absent, [], _LINE, "#fafaf7"))
    if where:
        out.append(f"<tr><td style='padding:0 28px;font-family:{_FONT};font-size:13px;color:{_MUTED}'>{_e(where)}</td></tr>")
    # buttons
    if link:
        out.append(f"<tr><td style='padding:22px 28px 4px'><table role='presentation' cellpadding='0' cellspacing='0'><tr>"
                   f"<td bgcolor='{_BRAND_DARK}' style='background:{_BRAND_DARK};padding:11px 18px'>"
                   f"<a href='{_e(link)}' style='font-family:{_FONT};font-size:14px;font-weight:600;color:{_BRAND};"
                   f"text-decoration:none'>Open HRInventry Anywhere</a></td><td width='10'></td>"
                   f"<td style='border:1px solid {_BRAND_DARK};padding:10px 18px'>"
                   f"<a href='{_e(link)}#roll' style='font-family:{_FONT};font-size:14px;font-weight:600;color:{_INK};"
                   f"text-decoration:none'>The roll call</a></td></tr></table></td></tr>")
    # who is clocked in, three to a row
    out.append(section(f"Who is clocked in on BrightHR ({n_in})"))
    if not n_in:
        out.append(f"<tr><td style='padding:0 28px;font-family:{_FONT};font-size:14px;color:{_MUTED}'>Nobody.</td></tr>")
    for mgr, rows in groups:
        if mgr:
            out.append(f"<tr><td style='padding:10px 28px 4px;font-family:{_FONT};font-size:14px;font-weight:600;"
                       f"color:{_INK}'>{_e(mgr)} ({len(rows)})</td></tr>")
        trs = []
        for i in range(0, len(rows), 3):
            tds = "".join(
                f"<td width='33%' style='padding:3px 8px 3px 0;font-family:{_FONT};font-size:13px;color:{_INK};"
                f"border-bottom:1px solid #f0f0ea'>{_e(n)} <span style='color:{_MUTED}'>{_e(tm)}</span></td>"
                for n, tm in rows[i:i + 3])
            tds += "<td width='33%'></td>" * (3 - len(rows[i:i + 3]))
            trs.append(f"<tr>{tds}</tr>")
        out.append(f"<tr><td style='padding:0 28px'><table role='presentation' width='100%' cellpadding='0' "
                   f"cellspacing='0'>{''.join(trs)}</table></td></tr>")
    # footer
    out.append(f"<tr><td style='padding:24px 28px;font-family:{_FONT};font-size:12px;line-height:17px;"
               f"color:{_MUTED};border-top:1px solid {_LINE}'>{_e(foot)}</td></tr>")
    out.append("</table></td></tr></table></div>")
    return "".join(out)


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
