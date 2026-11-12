#!/usr/bin/env python3
""""Drawing pack used for this estimate": the run's actual input files, in the covering note
and so in the automatic e-mail (JG, 12 Nov 2026).

"Near the top of the generated HTML covering note, and in the body of the automatic email,
include a 'Drawing pack used for this estimate' section listing the actual staged input files,
drawing numbers and revisions where known. Distinguish files successfully read from supporting
files and failed reads. Show missing references and provisional scope clearly. Generate this
from the run's pinned input manifest, not a later folder scan."

Built ONLY from what the run recorded as it ran: the record's cad_inputs (which files it read,
which models went to SolidWorks or Document Manager, which it could not read), the model
reader's own failures, and the pack manifest saved in the job folder when the pack was staged.
Nothing is listed from a folder looked at afterwards.
"""
from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_REV = re.compile(r"(?:^|[_\s\-.])REV(?:ISION)?[_\s\-]?([A-Z]{1,2}|\d{1,2}|P\d{1,2})(?=$|[_\s\-.()\[\]])", re.I)
_MODEL = (".sldprt", ".sldasm", ".slddrw")


def _name(path: Any) -> str:
    return re.split(r"[\\/]", str(path or ""))[-1]


def _number(name: str) -> str:
    try:
        import pack_resolver
        return pack_resolver.drawing_id(name)
    except Exception:                                                # noqa: BLE001
        return ""


def _manifest_beside(record: Dict[str, Any]) -> Dict[str, Any]:
    """The pack manifest staged with the job, if one was: read from the run's own job folder."""
    for folder in (record.get("job_folder"), (record.get("cad_inputs") or {}).get("folder")):
        if not folder:
            continue
        try:
            p = Path(str(folder)) / "pack_manifest.json"
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def gather(record: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every input file the run recorded, each with what became of it."""
    manifest = manifest if manifest is not None else _manifest_beside(record)
    cad = record.get("cad_inputs") or {}
    sw = record.get("solidworks_native") or {}
    failed: Dict[str, str] = {}
    for e in sw.get("extract_errors") or []:
        if isinstance(e, dict):
            n, why = _name(e.get("path") or e.get("file")), "; ".join(map(str, e.get("errors") or [e.get("error") or ""]))
        else:
            m = re.search(r"([^\\/]+\.SLD(?:PRT|ASM|DRW))", str(e), re.I)
            n, why = (m.group(1) if m else ""), str(e)
        if n:
            failed[n.lower()] = re.sub(r"\s+", " ", why)[:160]
    revs = {str(m.get("drawing") or "").upper(): str(m.get("revision") or "")
            for m in manifest.get("members") or []}
    rows: List[Dict[str, str]] = []
    seen = set()

    def add(name: str, state: str, why: str = "") -> None:
        name = _name(name)
        if not name or name.lower() in seen:
            return
        seen.add(name.lower())
        number = _number(name)
        m = _REV.search(Path(name).stem)
        rows.append({"file": name, "drawing": number,
                     "revision": revs.get(number.upper()) or (m.group(1).upper() if m else ""),
                     "state": state, "why": why})

    for n in cad.get("read") or []:
        add(n, "read")
    for n in cad.get("solidworks") or []:
        nm = _name(n)
        if nm.lower() in failed:
            add(nm, "NOT READ", failed[nm.lower()])
        elif nm.lower().endswith(".slddrw"):
            add(nm, "supporting", "the model's drawing file; its content is read from the PDF and the model")
        else:
            add(nm, "read", "model read by " + str(sw.get("extract_reader") or sw.get("source") or "the model reader").replace("_", " "))
    for n in cad.get("converted") or []:
        add(n, "read", "converted, then read")
    for n in cad.get("unread") or []:
        add(n, "NOT READ", "this machine has no reader for this format")
    for n in cad.get("unknown") or []:
        add(n, "supporting", "not a drawing format the engine reads")
    for n in record.get("staged_inputs") or []:
        add(n, "read")
    for nm, why in failed.items():
        add(nm, "NOT READ", why)
    return {
        "rows": rows,
        "read": sum(1 for r in rows if r["state"] == "read"),
        "not_read": [r for r in rows if r["state"] == "NOT READ"],
        "supporting": sum(1 for r in rows if r["state"] == "supporting"),
        "missing": list(manifest.get("missing") or []),
        "bought_in_unmatched": list(manifest.get("bought_in_unmatched") or []),
        "unassigned": [_name(u.get("path")) for u in manifest.get("unassigned_files") or []],
        "parts_list_read": manifest.get("references_read") if manifest else None,
        "pack_status": manifest.get("status") if manifest else "",
        "configurations_unconfirmed": bool(manifest.get("configurations_unconfirmed")),
        "has_manifest": bool(manifest),
    }


def section(record: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """{"html", "text"} for the note; both empty when the run recorded no inputs at all."""
    g = gather(record, manifest)
    if not g["rows"]:
        return {"html": "", "text": ""}
    e = _html.escape
    warn: List[str] = []
    if g["not_read"]:
        warn.append(f"{len(g['not_read'])} file(s) could NOT be read: "
                    + ", ".join(r["file"] for r in g["not_read"][:8]))
    if g["missing"]:
        warn.append("Referenced by the drawings, no file found: " + ", ".join(g["missing"][:12]))
    if g["bought_in_unmatched"]:
        warn.append("Bought-in, no drawing needed, still to be priced: " + ", ".join(g["bought_in_unmatched"][:12]))
    if g["unassigned"]:
        warn.append("In the pack's folders, belonging to no drawing, NOT used: " + ", ".join(g["unassigned"][:8]))
    if g["has_manifest"] and g["parts_list_read"] is False:
        warn.append("The GA's parts list was not read, so the pack is not proved complete.")
    if g["configurations_unconfirmed"]:
        warn.append("The GA's sheets may be alternative configurations: confirm which before relying on the total.")
    if not g["has_manifest"]:
        warn.append("No pack manifest was saved with this job, so missing references are not known here.")
    head = (f"{g['read']} file(s) read" + (f", {g['supporting']} supporting" if g["supporting"] else "")
            + (f", {len(g['not_read'])} NOT READ" if g["not_read"] else "")
            + (f"; pack {g['pack_status']}" if g["pack_status"] else ""))
    td = "padding:3px 10px 3px 0;border-bottom:1px solid #e3e8ee;font-size:13px;vertical-align:top"
    body = "".join(
        f'<tr><td style="{td}">{e(r["file"])}</td><td style="{td}">{e(r["drawing"] or "-")}</td>'
        f'<td style="{td}">{e(r["revision"] or "-")}</td>'
        f'<td style="{td};{"color:#8a1f11;font-weight:bold" if r["state"] == "NOT READ" else ""}">'
        f'{e(r["state"])}{(" - " + e(r["why"])) if r["why"] else ""}</td></tr>' for r in g["rows"])
    html = (
        '<div style="margin:14px 0 18px;padding:12px 14px;border:1px solid #d5dbe3;border-radius:4px">'
        '<p style="margin:0 0 6px;font-weight:bold;font-size:15px">Drawing pack used for this estimate</p>'
        f'<p style="margin:0 0 8px;color:#5b6b7d;font-size:13px">{e(head)}. These are the files this run '
        'was given and what it did with each, as the run recorded them.</p>'
        + "".join(f'<p style="margin:0 0 6px;color:#8a1f11;font-size:13px">{e(w)}</p>' for w in warn)
        + '<table style="border-collapse:collapse"><tr>'
        + "".join(f'<th style="{td};text-align:left">{h}</th>' for h in ("File", "Drawing", "Rev", "Used"))
        + f"</tr>{body}</table></div>")
    text = ("DRAWING PACK USED FOR THIS ESTIMATE\n" + head + "\n"
            + "".join(f"  ! {w}\n" for w in warn)
            + "".join(f"  {r['file']}  |  {r['drawing'] or '-'}  |  rev {r['revision'] or '-'}  |  "
                      f"{r['state']}{(' - ' + r['why']) if r['why'] else ''}\n" for r in g["rows"]) + "\n")
    return {"html": html, "text": text}


def into_note(note: Dict[str, str], record: Dict[str, Any],
              manifest: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The note with the section near its top: just inside its first <div>, where the mail
    service later puts its buttons above it."""
    s = section(record, manifest)
    if not s["html"] or "Drawing pack used for this estimate" in str(note.get("html") or ""):
        return note
    html = str(note.get("html") or "")
    m = re.search(r"<div[^>]*>", html)
    at = m.end() if m else 0
    return dict(note, html=html[:at] + s["html"] + html[at:], text=s["text"] + str(note.get("text") or ""))
