"""The page behind the e-mail's walkthrough button (D-610).

JG, 31 Oct 2026: "The voice also should be a button on the e-mail that starts the portal in a
new area where it lists the commentary also and it also allows an area where questions on the
estimate can be asked."

A LINK THAT OUTLIVES THE SERVICE. Runs are held in memory and a restart forgets them, and this
service is restarted with every deployment, so an e-mail link to a run id would be dead by the
next morning. When a finished run carries a walkthrough, a small record is written here, on
disk, under a random token: what the page needs to show and which files it may hand out. The
e-mail links to the token; the page and its question box read the record.

ONLY THE RUN'S OWN FILES. The record lists the deliverables the runner filed for that run, and
the page serves those names and nothing else: never a path a caller typed. A customer quote is
held by the same release gate as everywhere else.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_COMMENTARY_MAX_CHARS = 20000


def store_dir() -> Path:
    import estimate_email
    return estimate_email.state_dir() / "walkthroughs"


def portal_base() -> str:
    """Where a reader of the e-mail reaches this service. SDI_PORTAL_URL where set; otherwise
    the portal's public address, https:// and the first of SDI_PUBLIC_HOSTS, which a phone
    opens through Microsoft sign-in with no VPN (D-613); otherwise this machine's name and
    port, which only a PC on the SDI network can open. Never localhost: on the reader's own
    PC that is their PC."""
    explicit = os.getenv("SDI_PORTAL_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    public = [h.strip().lower() for h in os.getenv("SDI_PUBLIC_HOSTS", "").split(",")
              if h.strip()]
    if public:
        return "https://" + public[0].split("/")[0]
    port = os.getenv("SDI_PORT", "").strip()
    if not port:
        try:
            import config
            port = str(getattr(config, "PORT", "") or "8071")
        except Exception:                                            # noqa: BLE001
            port = "8071"
    return f"http://{socket.gethostname()}:{port}"


def url_for(token: str) -> str:
    return f"{portal_base()}/estimating/walkthrough/{token}"


def ask_url(url: str) -> str:
    """The same page, opened at its question box."""
    return url.split("#", 1)[0] + "#ask"


def _names(deliverables: List[Dict[str, str]]) -> List[str]:
    return [str(d.get("name") or "") for d in deliverables or [] if isinstance(d, dict)]


def has_walkthrough(deliverables: List[Dict[str, str]]) -> bool:
    return any(n.lower().endswith(("_walkthrough.wav", "_walkthrough.txt"))
               for n in _names(deliverables))


def make(run: Dict[str, Any], deliverables: List[Dict[str, str]]) -> Optional[str]:
    """Write the record for a finished run that carries a walkthrough; its token, or None."""
    if not has_walkthrough(deliverables):
        return None
    token = secrets.token_urlsafe(18)
    record = {
        "token": token, "created": time.time(), "run_id": run.get("run_id"),
        "client": run.get("client") or "", "drawing_number": run.get("drawing_number") or "",
        "units": run.get("units"), "unit_cost_gbp": run.get("engine_price_gbp"),
        "quantity_prices": list(run.get("quantity_prices") or []),
        "output_path": run.get("output_path") or "",
        "deliverables": [{"name": str(d.get("name")), "path": str(d.get("path"))}
                         for d in deliverables or []
                         if isinstance(d, dict) and d.get("name") and d.get("path")],
    }
    folder = store_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{token}.tmp"
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, folder / f"{token}.json")
    return token


def load_token_ok(path: str) -> bool:
    """True when a relayed walkthrough path names a well-formed token (nothing else travels)."""
    m = re.match(r"^/api/estimate/walkthrough/([^/]+)(?:/|$)", str(path or ""))
    return bool(m and _TOKEN.match(m.group(1)))


def load(token: str) -> Optional[Dict[str, Any]]:
    if not _TOKEN.match(str(token or "")):
        return None
    try:
        data = json.loads((store_dir() / f"{token}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("token") == token else None


def file_for(record: Dict[str, Any], name: str) -> Optional[Path]:
    """The path of one of the record's own files, by exact name; None for anything else."""
    want = str(name or "").strip()
    if not want or "/" in want or "\\" in want:
        return None
    hit = next((d for d in record.get("deliverables") or [] if d.get("name") == want), None)
    path = Path(str(hit.get("path"))) if hit else None
    return path if path is not None and path.is_file() else None


def _first(record: Dict[str, Any], suffix: str) -> str:
    return next((d["name"] for d in record.get("deliverables") or []
                 if str(d.get("name") or "").lower().endswith(suffix)), "")


def commentary(record: Dict[str, Any]) -> str:
    path = file_for(record, _first(record, "_walkthrough.txt"))
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")[:_COMMENTARY_MAX_CHARS].strip()
    except OSError:
        return ""


def records_json(record: Dict[str, Any]) -> List[str]:
    """The run's saved records, for the question box to answer from."""
    return [str(file_for(record, d["name"])) for d in record.get("deliverables") or []
            if str(d.get("name") or "").lower().endswith(".json") and file_for(record, d["name"])]


def public_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """What the page shows: never a path, only names it can ask for.

    THE PORTAL CLIENT ESTIMATE IS AVAILABLE EVERY TIME (D-645). JG, 3 Nov 2026: "remove this
    immediately ... make the portal client estimate available every time". The quotation was
    listed as held, as words, while it was not released for a customer. This page is for our
    own people, signed in: every file the run filed is a link, and a quotation not released
    for a customer opens as the portal working copy (walkthrough_file serves it to be read,
    not as a download). Sending a quotation TO a customer is still the e-mail's release gate,
    not this page's. `held` stays in the reply, empty, for a page that still reads it."""
    files: List[str] = [str(d.get("name") or "") for d in record.get("deliverables") or []
                        if str(d.get("name") or "")]
    held: List[Dict[str, str]] = []
    return {
        "client": record.get("client"), "drawing_number": record.get("drawing_number"),
        "units": record.get("units"), "unit_cost_gbp": record.get("unit_cost_gbp"),
        "quantity_prices": record.get("quantity_prices") or [],
        "created": record.get("created"),
        "audio": _first(record, "_walkthrough.wav"),
        "commentary": commentary(record),
        "files": files, "held": held,
    }


# Marks a note that already carries the two buttons, so neither the filed note nor the e-mail
# made from it ever shows them twice (D-709).
BUTTON_MARK = "<!-- sdi-ask-buttons -->"
_ASK_TEXT = "Ask a question about this estimate:"


def audio_of(deliverables: Any) -> Optional[str]:
    """The run's own spoken walkthrough among its files: its file name, "" when the run filed
    a walkthrough's words but no sound (the audio was not made), None when it filed neither."""
    names = [str((d or {}).get("name") or "") for d in (deliverables or []) if isinstance(d, dict)]
    wav = sorted(n for n in names if n.lower().endswith("_walkthrough.wav"))
    if wav:
        return wav[-1]
    return "" if any(n.lower().endswith("_walkthrough.txt") for n in names) else None


def wav_url(url: str, audio: str) -> str:
    """The address of the WAV itself, served by this service to anyone who can open the page:
    never a path on the machine that made it."""
    from urllib.parse import quote
    page = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    # the page is /estimating/walkthrough/<token>; its files are served, as the page itself
    # fetches them, from /api/estimate/walkthrough/<token>/file/<name>
    api = page.replace("/estimating/walkthrough/", "/api/estimate/walkthrough/", 1)
    return api + "/file/" + quote(audio)


def _buttons(url: str, audio: Optional[str] = None) -> Dict[str, str]:
    """The buttons, as HTML and as plain text: ask about the estimate, which opens the page
    at its question box, and listen to the walkthrough.

    THE WAV, NAMED AS ONE (JG, 12 Nov 2026): "Add a clearly labelled 'Listen to the estimate
    walkthrough, WAV' link to both the HTML covering note and the automatic email body. Use a
    location recipients can access, not a runner-local path. If audio generation failed, say so
    rather than showing a broken link." `audio` is the run's WAV file name, "" when the run
    made the words and no sound, None when nothing is known (the buttons as they were)."""
    ask = ask_url(url)
    listen = url.split("#", 1)[0] + "#listen"
    _btn = ("display:inline-block;padding:11px 18px;border-radius:4px;text-decoration:none;"
            "font-weight:bold;margin:0 8px 8px 0")
    html = (
        '<p style="margin:14px 0 4px">'
        '<a href="' + ask + '" style="' + _btn + 'background:#B8860B;color:#ffffff">'
        '&#10067; Ask a question about this estimate</a>'
        '<a href="' + listen + '" style="' + _btn + 'background:#ffffff;color:#B8860B;'
        'border:2px solid #B8860B">&#9654; Listen to the walkthrough</a></p>'
        '<p style="margin:0 0 14px;color:#5b6b7d;font-size:12px">Opens the SDI Intelligence '
        'app: type a question and it is answered from this estimate\'s own figures. The price '
        'at every quantity, the spoken walkthrough and its words are on the same page. Works '
        'on a phone; you sign in with your SDI Microsoft account.</p>')
    text = f"{_ASK_TEXT} {ask}\nListen to the walkthrough: {listen}\n"
    if audio:
        _wav = wav_url(url, audio)
        html += ('<p style="margin:0 0 14px"><a href="' + _wav + '" style="color:#B8860B;'
                 'font-weight:bold">&#128266; Listen to the estimate walkthrough &mdash; WAV</a>'
                 '<span style="color:#5b6b7d;font-size:12px"> (' + audio + ')</span></p>')
        text += f"Listen to the estimate walkthrough - WAV: {_wav}\n"
    elif audio == "":
        html += ('<p style="margin:0 0 14px;color:#8a1f11;font-size:13px">The spoken walkthrough '
                 'was not made for this run: its audio could not be generated. Its words are on '
                 'the page above.</p>')
        text += "The spoken walkthrough was not made for this run: its audio could not be generated.\n"
    html += BUTTON_MARK
    text += "\n"
    return {"html": html, "text": text}


def _with_buttons_html(html: str, block: str) -> str:
    """The HTML with the buttons just inside its first <div>, after any leading comment (the
    engine's "<!-- subject: ... -->" stays first, where the mail service reads it)."""
    if BUTTON_MARK in html:
        return html
    m = re.search(r"<div[^>]*>", html)
    if m:
        return html[:m.end()] + block + html[m.end():]
    lead = re.match(r"\s*(?:<!--.*?-->\s*)*", html, flags=re.S)
    at = lead.end() if lead else 0
    return html[:at] + block + html[at:]


def email_button(note: Dict[str, str], url: str, audio: Optional[str] = None) -> Dict[str, str]:
    """The note with its two buttons at the top, in the HTML and the plain text: ask about
    the estimate, which opens the page at its question box, and listen to the walkthrough.

    JG, 1 Nov 2026: "when you select the button on the e-mail to prompt / question the
    estimate, it takes you to the app with the prompt part". The link is the portal's public
    address when there is one, so it opens on a phone, through Microsoft sign-in, with no VPN.
    A note whose filed copy already carries them (D-709) is left as it is.
    """
    b = _buttons(url, audio)
    html = _with_buttons_html(str(note.get("html") or ""), b["html"])
    text = str(note.get("text") or "")
    if _ASK_TEXT not in text:
        text = b["text"] + text
    return dict(note, html=html, text=text)


_NOTE_SUFFIXES = ("_covering_email.html", "_covering_note.html")


def stamp_note_files(paths: List[str], url: str, audio: Optional[str] = None) -> List[str]:
    """Write the two buttons into the filed covering note, so the file in AISheets and in the
    completed AI briefs area reads like the e-mail (D-709).

    JG, 5 Nov 2026: "can we add the voice ai part ... to the covering_email html file". The
    engine writes the note while it runs; the walkthrough page, and so its link, exists only
    once the run has finished and this service has recorded it. So the buttons are added here,
    to each copy of the note, and to its plain-text sibling. A copy that already carries them
    is left alone. Returns the files written; one that cannot be written is skipped, never
    raised: the estimate is filed whatever happens here."""
    if not url:
        return []
    b = _buttons(url, audio)
    done: List[str] = []
    for raw in paths or []:
        path = Path(str(raw or ""))
        if not path.name.lower().endswith(_NOTE_SUFFIXES):
            continue
        try:
            html = path.read_text(encoding="utf-8")
            new = _with_buttons_html(html, b["html"])
            if new != html:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(new, encoding="utf-8")
                os.replace(tmp, path)
                done.append(str(path))
            txt = path.with_suffix(".txt")
            if txt.exists():
                text = txt.read_text(encoding="utf-8")
                if _ASK_TEXT not in text:
                    tmp = txt.with_name(txt.name + ".tmp")
                    tmp.write_text(b["text"] + text, encoding="utf-8")
                    os.replace(tmp, txt)
        except OSError:
            continue
    return done
