"""A link to the exact drawing pack a run was given, for its e-mail and its filed note
(JG, 13 Nov 2026).

"An accessible link to the exact saved pack for that run, not just a laptop-only path ... the
run ID and pack version, so the email always identifies the correct evidence."

A LINK THAT OUTLIVES THE SERVICE AND NAMES ONE PACK. When a job is queued and its pack is kept
(pack_dropoff.py), a small record is written on disk under a random token: the run id, the
folder of the pack kept for THAT run and its version. The link is the portal's public address
and the token (the same address the walkthrough button uses), so it opens off the laptop,
through Microsoft sign-in. The page lists the pack's files and hands out those files and no
others: never a path a caller typed.

THE PACK THE RUN WAS GIVEN, NOT A LATER ONE. The record points at the version kept at queue
time. A version made afterwards by recovery is shown on the page as exactly that, under its
own heading and with what was added, and is never presented as what the run used.

THE ENGINE WRITES THE SECTION; THIS FILLS IN THE LINK. The drawing pack section is part of the
engine's covering note (src/pack_used.py), with a mark where the link goes. `into_note` fills
it in the e-mail and `stamp_note_files` in every filed copy. A run whose engine filed no note
still gets a section in its e-mail, built here from the kept pack's manifest, saying plainly
that the run recorded nothing of what it read.

Nothing here sends, resends or replaces an e-mail that has gone.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pack_dropoff

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MARK = "<!--sdi-pack-link-->"
DONE = "<!--sdi-pack-linked-->"
HEADING = "Drawing pack used for this estimate"
HEADING_TEXT = "DRAWING PACK USED FOR THIS ESTIMATE"
_LINK_TEXT = "The exact pack this run was given:"
_NOTE_SUFFIXES = ("_covering_email.html", "_covering_note.html")
_REV = re.compile(r"(?:^|[_\s\-.])REV(?:ISION)?[_\s\-]?([A-Z]{1,2}|\d{1,2}|P\d{1,2})(?=$|[_\s\-.()\[\]])", re.I)


def store_dir() -> Path:
    import estimate_email
    return estimate_email.state_dir() / "packs"


def url_for(token: str) -> str:
    import estimate_walkthrough
    return f"{estimate_walkthrough.portal_base()}/estimating/pack/{token}"


def make(run_id: str, client: str, drawing: str, kept: Dict[str, Any]) -> str:
    """Record which kept pack this run was given; its token, or "" where no pack was kept."""
    if not kept or not kept.get("saved") or not kept.get("folder"):
        return ""
    token = secrets.token_urlsafe(18)
    record = {"token": token, "created": time.time(), "run_id": run_id, "client": client or "",
              "drawing_number": drawing or "", "folder": str(kept["folder"]),
              "version": int(kept.get("version") or 1)}
    folder = store_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{token}.tmp"
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, folder / f"{token}.json")
    return token


def token_ok(token: str) -> bool:
    return bool(_TOKEN.match(str(token or "")))


def load(token: str) -> Optional[Dict[str, Any]]:
    if not token_ok(token):
        return None
    try:
        data = json.loads((store_dir() / f"{token}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("token") == token else None


def _manifest(folder: Path) -> Dict[str, Any]:
    try:
        return json.loads((folder / pack_dropoff.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _number(name: str) -> str:
    try:
        import sys
        src = str(Path(__file__).resolve().parents[1] / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        import pack_resolver
        return pack_resolver.drawing_id(name)
    except Exception:                                                # noqa: BLE001
        return ""


def file_for(record: Dict[str, Any], name: str) -> Optional[Path]:
    """One of this pack's own files, by the name its manifest lists; None for anything else."""
    folder = Path(str(record.get("folder") or ""))
    listed = {str(f.get("name")) for f in _manifest(folder).get("files") or []}
    want = str(name or "").replace("\\", "/").strip()
    if want not in listed or ".." in want.split("/"):
        return None
    path = folder / want
    return path if path.is_file() else None


def _later_recoveries(folder: Path) -> List[Dict[str, Any]]:
    """Versions made from this pack by recovery, each labelled as that."""
    out = []
    try:
        siblings = [p for p in folder.parent.iterdir() if p.is_dir() and p != folder]
    except OSError:
        return out
    for p in sorted(siblings):
        rec = _manifest(p).get("recovery") or {}
        if rec.get("recovered_from") == folder.name:
            out.append({"folder": p.name, "at": rec.get("at") or "", "added": list(rec.get("added") or []),
                        "not_recovered": [str(c.get("name")) for c in rec.get("not_recovered") or []]})
    return out


def view(record: Dict[str, Any]) -> Dict[str, Any]:
    """What the page shows, from the kept pack's manifest as it stands."""
    folder = Path(str(record.get("folder") or ""))
    m = _manifest(folder)
    run_id = str(record.get("run_id") or "")
    on_run = ((m.get("read_on_runs") or {}).get(run_id) or {})
    outcome = {str(f.get("file")).lower(): f for f in on_run.get("files") or []}
    files = []
    for f in m.get("files") or []:
        name = str(f.get("name"))
        base = name.split("/")[-1]
        o = outcome.get(base.lower()) or {}
        rev = f.get("revision") or ""
        if not rev:
            hit = _REV.search(Path(base).stem)
            rev = hit.group(1).upper() if hit else ""
        files.append({"name": name, "drawing": _number(base), "revision": rev,
                      "format": Path(base).suffix.lstrip(".").upper() or "-",
                      "size": f.get("size"),
                      "intended_handling": f.get("intended_handling") or pack_dropoff.intended_handling(base),
                      "on_this_run": o.get("state") or "", "why": o.get("why") or "",
                      "recovered": bool(f.get("recovered"))})
    c = m.get("completeness") or {}
    recovery = m.get("recovery") or {}
    return {
        "run_id": run_id, "client": record.get("client") or m.get("client") or "",
        "drawing_number": record.get("drawing_number") or m.get("drawing") or "",
        "pack_version": record.get("version") or m.get("version"), "folder_name": folder.name,
        "available": bool(m), "files": files,
        "read_recorded": bool(on_run),
        "completeness": c,
        "not_in_this_copy": list(m.get("not_in_this_copy") or []),
        "missing": list(m.get("missing") or []),
        "unread_assemblies": list(m.get("unread_assemblies") or []),
        # A PACK THAT IS ITSELF A RECOVERY SAYS SO; so does one that has been recovered from.
        "this_is_a_recovered_pack": bool(recovery),
        "recovery": recovery,
        "recovered_versions_made_later": _later_recoveries(folder),
        "runs": list(m.get("runs") or []),
    }


# ── INTO THE NOTE ────────────────────────────────────────────────────────────────────────
def _link_html(url: str) -> str:
    return ('<p style="margin:0 0 8px;font-size:13px"><a href="' + _html.escape(url, quote=True)
            + '" style="color:#B8860B;font-weight:bold">&#128193; Open the exact drawing pack this '
              'run was given</a><span style="color:#5b6b7d"> (the files, their revisions and what '
              'was read; you sign in with your SDI Microsoft account)</span></p>' + DONE)


_NO_LINK_HTML = ('<p style="margin:0 0 8px;color:#8a1f11;font-size:13px">No link to the saved pack: '
                 'no copy of this run\'s pack was kept, so there is nothing to open.</p>' + DONE)
_NO_LINK_TEXT = "No link to the saved pack: no copy of this run's pack was kept."


def _fill_html(html: str, url: str) -> str:
    if DONE in html or MARK not in html:
        return html
    return html.replace(MARK, _link_html(url) if url else _NO_LINK_HTML, 1)


def _fill_text(text: str, url: str) -> str:
    if _LINK_TEXT in text or _NO_LINK_TEXT in text or HEADING_TEXT not in text:
        return text
    line = f"{_LINK_TEXT} {url}" if url else _NO_LINK_TEXT
    head, rest = text.split(HEADING_TEXT, 1)
    first, _, after = rest.partition("\n")          # the heading's own line end
    ident, _, body = after.partition("\n")          # "Run ... · pack version N"
    return head + HEADING_TEXT + first + "\n" + ident + "\n" + line + "\n" + body


def section_from_kept_pack(snapshot: Dict[str, Any], token: str) -> Dict[str, str]:
    """The section for a run whose engine filed no note: what was kept, and that the run
    recorded nothing of what it read. Empty when there is no kept pack either."""
    record = load(token) if token else None
    if not record:
        return {"html": "", "text": ""}
    v = view(record)
    e = _html.escape
    ident = f"Run {v['run_id'] or 'not recorded'} · pack version {v['pack_version']}"
    gaps = ["This run filed no covering note, so there is no record here of which files it read."]
    for k in ("source_pack", "copy"):
        part = v["completeness"].get(k) or {}
        if part.get("state") and part.get("state") != "complete":
            gaps += [str(w) for w in part.get("because") or []]
    td = "padding:3px 10px 3px 0;border-bottom:1px solid #e3e8ee;font-size:13px;vertical-align:top"
    body = "".join(f'<tr><td style="{td}">{e(f["name"])}</td><td style="{td}">{e(f["drawing"] or "-")}</td>'
                   f'<td style="{td}">{e(f["revision"] or "-")}</td><td style="{td}">{e(f["format"])}</td>'
                   f'<td style="{td}">not recorded</td></tr>' for f in v["files"])
    html = ('<div style="margin:14px 0 18px;padding:12px 14px;border:1px solid #d5dbe3;border-radius:4px">'
            f'<p style="margin:0 0 6px;font-weight:bold;font-size:15px">{HEADING}</p>'
            f'<p style="margin:0 0 6px;font-size:13px"><b>{e(ident)}</b></p>' + MARK
            + '<p style="margin:0 0 6px;color:#8a1f11;font-weight:bold;font-size:14px">PACK COMPLETENESS NOT PROVED</p>'
            + "".join(f'<p style="margin:0 0 6px;color:#8a1f11;font-size:13px">{e(w)}</p>' for w in gaps)
            + '<table style="border-collapse:collapse"><tr>'
            + "".join(f'<th style="{td};text-align:left">{h}</th>' for h in ("File", "Drawing", "Rev", "Format", "On this run"))
            + f"</tr>{body}</table></div>")
    text = (HEADING_TEXT + "\n" + ident + "\n  !! PACK COMPLETENESS NOT PROVED\n"
            + "".join(f"  ! {w}\n" for w in gaps)
            + "".join(f"  {f['name']}  |  {f['drawing'] or '-'}  |  rev {f['revision'] or '-'}  |  {f['format']}  |  not recorded\n"
                      for f in v["files"]) + "\n")
    return {"html": html, "text": text}


def into_note(note: Dict[str, str], snapshot: Dict[str, Any]) -> Dict[str, str]:
    """The e-mail's note with the link to the run's pack filled in. A note with no drawing
    pack section at all (the short form, where the engine filed none) gains one first."""
    token = str(snapshot.get("pack_token") or "")
    url = url_for(token) if token and load(token) else ""
    html, text = str(note.get("html") or ""), str(note.get("text") or "")
    if HEADING not in html:
        s = section_from_kept_pack(snapshot, token)
        if s["html"]:
            m = re.search(r"<div[^>]*>", html)
            at = m.end() if m else 0
            html, text = html[:at] + s["html"] + html[at:], s["text"] + text
    return dict(note, html=_fill_html(html, url), text=_fill_text(text, url))


def stamp_note_files(paths: List[str], snapshot: Dict[str, Any]) -> List[str]:
    """Fill the link into each filed copy of the covering note and its plain-text sibling.
    A copy already filled is left alone; one that cannot be written is skipped, never raised."""
    token = str(snapshot.get("pack_token") or "")
    url = url_for(token) if token and load(token) else ""
    done: List[str] = []
    for raw in paths or []:
        path = Path(str(raw or ""))
        if not path.name.lower().endswith(_NOTE_SUFFIXES):
            continue
        try:
            html = path.read_text(encoding="utf-8")
            new = _fill_html(html, url)
            if new != html:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(new, encoding="utf-8")
                os.replace(tmp, path)
                done.append(str(path))
            txt = path.with_suffix(".txt")
            if txt.exists():
                text = txt.read_text(encoding="utf-8")
                new_text = _fill_text(text, url)
                if new_text != text:
                    tmp = txt.with_name(txt.name + ".tmp")
                    tmp.write_text(new_text, encoding="utf-8")
                    os.replace(tmp, txt)
        except OSError:
            continue
    return done
