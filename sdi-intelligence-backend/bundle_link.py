"""One completed estimate, its filed bundle checked, and a link to it (JG, 13 Nov 2026).

"One combined completed-estimates list in Grid Control. We should not need to identify a
runner or search two folders. For each completed run, show the drawing, run ID, completion
time and a link to its verified AISheets bundle. Flag missing deliverables explicitly. Put the
same bundle link in the email and saved covering note. Local working-folder paths can remain
secondary diagnostic information."

THE BUNDLE IS THE FOLDER ON THE SHARE, NOT A RUNNER'S WORKING FOLDER. Each runner writes into
its own checkout while it works and then files the run's files to
<AISheets>\\<client>\\<drawing>\\<date time> (<units> off). That folder is the same place
whichever runner ran the job, and it is what this checks and links to.

CHECKED, NOT ASSUMED. "The runner said it filed them" is not "they are there". `verify` looks
at the share when asked and says one of three things, never a fourth:
  verified      the folder is there, every file the runner reported and every file the run's
                own manifest lists is in it and not empty, and each kind of deliverable an
                estimate should have is present
  INCOMPLETE    the folder is there and something is missing; each missing thing is named
  NOT CHECKED   the share could not be reached from this service, which is not the same as
                the files being absent, and is said as that
It checks presence and size. It does not compare content with the runner's working copy.

A LINK THAT OUTLIVES THE SERVICE. Like the walkthrough and the pack, a finished run gets a
small record on disk under a random token; the link is the portal's public address and the
token, behind sign-in. The page hands out the files of that one bundle and no others, and a
quotation not yet released is held by the same gate as everywhere else.

Nothing here moves a file, reprices anything, or sends or resends an e-mail.
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

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
DONE = "<!--sdi-bundle-linked-->"
_LINK_TEXT = "This estimate's filed bundle:"
_NOTE_SUFFIXES = ("_covering_email.html", "_covering_note.html")
_MANIFEST_SUFFIX = "_deliverables.json"
# What a finished estimate should have filed, by the tail of its file name. The spoken
# walkthrough is listed with the rest: a run that made no sound is flagged, not passed.
EXPECTED = (
    ("the estimate workbook", (".xlsx", ".xlsm")),
    ("the run's pinned record", ("_record.json",)),
    ("the report", ("_report.html",)),
    ("the covering note", ("_covering_email.html", "_covering_note.html")),
    ("the walkthrough's words", ("_walkthrough.txt",)),
    ("the spoken walkthrough", ("_walkthrough.wav",)),
)
# The suffixes a runner files (tools/runner/sdi_estimate_runner.py DELIVERABLE_SUFFIXES): a
# file the run wrote of another kind was never going to be in the bundle.
_FILED_SUFFIXES = (".xlsx", ".html", ".json", ".log", ".csv", ".txt", ".md", ".sql", ".xlsm", ".wav")


def store_dir() -> Path:
    import estimate_email
    return estimate_email.state_dir() / "bundles"


def url_for(token: str) -> str:
    import estimate_walkthrough
    return f"{estimate_walkthrough.portal_base()}/estimating/bundle/{token}"


def token_ok(token: str) -> bool:
    return bool(_TOKEN.match(str(token or "")))


def make(run: Dict[str, Any]) -> str:
    """Record a finished run's bundle; its token, or "" where the run has no bundle folder."""
    folder = str(run.get("output_path") or "").strip()
    if not folder:
        return ""
    token = secrets.token_urlsafe(18)
    record = {"token": token, "created": time.time(), "run_id": run.get("run_id") or "",
              "client": run.get("client") or "", "drawing_number": run.get("drawing_number") or "",
              "units": run.get("units"), "finished_at": run.get("finished_at"),
              "runner": run.get("runner") or "", "folder": folder,
              "deliverables": [{"name": str(d.get("name")), "path": str(d.get("path"))}
                               for d in run.get("deliverables") or []
                               if isinstance(d, dict) and d.get("name") and d.get("path")]}
    store = store_dir()
    store.mkdir(parents=True, exist_ok=True)
    tmp = store / f"{token}.tmp"
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, store / f"{token}.json")
    return token


def load(token: str) -> Optional[Dict[str, Any]]:
    if not token_ok(token):
        return None
    try:
        data = json.loads((store_dir() / f"{token}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("token") == token else None


def _kind(name: str) -> str:
    low = name.lower()
    # the workbook last: "_record.json" and the rest are tested by their own tails first
    for what, tails in EXPECTED[1:] + EXPECTED[:1]:
        if any(low.endswith(t) for t in tails):
            return what
    return ""


def _reachable(folder: Path) -> bool:
    """Whether anything above the bundle folder answers: a share that is off is not a
    missing bundle."""
    for parent in list(folder.parents)[:3]:
        try:
            if parent.is_dir():
                return True
        except OSError:
            continue
    return False


def verify(folder: Any, deliverables: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Look at the bundle on the share now. See the module's opening note for what it means."""
    out: Dict[str, Any] = {"state": "", "folder": str(folder or ""), "files": [], "missing": [],
                           "working_folder": "", "runner_id": "", "says": ""}
    path = Path(str(folder or ""))
    if not str(folder or "").strip():
        out.update(state="INCOMPLETE", missing=[{"what": "the bundle folder",
                                                 "why": "the run recorded no folder to file to"}])
        out["says"] = "INCOMPLETE: the run recorded no folder to file to"
        return out
    try:
        there = path.is_dir()
    except OSError:
        there = False
    if not there:
        if not _reachable(path):
            out.update(state="NOT CHECKED")
            out["says"] = ("NOT CHECKED: the share could not be reached from this service, so "
                           "nothing is known about this bundle")
            return out
        out.update(state="INCOMPLETE", missing=[{"what": "the bundle folder",
                                                 "why": f"{path} is not there"}])
        out["says"] = "INCOMPLETE: the bundle folder is not on the share"
        return out
    present: Dict[str, int] = {}
    try:
        for p in sorted(path.iterdir()):
            if p.is_file():
                present[p.name] = p.stat().st_size
    except OSError as exc:
        out.update(state="NOT CHECKED")
        out["says"] = f"NOT CHECKED: the bundle folder could not be listed ({exc})"
        return out
    low = {n.lower(): n for n in present}
    out["files"] = [{"name": n, "what": _kind(n), "size": s} for n, s in present.items()]
    missing: List[Dict[str, str]] = []
    said = set()

    def lack(name: str, what: str, why: str) -> None:
        if name.lower() not in said:
            said.add(name.lower())
            missing.append({"name": name, "what": what or "a file of this run", "why": why})

    for d in deliverables or []:
        name = str(d.get("name") or "")
        if not name:
            continue
        if name.lower() not in low:
            lack(name, _kind(name), "the runner reported filing it and it is not in the bundle")
        elif present[low[name.lower()]] == 0:
            lack(name, _kind(name), "it is in the bundle and is empty")
    # WHAT THE RUN ITSELF SAYS IT WROTE (src/run_manifest.py), where its manifest was filed.
    for n in present:
        if not n.lower().endswith(_MANIFEST_SUFFIX):
            continue
        try:
            doc = json.loads((path / n).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out["working_folder"] = str(doc.get("output_folder") or "")
        out["runner_id"] = str(doc.get("runner_id") or "")
        for f in doc.get("files") or []:
            name = str((f or {}).get("name") or "")
            if name and name.lower().endswith(_FILED_SUFFIXES) and name.lower() not in low:
                lack(name, str(f.get("what") or "") or _kind(name),
                     "the run wrote it and it was not filed to the bundle")
    for what, tails in EXPECTED:
        if not any(n.lower().endswith(t) for n in present for t in tails):
            missing.append({"name": "", "what": what, "why": "no file of this kind is in the bundle"})
        elif all(present[n] == 0 for n in present if any(n.lower().endswith(t) for t in tails)):
            missing.append({"name": "", "what": what, "why": "the only file of this kind is empty"})
    out["missing"] = missing
    out["state"] = "INCOMPLETE" if missing else "verified"
    out["says"] = (f"verified: {len(present)} file(s) on the share" if not missing else
                   "INCOMPLETE: missing " + "; ".join(
                       (m["name"] or m["what"]) for m in missing[:8])
                   + (f" and {len(missing) - 8} more" if len(missing) > 8 else ""))
    return out


def file_for(record: Dict[str, Any], name: str) -> Optional[Path]:
    """One of this bundle's own files, by exact name; None for anything else."""
    want = str(name or "").strip()
    if not want or "/" in want or "\\" in want or want in (".", ".."):
        return None
    path = Path(str(record.get("folder") or "")) / want
    try:
        return path if path.is_file() and path.parent == Path(str(record.get("folder"))) else None
    except OSError:
        return None


def view(record: Dict[str, Any]) -> Dict[str, Any]:
    v = verify(record.get("folder"), record.get("deliverables"))
    return {"run_id": record.get("run_id") or "", "client": record.get("client") or "",
            "drawing_number": record.get("drawing_number") or "", "units": record.get("units"),
            "finished_at": record.get("finished_at"), "runner": record.get("runner") or "",
            "bundle_folder": str(record.get("folder") or ""), "verification": v,
            "files": v["files"], "missing": v["missing"],
            # secondary, for diagnosis only: where the runner worked before it filed
            "working_folder": v["working_folder"]}


def completed(runs: List[Dict[str, Any]], check=verify, limit: int = 300) -> List[Dict[str, Any]]:
    """Every finished estimate this service knows, newest first, whichever runner ran it."""
    rows = []
    for r in runs:
        if str(r.get("job_type") or "") or str(r.get("status") or "") not in ("done", "error"):
            continue
        rows.append(r)
    rows.sort(key=lambda r: float(r.get("finished_at") or 0), reverse=True)
    out = []
    for r in rows[:limit]:
        done = str(r.get("status")) == "done"
        v = check(r.get("output_path"), r.get("deliverables")) if (done or r.get("deliverables")) \
            else {"state": "NO BUNDLE", "says": "NO BUNDLE: the run did not finish, so nothing "
                                                 "was filed as an estimate", "missing": [],
                  "files": [], "working_folder": "", "runner_id": ""}
        out.append({"run_id": r.get("run_id"), "drawing_number": r.get("drawing_number"),
                    "client": r.get("client"), "units": r.get("units"),
                    "finished_at": r.get("finished_at"),
                    "outcome": "completed" if done else "did not finish",
                    "error": str(r.get("error") or "")[:240],
                    "price_validated": bool(r.get("price_validated")),
                    "bundle_url": r.get("bundle_url") or "", "pack_url": r.get("pack_url") or "",
                    "bundle_state": v["state"], "bundle_says": v["says"],
                    "missing": v["missing"], "files": len(v["files"]),
                    "bundle_folder": str(r.get("output_path") or ""),
                    "runner": r.get("runner") or "", "working_folder": v.get("working_folder") or ""})
    return out


# ── INTO THE NOTE ────────────────────────────────────────────────────────────────────────
def _block(url: str, v: Dict[str, Any], run_id: str) -> Dict[str, str]:
    ok = v.get("state") == "verified"
    colour = "#1f6b2a" if ok else "#8a1f11"
    html = ('<p style="margin:10px 0 4px;font-size:13px"><a href="' + _html.escape(url, quote=True)
            + '" style="color:#B8860B;font-weight:bold">&#128230; Open this estimate\'s filed bundle</a>'
            + f'<span style="color:#5b6b7d"> (run {_html.escape(run_id or "not recorded")}; every file of '
              'this run on the share; you sign in with your SDI Microsoft account)</span></p>'
            + f'<p style="margin:0 0 10px;font-size:13px;color:{colour};font-weight:bold">Bundle '
            + _html.escape(str(v.get("says") or "not checked")) + "</p>" + DONE)
    text = (f"{_LINK_TEXT} {url}\n  Run {run_id or 'not recorded'}. Bundle {v.get('says') or 'not checked'}\n\n")
    return {"html": html, "text": text}


def _with_block_html(html: str, block: str) -> str:
    if DONE in html:
        return html
    m = re.search(r"<div[^>]*>", html)
    if m:
        return html[:m.end()] + block + html[m.end():]
    lead = re.match(r"\s*(?:<!--.*?-->\s*)*", html, flags=re.S)
    at = lead.end() if lead else 0
    return html[:at] + block + html[at:]


def into_note(note: Dict[str, str], snapshot: Dict[str, Any]) -> Dict[str, str]:
    """The e-mail's note with the link to the run's filed bundle and what the check found."""
    token = str(snapshot.get("bundle_token") or "")
    record = load(token) if token else None
    if not record:
        return note
    b = _block(url_for(token), verify(record.get("folder"), record.get("deliverables")),
               str(record.get("run_id") or ""))
    text = str(note.get("text") or "")
    return dict(note, html=_with_block_html(str(note.get("html") or ""), b["html"]),
                text=text if _LINK_TEXT in text else b["text"] + text)


def stamp_note_files(paths: List[str], snapshot: Dict[str, Any]) -> List[str]:
    """The same link in each filed copy of the covering note and its plain-text sibling. A
    copy that already carries it is left alone; one that cannot be written is skipped."""
    token = str(snapshot.get("bundle_token") or "")
    record = load(token) if token else None
    if not record:
        return []
    b = _block(url_for(token), verify(record.get("folder"), record.get("deliverables")),
               str(record.get("run_id") or ""))
    done: List[str] = []
    for raw in paths or []:
        path = Path(str(raw or ""))
        if not path.name.lower().endswith(_NOTE_SUFFIXES):
            continue
        try:
            html = path.read_text(encoding="utf-8")
            new = _with_block_html(html, b["html"])
            if new != html:
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(new, encoding="utf-8")
                os.replace(tmp, path)
                done.append(str(path))
            txt = path.with_suffix(".txt")
            if txt.exists():
                text = txt.read_text(encoding="utf-8")
                if _LINK_TEXT not in text:
                    tmp = txt.with_name(txt.name + ".tmp")
                    tmp.write_text(b["text"] + text, encoding="utf-8")
                    os.replace(tmp, txt)
        except OSError:
            continue
    return done
