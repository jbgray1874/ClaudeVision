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
    """Where a reader of the e-mail reaches this service: SDI_PORTAL_URL where set, otherwise
    this machine's name and port, which any PC on the SDI network can open. Never localhost:
    on the reader's own PC that is their PC."""
    explicit = os.getenv("SDI_PORTAL_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
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
    """What the page shows: never a path, only names it can ask for."""
    return {
        "client": record.get("client"), "drawing_number": record.get("drawing_number"),
        "units": record.get("units"), "unit_cost_gbp": record.get("unit_cost_gbp"),
        "quantity_prices": record.get("quantity_prices") or [],
        "created": record.get("created"),
        "audio": _first(record, "_walkthrough.wav"),
        "commentary": commentary(record),
        "files": [d["name"] for d in record.get("deliverables") or []],
    }


def email_button(note: Dict[str, str], url: str) -> Dict[str, str]:
    """The note with the walkthrough button at its top, in the HTML and the plain text."""
    button = (
        '<p style="margin:14px 0 4px"><a href="' + url + '" style="display:inline-block;'
        'background:#B8860B;color:#ffffff;padding:10px 18px;border-radius:4px;'
        'text-decoration:none;font-weight:bold">&#9654; Listen to the walkthrough and ask about '
        'this estimate</a></p><p style="margin:0 0 14px;color:#5b6b7d;font-size:12px">Opens the '
        'SDI Intelligence portal: the spoken walkthrough, its words, the price at every '
        'quantity and a box to ask questions about this estimate. On the SDI network.</p>')
    html = str(note.get("html") or "")
    m = re.match(r"\s*<div[^>]*>", html)
    html = (html[:m.end()] + button + html[m.end():]) if m else button + html
    text = (f"Listen to the walkthrough and ask about this estimate: {url}\n\n"
            + str(note.get("text") or ""))
    return dict(note, html=html, text=text)
