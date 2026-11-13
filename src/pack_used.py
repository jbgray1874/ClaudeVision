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


def _drop_off_beside(record: Dict[str, Any]) -> Dict[str, Any]:
    """What became of this job's review copy in the drop-off folder, as the service noted it
    beside the staged drawings. Empty when the machine keeps no drop-off."""
    for folder in (record.get("job_folder"), (record.get("cad_inputs") or {}).get("folder")):
        if not folder:
            continue
        try:
            p = Path(str(folder)) / "PACK_DROPOFF.json"
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
        "unread_assemblies": [str(a.get("drawing") or a.get("name") or a) if isinstance(a, dict)
                              else str(a) for a in manifest.get("unread_assemblies") or []],
        "bought_in_unmatched": list(manifest.get("bought_in_unmatched") or []),
        "unassigned": [_name(u.get("path")) for u in manifest.get("unassigned_files") or []],
        "parts_list_read": manifest.get("references_read") if manifest else None,
        "pack_status": manifest.get("status") if manifest else "",
        "configurations_unconfirmed": bool(manifest.get("configurations_unconfirmed")),
        "has_manifest": bool(manifest),
    }


# WHERE THE SERVICE PUTS THE LINK TO THE EXACT PACK. The engine writes the note while it
# runs; the link is to a record the service makes, so the service fills this in, in the filed
# note and in the e-mail alike (pack_link.py). Unfilled, it is an HTML comment and shows nothing.
PACK_LINK_MARK = "<!--sdi-pack-link-->"
PACK_HEADING = "Drawing pack used for this estimate"
PACK_HEADING_TEXT = "DRAWING PACK USED FOR THIS ESTIMATE"
NOT_PROVED = "PACK COMPLETENESS NOT PROVED"


def _format(name: str) -> str:
    return Path(_name(name)).suffix.lstrip(".").upper() or "-"


def section(record: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """{"html", "text"} for the note; both empty when the run recorded no inputs at all.

    WHAT IT CARRIES (JG, 13 Nov 2026): the run id and the version of the pack kept for it,
    a place for the link to that exact pack, every file with its drawing number, revision
    and format, what became of each on this run, and what is missing or unread. Where
    anything leaves the pack unproved it says PACK COMPLETENESS NOT PROVED and why."""
    g = gather(record, manifest)
    if not g["rows"]:
        return {"html": "", "text": ""}
    e = _html.escape
    kept = _drop_off_beside(record)
    ev = read_evidence(record, [r["file"] for r in g["rows"]], manifest)
    outcome = {f["file"].lower(): f for f in ev["files"]}
    rows = []
    for r in g["rows"]:
        o = outcome.get(r["file"].lower()) or {}
        # A kind of file the engine never reads is shown by whether its component was covered.
        state, why = (o.get("state"), o.get("why")) if r["file"].lower().endswith(_KEPT_NOT_READ) \
            else (r["state"], r["why"])
        rows.append(dict(r, state=state or r["state"], why=why or "", format=_format(r["file"])))
    bad = [r for r in rows if r["state"].startswith("NOT READ")]
    gaps: List[str] = []
    failed = [r["file"] for r in rows if r["state"] == "NOT READ"]
    if failed:
        gaps.append(f"{len(failed)} file(s) could NOT be read: " + ", ".join(failed[:8]))
    if ev["coverage_unresolved"]:
        gaps.append(f"{len(ev['coverage_unresolved'])} model file(s) of a kind the engine does not "
                    "read have no equivalent native model shown read in their place: "
                    + ", ".join(ev["coverage_unresolved"][:8]))
    if g["missing"]:
        gaps.append("Referenced by the drawings, no file found: " + ", ".join(g["missing"][:12]))
    if g["unread_assemblies"]:
        gaps.append("Assemblies not read for their parts, so what they call for is not known: "
                    + ", ".join(g["unread_assemblies"][:12]))
    if g["has_manifest"] and g["parts_list_read"] is False:
        gaps.append("The GA's parts list was not read, so the pack is not proved complete.")
    if g["configurations_unconfirmed"]:
        gaps.append("The GA's sheets may be alternative configurations: confirm which before relying on the total.")
    if not g["has_manifest"]:
        gaps.append("No pack manifest was saved with this job, so missing references are not known here.")
    for w in kept.get("incomplete_because") or []:
        if w.startswith("copy:"):
            gaps.append("The kept copy of the pack lacks files found for it. " + w[5:].strip())
    info: List[str] = []
    if g["bought_in_unmatched"]:
        info.append("Bought-in, no drawing needed, still to be priced: " + ", ".join(g["bought_in_unmatched"][:12]))
    if g["unassigned"]:
        info.append("In the pack's folders, belonging to no drawing, NOT used: " + ", ".join(g["unassigned"][:8]))
    if kept and kept.get("saved") and kept.get("said"):
        # where the review copy sits on the estimating machine; the link above is how to open it
        info.append(str(kept["said"]).split(". NOT SHOWN COMPLETE")[0])
    if kept and not kept.get("saved"):
        gaps.append(str(kept.get("said") or "No copy of this pack was kept, so there is no saved pack to link to."))
    run_id = str(record.get("run_id") or "")
    ident = ("Run " + (run_id or "not recorded")
             + (f" · pack version {kept.get('version') or 'not recorded'}" if kept.get("saved") else
                " · no copy of the pack was kept on this machine"))
    head = (f"{sum(1 for r in rows if r['state'] == 'read')} file(s) read"
            + (f", {sum(1 for r in rows if r['state'] == 'supporting')} supporting" if any(r["state"] == "supporting" for r in rows) else "")
            + (f", {len(bad)} NOT READ" if bad else "")
            + (f"; pack {g['pack_status']}" if g["pack_status"] else ""))
    td = "padding:3px 10px 3px 0;border-bottom:1px solid #e3e8ee;font-size:13px;vertical-align:top"
    red = "color:#8a1f11;font-weight:bold"
    body = "".join(
        f'<tr><td style="{td}">{e(r["file"])}</td><td style="{td}">{e(r["drawing"] or "-")}</td>'
        f'<td style="{td}">{e(r["revision"] or "-")}</td><td style="{td}">{e(r["format"])}</td>'
        f'<td style="{td};{red if r["state"].startswith("NOT READ") else ""}">'
        f'{e(r["state"])}{(" - " + e(r["why"])) if r["why"] else ""}</td></tr>' for r in rows)
    html = (
        '<div style="margin:14px 0 18px;padding:12px 14px;border:1px solid #d5dbe3;border-radius:4px">'
        f'<p style="margin:0 0 6px;font-weight:bold;font-size:15px">{PACK_HEADING}</p>'
        f'<p style="margin:0 0 6px;font-size:13px"><b>{e(ident)}</b></p>'
        + PACK_LINK_MARK
        + (f'<p style="margin:0 0 6px;{red};font-size:14px">{NOT_PROVED}</p>' if gaps else "")
        + "".join(f'<p style="margin:0 0 6px;color:#8a1f11;font-size:13px">{e(w)}</p>' for w in gaps)
        + f'<p style="margin:0 0 8px;color:#5b6b7d;font-size:13px">{e(head)}. These are the files this run '
          'was given and what it did with each, as the run recorded them.</p>'
        + "".join(f'<p style="margin:0 0 6px;color:#5b6b7d;font-size:13px">{e(w)}</p>' for w in info)
        + '<table style="border-collapse:collapse"><tr>'
        + "".join(f'<th style="{td};text-align:left">{h}</th>' for h in ("File", "Drawing", "Rev", "Format", "On this run"))
        + f"</tr>{body}</table></div>")
    text = (PACK_HEADING_TEXT + "\n" + ident + "\n"
            + (f"  !! {NOT_PROVED}\n" if gaps else "")
            + "".join(f"  ! {w}\n" for w in gaps)
            + head + "\n"
            + "".join(f"  {w}\n" for w in info)
            + "".join(f"  {r['file']}  |  {r['drawing'] or '-'}  |  rev {r['revision'] or '-'}  |  {r['format']}  |  "
                      f"{r['state']}{(' - ' + r['why']) if r['why'] else ''}\n" for r in rows) + "\n")
    return {"html": html, "text": text}


def into_note(note: Dict[str, str], record: Dict[str, Any],
              manifest: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """The note with the section near its top: just inside its first <div>, where the mail
    service later puts its buttons above it."""
    s = section(record, manifest)
    # PRICE LOOKUPS THE RUN GAVE UP ON, SAID AT THE TOP (12 Nov 2026): a run whose databases
    # timed out prices from web and AI figures, and its note must not read like any other.
    says = ""
    try:
        est = record.get("estimate_summary") if isinstance(record.get("estimate_summary"), dict) else record
        says = str(((((est.get("cost_breakdown") or {}).get("pricing_metadata") or {})
                     .get("lookups_abandoned") or {}).get("says")) or "")
    except AttributeError:
        says = ""
    if says and "price lookup(s) were abandoned" not in str(note.get("html") or ""):
        s = {"html": ('<p style="margin:10px 0;padding:10px 12px;border:2px solid #8a1f11;color:#8a1f11;'
                      'font-weight:bold;font-size:14px">' + _html.escape(says) + "</p>") + s["html"],
             "text": "!! " + says + "\n\n" + s["text"]}
    if not s["html"] or PACK_HEADING in str(note.get("html") or ""):
        return note
    html = str(note.get("html") or "")
    m = re.search(r"<div[^>]*>", html)
    at = m.end() if m else 0
    return dict(note, html=html[:at] + s["html"] + html[at:], text=s["text"] + str(note.get("text") or ""))


# ── WHAT THIS RUN ACTUALLY READ, WRITTEN INTO THE REVIEW COPY (JG, 13 Nov 2026) ──────────
_KEPT_NOT_READ = (".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".sat", ".stl", ".3dm")
_NATIVE = (".sldprt", ".sldasm")


def _stated_revision(name: str) -> str:
    m = _REV.search(Path(_name(name)).stem)
    return m.group(1).upper() if m else ""


def _equivalent(unread: str, model: str) -> str:
    """"same" where the two files are shown to be one issue of one model; otherwise why not."""
    if Path(_name(unread)).stem.casefold() == Path(_name(model)).stem.casefold():
        return "same"
    a, b = _stated_revision(unread), _stated_revision(model)
    if a and b:
        return "same" if a == b else f"revisions differ ({_name(unread)} is rev {a}, {_name(model)} is rev {b})"
    return ("no revision is stated on " + " or ".join(_name(n) for n, r in ((unread, a), (model, b)) if not r)
            + ", so the two cannot be compared")


def _component(name: str) -> str:
    return (_number(name) or Path(_name(name)).stem).upper()


def read_evidence(record: Dict[str, Any], pack_files: List[str],
                  manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What became of each file of the pack ON THIS RUN, from the run's own record.

    "The engine reads this kind of file" is not "it was read". Each file is one of: read,
    NOT READ (with the reader's reason), supporting, or NO RECORD where the run's record does
    not mention it. A file of a kind the engine never reads (IGS, STEP) is covered only where
    a native model of the same component was read on this run. Otherwise that component's
    coverage is UNRESOLVED: the absence of a reader is not proof nothing was lost."""
    g = gather(record, manifest)
    unconfirmed = bool(g.get("configurations_unconfirmed"))
    by_name = {r["file"].lower(): r for r in g["rows"]}
    native: Dict[str, List[Dict[str, str]]] = {}
    drawings: Dict[str, List[str]] = {}
    for r in g["rows"]:
        low = r["file"].lower()
        if low.endswith(_NATIVE):
            native.setdefault(_component(r["file"]), []).append(r)
        elif low.endswith((".pdf", ".dxf")) and r["state"] == "read":
            drawings.setdefault(_component(r["file"]), []).append(r["file"])
    files, unresolved = [], []
    for name in pack_files:
        nm = _name(name)
        row = by_name.get(nm.lower())
        if nm.lower().endswith(_KEPT_NOT_READ):
            models = native.get(_component(nm)) or []
            read = [m for m in models if m["state"] == "read"]
            # THE SAME NUMBER IS NOT THE SAME MODEL (JG, 13 Nov 2026). A native model covers
            # this file only where it is shown to be the same issue of it: the same file name,
            # or the same stated revision, and no question over which configuration the pack
            # is. A number alone establishes nothing where revisions or configurations differ.
            same = [m["file"] for m in read if _equivalent(nm, m["file"]) == "same"]
            if same and not unconfirmed:
                files.append({"file": nm, "state": "not read; covered",
                              "why": "a native model of the same component and issue was read "
                                     "on this run: " + ", ".join(same)})
                continue
            if read:
                how = sorted({_equivalent(nm, m["file"]) for m in read})
                why = ("a native model of this drawing number was read (" + ", ".join(m["file"] for m in read)
                       + ") but is not shown to be the same model: "
                       + ("; ".join(h for h in how if h != "same") or "")
                       + ("; " if unconfirmed and any(h != "same" for h in how) else "")
                       + ("the pack's configurations are unconfirmed" if unconfirmed else ""))
                files.append({"file": nm, "state": "NOT READ; COVERAGE UNRESOLVED", "why": why})
                unresolved.append(nm)
                continue
            if models:
                why = ("its native model was NOT read on this run: "
                       + "; ".join(f"{m['file']} ({m['why'] or m['state']})" for m in models))
            else:
                why = "no native model of this component was given to this run"
            also = drawings.get(_component(nm)) or []
            if also:
                why += ". A drawing of this number was read (" + ", ".join(also) + "), which is not the model"
            files.append({"file": nm, "state": "NOT READ; COVERAGE UNRESOLVED", "why": why})
            unresolved.append(nm)
        elif row:
            files.append({"file": nm, "state": row["state"], "why": row["why"]})
        else:
            files.append({"file": nm, "state": "NO RECORD",
                          "why": "the run's record does not mention this file"})
    not_read = [f["file"] for f in files if f["state"] == "NOT READ"]
    no_record = [f["file"] for f in files if f["state"] == "NO RECORD"]
    because = []
    if not_read:
        because.append(f"{len(not_read)} file(s) could not be read: {', '.join(not_read[:12])}")
    if unresolved:
        because.append(f"{len(unresolved)} file(s) of a kind the engine does not read have no "
                       f"native model read in their place: {', '.join(unresolved[:12])}")
    if no_record:
        because.append(f"{len(no_record)} file(s) are not mentioned in the run's record: "
                       f"{', '.join(no_record[:12])}")
    return {"files": files, "not_read": not_read, "coverage_unresolved": unresolved,
            "no_record": no_record,
            "state": "incomplete" if because else "complete",
            "because": because or ["every file of the pack was read, or covered by a native "
                                   "model that was read"]}


def record_read_evidence_safely(record: Dict[str, Any]) -> str:
    """Write this run's read evidence into the review copy's manifest, under its run id.
    Adds to `read_on_runs` and sets completeness.read; touches nothing else in the pack.
    Never raises; returns one line saying what happened, or "" where there is no review copy."""
    try:
        from datetime import datetime
        note = _drop_off_beside(record)
        folder = Path(str(note.get("folder") or ""))
        path = folder / "pack_manifest.json"
        if not note.get("saved") or not path.is_file():
            return ""
        kept = json.loads(path.read_text(encoding="utf-8"))
        names = [str(f.get("name")) for f in kept.get("files") or []] + \
                [str(a.get("name")) for a in kept.get("not_in_this_copy") or []]
        ev = read_evidence(record, names)
        run_id = str(record.get("run_id") or "") or \
            str(((kept.get("runs") or [{}])[-1]).get("run_id") or "") or "unnamed run"
        ev["recorded_at"] = datetime.now().isoformat(timespec="seconds")
        kept.setdefault("read_on_runs", {})[run_id] = ev
        kept.setdefault("completeness", {})["read"] = {
            "state": ev["state"], "because": ev["because"], "run_id": run_id}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(kept, indent=1), encoding="utf-8")
        tmp.replace(path)
        return (f"Review copy: what this run read is recorded in {path} "
                f"(read coverage {ev['state']}"
                + (": " + "; ".join(ev["because"]) if ev["state"] != "complete" else "") + ")")
    except Exception as exc:                                         # noqa: BLE001
        return f"WARNING: this run's read evidence was NOT written to the review copy ({type(exc).__name__}: {exc})"


def into_note_safely(note: Dict[str, str], record: Dict[str, Any]) -> Dict[str, str]:
    """into_note that never stops a note being written: on any failure the note goes out as
    it was, and the console says the section is missing."""
    try:
        return into_note(note, record)
    except Exception as exc:                                         # noqa: BLE001
        print(f"   [covering-note] no drawing pack section ({exc})", flush=True)
        return note
