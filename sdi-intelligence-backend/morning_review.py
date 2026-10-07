"""
SDI Intelligence AM CRM — the morning review.

Each weekday morning Nick's sandbox tracker is checked and a review is
emailed to him (and James): how many active records there are, how many have
conflicting status/invoice/PO data, overdue actions, ordered work past its
end date, missing or invalid core data, client contact gone stale, what is due
this week, what moved since the last review, and the five records most worth
a decision today.

THE NUMBERS ARE COUNTED, NOT WRITTEN. Every count, date, value and the choice
of the five records comes from the rules in this file, so the same sheet always
gives the same review and any figure can be checked by hand. Claude is used
only to word each record's "Issue" and "Decision needed" lines and the
movement sentence, from those facts alone; if it is unavailable the review is
sent with plain wording instead of not at all.

READ-ONLY. Nothing here writes to the tracker.

Two ways in:
  * GET  /api/voicecrm/review       a preview for the signed-in user (their own
                                    Graph token), and POST .../review/send to
                                    send it now (pilot writers only).
  * python morning_review.py --send the scheduled run, with no one signed in.
                                    It uses an app-only token, which needs the
                                    Sites.Selected application permission
                                    granted on the sandbox site only.

Configuration (.env):
    SDI_REVIEW_TO            who gets it, comma separated. Empty = never sent.
    SDI_REVIEW_CONTACT_DAYS  days since last client contact that trigger a
                             contact review (default 14)
    SDI_REVIEW_DUE_DAYS      "due within" window in days (default 7)
    SDI_REVIEW_MODEL         model that words the five items (default claude-opus-5-5)
    SDI_REVIEW_FROM          mailbox to send from via Microsoft Graph (app-only,
                             Mail.Send restricted to that mailbox). Empty =
                             use the service's SMTP_* settings instead.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


# ── Columns ──────────────────────────────────────────────────────────────────
# Found by name, ignoring case, spaces and punctuation, so "Invoiced?" and
# "INVOICED" are the same column. A column the sheet does not have simply
# switches off the checks that need it.
COLUMNS = {
    "account":  ["ACCOUNT", "Client"],
    "unit":     ["BUSINESS UNIT"],
    "desc":     ["OVERVIEW / DESCRIPTION / DELIVERABLES", "Description", "Project"],
    "code":     ["Project code", "Project number", "Job number"],
    "am":       ["AM Owner"],
    "pm":       ["PM Owner", "PM", "Project Manager"],
    "status":   ["Status"],
    "next":     ["NEXT STEPS"],
    "action":   ["KEY DATES FOR NEXT STEPS", "Action date", "Next action date"],
    "start":    ["START", "Start date"],
    "end":      ["END", "End date"],
    "commercial": ["Commercial Status"],
    "confidence": ["Confidence to Order"],
    "contact":  ["Last Client Contact Date", "Last contact"],
    "budget":   ["BUDGET COST", "Budget"],
    "invoiced": ["Invoiced"],
    "po":       ["PO", "PO Number", "PO No", "PO Received", "PO Ref"],
}


def resolve_columns(headers: list[str]) -> dict[str, str]:
    """Logical name -> the sheet's own header, for the columns that exist."""
    found: dict[str, str] = {}
    normed = {_norm(h): h for h in headers if h}
    for key, names in COLUMNS.items():
        for n in names:
            if _norm(n) in normed:
                found[key] = normed[_norm(n)]
                break
        else:
            for n in names:
                hit = next((h for k, h in normed.items() if k.startswith(_norm(n))), None)
                if hit and len(_norm(n)) >= 4:
                    found[key] = hit
                    break
    return found


# ── Values ───────────────────────────────────────────────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(raw: Any) -> Optional[date]:
    """A cell as a date. The sheet displays dates month-first (9/4/2026 is
    4 September 2026). Returns None for blank or unreadable."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, (int, float)) and 20000 < raw < 80000:      # Excel serial
        return date(1899, 12, 30) + timedelta(days=int(raw))
    text = str(raw).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", text)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
        if m:
            mo, d, y = map(int, m.groups())
            y += 2000 if y < 100 else 0
        else:
            m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?[ -]([A-Za-z]{3,})[ -,]*(\d{2,4})", text)
            if not m or m.group(2)[:3].lower() not in _MONTHS:
                return None
            d, y = int(m.group(1)), int(m.group(3))
            mo = _MONTHS[m.group(2)[:3].lower()]
            y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_money(raw: Any) -> Optional[float]:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[£$€,\s]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return None


def spoken_date(d: Optional[date]) -> str:
    return f"{d.day} {d:%B}" if d else "missing"


def money(v: Optional[float]) -> str:
    if v is None:
        return "missing"
    return f"£{v:,.2f}" if v != int(v) else f"£{int(v):,}"


def _blank(v: Any) -> bool:
    return v is None or str(v).strip() == ""


# ── The rules ────────────────────────────────────────────────────────────────
_DONE = re.compile(r"\b(complete[ds]?|completed|delivered|installed|fitted|finished|handed over)\b", re.I)
_CLOSED = re.compile(r"\b(lost|cancel+ed|cancel|closed|declined|dead|not proceeding)\b", re.I)
_YES = re.compile(r"^\s*(y|yes|true|done|invoiced)\b", re.I)
_NA = re.compile(r"^\s*(n/?a|not applicable)\s*$", re.I)


def _issue(kind: str, text: str, weight: float) -> dict:
    return {"kind": kind, "text": text, "weight": weight}


def assess(fields: dict, col: dict, today: date, contact_days: int, due_days: int) -> dict:
    """One record: its facts and every rule it trips."""
    def g(k):
        v = fields.get(col[k]) if k in col else None
        return "" if v is None else v
    status, nxt, comm = str(g("status")), str(g("next")), str(g("commercial"))
    invoiced = str(g("invoiced")).strip()
    action, end = parse_date(g("action")), parse_date(g("end"))
    contact = parse_date(g("contact"))
    budget = parse_money(g("budget"))
    inv_yes, inv_na = bool(_YES.match(invoiced)), bool(_NA.match(invoiced))

    closed = inv_yes or inv_na or bool(_CLOSED.search(comm)) or bool(
        re.match(r"\s*(closed|lost|cancel)", status, re.I))
    issues: list[dict] = []
    flags: dict[str, Any] = {}

    # Completion / invoice / PO / status conflicts
    if not closed and "invoiced" in col:
        said = _DONE.search(status) or _DONE.search(nxt)
        if said:
            issues.append(_issue("conflict",
                f"{'Status' if _DONE.search(status) else 'Next steps'} says "
                f"{said.group(0).lower()}, but Invoiced is {invoiced or 'blank'} and the "
                f"project remains active", 50))
    if not closed and "po" in col:
        po = str(g("po")).strip()
        if re.search(r"\bordered\b", comm, re.I) and not po:
            issues.append(_issue("conflict", "Commercial Status is Ordered but no PO is recorded", 35))
        if re.search(r"awaiting po", comm, re.I) and po and not _NA.match(po):
            issues.append(_issue("conflict", f"A PO ({po}) is recorded but Commercial Status "
                                             f"still says Awaiting PO", 30))
    flags["conflict"] = any(i["kind"] == "conflict" for i in issues)

    # Overdue next action
    if not closed and action and action < today:
        days = (today - action).days
        flags["overdue"] = days
        issues.append(_issue("overdue", f"Next action was due {spoken_date(action)} "
                                        f"({days} days ago)", min(days, 60) / 3))

    # Ordered work past its end date
    if (not closed and end and end < today and re.search(r"\bordered\b", comm, re.I)
            and not re.search(r"awaiting", comm, re.I)):
        days = (today - end).days
        flags["ordered_past_end"] = days
        inv = "invoicing is blank" if not invoiced else f"Invoiced is {invoiced}"
        issues.append(_issue("ordered_past_end",
            f"Ordered work is {days} days past its end date and {inv}", 40))

    # Missing / invalid core data
    missing = []
    if not closed:
        for key, label in (("budget", "budget"), ("pm", "PM"), ("action", "next action date"),
                           ("end", "end date"), ("status", "status")):
            if key not in col:
                continue
            raw = g(key)
            if _blank(raw):
                missing.append(f"{label} missing")
            elif key in ("action", "end") and parse_date(raw) is None:
                missing.append(f"{label} unreadable ('{raw}')")
            elif key == "budget" and parse_money(raw) is None:
                missing.append(f"budget not a number ('{raw}')")
        if "start" in col and not _blank(g("start")) and parse_date(g("start")) is None:
            missing.append(f"start date unreadable ('{g('start')}')")
        if missing:
            flags["missing"] = missing
            issues.append(_issue("missing", "Core data: " + ", ".join(missing), 4 * len(missing)))

    # Client contact gone stale
    if not closed and "contact" in col:
        if contact is None:
            flags["contact"] = None
            issues.append(_issue("contact", "No client contact date is recorded", 8))
        elif (today - contact).days > contact_days:
            days = (today - contact).days
            flags["contact"] = days
            issues.append(_issue("contact", f"Last recorded client contact is {days} days old "
                                            f"({spoken_date(contact)})", 8 + min(days, 60) / 6))

    if not closed and action and today <= action <= today + timedelta(days=due_days):
        flags["due"] = (action - today).days

    factor = 1 + min((budget or 0) / 50000, 3)
    return {
        "closed": closed,
        "issues": issues,
        "flags": flags,
        "score": round(sum(i["weight"] for i in issues) * factor, 2),
        "facts": {
            "account": str(g("account")), "unit": str(g("unit")),
            "job": str(g("desc")).split("\n")[0].strip()[:90],
            "code": str(g("code")).strip() or "blank", "am": str(g("am")).strip(),
            "pm": str(g("pm")).strip() or "missing",
            "action": spoken_date(action) if not _blank(g("action")) else "missing",
            "end": spoken_date(end) if not _blank(g("end")) else "missing",
            "budget": money(budget), "budget_value": budget or 0,
            "status": status[:200], "next_steps": nxt[:200], "commercial": comm,
            "invoiced": invoiced or "blank",
            "last_contact": spoken_date(contact) if contact else "missing",
        },
    }


def record_key(fields: dict, col: dict) -> str:
    parts = [fields.get(col.get(k, "")) or "" for k in ("account", "unit", "desc")]
    return " | ".join(str(p).split("\n")[0].strip().lower() for p in parts)


def build_review(rows: list[dict], headers: list[str], owner_field: str, owner: str,
                 today: date, previous: Optional[dict] = None) -> dict:
    """Counts, movement since the previous review, and the five to look at."""
    col = resolve_columns(headers)
    col["am"] = owner_field if owner_field in headers else col.get("am", owner_field)
    contact_days = int(_opt("SDI_REVIEW_CONTACT_DAYS", "14") or 14)
    due_days = int(_opt("SDI_REVIEW_DUE_DAYS", "7") or 7)

    mine = [r for r in rows
            if str(r.get(col["am"], "")).strip().upper() == owner.upper()]
    assessed = []
    for r in mine:
        a = assess(r, col, today, contact_days, due_days)
        a["key"] = record_key(r, col)
        assessed.append(a)
    active = [a for a in assessed if not a["closed"]]

    counts = {
        "active": len(active),
        "conflicts": sum(1 for a in active if a["flags"].get("conflict")),
        "overdue": sum(1 for a in active if "overdue" in a["flags"]),
        "ordered_past_end": sum(1 for a in active if "ordered_past_end" in a["flags"]),
        "missing": sum(1 for a in active if "missing" in a["flags"]),
        "contact": sum(1 for a in active if "contact" in a["flags"]),
        "due": sum(1 for a in active if "due" in a["flags"]),
    }

    # What moved since the last review that was sent.
    movement: list[str] = []
    prev_counts = (previous or {}).get("counts", {})
    prev_flags = (previous or {}).get("flags", {})
    if previous:
        for a in active:
            before = prev_flags.get(a["key"])
            f = a["facts"]
            name = f"{f['account']} {f['unit']} '{f['job']}'".strip()
            if before is None:
                movement.append(f"New active record: {name}.")
                continue
            c = a["flags"].get("contact")
            if "contact" in a["flags"] and "contact" not in before and isinstance(c, int):
                movement.append(f"{name} reached {c} days since the last client contact.")
            if a["flags"].get("conflict") and not before.get("conflict"):
                movement.append(f"{name} now has a status/invoice conflict.")
            if "ordered_past_end" in a["flags"] and "ordered_past_end" not in before:
                movement.append(f"{name} has passed its end date while ordered.")
        gone = set(prev_flags) - {a["key"] for a in active}
        if gone:
            movement.append(f"{len(gone)} record(s) are no longer active (closed, invoiced or removed).")

    top = sorted(active, key=lambda a: (-a["score"], -a["facts"]["budget_value"]))[:5]
    return {
        "date": today.isoformat(), "owner": owner, "counts": counts,
        "previous_counts": prev_counts, "previous_date": (previous or {}).get("date"),
        "movement": movement, "top": top,
        "columns_used": col,
        "snapshot": {"date": today.isoformat(), "counts": counts,
                     "flags": {a["key"]: a["flags"] for a in active}},
    }


# ── Wording ──────────────────────────────────────────────────────────────────
_WRITER_SYSTEM = """You write the five items of an account manager's morning
review of his project tracker. For each record you get its facts and the rule
findings ("issues"), already checked. Write:
  "issue": one sentence stating what is inconsistent or late, using only the
           given facts and findings (dates in words, money as given).
  "decision": one sentence saying the decision or update needed from him
           today, starting with a verb, e.g. "Confirm completion date, final
           value and whether invoicing is Yes or N/A." or "Provide one new next
           action and date."
Also write "movement": one or two plain sentences summarising the movement
list (or "No change since the last review." when it is empty). Mention that the
sandbox tracker itself was not changed.
Never add facts that are not given. UK English, no markdown.
Reply with ONLY JSON: {"movement": "...", "items": [{"issue": "...", "decision": "..."}]}
with exactly one item per record, in the order given."""


def _fallback_words(review: dict) -> dict:
    items = []
    for a in review["top"]:
        kinds = [i["kind"] for i in a["issues"]]
        issue = "; ".join(i["text"] for i in a["issues"][:3]) + "."
        if "conflict" in kinds:
            decision = "If complete, confirm the completion date, final value and whether invoicing is Yes or N/A."
        elif "ordered_past_end" in kinds:
            decision = "Confirm the current manufacturing position and provide one new next action date."
        elif "missing" in kinds:
            decision = "Fill in the missing details listed above."
        else:
            decision = "Provide one new next action and date."
        items.append({"issue": issue[:1].upper() + issue[1:], "decision": decision})
    mv = " ".join(review["movement"][:4]) if review["movement"] else "No change since the last review."
    return {"movement": mv + " The sandbox tracker itself remains unchanged.", "items": items}


def word_items(review: dict) -> dict:
    """Claude words the five; plain wording if it cannot."""
    if not review["top"]:
        return {"movement": "No active records need attention.", "items": []}
    if not os.getenv("ANTHROPIC_API_KEY"):
        return _fallback_words(review)
    try:
        import anthropic
        payload = {"today": review["date"], "movement": review["movement"][:12],
                   "records": [{"facts": {k: v for k, v in a["facts"].items() if k != "budget_value"},
                                "issues": [i["text"] for i in a["issues"]]}
                               for a in review["top"]]}
        resp = anthropic.Anthropic().messages.create(
            model=_opt("SDI_REVIEW_MODEL", "claude-opus-5-5"),
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=_WRITER_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        out = json.loads(text)
        if len(out.get("items", [])) != len(review["top"]):
            raise ValueError("wrong number of items")
        return out
    except Exception as exc:                                       # noqa: BLE001
        print(f"[morning_review] wording fell back to plain text: {exc}", flush=True)
        return _fallback_words(review)


def _delta(now: int, before: Optional[int]) -> str:
    if before is None or before == now:
        return ""
    return f" — {'up' if now > before else 'down'} from {before}"


def listen_url() -> str:
    """Where the email's Listen link goes: the app, which reads the briefing aloud."""
    explicit = _opt("SDI_REVIEW_LISTEN_URL")
    if explicit:
        return explicit
    hosts = sorted(h.strip().lower() for h in _opt("SDI_PUBLIC_HOSTS").split(",") if h.strip())
    return f"https://{hosts[0]}/app/voice-crm.html?briefing=1" if hosts else ""


def _speak(text: Any) -> str:
    """Sheet text as it should be heard: capitalised words of four letters or
    more become ordinary words ("TESCO BANK" -> "Tesco Bank"), short ones stay
    as letters ("KD", "FSU", "TPS"), dashes and quotes become pauses."""
    words = []
    for w in str(text or "").replace(" — ", ", ").replace("'", "").split():
        core = re.sub(r"[^A-Za-z]", "", w)
        words.append(w.capitalize() if core.isupper() and len(core) >= 4 else w)
    return " ".join(words)


def _say_money(f: dict) -> str:
    v = f.get("budget_value") or 0
    if not v:
        return ""
    if v >= 1000:
        return f", worth about {round(v / 1000):,} thousand pounds"
    return f", worth {int(v)} pounds"


def greeting(hour: Optional[int] = None) -> str:
    """Good morning / afternoon / evening, by the server's clock (UK time)."""
    hour = datetime.now().hour if hour is None else hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


def spoken_briefing(review: dict, changes: list[dict], first_name: str = "Nick",
                    hour: Optional[int] = None) -> str:
    """The briefing read aloud: what changed in the last 24 hours, what moved in
    the sheet, the headline counts and the top three. Plain sentences, no
    symbols - it goes straight to the phone's speech engine."""
    d = date.fromisoformat(review["date"])
    out = [f"{greeting(hour)} {first_name}. Here's your briefing for {d:%A} {d.day} {d:%B}."]
    if changes:
        n = len(changes)
        out.append(f"In the last 24 hours, {n} update{'s were' if n != 1 else ' was'} saved.")
        for c in changes[:6]:
            who = f", by {c['user_name']}" if c.get("user_name") else ""
            old = c.get("old_value") or "blank"
            out.append(f"On {_speak(c.get('project_ref')) or 'a record'}, {_speak(c['field'])} changed "
                       f"from {old} to {c.get('new_value') or 'blank'}{who}.")
        if n > 6:
            out.append(f"And {n - 6} more.")
    else:
        out.append("No updates were saved through the app in the last 24 hours.")
    if review["movement"]:
        out.append("In the sheet since the last review: " + " ".join(_speak(m) for m in review["movement"][:3]))
        if len(review["movement"]) > 3:
            out.append(f"Plus {len(review['movement']) - 3} other changes.")
    c = review["counts"]
    out.append(f"You have {c['active']} active records. {c['overdue']} have overdue actions, "
               f"{c['conflicts']} have status or invoice conflicts, and {c['ordered_past_end']} "
               f"ordered jobs are past their end date.")
    out.append("Nothing is due in the next seven days." if not c["due"] else
               f"{c['due']} {'is' if c['due'] == 1 else 'are'} due in the next seven days.")
    for label, a in zip(("First", "Second", "Third"), review["top"][:3]):
        f = a["facts"]
        what = a["issues"][0]["text"] if a["issues"] else ""
        out.append(f"{label} priority: {_speak(f['account'])}, {_speak(f['unit'])}, "
                   f"{_speak(f['job'])}{_say_money(f)}. {what}.")
    out.append("That's your briefing. What would you like to update?")
    return " ".join(s.replace("..", ".") for s in out)


def render(review: dict, words: dict, first_name: str = "Nick") -> dict:
    """Subject, plain text and HTML, laid out like Nick's own review."""
    d = date.fromisoformat(review["date"])
    listen = listen_url()
    c, p = review["counts"], review["previous_counts"]
    lines = [
        ("Active NG records reviewed", c["active"], p.get("active")),
        ("Completion/invoice or PO/status conflicts", c["conflicts"], p.get("conflicts")),
        ("Overdue actions", c["overdue"], p.get("overdue")),
        ("Ordered projects past their end date", c["ordered_past_end"], p.get("ordered_past_end")),
        ("Missing/invalid core-data issues", c["missing"], p.get("missing")),
        ("Contact-review triggers", c["contact"], p.get("contact")),
        ("Due within seven days", c["due"], p.get("due")),
    ]
    subject = f"NG Sandbox CRM — Morning Review ({d.day} {d:%B})"
    text = [f"Morning {first_name},", ""]
    if listen:
        text += [f"Listen to this briefing: {listen}", ""]
    text += [f"{d:%A} sandbox-only {review['owner']} review:", ""]
    text += [f"• {label}: {n}{_delta(n, b)}" for label, n, b in lines]
    text += ["", f"New movement: {words['movement']}", "", "Today's five questions", ""]
    blocks = []
    for i, (a, w) in enumerate(zip(review["top"], words["items"]), 1):
        f = a["facts"]
        dates = (f"Action/end date: {f['action']}" if f["action"] == f["end"]
                 else f"Action: {f['action']} | End: {f['end']}")
        head = f"{f['account']} | {f['unit']} | {f['job']} | Project code: {f['code']} | AM Owner: {f['am']}"
        meta = f"PM: {f['pm']} | {dates} | Budget: {f['budget']}"
        text += [f"{i}. {head}", meta, f"Issue: {w['issue']}", f"Decision needed: {w['decision']}", ""]
        blocks.append((head, meta, w))
    text += ["Sent automatically by SDI Intelligence from the sandbox tracker. Read-only: "
             "nothing in the tracker was changed."]

    e = html.escape
    h = [f"<p>Morning {e(first_name)},</p>"]
    if listen:
        h.append(f"<p><a href='{e(listen)}' style='display:inline-block;padding:8px 14px;"
                 f"background:#0b5cad;color:#fff;border-radius:6px;text-decoration:none'>"
                 f"&#9654; Listen to this briefing</a></p>")
    h += [f"<p>{d:%A} sandbox-only {e(review['owner'])} review:</p><ul>"]
    h += [f"<li>{e(label)}: <b>{n}</b>{e(_delta(n, b))}</li>" for label, n, b in lines]
    h += [f"</ul><p><b>New movement:</b> {e(words['movement'])}</p><p><b>Today's five questions</b></p><ol>"]
    for head, meta, w in blocks:
        h.append(f"<li style='margin-bottom:12px'><b>{e(head)}</b><br>{e(meta)}<br>"
                 f"<i>Issue:</i> {e(w['issue'])}<br><i>Decision needed:</i> {e(w['decision'])}</li>")
    h.append("</ol><p style='color:#666;font-size:12px'>Sent automatically by SDI Intelligence "
             "from the sandbox tracker. Read-only: nothing in the tracker was changed.</p>")
    return {"subject": subject, "text": "\n".join(text), "html": "".join(h)}


# ── Snapshots (for "up from 74") ─────────────────────────────────────────────
def _snapshot_file() -> Path:
    import estimate_email
    return estimate_email.state_dir() / "morning_review_snapshots.json"


def last_snapshot(before: date) -> Optional[dict]:
    try:
        snaps = json.loads(_snapshot_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    earlier = [s for s in snaps if s.get("date", "") < before.isoformat()]
    return earlier[-1] if earlier else None


def save_snapshot(snap: dict) -> None:
    path = _snapshot_file()
    try:
        snaps = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snaps = []
    snaps = [s for s in snaps if s.get("date") != snap["date"]] + [snap]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snaps[-40:], indent=1), encoding="utf-8")


def recipients() -> list[str]:
    return [a.strip() for a in re.split(r"[,;\s]+", _opt("SDI_REVIEW_TO")) if "@" in a]


def compose(rows: list[dict], headers: list[str], owner_field: str, owner: str,
            today: Optional[date] = None) -> dict:
    today = today or date.today()
    review = build_review(rows, headers, owner_field, owner, today, last_snapshot(today))
    words = word_items(review)
    return {"review": review, "email": render(review, words)}


def send(composed: dict) -> dict:
    import estimate_email
    to = recipients()
    e = composed["email"]
    if _opt("SDI_REVIEW_FROM"):
        result = send_via_graph(to, e["subject"], e["html"])
    else:
        result = estimate_email.send(to, e["subject"], e["html"], e["text"])
    if result.get("sent"):
        save_snapshot(composed["review"]["snapshot"])
    return result


def send_via_graph(to: list[str], subject: str, body_html: str) -> dict:
    """Send from the SDI_REVIEW_FROM mailbox through Microsoft Graph, app-only.

    Office 365 SMTP needs a mailbox password and SMTP AUTH switched on, which
    MFA and security defaults usually block. Graph needs the Mail.Send
    application permission instead - restricted in Exchange to this one
    mailbox (see MORNING_REVIEW.md) so the app cannot send as anyone else.
    """
    import httpx
    if not to:
        return {"sent": False, "reason": "no recipients - nothing was sent"}
    token, why = app_only_token()
    if not token:
        return {"sent": False, "reason": f"No app-only Graph token: {why}"}
    sender = _opt("SDI_REVIEW_FROM")
    msg = {"message": {"subject": subject,
                       "body": {"contentType": "HTML", "content": body_html},
                       "toRecipients": [{"emailAddress": {"address": a}} for a in to]},
           "saveToSentItems": True}
    try:
        res = httpx.post(f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
                         headers={"Authorization": f"Bearer {token}"}, json=msg, timeout=60)
    except httpx.HTTPError as exc:
        return {"sent": False, "reason": f"Could not reach Microsoft Graph: {exc}"}
    if res.status_code != 202:
        try:
            err = res.json().get("error", {})
            detail = f"{err.get('code')}: {err.get('message')}"
        except ValueError:
            detail = res.text[:300]
        return {"sent": False, "reason": f"Graph sendMail {res.status_code} - {detail}"}
    return {"sent": True, "recipients": to, "via": f"Graph as {sender}"}


# ── The scheduled run ────────────────────────────────────────────────────────
def rows_from_xlsx(data: bytes, key_columns: list[str]) -> tuple[list[dict], list[str], str]:
    """Every data row of the tracker sheet, read from the downloaded file."""
    import io
    import openpyxl
    import voicecrm_excel

    import warnings
    # "Data Validation extension is not supported": the sheet's dropdown lists,
    # which a read of the values does not need. Raised while rows are read
    # (read-only mode parses lazily), so filtered for the whole run.
    warnings.filterwarnings("ignore", message="Data Validation extension", category=UserWarning)
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    store = voicecrm_excel.ExcelStore.__new__(voicecrm_excel.ExcelStore)
    store.key_columns = key_columns
    best = None
    for ws in wb.worksheets[:12]:
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        text = [[("" if v is None else str(v)) for v in r] for r in grid[:25]]
        off, headers, found = store._headers_row(text)
        if found:
            best = (ws.title, grid, off, headers)
            break
        best = best or (ws.title, grid, off, headers)
    if not best:
        return [], [], ""
    title, grid, off, headers = best
    rows = []
    for r in grid[off + 1:]:
        if not any(v not in (None, "") for v in r):
            continue
        rows.append({h: (r[j] if j < len(r) else None) for j, h in enumerate(headers) if h})
    return rows, [h for h in headers if h], title


def app_only_token() -> tuple[Optional[str], str]:
    import auth
    if not (auth.CLIENT_ID and auth.CLIENT_SECRET):
        return None, "SDI_CLIENT_ID / SDI_CLIENT_SECRET are not set."
    result = auth._msal_app().acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        return None, f"{result.get('error')}: {result.get('error_description', '')[:300]}"
    return result["access_token"], ""


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build (and optionally email) Nick's morning review.")
    ap.add_argument("--send", action="store_true", help="email it to SDI_REVIEW_TO")
    ap.add_argument("--weekdays-only", action="store_true", help="do nothing on Saturday/Sunday")
    args = ap.parse_args(argv)

    os.chdir(Path(__file__).resolve().parent)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config  # noqa: F401  — loads .env
    import voicecrm

    if args.weekdays_only and date.today().weekday() >= 5:
        print("Weekend — no review sent.")
        return 0
    if not voicecrm.EXCEL:
        print("SDI_VOICECRM_STORE is not 'excel'.")
        return 1
    token, why = app_only_token()
    if not token:
        print(f"No app-only Graph token: {why}")
        return 1
    data, err = voicecrm.EXCEL.download(token)
    if err:
        print(f"Could not read the tracker: {err}")
        if err.get("status") in (401, 403, 404):
            print("The app needs the Sites.Selected application permission, admin-consented, "
                  "and read access granted on the sandbox site. See MORNING_REVIEW.md.")
        return 1
    rows, headers, sheet = rows_from_xlsx(data, voicecrm.EXCEL.key_columns)
    composed = compose(rows, headers, voicecrm.OWNER_FIELD, voicecrm.OWNER or "NG")
    print(f"Sheet '{sheet}': {len(rows)} rows. {composed['review']['counts']}")
    print(composed["email"]["text"])
    if not args.send:
        print("\n(Preview only — run with --send to email it.)")
        return 0
    if not recipients():
        print("SDI_REVIEW_TO is empty — nothing sent.")
        return 1
    result = send(composed)
    print("Sent to " + ", ".join(recipients()) if result.get("sent") else f"NOT sent: {result.get('reason')}")
    return 0 if result.get("sent") else 1


if __name__ == "__main__":
    sys.exit(main())
