#!/usr/bin/env python3
"""The drawing pack for a drawing number: found, chosen and proved, with its manifest (SCRUM-199, 9 Nov 2026).

One resolver for every way a job starts (the estimating page, AI Estimate Self-Running and the
tracker pricer), with one set of selection rules and one manifest.

    python src/pack_resolver.py --drawing 11896-01-00-GA            the pack, its members, why
    python src/pack_resolver.py --drawing 11896-01-00-GA --json     the manifest as JSON

CANDIDATES COME FROM THE DRAWING INDEX (src/drawing_index.py): every folder holding a file named
for the drawing number. Archive folders are evidence only: never chosen automatically, used only
where nothing current exists, and then said.

THE GA IS PROVED BY READING IT, NOT BY ITS FOLDER. Its PDF's text must carry the drawing number
for the pack to be "verified"; a file name alone makes it "provisional". Its revision comes from
the drawing (its title block and revision table) where it can be read, else from the "_RevE"
the exported files carry, said which. "Technical" in the path and the newest date only break ties
between candidates that the evidence leaves equal; neither ever settles a revision.

REVISIONS FOLLOW THEIR OWN SCHEME. A, B ... Z, AA; 1, 2, 3; P1, P2 (preliminary, below any issued
letter). Two schemes are not compared. Two different files claiming the same revision of the same
drawing are a CONFLICT, and a modified date never resolves one.

THE PACK IS THE DRAWING NUMBER'S FAMILY, confirmed by the GA's references. 11896-01-00-GA's family
is everything numbered 11896-01-...; a drawing number the GA's own text references outside that
family (a shared-library part) is looked up across the whole index. A family member the GA does
not reference is kept and flagged; a reference with no file is a MISSING child, never dropped.
Each drawing is one member however many formats it exists in (SLDASM, SLDDRW, PDF, DWG, DXF,
IGS), every format kept. Quantities are the BOM's: the engine reads every occurrence and
multiplies through the parents; the resolver never de-duplicates occurrences, only files.

STATUS. verified: the GA's text carries its number, its revision was read, no conflict.
provisional: a sensible match short of that (name only, revision unread, job folder only); priced,
with the assumptions on the book. ambiguous: a conflict the evidence cannot settle; the best
candidate is NOT priced on its own say-so, and the manifest names the choice to ask for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
SCHEMA = "pack_manifest.v1"
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp", ".igs", ".iges"}

# One file: (path, size, modified time).
FileRow = Tuple[Path, int, float]
# One folder of the index: (folder, its files, is it an archive).
FolderRow = Tuple[Path, List[FileRow], bool]

_ID = re.compile(r"^\s*((?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)*)")
_REF = re.compile(r"(?<![0-9A-Za-z])((?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)+)")
_REV_NAME = re.compile(r"(?:^|[_\s\-.])REV(?:ISION)?[_\s\-]?([A-Z]{1,2}|\d{1,2}|P\d{1,2})(?=$|[_\s\-.()\[\]])",
                       re.IGNORECASE)
_REV_TEXT = re.compile(r"\bREV(?:ISION)?\.?\s*[:\-]?\s*([A-Z]{1,2}|\d{1,2}|P\d{1,2})\b")
_ASSEMBLY = re.compile(r"^(GA|SA|ASSY|ASM)\d*$", re.IGNORECASE)


# ── identities and revisions ─────────────────────────────────────────────────────────────

def drawing_id(name: str) -> str:
    """The drawing number a file name opens with: "11896-01-01-02M_1.2mm MS_RevE" is 11896-01-01-02M."""
    head = re.split(r"[_\s]", Path(str(name)).stem.strip(), maxsplit=1)[0]
    m = _ID.match(head)
    return m.group(1).upper() if m else ""


def _same(a: str, b: str) -> bool:
    return re.sub(r"[\s_]", "", a).upper() == re.sub(r"[\s_]", "", b).upper()


def family_prefix(drawing: str) -> str:
    """11896-01-00-GA -> 11896-01-; 12181-00-GA -> 12181-; 7758C-GA -> 7758C-; 12739 -> 12739."""
    segs = [s for s in str(drawing or "").upper().split("-") if s]
    if not segs:
        return ""
    if len(segs) > 1 and _ASSEMBLY.match(segs[-1]):
        segs = segs[:-1]
    while len(segs) > 1 and re.fullmatch(r"0+", segs[-1]):
        segs = segs[:-1]
    return "-".join(segs) + ("-" if len(segs) > 1 or "-" in str(drawing) else "")


def in_family(member: str, drawing: str) -> bool:
    pre = family_prefix(drawing)
    m = member.upper()
    if not pre:
        return False
    if pre.endswith("-"):
        return m.startswith(pre) or m == pre[:-1]
    return m == pre or (m.startswith(pre) and not m[len(pre):len(pre) + 1].isdigit())


def revision_from_name(name: str) -> str:
    m = _REV_NAME.search(Path(str(name)).stem)
    return m.group(1).upper() if m else ""


def revision_rank(rev: str) -> Optional[Tuple[str, int]]:
    """(scheme, value): letters, numbers and P-prefixed preliminaries are separate schemes."""
    r = str(rev or "").strip().upper()
    if not r:
        return None
    if re.fullmatch(r"P\d{1,2}", r):
        return ("prelim", int(r[1:]))
    if r.isdigit():
        return ("number", int(r))
    if re.fullmatch(r"[A-Z]{1,2}", r):
        v = 0
        for ch in r:
            v = v * 26 + (ord(ch) - 64)
        return ("letter", v)
    return None


def later(a: str, b: str) -> Optional[bool]:
    """True when revision a is later than b, False when earlier or equal, None when they cannot be
    compared (different schemes, or one unread). A preliminary is earlier than any issued letter."""
    ra, rb = revision_rank(a), revision_rank(b)
    if ra is None or rb is None:
        return None
    if ra[0] == rb[0]:
        return ra[1] > rb[1]
    if {ra[0], rb[0]} == {"prelim", "letter"}:
        return ra[0] == "letter"
    return None


# ── reading a drawing ────────────────────────────────────────────────────────────────────

def read_pdf_text(path: Path, pages: int = 6) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:pages])
    except Exception:                                                    # noqa: BLE001
        return ""


def read_drawing(path: Path, drawing: str, read_text: Callable[[Path], str] = read_pdf_text) -> Dict[str, Any]:
    """What a PDF drawing says about itself: does it carry this number, which revision, what it references."""
    text = read_text(path) if path.suffix.lower() == ".pdf" else ""
    flat = re.sub(r"\s+", "", text).upper()
    carries = bool(text) and re.sub(r"[\s_]", "", drawing).upper() in flat
    revs = [r for r in _REV_TEXT.findall(text.upper()) if revision_rank(r)]
    best = ""
    for r in revs:
        if not best or later(r, best):
            best = r
    refs = sorted({m.upper() for m in _REF.findall(text.upper())} - {drawing.upper()})
    return {"read": bool(text), "carries_number": carries, "revision": best, "references": refs}


# ── fingerprints ─────────────────────────────────────────────────────────────────────────

def fingerprint(path: Path, size: int, mtime: float, full_below: int = 25 * 1024 * 1024) -> str:
    """sha1 of the file's bytes below 25 MB, else of its size and time: what a later run compares."""
    if size and size < full_below:
        try:
            h = hashlib.sha1()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return "sha1:" + h.hexdigest()
        except OSError:
            pass
    return f"stat:{size}:{int(mtime)}"


# ── the resolver ─────────────────────────────────────────────────────────────────────────

def _token(drawing: str) -> Optional[re.Pattern]:
    d = re.sub(r"\s+", "", drawing or "")
    if len(re.sub(r"\D", "", d)) < 3:
        return None
    return re.compile(r"(?<![0-9A-Za-z])" + re.escape(d).replace(r"\-", r"[-_ ]?") + r"(?![0-9])", re.IGNORECASE)


def _members(rows: Sequence[FileRow], drawing: str, also: Iterable[str] = ()) -> Dict[str, List[FileRow]]:
    """The family's files grouped by drawing number (one member, every format)."""
    out: Dict[str, List[FileRow]] = {}
    wanted = {a.upper() for a in also}
    for f in rows:
        if f[0].suffix.lower() not in DRAWING_EXT:
            continue
        did = drawing_id(f[0].name)
        if did and (in_family(did, drawing) or did in wanted or _same(did, drawing)):
            out.setdefault(did, []).append(f)
    return out


def _pick_revision(files: List[FileRow]) -> Tuple[List[FileRow], str, List[str], List[str]]:
    """The files of a member's latest revision (untagged CAD files ride with it), that revision,
    the superseded revisions present, and any conflict found."""
    tagged = [(revision_from_name(f[0].name), f) for f in files]
    revs = sorted({r for r, _ in tagged if r})
    best = ""
    notes: List[str] = []
    for r in revs:
        if not best:
            best = r
            continue
        cmp = later(r, best)
        if cmp is None:
            notes.append(f"revisions {best} and {r} use different schemes and are not compared")
        elif cmp:
            best = r
    chosen = [f for r, f in tagged if r == best or not r]
    by_kind: Dict[Tuple[str, str], List[FileRow]] = {}
    for f in chosen:
        if revision_from_name(f[0].name) == best and best:
            by_kind.setdefault((f[0].suffix.lower(), best), []).append(f)
    for (ext, r), fs in by_kind.items():
        if len({(s, int(m)) for _p, s, m in fs}) > 1:
            notes.append(f"{len(fs)} different {ext} files claim revision {r}")
    return chosen, best, [r for r in revs if r != best], notes


def resolve(drawing: str, folders: Sequence[FolderRow], client: str = "",
            read_text: Callable[[Path], str] = read_pdf_text, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The pack for one drawing number, from the index's folders: chosen, proved and explained."""
    drawing = str(drawing or "").strip().upper()
    now = now or datetime.now()
    manifest: Dict[str, Any] = {"schema": SCHEMA, "drawing": drawing, "client": client,
                                "resolved_at": now.isoformat(timespec="seconds"), "family": family_prefix(drawing),
                                "status": "not found", "price_ok": False, "candidates": [], "members": [],
                                "missing": [], "unreferenced": [], "library": [], "conflicts": [],
                                "assumptions": [], "question": ""}
    pat = _token(drawing)
    if not pat:
        manifest["question"] = "No drawing number to look for."
        return manifest

    # 1. CANDIDATES: folders holding a file named for the drawing itself (the GA, any format).
    cands = []
    for folder, files, archive in folders:
        own = [f for f in files if _same(drawing_id(f[0].name), drawing)]
        if not own:
            continue
        pdfs = [f for f in own if f[0].suffix.lower() == ".pdf"]
        seen = read_drawing(max(pdfs, key=lambda f: f[2])[0], drawing, read_text) if pdfs else \
            {"read": False, "carries_number": False, "revision": "", "references": []}
        name_rev = ""
        for f in own:
            r = revision_from_name(f[0].name)
            if r and (not name_rev or later(r, name_rev)):
                name_rev = r
        cands.append({"folder": str(folder), "archive": archive, "files": own,
                      "carries_number": seen["carries_number"], "pdf_read": seen["read"],
                      "revision": seen["revision"] or name_rev,
                      "revision_from": "drawing" if seen["revision"] else ("file name" if name_rev else ""),
                      "references": seen["references"],
                      "technical": "technical" in str(folder).lower(),
                      "newest": max(f[2] for f in own)})
    for c in cands:
        manifest["candidates"].append({k: c[k] for k in ("folder", "archive", "carries_number", "revision",
                                                         "revision_from", "technical")} |
                                      {"newest": datetime.fromtimestamp(c["newest"]).isoformat(timespec="minutes")})
    if not cands:
        manifest["question"] = f"No file named {drawing} was found on the share."
        return manifest

    # 2. CHOOSE: current over archive; proved over named; later revision; then Technical; then date.
    live = [c for c in cands if not c["archive"]] or cands
    if live is cands and all(c["archive"] for c in cands):
        manifest["assumptions"].append("only archive copies exist; the latest of them is used and said")

    def better(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        if a["carries_number"] != b["carries_number"]:
            return a["carries_number"]
        cmp = later(a["revision"], b["revision"])
        if cmp is not None and a["revision"] != b["revision"]:
            return cmp
        if a["technical"] != b["technical"]:
            return a["technical"]
        return a["newest"] > b["newest"]

    best = live[0]
    for c in live[1:]:
        if better(c, best):
            best = c
    for c in live:
        if c is best:
            continue
        if c["revision"] and c["revision"] == best["revision"]:
            a = {(f[0].suffix.lower(), f[1]) for f in best["files"]}
            b = {(f[0].suffix.lower(), f[1]) for f in c["files"]}
            if a != b:
                manifest["conflicts"].append(f"{c['folder']} holds a different {drawing} also marked revision "
                                             f"{best['revision']}")
        elif c["revision"] and best["revision"] and later(best["revision"], c["revision"]):
            manifest["assumptions"].append(f"{c['folder']} holds revision {c['revision']}, superseded by "
                                           f"{best['revision']}")
    manifest["selected_folder"] = best["folder"]
    manifest["revision"] = best["revision"]
    manifest["revision_from"] = best["revision_from"]

    # 3. MEMBERS: the family's files in the chosen folder and below it, and the job's other folders
    #    when the GA references a child that is not there; referenced shared-library parts anywhere.
    root = Path(best["folder"])
    near = [f for folder, files, archive in folders if not archive and (folder == root or root in folder.parents)
            for f in files]
    refs = set(best["references"])
    fam_refs = {r for r in refs if in_family(r, drawing)}
    lib_refs = {r for r in refs if not in_family(r, drawing) and re.search(r"\d{4,}", r)}
    groups = _members(near, drawing, also=lib_refs)
    missing_fam = fam_refs - set(groups)
    if missing_fam:
        job = re.match(r"\s*(\d{3,})", drawing)
        wider = [f for folder, files, archive in folders if not archive and job and job.group(1) in str(folder)
                 for f in files]
        for k, v in _members(wider, drawing).items():
            if k in missing_fam:
                groups[k] = v
    for r in sorted(lib_refs - set(groups)):
        hit = [f for folder, files, archive in folders if not archive for f in files
               if _same(drawing_id(f[0].name), r)]
        if hit:
            groups[r] = hit
            manifest["library"].append(r)

    ids = set(groups)
    for did in sorted(ids):
        chosen, rev, superseded, notes = _pick_revision(groups[did])
        manifest["members"].append({
            "drawing": did, "revision": rev, "superseded_revisions": superseded,
            "parent": _parent(did, ids, drawing),
            "referenced_by_ga": did in refs or _same(did, drawing),
            "files": [{"path": str(p), "format": p.suffix.lower().lstrip("."), "size": s,
                       "modified": datetime.fromtimestamp(m).isoformat(timespec="minutes"),
                       "fingerprint": fingerprint(p, s, m)} for p, s, m in sorted(chosen)]})
        manifest["conflicts"] += [f"{did}: {n}" for n in notes if "claim revision" in n]
        manifest["assumptions"] += [f"{did}: {n}" for n in notes if "claim revision" not in n]
    manifest["missing"] = sorted((fam_refs | lib_refs) - ids)
    if refs:
        manifest["unreferenced"] = sorted(d for d in ids if d not in refs and not _same(d, drawing))

    # 4. STATUS, and whether pricing may go ahead.
    if manifest["conflicts"]:
        manifest["status"] = "ambiguous"
        manifest["price_ok"] = False
        manifest["question"] = ("Which copy is the issued one? " + "; ".join(manifest["conflicts"][:3]))
    else:
        proved = best["carries_number"] and best["revision_from"] == "drawing" and not best["archive"]
        manifest["status"] = "verified" if proved else "provisional"
        manifest["price_ok"] = True
        if not best["carries_number"]:
            manifest["assumptions"].append("the GA was matched by its file name; its own text was not read")
        if best["revision_from"] == "file name":
            manifest["assumptions"].append(f"revision {best['revision']} is from the exported file names, not "
                                           f"the drawing's revision table")
        if not best["revision"]:
            manifest["assumptions"].append("no revision could be read")
        if manifest["missing"]:
            manifest["assumptions"].append("referenced drawing(s) not found, to be priced as labelled "
                                           "allowances: " + ", ".join(manifest["missing"]))
    manifest["reason"] = _reason(best, live, manifest)
    return manifest


def _parent(did: str, ids: Iterable[str], drawing: str) -> str:
    """The nearest assembly above a member by its number: 11896-01-01-02M -> 11896-01-01-GA if
    present, else the top drawing."""
    if _same(did, drawing):
        return ""
    segs = did.split("-")
    pool = [i for i in ids if i != did]
    while len(segs) > 1:
        segs = segs[:-1]
        base = "-".join(segs)
        for i in sorted(pool):
            rest = i[len(base):] if i.startswith(base + "-") else ""
            if rest and _ASSEMBLY.match(rest.lstrip("-")) and i != did:
                return i
    return drawing


def _reason(best: Dict[str, Any], live: List[Dict[str, Any]], m: Dict[str, Any]) -> str:
    bits = [f"{best['folder']} chosen"]
    bits.append("its PDF carries the drawing number" if best["carries_number"] else "matched by file name")
    if best["revision"]:
        bits.append(f"revision {best['revision']} (from the {best['revision_from']})")
    if best["technical"]:
        bits.append("in a Technical folder")
    others = [c for c in live if c is not best]
    if others:
        bits.append(f"{len(others)} other candidate(s) ranked lower")
    return "; ".join(bits)


# ── the index as folders ─────────────────────────────────────────────────────────────────

def folders_from_index(roots: Optional[List[Path]] = None) -> Tuple[List[FolderRow], str]:
    sys.path.insert(0, str(HERE))
    import drawing_index as di
    cfg = di.settings()
    idx = di.load(cfg["path"])
    if not idx:
        return [], f"no drawing index at {cfg['path']}; run src/drawing_index.py --build"
    out: List[FolderRow] = []
    for k, v in (idx.get("folders") or {}).items():
        p = Path(k)
        out.append((p, [(p / n, int(s), float(m)) for n, s, m in v.get("files") or []], di.is_archive(k)))
    fresh = di.is_fresh(idx, cfg["max_hours"])
    return out, f"drawing index built {di.summary(idx)['built_at']}" + ("" if fresh else " (STALE)")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drawing", required=True)
    ap.add_argument("--client", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(HERE))
    try:
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    folders, source = folders_from_index()
    m = resolve(args.drawing, folders, args.client)
    m["source"] = source
    if args.json:
        print(json.dumps(m, indent=1))
        return 0 if m["price_ok"] else 2
    print(f"{m['drawing']}  {m['status'].upper()}  ({source})")
    for c in m["candidates"]:
        print(f"  candidate  {'ARCHIVE ' if c['archive'] else ''}{c['folder']}  rev {c['revision'] or '?'}"
              f"{' (' + c['revision_from'] + ')' if c['revision_from'] else ''}"
              f"{'  number in its PDF' if c['carries_number'] else ''}")
    if m.get("reason"):
        print(f"  why: {m['reason']}")
    for x in m["members"]:
        fm = ", ".join(sorted({f["format"] for f in x["files"]}))
        print(f"  member  {x['drawing']:<22} rev {x['revision'] or '-':<3} under {x['parent'] or '(top)':<20} {fm}"
              + (f"  superseded {','.join(x['superseded_revisions'])}" if x["superseded_revisions"] else ""))
    for k in ("missing", "unreferenced", "library", "conflicts", "assumptions"):
        if m[k]:
            print(f"  {k}: " + "; ".join(m[k]))
    if m["question"]:
        print(f"  ASK: {m['question']}")
    return 0 if m["price_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
