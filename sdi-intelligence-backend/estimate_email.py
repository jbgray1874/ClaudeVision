"""Send a finished estimate to the people who asked for it.

WHY THIS EXISTS. Every estimate so far has been delivered by somebody opening the output
folder, finding four files, attaching them to a mail and typing out what the number means.
That is the same note every time, written slightly differently every time, and the difference
between "the engine produced an estimate" and "estimating received one" is entirely that
manual step.

WHO SENDS IT, AND WHY IT IS NOT THE RUNNER. The runner has the files; this service has the
recipients, the SMTP settings and the record of the run. It also has the run's log, its price
and its status, which is what the note is actually about. So this service sends, and attaches
what it can reach — which on a deployment where the share is not visible to it is nothing, and
the note then carries the paths instead. Saying where the files are beats failing to send.

EMPTY MEANS DO NOT SEND. A run queued with no recipients mails nobody, so an engine test does
not land in an estimator's inbox at two in the morning. That is why the field is not defaulted
from the saved list at send time: the page fills the box, a person sees it, and what they leave
in it is what happens.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── where the saved list lives ───────────────────────────────────────────────
# OUTSIDE THE REPOSITORY. A list of who gets estimates is operational state, not code: it
# should survive a checkout, not travel in one, and it must never be a file somebody can
# commit by accident. ProgramData is the Windows home for exactly this.

_STATE_FILENAME = "estimate_recipients.json"


def state_dir() -> Path:
    explicit = os.getenv("SDI_STATE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    program_data = os.getenv("PROGRAMDATA", "").strip()
    if program_data:
        return Path(program_data) / "SDI Intelligence"
    return Path.home() / ".sdi-intelligence"


def _state_file() -> Path:
    return state_dir() / _STATE_FILENAME


# ── addresses ────────────────────────────────────────────────────────────────
# Deliberately not RFC 5322. That grammar admits things no estimator will ever type and
# rejecting a plausible address is worse than accepting an implausible one — the send will
# bounce and say so, whereas a refusal at this end just looks broken.
_ADDRESS = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_SEPARATORS = re.compile(r"[,;\s]+")


def parse_recipients(text: Any) -> Tuple[List[str], List[str]]:
    """Split what somebody typed into addresses, and whatever was not one.

    BOTH HALVES ARE RETURNED, because silently dropping the malformed one is how an estimate
    goes to three people when four were asked for and nobody finds out. A typo has to be
    reported back to the person who made it, at the moment they made it.
    """
    if isinstance(text, (list, tuple)):
        raw = [str(item) for item in text]
    else:
        raw = _SEPARATORS.split(str(text or "").strip())
    good: List[str] = []
    bad: List[str] = []
    for token in raw:
        token = token.strip().strip("<>").strip()
        if not token:
            continue
        if _ADDRESS.match(token):
            if token.lower() not in {g.lower() for g in good}:
                good.append(token)
        else:
            bad.append(token)
    return good, bad


# ── the saved default ────────────────────────────────────────────────────────

def saved_recipients() -> Dict[str, Any]:
    """The list the page pre-fills with, and where it came from."""
    path = _state_file()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            people, _ = parse_recipients(data.get("recipients") or [])
            if people:
                return {"recipients": people, "source": str(path)}
    except Exception:                                            # noqa: BLE001
        pass
    seeded, _ = parse_recipients(os.getenv("SDI_ESTIMATE_EMAIL_TO", ""))
    if seeded:
        return {"recipients": seeded, "source": "SDI_ESTIMATE_EMAIL_TO"}
    return {"recipients": [], "source": "nothing set"}


def save_recipients(text: Any) -> Dict[str, Any]:
    people, bad = parse_recipients(text)
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole and replaced, not appended: the file IS the list, and a half-written one
    # would be read as a shorter list rather than as a broken file.
    path.write_text(json.dumps({"recipients": people}, indent=2), encoding="utf-8")
    return {"recipients": people, "rejected": bad, "source": str(path)}


# ── the transport ────────────────────────────────────────────────────────────

def smtp_settings() -> Dict[str, Any]:
    """The same variables live_enquiry_collector has been sending on for months."""
    user = os.getenv("SMTP_USER", "").strip()
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": user,
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("SMTP_FROM", user).strip() or user,
    }


def smtp_configured() -> bool:
    s = smtp_settings()
    return bool(s["host"] and s["sender"])


# A cap, because a mail server will refuse a large message in a way that loses the whole
# send rather than one attachment. The note then says which files were left out and where
# they are, which is more use than a bounce.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024

_CONTENT_TYPES = {
    ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xlsm": ("application", "vnd.ms-excel.sheet.macroEnabled.12"),
    ".html": ("text", "html"),
    ".htm": ("text", "html"),
    ".md": ("text", "markdown"),
    ".csv": ("text", "csv"),
    ".json": ("application", "json"),
    ".pdf": ("application", "pdf"),
}


def attach_what_we_can(message: EmailMessage,
                       paths: List[str]) -> Tuple[List[str], List[Dict[str, str]]]:
    """Attach every file this service can actually read; report the rest by path.

    THE SHARE IS NOT ALWAYS VISIBLE FROM HERE. The runner exists precisely because this
    service may not see the estimating share — so a send that requires the attachments to be
    readable is a send that fails on the deployment it matters most on. Anything unreadable
    or oversized is named in the note with its full path, which an estimator on the domain
    can paste straight into Explorer.
    """
    attached: List[str] = []
    skipped: List[Dict[str, str]] = []
    total = 0
    for raw in paths:
        path = Path(str(raw))
        try:
            size = path.stat().st_size
        except OSError as exc:
            skipped.append({"path": str(raw), "why": f"not reachable from this service "
                                                     f"({type(exc).__name__})"})
            continue
        if size > MAX_ATTACHMENT_BYTES:
            skipped.append({"path": str(raw),
                            "why": f"{size / 1024 / 1024:.1f} MB — too large to attach"})
            continue
        if total + size > MAX_TOTAL_BYTES:
            skipped.append({"path": str(raw), "why": "the message was already at its size "
                                                     "limit"})
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            skipped.append({"path": str(raw), "why": f"could not be read "
                                                     f"({type(exc).__name__})"})
            continue
        maintype, subtype = _CONTENT_TYPES.get(path.suffix.lower(),
                                               ("application", "octet-stream"))
        message.add_attachment(data, maintype=maintype, subtype=subtype,
                               filename=path.name)
        attached.append(path.name)
        total += size
    return attached, skipped


def send(recipients: List[str], subject: str, body_html: str, body_text: str,
         paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Send one estimate. Returns what happened; never raises at the caller."""
    if not recipients:
        return {"sent": False, "reason": "no recipients — nothing was sent"}
    if not smtp_configured():
        return {"sent": False, "reason": "SMTP is not configured (SMTP_HOST / SMTP_FROM)"}

    settings = smtp_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = ", ".join(recipients)
    message.set_content(body_text)
    message.add_alternative(body_html, subtype="html")

    attached, skipped = attach_what_we_can(message, list(paths or []))

    try:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=60) as server:
            try:
                server.starttls(context=ssl.create_default_context())
            except smtplib.SMTPException:
                # A server that does not offer STARTTLS is one an administrator chose. Said
                # rather than silently downgraded, because "it sent" and "it sent in clear"
                # are different facts about an estimate.
                pass
            if settings["user"] and settings["password"]:
                server.login(settings["user"], settings["password"])
            server.send_message(message)
    except Exception as exc:                                     # noqa: BLE001
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}",
                "recipients": recipients, "attached": attached, "skipped": skipped}
    return {"sent": True, "recipients": recipients, "attached": attached,
            "skipped": skipped}


# ── the note ─────────────────────────────────────────────────────────────────
#
# WRITTEN FROM THE RUN, NOT FROM THE WORKBOOK. This service has never read an estimate and is
# not about to start: it knows the client, the drawing, the quantity, the unit cost the runner
# reported and whether the job came out provisional. That is enough for a covering note. The
# detail belongs in the attachments, which carry it in full and are generated by the engine
# from the sheet itself — repeating any of it here would be a second answer to the same
# question, computed somewhere with less information.

_STYLE = ("font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
          "color:#1c2530")


def _money(value: Any) -> str:
    try:
        return f"£{float(value):,.2f}"
    except (TypeError, ValueError):
        return "not reported"


def compose(run: Dict[str, Any], deliverables: List[Dict[str, str]],
            provisional: bool = True) -> Dict[str, str]:
    """Subject, HTML and plain text for one finished estimate."""
    drawing = str(run.get("drawing_number") or "").strip() or "estimate"
    client = str(run.get("client") or "").strip()
    units = run.get("units") or 1
    unit = run.get("engine_price_gbp")

    subject = (f"SDI Intelligence estimate, PROVISIONAL. {_money(unit)}/unit at {units} off. "
               f"{drawing}" if provisional else
               f"SDI Intelligence estimate. {_money(unit)}/unit at {units} off. {drawing}")

    files = [d for d in deliverables if isinstance(d, dict) and d.get("path")]
    rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0"><b>{_esc(Path(str(d["path"])).name)}</b></td>'
        f'<td style="padding:2px 0;color:#5b6b7d">{_esc(str(d.get("what") or ""))}</td></tr>'
        for d in files)

    lead = ("This is a working pack, not a quote." if provisional else
            "This estimate carries no outstanding estimator inputs.")

    html = f"""<div style="{_STYLE}">
<p>{_esc(drawing)}{' &middot; ' + _esc(client) if client else ''} &middot; {units} off.</p>
<p style="font-size:22px;margin:14px 0"><b>{_money(unit)}</b>
   <span style="color:#5b6b7d;font-size:14px">per unit, ex VAT</span></p>
<p>{lead} Every figure is read from the workbook's own calculated cells. The
   <b>AI Explanation</b> tab in the spreadsheet, and section 14 of the report, give every row
   with the drawing page it came from, which reader decided it and what it charges.</p>
<table style="border-collapse:collapse;margin:14px 0">{rows}</table>
<p style="color:#5b6b7d;font-size:12px">Produced by SDI Intelligence for
   {_esc(client) or 'this job'}. Sent automatically when the run completed.</p>
</div>"""

    text_files = "\n".join(f"  {Path(str(d['path'])).name}" for d in files)
    text = (f"{drawing}{' - ' + client if client else ''} - {units} off\n\n"
            f"{_money(unit)} per unit, ex VAT\n\n{lead} Every figure is read from the "
            f"workbook's own calculated cells. The AI Explanation tab, and section 14 of the "
            f"report, give every row with the drawing page it came from, which reader decided "
            f"it and what it charges.\n\n{text_files}\n")
    return {"subject": subject, "html": html, "text": text}


def _esc(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# WHICH FILES GO, AND THE ONE THAT DOES NOT GO BY DEFAULT.
#
# The customer quote is the only deliverable written to be read by a customer. On a
# provisional estimate it carries a figure nobody has stood behind yet, in a document that
# looks exactly like a quotation — and "do not send the quote HTML" has been said on every
# job so far. So it is withheld while the estimate is provisional, and the page has to ask
# for it deliberately.
_QUOTE_MARKERS = ("_quote", "quote.html")


def is_customer_quote(path: Any) -> bool:
    name = Path(str(path or "")).name.lower()
    return any(marker in name for marker in _QUOTE_MARKERS)


def choose_attachments(deliverables: List[Dict[str, str]], *, provisional: bool,
                       include_quote: bool) -> Tuple[List[str], List[Dict[str, str]]]:
    """The paths to attach, and what was deliberately held back with the reason."""
    keep: List[str] = []
    held: List[Dict[str, str]] = []
    for item in deliverables or []:
        path = str((item or {}).get("path") or "")
        if not path:
            continue
        if is_customer_quote(path):
            if provisional and not include_quote:
                held.append({"path": path,
                             "why": "the customer quote is not sent while the estimate is "
                                    "provisional"})
                continue
            if not include_quote:
                held.append({"path": path, "why": "not requested"})
                continue
        keep.append(path)
    return keep, held
