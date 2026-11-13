"""EVERY NEW JOB'S DRAWING PACK IS ALSO KEPT IN THE DROP-OFF FOLDER (JG and the reviewer, 12 Nov 2026).

"For every new job we also need to save the drawing pack to C:\\ClaudeVision\\chatgptdropoff.
Auto create a client name folder where none exists, then a folder below that with the job
number / name identifier and all the drawings. Same as at ...\\AI Estimating\\Live Enquiry."

    <drop-off>\\<client>\\<drawing number> - <job title>\\
        the drawings, models and supporting files the estimate was given
        pack_manifest.json

THE EXACT PACK THE ESTIMATE WAS GIVEN. The copy is made from the job's staged folder when the
job is queued: the files the engine will read, not a fresh search that might find other
revisions. The same call serves the estimating page, Self-Running and a TTI batch, because all
three queue through the one place. Sub-folders keep their place.

AN UNCHANGED PACK IS REUSED; A CHANGED ONE IS A NEW VERSION. The pack is fingerprinted by the
content of its files. The same content again adds this run to the manifest and copies
nothing. Different content is saved beside the earlier pack as "<name> v2", "v3", and the
earlier one is left exactly as it was. Nothing is ever deleted, moved or overwritten.

THE MANIFEST SAYS WHERE EACH FILE CAME FROM: its source path, revision, size and fingerprint,
the runs that used this pack, and what the pack resolver found missing or could not read.

THREE QUESTIONS, KEPT APART (JG, 13 Nov 2026). Four packs were kept that night and three
lacked files the resolver had listed, with nothing in the manifest to say so. `completeness`
answers three things and never folds them into one:
  source_pack  was everything the product needs found? Only the pack resolver can say, from
               the drawings' own parts lists. Every gathered file being kept proves nothing
               about what was never gathered; with no resolver manifest it is "not established".
  copy         is every file that was found in this folder? `not_in_this_copy` names each
               one that is not, with its reason.
  read         what did a run actually read? Written when a run finishes, from that run's own
               record, under `read_on_runs`. Until then it says so.
`intended_handling` on a file is what the engine does with that KIND of file. It is not
evidence the file was read. A file kept and not read (an IGS, a STEP) is covered only where
a native model of the same component was read on the run; otherwise its component's
coverage is unresolved, and said.

RECOVERY IS PREVIEWED, VERSIONED AND NEVER REWRITES EVIDENCE. `recovery_plan` checks each
absent file against its recorded source and fingerprint; `recover` writes a new version
beside the pack holding the original files and the recovered ones. The original folder, its
manifest and its runs' evidence are left exactly as they were.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA = "pack_dropoff.v1"
MANIFEST = "pack_manifest.json"
RESULT_NOTE = "PACK_DROPOFF.json"          # written beside the staged drawings by the service
_OFF = {"off", "0", "no", "false", "none"}
# The service's own notes in a staged folder (CONCEPT_DOCUMENT.json, ENQUIRY_BRIEF.txt): not
# part of the pack. The resolver's pack_manifest.json is read into the manifest, not copied.
_STAGE_NOTE = re.compile(r"[A-Z][A-Z_]+\.json|ENQUIRY_BRIEF\.txt")
_VERSION = re.compile(r"^(.*) v(\d+)$")


# WHAT THE ENGINE DOES WITH A KIND OF FILE, as src/cad_inputs.py has it (a test holds the two
# together). Said per file so "in the pack" is never read as "read by the estimate".
_ENGINE = {".pdf": "read by the engine", ".dxf": "read by the engine",
           ".sldprt": "read through SolidWorks", ".sldasm": "read through SolidWorks",
           ".slddrw": "read through SolidWorks",
           ".dwg": "converted to DXF where it can be, then read"}
_KEPT_NOT_READ = {".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".sat", ".stl", ".3dm"}


def intended_handling(name: str) -> str:
    """What the engine does with this KIND of file. Not evidence that it was read."""
    suffix = Path(str(name)).suffix.lower()
    if suffix in _ENGINE:
        return _ENGINE[suffix]
    if suffix in _KEPT_NOT_READ:
        return "kept with the pack; the engine does not read this kind of file"
    return "supporting file; not a drawing or model"


def not_in_this_copy(resolver: Dict[str, Any], copied: List[str],
                     left_out: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Every file the resolver listed for the pack, or staging left behind, that is not in
    the copy, with the reason given for it. A file with no reason on record says exactly that."""
    have = {Path(n).name.lower() for n in copied}
    why = {}
    for item in left_out or []:
        name = Path(str(item.get("path") or "")).name
        if name:
            why[name.lower()] = (name, str(item.get("reason") or ""))
    out, seen = [], set()
    for member in (resolver or {}).get("members") or []:
        for f in member.get("files") or []:
            name = Path(str(f.get("path") or "")).name
            key = name.lower()
            if not name or key in have or key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "source_path": str(f.get("path") or ""),
                        "listed_by": "the pack resolver",
                        "reason": why.get(key, ("", ""))[1]
                        or "no reason was recorded when the pack was staged"})
    for key, (name, reason) in sorted(why.items()):
        if key not in have and key not in seen:
            seen.add(key)
            out.append({"name": name, "source_path": "", "listed_by": "staging",
                        "reason": reason or "no reason was recorded when the pack was staged"})
    return out


READ_NOT_RECORDED = "not recorded yet: written from the run's own record when a run finishes"


def completeness_of(resolver: Dict[str, Any], absent: List[Dict[str, str]]) -> Dict[str, Any]:
    """The three questions, each with its own answer. See the module's opening note."""
    if not resolver:
        source = {"state": "not established",
                  "because": ["no pack resolver manifest was staged with this job, so nothing "
                              "says whether every drawing the product needs was found"]}
    else:
        why = []
        if resolver.get("missing"):
            why.append(f"{len(resolver['missing'])} drawing(s) the pack calls for were not "
                       f"found: {', '.join(map(str, resolver['missing'][:12]))}")
        if resolver.get("unread_assemblies"):
            why.append(f"{len(resolver['unread_assemblies'])} assembly(ies) could not be read "
                       f"for their parts, so what they call for is not known: "
                       f"{', '.join(map(str, resolver['unread_assemblies'][:12]))}")
        if resolver.get("references_read") is False:
            why.append("the parts list was not read, so the pack was gathered by file name only")
        source = {"state": "incomplete" if why else "complete",
                  "because": why or ["the pack resolver found every drawing its parts lists call for"]}
    copy = {"state": "incomplete" if absent else "complete",
            "because": ([f"{len(absent)} file(s) found for the pack are not in this copy: "
                         f"{', '.join(a['name'] for a in absent[:12])}"] if absent
                        else ["every file found for the pack is in this copy"])}
    return {"source_pack": source, "copy": copy,
            "read": {"state": READ_NOT_RECORDED, "because": []}}


def _because(completeness: Dict[str, Any]) -> List[str]:
    return [f"{k.replace('_', ' ')}: {w}" for k in ("source_pack", "copy")
            for w in (completeness.get(k) or {}).get("because") or []
            if (completeness.get(k) or {}).get("state") != "complete"]


def root(repo_root: Path) -> Optional[Path]:
    """Where packs are dropped, or None when there is nowhere (or it is switched off)."""
    raw = str(os.getenv("SDI_PACK_DROPOFF_DIR", "")).strip()
    if raw.lower() in _OFF:
        return None
    folder = Path(raw) if raw else Path(repo_root) / "chatgptdropoff"
    return folder if folder.is_dir() else None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pack_files(src: Path) -> List[Path]:
    return sorted(p for p in src.rglob("*")
                  if p.is_file() and p.name != MANIFEST and not _STAGE_NOTE.fullmatch(p.name))


def _versions(client_dir: Path, drawing: str) -> List[Path]:
    """This job's pack folders, oldest first: "<drawing>", "<drawing> - <title>", "... v2"."""
    found = []
    try:
        entries = [p for p in client_dir.iterdir() if p.is_dir()]
    except OSError:
        return []
    for p in entries:
        m = _VERSION.match(p.name)
        stem, n = (m.group(1), int(m.group(2))) if m else (p.name, 1)
        if stem.upper() == drawing.upper() or stem.upper().startswith(drawing.upper() + " - "):
            found.append((n, p))
    return [p for _n, p in sorted(found, key=lambda x: (x[0], x[1].name))]


def _saved(folder: Path) -> Dict[str, Any]:
    try:
        return json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(staged_folder: Any, client: str, drawing: str, repo_root: Path, *, run_id: str = "",
         title: str = "", sources: Optional[Dict[str, str]] = None,
         revision_of: Optional[Callable[[str], str]] = None,
         safe: Callable[[Any], str] = str, now: Optional[datetime] = None,
         left_out: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Keep the staged pack under <drop-off>\\<client>\\<drawing> - <title>. Never raises."""
    out: Dict[str, Any] = {"saved": False, "folder": "", "state": "", "version": 0,
                           "files": 0, "why": ""}
    try:
        base = root(repo_root)
        if base is None:
            out["why"] = "no drop-off folder on this machine"
            return out
        _client, _drawing, _title = safe(client).strip(), safe(drawing).strip(), safe(title).strip()
        if not _client or not _drawing:
            out["why"] = "no client or drawing number to name the folder"
            return out
        src = Path(str(staged_folder))
        files = _pack_files(src)
        if not files:
            out["why"] = "nothing was staged"
            return out
        prints = {p.relative_to(src).as_posix(): _sha(p) for p in files}
        client_dir = base / _client
        earlier = _versions(client_dir, _drawing)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        run = {"run_id": run_id, "at": stamp}

        for folder in reversed(earlier):                       # the same pack again: reuse it
            had = _saved(folder)
            if {f.get("name"): f.get("sha256") for f in had.get("files") or []} == prints:
                if run_id and run_id not in {r.get("run_id") for r in had.get("runs") or []}:
                    had.setdefault("runs", []).append(run)
                    (folder / MANIFEST).write_text(json.dumps(had, indent=1), encoding="utf-8")
                out.update(saved=True, folder=str(folder), state="unchanged",
                           version=int(had.get("version") or 1), files=len(files),
                           incomplete_because=_because(had.get("completeness") or {}))
                return out

        version = len(earlier) + 1
        name = _drawing + (f" - {_title}" if _title else "")
        if earlier:                                 # keep the name the job already goes under
            m = _VERSION.match(earlier[0].name)
            name = m.group(1) if m else earlier[0].name
        dest = client_dir / (name if version == 1 else f"{name} v{version}")
        while dest.exists():                         # never into a folder that is already there
            version += 1
            dest = client_dir / f"{name} v{version}"
        dest.mkdir(parents=True)
        resolver: Dict[str, Any] = {}
        try:
            resolver = json.loads((src / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            resolver = {}
        listed = []
        for p in files:
            rel = p.relative_to(src)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / rel)
            listed.append({"name": rel.as_posix(), "size": p.stat().st_size,
                           "sha256": prints[rel.as_posix()],
                           "revision": (revision_of(p.name) if revision_of else "") or "",
                           "source_path": (sources or {}).get(p.name.lower(), ""),
                           "intended_handling": intended_handling(p.name)})
        absent = not_in_this_copy(resolver, [f["name"] for f in listed], left_out)
        completeness = completeness_of(resolver, absent)
        because = [f"{k.replace('_', ' ')}: {w}" for k in ("source_pack", "copy")
                   for w in completeness[k]["because"] if completeness[k]["state"] != "complete"]
        manifest = {
            "schema": SCHEMA, "client": client, "drawing": drawing, "title": title,
            "version": version, "saved_at": stamp, "staged_from": str(src), "runs": [run],
            "files": listed,
            "completeness": completeness,
            "not_in_this_copy": absent,
            "read_on_runs": {},
            "missing": list(resolver.get("missing") or []),
            "unread_assemblies": list(resolver.get("unread_assemblies") or []),
            "parts_list_read": resolver.get("references_read") if resolver else None,
            "pack_status": resolver.get("status") or "",
            "resolver": resolver or None,
            "earlier_versions": [p.name for p in earlier],
        }
        (dest / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        out.update(saved=True, folder=str(dest), state="new" if version == 1 else "new version",
                   version=version, files=len(files), incomplete_because=because)
    except Exception as exc:                                             # noqa: BLE001
        out.update(saved=False, why=f"{type(exc).__name__}: {exc}")
    return out


# ── RECOVERY OF A COPY ALREADY KEPT ──────────────────────────────────────────────────────
def _source_print(path: Path) -> str:
    """The pack resolver's own fingerprint of a source file, to compare with what it recorded."""
    import sys
    src = str(Path(__file__).resolve().parents[1] / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import pack_resolver
    st = path.stat()
    return pack_resolver.fingerprint(path, st.st_size, st.st_mtime)


def recovery_plan(pack_folder: Any) -> Dict[str, Any]:
    """What a recovery of this kept pack would do. Reads only; changes nothing.

    A file is recoverable when its recorded source still exists and still carries the
    fingerprint the resolver recorded when it gathered the pack. Anything else is listed
    with the reason and left out: a file that has since changed is not the file the pack was
    gathered with. The files already kept must still match their own recorded checksums, or
    nothing is offered at all."""
    folder = Path(str(pack_folder))
    had = _saved(folder)
    plan: Dict[str, Any] = {"folder": str(folder), "ok": False, "why": "", "add": [],
                            "cannot": [], "kept": 0, "would_create": ""}
    if not had.get("files"):
        plan["why"] = "no pack manifest of ours in this folder"
        return plan
    for f in had["files"]:
        p = folder / str(f.get("name"))
        if not p.is_file() or _sha(p) != f.get("sha256"):
            plan["why"] = (f"{f.get('name')} in the kept pack no longer matches its recorded "
                           f"checksum; the copy is not recovered from")
            return plan
    plan["kept"] = len(had["files"])
    resolver = had.get("resolver") or {}
    recorded = {}
    for member in resolver.get("members") or []:
        for f in member.get("files") or []:
            recorded[Path(str(f.get("path") or "")).name.lower()] = f
    absent = not_in_this_copy(resolver, [f["name"] for f in had["files"]],
                              [{"path": a.get("name"), "reason": a.get("reason")}
                               for a in had.get("not_in_this_copy") or []])
    for a in absent:
        rec = recorded.get(a["name"].lower()) or {}
        src, want = Path(str(rec.get("path") or a.get("source_path") or "")), str(rec.get("fingerprint") or "")
        if not str(src) or str(src) == ".":
            plan["cannot"].append(dict(a, why="no source path was recorded for it"))
        elif not want:
            plan["cannot"].append(dict(a, why="no fingerprint was recorded for it, so the source "
                                              "cannot be shown to be the file that was gathered"))
        elif not src.is_file():
            plan["cannot"].append(dict(a, why=f"its source is not there now: {src}"))
        else:
            try:
                now = _source_print(src)
            except OSError as exc:
                plan["cannot"].append(dict(a, why=f"its source could not be read: {exc}"))
                continue
            if now != want:
                plan["cannot"].append(dict(a, why="its source has changed since the pack was "
                                                  "gathered (fingerprint differs)"))
            else:
                plan["add"].append({"name": a["name"], "source_path": str(src), "fingerprint": want})
    if not plan["add"]:
        plan["why"] = ("nothing is absent from this copy" if not absent
                       else "none of the absent files can be verified against its source")
        return plan
    m = _VERSION.match(folder.name)
    stem, n = (m.group(1), int(m.group(2))) if m else (folder.name, 1)
    n += 1
    while (folder.parent / f"{stem} v{n}").exists():
        n += 1
    plan.update(ok=True, would_create=str(folder.parent / f"{stem} v{n}"), version=n)
    return plan


def recover(pack_folder: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Carry out recovery_plan: a NEW version beside the pack, holding the kept files and the
    verified absent ones. The original folder is not written to. Returns the plan, with
    `created` set when a version was made."""
    plan = recovery_plan(pack_folder)
    if not plan["ok"]:
        return plan
    folder, dest = Path(plan["folder"]), Path(plan["would_create"])
    had = _saved(folder)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    dest.mkdir(parents=True)
    files = []
    for f in had["files"]:
        rel = Path(str(f["name"]))
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / rel, dest / rel)
        files.append(dict(f))
    for a in plan["add"]:
        src = Path(a["source_path"])
        shutil.copy2(src, dest / a["name"])
        files.append({"name": a["name"], "size": (dest / a["name"]).stat().st_size,
                      "sha256": _sha(dest / a["name"]), "revision": "",
                      "source_path": str(src), "intended_handling": intended_handling(a["name"]),
                      "recovered": True,
                      "given_to_runs": "no: recovered after the runs below; they were given "
                                       "the pack without this file"})
    still = [c for c in plan["cannot"]]
    resolver = had.get("resolver") or {}
    absent = [dict(name=c["name"], source_path=c.get("source_path", ""),
                   listed_by=c.get("listed_by", "the pack resolver"), reason=c["why"]) for c in still]
    completeness = completeness_of(resolver, absent)
    completeness["read"] = (had.get("completeness") or {}).get("read") or completeness["read"]
    manifest = dict(had, version=plan["version"], saved_at=stamp, files=files,
                    not_in_this_copy=absent, completeness=completeness,
                    earlier_versions=list(had.get("earlier_versions") or []) + [folder.name],
                    recovery={"at": stamp, "recovered_from": folder.name,
                              "added": [a["name"] for a in plan["add"]],
                              "not_recovered": still,
                              "note": "The runs and read evidence carried here are those of "
                                      "the original pack. No estimate was rerun."})
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    plan["created"] = str(dest)
    return plan


def said(result: Dict[str, Any]) -> str:
    """One line for the run log and the note. Empty when this machine keeps no drop-off."""
    if result.get("saved"):
        how = {"unchanged": "unchanged, the pack already kept is reused",
               "new": "new", "new version": f"changed, saved as version {result.get('version')}; "
                                            f"the earlier pack is kept"}.get(result.get("state"), "")
        gaps = "; ".join(result.get("incomplete_because") or [])
        return (f"Review copy of this pack ({result.get('files')} file(s), {how}): "
                f"{result.get('folder')}"
                + (f". NOT SHOWN COMPLETE: {gaps} (see pack_manifest.json)" if gaps else ""))
    if "no drop-off folder" in str(result.get("why")):
        return ""
    return f"WARNING: the review copy of this pack was NOT saved to the drop-off folder: {result.get('why')}"
