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
import time
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
# A drawing reference starts a token: never partway through a supplier's code ("ROSS: 50-360-R-FP"
# read "360-R-FP" as a drawing, 10 Nov 2026).
_REF = re.compile(r"(?<![0-9A-Za-z\-/.:])((?:[A-Za-z]{1,4}-)?\d{3,}[A-Za-z]?(?:-[A-Za-z0-9]+)+)")
_REV_NAME = re.compile(r"(?:^|[_\s\-.])REV(?:ISION)?[_\s\-]?([A-Z]{1,2}|\d{1,2}|P\d{1,2})(?=$|[_\s\-.()\[\]])",
                       re.IGNORECASE)
_REV_TEXT = re.compile(r"\bREV(?:ISION)?\.?\s*[:\-]?\s*([A-Z]{1,2}|\d{1,2}|P\d{1,2})\b")
# A REVISION TABLE'S COLUMN HEADINGS ARE NOT REVISIONS (JG, 10 Nov 2026): 12736-00-01's table reads
# "ZONE REV. CN REASON DATE", and CN, the change-note column, was taken as the GA's revision.
_REV_HEADINGS = {"CN", "ECN", "ECO", "DCN", "CR", "ZONE", "BY", "NO", "DATE", "DESC", "REASON"}
_ASSEMBLY = re.compile(r"^(GA|SA|ASSY|ASM)\d*$", re.IGNORECASE)


# ── identities and revisions ─────────────────────────────────────────────────────────────

def drawing_id(name: str) -> str:
    """The drawing number a file name opens with: "11896-01-01-02M_1.2mm MS_RevE" is 11896-01-01-02M.

    A CUSTOMER'S ITEM NUMBER IN FRONT (JG, 10 Nov 2026): "0359829_12674-01-GA_Smart Shirt
    Table_revB.PDF" is M&S item 0359829 and SDI drawing 12674-01-GA. Read by its first token it
    was drawing "0359829", so the GA PDF, the one file the engine prices from, was left out of
    the pack. A name that opens with a bare number (no dash) and carries a dashed drawing number
    after it is that drawing."""
    tokens = [x for x in re.split(r"[_\s]+", Path(str(name)).stem.strip()) if x]
    if not tokens:
        return ""
    m = _ID.match(tokens[0])
    first = m.group(1).upper() if m else ""
    # "12773-02 GA.SLDASM" IS DRAWING 12773-02-GA (12 Nov 2026): the assembly word stood apart
    # from its number, the file read as "12773-02", and the lower-body assembly the GA calls
    # for was never gathered; the estimate priced a lower body with no members.
    if first and "-" in first and len(tokens) > 1 and _ASSEMBLY.match(tokens[1]) \
            and not _ASSEMBLY.match(first.split("-")[-1]) and re.fullmatch(r"\d+[A-Z]?", first.split("-")[-1]):
        return first + "-" + tokens[1].upper()
    if first and "-" not in first:
        for tok in tokens[1:]:
            n = _ID.match(tok)
            if n and "-" in n.group(1) and re.match(r"\d", n.group(1)):
                return n.group(1).upper()
    return first


def _same(a: str, b: str) -> bool:
    return re.sub(r"[\s_]", "", a).upper() == re.sub(r"[\s_]", "", b).upper()


def _archive_path(path: Path) -> bool:
    try:
        sys.path.insert(0, str(HERE))
        import drawing_index as di
        return di.is_archive(str(path))
    except Exception:                                                    # noqa: BLE001
        return False


def _segments(folder: str) -> List[str]:
    return [x.strip().lower() for x in re.split(r"[\\/]", str(folder)) if x.strip()]


def _in_job(folder: str, job: str) -> bool:
    """A folder of job `job`: a path segment that opens with the job number ("11203 - QUIK-LOK
    Holder", "11203-Technical", "12754_Gen 5 Wall CDU")."""
    return any(re.match(re.escape(job) + r"(?!\d)", seg) for seg in _segments(folder))


def _customer_folder(folder: str) -> bool:
    """Under a customers folder of the design share, where the next segment names the customer."""
    return any("customers" in seg for seg in _segments(folder))


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

_NO_PDF_READER_SAID = []


def read_pdf_text(path: Path, pages: int = 6) -> str:
    # A PYTHON WITHOUT PDFPLUMBER READS NO DRAWING, AND SAYS SO (JG, 10 Nov 2026). Run with the
    # system Python instead of the engine's .venv, every GA came back "its own text was not
    # read" with nothing to say why, and its references (12736-00-01's parts table) went
    # unfollowed. It is said once, loudly, with the interpreter to use.
    try:
        import pdfplumber
    except ImportError:
        if not _NO_PDF_READER_SAID:
            _NO_PDF_READER_SAID.append(1)
            print(f"   [pack] pdfplumber is not installed in this Python ({sys.executable}): no "
                  f"drawing's text can be read, so numbers, revisions and the GA's parts list go "
                  f"unread. Run with the engine's own Python: .\\.venv\\Scripts\\python.exe",
                  flush=True)
        return ""
    try:
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:pages])
    except Exception:                                                    # noqa: BLE001
        return ""


def read_drawing(path: Path, drawing: str, read_text: Callable[[Path], str] = read_pdf_text) -> Dict[str, Any]:
    """What a PDF drawing says about itself: does it carry this number, which revision, what it references."""
    text = read_text(path) if path.suffix.lower() == ".pdf" else ""
    flat = re.sub(r"\s+", "", text).upper()
    # THE NUMBER AS THE TITLE BLOCK PRINTS IT (12 Nov 2026): 12674-01-GA and 12674-02-GA were
    # read, yet "the GA is matched by file name; its own title block did not confirm". A title
    # block prints the number across boxes, "12674-01" and "GA", or with other dashes; compared
    # letter for letter with its hyphens the number was never found. Letters and digits only.
    _only = lambda t: re.sub(r"[^0-9A-Z]", "", str(t).upper())          # noqa: E731
    carries = bool(text) and (re.sub(r"[\s_]", "", drawing).upper() in flat
                              or (len(_only(drawing)) >= 7 and _only(drawing) in _only(text)))
    up = text.upper()
    revs = [r for r in _REV_TEXT.findall(up) if revision_rank(r) and r not in _REV_HEADINGS]
    best = ""
    for r in revs:
        if not best or later(r, best):
            best = r
    # THE TITLE BLOCK'S OWN REVISION BEATS ANY OTHER: the drawing number with its revision after
    # it ("12736-00-01 B"), as the DWG NO. / REVISION boxes print side by side.
    _num = re.escape(drawing.upper()).replace(r"\-", r"[-_ ]?")
    _tb = [m.group(1) for m in re.finditer(r"(?<![0-9A-Z])" + _num + r"\s+([A-Z]{1,2}|P\d{1,2})(?![0-9A-Z])", up)
           if revision_rank(m.group(1)) and m.group(1) not in _REV_HEADINGS]
    if _tb:
        best = max(_tb, key=lambda r: revision_rank(r) or ("", 0))
    refs = sorted({m.upper() for m in _REF.findall(_joined_assembly_words(text.upper()))} - {drawing.upper()})
    _sh = re.search(r"\bSHEET\s*(\d{1,2})\s*(?:OF|/)\s*(\d{1,2})\b", up)
    return {"read": bool(text), "carries_number": carries, "revision": best, "references": refs,
            "sheet_of": f"{_sh.group(1)} of {_sh.group(2)}" if _sh and int(_sh.group(2)) > 1 else ""}


_SPLIT_ASSEMBLY = re.compile(r"(?<![0-9A-Z\-/.:])(\d{3,}[A-Z]?(?:-\d+[A-Z]?)+)[ ](GA|SA|ASSY|ASM)(?![0-9A-Z])")
_TAIL_ASSEMBLY = re.compile(r"^(.*\d)-?(GA|SA|ASSY|ASM)(\d*)$")


def spellings(drawing: str) -> List[str]:
    """One assembly number as it may be written: 12674-01-101SA and 12674-01-101-SA are the
    same drawing (12 Nov 2026: joining every glued form with a dash made the estimator's own
    "12674-01-101SA.SLDASM" a missing reference). The number as given comes first."""
    d = str(drawing or "").upper()
    m = _TAIL_ASSEMBLY.match(d)
    if not m:
        return [d]
    out = [d]
    for alt in (f"{m.group(1)}-{m.group(2)}{m.group(3)}", f"{m.group(1)}{m.group(2)}{m.group(3)}"):
        if alt not in out:
            out.append(alt)
    return out


def _joined_assembly_words(text: str) -> str:
    """"12773-02 GA" in a parts list is drawing 12773-02-GA. A glued "12773-02GA" is kept as
    printed and matched by `spellings`."""
    return _SPLIT_ASSEMBLY.sub(r"\1-\2", text)


def sheets_of(assembly: str, ids: Iterable[str]) -> List[str]:
    """The members that are numbered SHEETS of an assembly drawing: 11896-04-00-GA-01, -02, -03
    are the three sheets of 11896-04-00-GA."""
    # THE TOP DRAWING NUMBERED ALL ZEROS IS THE ASSEMBLY'S OWN DRAWING (12 Nov 2026): a job asked
    # for as "NNNN-02" keeps its general assembly as "NNNN-02-000 <title>_revW.pdf", with its
    # parts numbered -001, -002 after it. The pack gathered 34 drawings, read 0 PDFs and was
    # classed "incorrect pack: the GA's parts list was not read". Zeros of any length are the
    # top sheet; -001 and on stay parts.
    pre = assembly.upper() + "-"
    return sorted(d for d in ids if d.upper().startswith(pre)
                  and (re.fullmatch(r"\d{1,2}", d[len(pre):]) or re.fullmatch(r"0{3,4}", d[len(pre):])))


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


# A PART'S NUMBERED PIECE IN ITS FILE NAME, as drawing_job_merge.member_number_from_filename reads
# it (D-669): "...01A_-07_5MM..." -> "07", "...01J_PART5_10.8mm..." -> "5". Mirrored here because
# that module takes seconds to import; a test holds the two readings together.
_MEMBER_NUMBER = re.compile(r"[_\s-]-(\d{1,3})(?=[_\s.-])")
_PIECE_WORD_NUMBER = re.compile(r"(?<=[_\s-])(?:PART|PIECE)[\s_-]?(\d{1,2})(?=[_\s-]|\.(?!\d)|$)", re.I)


def piece_number(name: str) -> str:
    stem = Path(str(name)).stem
    m = _MEMBER_NUMBER.search(stem) or _PIECE_WORD_NUMBER.search(stem)
    return (m.group(1).lstrip("0") or "0") if m else ""


_COPY_MARK = re.compile(r"(\s*-\s*copy(\s*\(\d+\))?|\s*\(\d+\)|[_\s-]copy\d*)$", re.I)


def piece_key(name: str) -> str:
    """What one file of a member IS, apart from its revision and from being a copy.

    A PART'S NAMED PIECES ARE NOT RIVAL COPIES (the real share, 12 Nov 2026). Three jobs
    already sent were classed "incorrect pack: two copies claim to be the issue":
        11896-02-01-03J_BASE_MDF_18.0mm_REV F.DXF   ..._LHS_...   ..._REAR_...   ..._RIB_...
        6364-01-004-LOCK COVER_3mm PETG_revR.DXF    6364-01-004-lock plate_5mm PETG_revR.DXF
        6364-02-001-LEFT END_18mm MFC_revW.DXF      6364-02-001-LEFT END LIP_18mm MFC_revW.DXF
    Each is a different piece of one part, cut from its own flat, and the name says which.
    Two files are the same piece only when their names agree once the revision and any copy
    mark ("- Copy", "(2)") are taken off. A numbered piece (PART5, _-07) keeps its number."""
    stem = Path(str(name)).stem
    stem = _REV_NAME.sub("", stem)
    stem = _COPY_MARK.sub("", stem)
    return re.sub(r"[\s_\-.]+", " ", stem).strip().upper()


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
    dropped: set = set()
    for (ext, r), fs in by_kind.items():
        # A PART'S NUMBERED PIECES ARE NOT COPIES (D-669): "01J_PART1" .. "01J_PART5" are five
        # flats of one part. Each piece number is compared with its own copies only.
        by_piece: Dict[str, List[FileRow]] = {}
        for f in fs:
            by_piece.setdefault(piece_key(f[0].name), []).append(f)
        for _pk, pf in by_piece.items():
            piece = piece_number(pf[0][0].name)
            # THE SAME BYTES ARE ONE FILE: a copy keeps its size whatever date the copy got.
            if len({s for _p, s, _m in pf}) <= 1:
                continue
            what = f"{ext} files" + (f" for piece {piece}" if piece else "")
            dirs: Dict[Path, List[FileRow]] = {}
            for f in pf:
                dirs.setdefault(f[0].parent, []).append(f)
            # COPIES IN OTHER FOLDERS (TTI dry run, 11 Nov 2026): a job keeps cutting copies in
            # sub-folders (Cutters, CNC, laser). The issued file sits beside the member's own PDF;
            # elsewhere is a copy, kept out of the pack and said. With no PDF beside one of them
            # the evidence cannot choose, and it is asked.
            pick = None
            if len(dirs) > 1:
                pdf_dirs = {f[0].parent for f in chosen if f[0].suffix.lower() == ".pdf"
                            and revision_from_name(f[0].name) in (r, "")}
                beside = [d for d in dirs if d in pdf_dirs]
                pick = beside[0] if len(beside) == 1 else None
            if pick is not None and len({s for _p, s, _m in dirs[pick]}) <= 1:
                others = [f for d, g in dirs.items() if d != pick for f in g]
                dropped.update(id(f) for f in others)
                notes.append(f"{len(others)} other {what} claiming revision {r} sit away from the "
                             f"drawing's PDF ({', '.join(sorted({str(f[0].parent) for f in others}))}); "
                             f"the copy beside the PDF is used")
                continue
            notes.append(f"{len(pf)} different {what} claim revision {r}")
    chosen = [f for f in chosen if id(f) not in dropped]
    return chosen, best, [r for r in revs if r != best], notes


def _default_area_rank() -> Callable[[Path], int]:
    """Search areas in the drawing index's own order: the design customers folder first, then
    Prototype (JG: Prototype is for drawings not in design). A folder under neither ranks last."""
    try:
        sys.path.insert(0, str(HERE))
        import drawing_index as di
        roots = [str(r) for r in di.settings()["roots"]]
    except Exception:                                                    # noqa: BLE001
        roots = []

    def rank(folder: Path) -> int:
        for i, r in enumerate(roots):
            if di._under(str(folder), r):
                return i
        return len(roots)
    return rank


def _looks_drawing(ref: str) -> bool:
    """A referenced number that is a drawing, not a dimension pair (2400-1200): three parts or more,
    or a last part with a letter in it."""
    parts = ref.split("-")
    return len(parts) >= 3 or bool(re.search(r"[A-Z]", parts[-1]))


def _is_assembly(did: str) -> bool:
    return bool(_ASSEMBLY.match(did.split("-")[-1]))


def resolve(drawing: str, folders: Sequence[FolderRow], client: str = "",
            read_text: Callable[[Path], str] = read_pdf_text, now: Optional[datetime] = None,
            area_rank: Optional[Callable[[Path], int]] = None,
            lookup: Optional[Callable[[str], List[FileRow]]] = None,
            client_folders_only: bool = False) -> Dict[str, Any]:
    """The pack for one drawing number, from the index's folders: chosen, proved and explained.
    `client_folders_only`: a caller whose client is spelt as its folder is (the TTI tracker) asks
    about a pack found only under another customer's folder instead of pricing it."""
    rank = area_rank or _default_area_rank()
    _reads = {"n": 0}
    _inner = read_text

    def read_text(path: Path) -> str:                                    # noqa: F811  (counted)
        _reads["n"] += 1
        return _inner(path)
    drawing = str(drawing or "").strip().upper()
    now = now or datetime.now()
    manifest: Dict[str, Any] = {"schema": SCHEMA, "drawing": drawing, "client": client,
                                "resolved_at": now.isoformat(timespec="seconds"), "family": family_prefix(drawing),
                                "status": "not found", "price_ok": False, "candidates": [], "members": [],
                                "missing": [], "bought_in_unmatched": [], "unreferenced": [], "library": [], "conflicts": [],
                                "assumptions": [], "question": ""}
    pat = _token(drawing)
    if not pat:
        manifest["question"] = "No drawing number to look for."
        return manifest

    # 1. CANDIDATES: folders holding a file named for the drawing itself (the GA, any format).
    #    A GA's PDF is read (over the network, seconds each) only where it could be chosen: the
    #    first search area's current copies, or the archive copies when nothing current exists.
    found = []
    for folder, files, archive in folders:
        own = [f for f in files if _same(drawing_id(f[0].name), drawing)]
        if own:
            found.append((folder, own, archive))
    current = [x for x in found if not x[2]]
    pool = current or found
    first_area = min((rank(x[0]) for x in pool), default=0)
    readable = {str(x[0]) for x in pool if rank(x[0]) == first_area}
    cands = []
    for folder, own, archive in found:
        pdfs = [f for f in own if f[0].suffix.lower() == ".pdf"]
        seen = read_drawing(max(pdfs, key=lambda f: f[2])[0], drawing, read_text) \
            if pdfs and str(folder) in readable else \
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
    # THE FIRST SEARCH AREA WINS (JG, 10 Nov): design, then Prototype, which is for drawings not in
    # design. A copy in a later area is noted, never compared, so it can never make a conflict.
    first = min(rank(Path(c["folder"])) for c in live)
    for c in live:
        if rank(Path(c["folder"])) != first:
            manifest["assumptions"].append(f"{c['folder']} also holds {drawing} (revision {c['revision'] or '?'}) "
                                           f"in a later search area; the first area's copy is used")
    live = [c for c in live if rank(Path(c["folder"])) == first]
    # THE DRAWING'S OWN JOB FOLDER OVER ANOTHER JOB'S COPY (TTI dry run, 11 Nov 2026): 11203-01-GA
    # also sits in 11437's data folder, where that job reused it. A copy in another job's folder
    # is noted, never compared, so it cannot make a conflict.
    _jobm = re.match(r"\s*(\d{3,})", drawing)
    if _jobm:
        mine = [c for c in live if _in_job(c["folder"], _jobm.group(1))]
        if mine and len(mine) < len(live):
            for c in live:
                if c not in mine:
                    manifest["assumptions"].append(
                        f"{c['folder']} also holds {drawing} (revision {c['revision'] or '?'}); it is "
                        f"another job's folder, so job {_jobm.group(1)}'s own copy is used")
            live = mine
    # THE CLIENT'S OWN FOLDERS (same review): row 12775 of the TTI tracker matched a file under an
    # M&S folder. Where the client is known, a copy in its folders wins; a pack found only in
    # another customer's folders is asked about, not priced on a name match.
    _cl = str(client or "").strip().lower()
    if _cl:
        ours = [c for c in live if _cl in _segments(c["folder"])]
        if ours and len(ours) < len(live):
            for c in live:
                if c not in ours:
                    manifest["assumptions"].append(
                        f"{c['folder']} also holds {drawing}; it is not in a {client} folder, so "
                        f"the {client} copy is used")
            live = ours
        elif not ours and client_folders_only and any(_customer_folder(c["folder"]) for c in live):
            manifest["conflicts"].append(
                f"{drawing} was found only outside the {client} folders ("
                + "; ".join(sorted({c['folder'] for c in live})[:2])
                + f"): is this the {client} drawing?")

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
            # ONLY A FORMAT BOTH COPIES HOLD IS COMPARED: a folder with the model and one with
            # the PDF are two halves of one issue, not two issues (12754-01-GA's 2D and 3D CAD).
            a = {(f[0].suffix.lower(), f[1]) for f in best["files"]}
            b = {(f[0].suffix.lower(), f[1]) for f in c["files"]}
            shared = {e for e, _s in a} & {e for e, _s in b}
            if any({x for x in a if x[0] == e} != {x for x in b if x[0] == e} for e in shared):
                manifest["conflicts"].append(f"{c['folder']} holds a different {drawing} also marked revision "
                                             f"{best['revision']}")
        elif c["revision"] and best["revision"] and later(best["revision"], c["revision"]):
            manifest["assumptions"].append(f"{c['folder']} holds revision {c['revision']}, superseded by "
                                           f"{best['revision']}")
    manifest["selected_folder"] = best["folder"]
    manifest["revision"] = best["revision"]
    manifest["revision_from"] = best["revision_from"]

    # 3. MEMBERS: the family's files in the chosen folder and below it; then every reference the GA
    #    makes, FOLLOWED THROUGH EACH SUB-ASSEMBLY'S OWN DRAWING (11896-01-00-GA -> 11896-01-01-GA ->
    #    its parts), found in the job's folders of the same search area when not under the chosen
    #    one; shared-library parts anywhere. Each member's parent is the drawing that references it.
    root = Path(best["folder"])
    area = rank(root)
    near = [f for folder, files, archive in folders if not archive and (folder == root or root in folder.parents)
            for f in files]
    job = re.match(r"\s*(\d{3,})", drawing)
    wider_rows = [f for folder, files, archive in folders
                  if not archive and job and job.group(1) in str(folder) and rank(folder) == area for f in files]
    wider: Optional[Dict[str, List[FileRow]]] = None
    groups = _members(near, drawing)
    refs_of: Dict[str, set] = {drawing: set(best["references"])}
    parent_of: Dict[str, str] = {}
    # EVERY PARENT IS KEPT (10 Nov 2026 review): a drawing two sub-assemblies reference is one file
    # in the pack but two occurrences in the build. The pack lists the file once; "parents" names
    # each drawing that calls for it, and the quantities stay with the BOM the estimate reads.
    parents_of: Dict[str, List[str]] = {}
    all_refs: set = set()
    queue = [drawing] + sorted(d for d in groups if _is_assembly(d) and not _same(d, drawing))
    done: set = set()
    read_any: set = set()                  # assemblies whose own drawing, or a sheet of it, was read
    sheets_read: Dict[str, List[str]] = {}
    sheet_refs: Dict[str, Dict[str, List[str]]] = {}
    sheet_says: Dict[str, Dict[str, str]] = {}
    if best.get("pdf_read"):
        read_any.add(drawing)
    while queue:
        a = queue.pop(0)
        if a in done:
            continue
        done.add(a)
        if a not in refs_of:
            pdfs = [f for f in groups.get(a, []) if f[0].suffix.lower() == ".pdf"]
            refs_of[a] = set(read_drawing(max(pdfs, key=lambda f: f[2])[0], a, read_text)["references"]) \
                if pdfs else set()
            if pdfs:
                read_any.add(a)
        # AN ASSEMBLY ISSUED AS NUMBERED SHEETS IS READ FROM ITS SHEETS (12 Nov 2026).
        # 11896-04-00-GA has no PDF of its own: its drawing is 11896-04-00-GA-01, -02 and -03.
        # None was read, so not one part it calls for was gathered, and the pack of 15 files
        # with no parts was reported "drawings complete". Each sheet's references are the
        # assembly's.
        for sheet in sheets_of(a, groups):
            spdfs = [f for f in groups[sheet] if f[0].suffix.lower() == ".pdf"]
            if not spdfs:
                continue
            got = read_drawing(max(spdfs, key=lambda f: f[2])[0], a, read_text)
            if got["read"]:
                read_any.add(a)
                sheets_read.setdefault(a, []).append(sheet)
                sheet_refs.setdefault(a, {})[sheet] = sorted(
                    x for x in got["references"] if _looks_drawing(x) and not x.upper().startswith(a.upper() + "-0"))
                if got.get("sheet_of"):
                    sheet_says.setdefault(a, {})[sheet] = got["sheet_of"]
            refs_of[a] |= {x for x in got["references"] if not x.upper().startswith(a.upper() + "-")
                           or not re.fullmatch(r"\d{1,2}", x[len(a) + 1:])}
        for x in sorted(refs_of[a]):
            if _same(x, a) or _same(x, drawing) or not _looks_drawing(x):
                continue
            # the same assembly, however its word is joined to its number
            _alts = spellings(x)
            _held = next((g for alt in _alts for g in groups if _same(g, alt)), None)
            if _held is None and len(_alts) > 1:
                if wider is None:
                    wider = _members(wider_rows, drawing)
                _held = next((g for alt in _alts[1:] for g in wider if _same(g, alt)), None)
                if _held is None and lookup:
                    _held = next((alt for alt in _alts[1:]
                                  if any(not _archive_path(f[0]) for f in lookup(alt))), None)
            if _held is not None:
                x = _held
            if any(_same(x, alt) for alt in spellings(a)) or any(_same(x, alt) for alt in spellings(drawing)):
                continue
            all_refs.add(x)
            parent_of.setdefault(x, a)
            if a not in parents_of.setdefault(x, []):
                parents_of[x].append(a)
            if x not in groups:
                if in_family(x, drawing):
                    if wider is None:
                        wider = _members(wider_rows, drawing)
                    if x in wider:
                        groups[x] = wider[x]
                    elif lookup:
                        # A PART OF THE FAMILY NOT IN THE JOB'S FOLDERS OF THIS AREA (11 Nov 2026):
                        # it was never looked for anywhere else, so a part kept in the other
                        # search area, or in a folder not named for the job, left the pack as its
                        # GA alone. It is looked up across the index, as a library part is.
                        hit = [f for f in lookup(x) if not _archive_path(f[0])]
                        if hit:
                            groups[x] = hit
                else:
                    hit = lookup(x) if lookup else [f for folder, files, archive in folders if not archive
                                                     for f in files if _same(drawing_id(f[0].name), x)]
                    if hit:
                        groups[x] = hit
                        # THE JOB'S OWN PART IN A SIBLING FOLDER IS NOT A LIBRARY PART.
                        if not (job and str(x).startswith(job.group(1))):
                            manifest["library"].append(x)
            if x in groups and _is_assembly(x) and x not in done:
                queue.append(x)
    refs = all_refs

    # FILES IN THE PACK'S FOLDERS WHOSE NAMES CARRY NO DRAWING NUMBER (JG and the reviewer,
    # 12 Nov 2026: "Inspect files in the associated folder even when their filenames do not
    # contain XXXX-03 ... establish what each file belongs to before costing it"). A detail
    # saved as "Back panel flat.pdf" beside 11896-04-01-01M was invisible: the pack is built
    # from names. Every drawing-format file in the chosen folder's tree and in the folders the
    # members came from is looked at. A PDF whose own text names a member is that member's
    # file. Anything else is LISTED with its folder, never dropped and never priced as a part
    # on the strength of where it sits: another job's copy or an old alternative can sit there.
    member_folders = {root} | {f[0].parent for fs in groups.values() for f in fs}
    held = {str(f[0]).lower() for fs in groups.values() for f in fs}
    pool: List[FileRow] = list(near) + [f for folder, files, archive in folders
                                        if not archive and folder in member_folders for f in files]
    by_key = {re.sub(r"[\s_]", "", d).upper(): d for d in groups}
    unassigned: List[Dict[str, str]] = []
    other_numbers: List[Dict[str, str]] = []
    assigned_by_text: List[Dict[str, str]] = []
    _seen_paths: set = set()
    _text_reads = 0
    for f in sorted(pool):
        path = f[0]
        if str(path).lower() in held or str(path).lower() in _seen_paths \
                or path.suffix.lower() not in DRAWING_EXT or _archive_path(path):
            continue
        _seen_paths.add(str(path).lower())
        did = drawing_id(path.name)
        if did and re.sub(r"[\s_]", "", did).upper() in by_key:
            continue                                 # a member's superseded or duplicate file
        if did and "-" in did:
            other_numbers.append({"path": str(path), "drawing": did})
            continue
        owner = ""
        if path.suffix.lower() == ".pdf" and _text_reads < 40:
            _text_reads += 1
            flat = re.sub(r"[\s_]", "", read_text(path) or "").upper()
            named = sorted((k for k in by_key if k in flat), key=len, reverse=True)
            # the longest number wins: a part's sheet names its assembly too
            owner = by_key[named[0]] if named else ""
        if owner:
            groups[owner] = list(groups[owner]) + [f]
            held.add(str(path).lower())
            assigned_by_text.append({"path": str(path), "drawing": owner})
        else:
            unassigned.append({"path": str(path), "why": (
                "its name carries no drawing number and its text names no drawing in this pack"
                if path.suffix.lower() == ".pdf" else
                "its name carries no drawing number; a model or flat cannot be assigned by name")})
    manifest["assigned_by_text"] = assigned_by_text
    manifest["unassigned_files"] = unassigned
    manifest["other_drawings_in_folders"] = other_numbers
    if assigned_by_text:
        manifest["assumptions"].append(
            f"{len(assigned_by_text)} file(s) with no drawing number in the name were assigned by "
            "their own text: " + ", ".join(f"{Path(a['path']).name} -> {a['drawing']}" for a in assigned_by_text[:6]))
    if unassigned:
        manifest["assumptions"].append(
            f"{len(unassigned)} drawing file(s) in the pack's folders belong to no drawing by name or "
            "text and are NOT in the pack: " + ", ".join(Path(u["path"]).name for u in unassigned[:6])
            + ". Say which part each is, or that it is not needed")

    ids = set(groups)
    for did in sorted(ids):
        chosen, rev, superseded, notes = _pick_revision(groups[did])
        manifest["members"].append({
            "drawing": did, "revision": rev, "superseded_revisions": superseded,
            "parent": parent_of.get(did) or _parent(did, ids, drawing),
            "parents": list(parents_of.get(did) or ([parent_of.get(did) or _parent(did, ids, drawing)]
                                                   if not _same(did, drawing) else [])),
            "referenced_by_ga": did in refs or _same(did, drawing),
            "files": [{"path": str(p), "format": p.suffix.lower().lstrip("."), "size": s,
                       "modified": datetime.fromtimestamp(m).isoformat(timespec="minutes"),
                       "fingerprint": fingerprint(p, s, m)} for p, s, m in sorted(chosen)]})
        manifest["conflicts"] += [f"{did}: {n}" for n in notes if "claim revision" in n]
        manifest["assumptions"] += [f"{did}: {n}" for n in notes if "claim revision" not in n]
    # A MISSING REFERENCE IS A MADE PART WITHOUT ITS DRAWING, OR A BOUGHT ITEM THAT NEEDS NONE
    # (JG, 10 Nov 2026): 12736-01-04X, "EU INTERNAL DOOR ... SDI TO SOURCE", is bought, by SDI's
    # X suffix, and needs a catalogue match, not a drawing. Only a missing MADE part leaves the
    # pack incomplete.
    _gone = sorted(refs - ids)
    try:
        import part_code_conventions as _pcc
        _bought = [x for x in _gone if _pcc.purchased_suffix(x) or _pcc.is_supplier_article(x)]
    except Exception:                                                    # noqa: BLE001
        _bought = []
    manifest["bought_in_unmatched"] = _bought
    manifest["missing"] = [x for x in _gone if x not in _bought]
    if refs:
        manifest["unreferenced"] = sorted(d for d in ids if d not in refs and not _same(d, drawing))

    # 4. STATUS, and whether pricing may go ahead.
    if manifest["conflicts"]:
        manifest["status"] = "ambiguous"
        manifest["price_ok"] = False
        manifest["question"] = ("Which copy is the issued one? " + "; ".join(manifest["conflicts"][:3]))
    else:
        proved = best["carries_number"] and best["revision_from"] == "drawing" and not best["archive"]
        # IDENTITY AND COMPLETENESS ARE TWO FACTS (10 Nov 2026 review): a GA proved by its own
        # title block with made parts missing is not a verified PACK. "verified" needs both.
        manifest["identity"] = "verified" if proved else "named"
        # COMPLETE NEEDS A PARTS LIST THAT WAS READ (12 Nov 2026). "No reference is missing" is
        # true of a GA nobody read: 11896-04-00-GA was called complete on 0 drawings read.
        manifest["references_read"] = drawing in read_any
        manifest["sheets_read"] = sheets_read.get(drawing, [])
        manifest["unread_assemblies"] = sorted(a for a in done if a not in read_any and not _same(a, drawing))
        manifest["complete"] = not manifest["missing"] and manifest["references_read"]
        # SHEETS OF ONE ASSEMBLY, OR ALTERNATIVE CONFIGURATIONS? (reviewer, 12 Nov 2026:
        # "distinguishing alternative configurations from cumulative assemblies"). -GA-01, -02
        # and -03 that each say "sheet n of m" are one drawing. Where they do not, and they call
        # for different parts, they may be three versions of the product: every part is still
        # gathered, each sheet's own list is kept, and the question is asked, because adding
        # three alternatives together prices the product three times.
        manifest["sheet_references"] = sheet_refs.get(drawing, {})
        _sets = {tuple(v) for v in manifest["sheet_references"].values()}
        _says = sheet_says.get(drawing, {})
        if len(manifest["sheet_references"]) > 1 and len(_sets) > 1 \
                and len(_says) < len(manifest["sheet_references"]):
            manifest["configurations_unconfirmed"] = True
            manifest["assumptions"].append(
                ", ".join(sorted(manifest["sheet_references"])) + " call for different parts and do "
                "not all say they are sheets of one drawing: they may be alternative configurations, "
                "not one assembly. Every part is gathered; confirm which the enquiry is for before "
                "the parts are added together")
        if not manifest["references_read"]:
            manifest["assumptions"].append(
                "the GA's parts list was NOT READ (no readable PDF of the GA or of its sheets), so "
                "what it calls for is unknown and the pack is not proved complete")
        if manifest["unread_assemblies"]:
            manifest["assumptions"].append(
                "sub-assembly drawing(s) with no readable PDF, so their parts were not followed: "
                + ", ".join(manifest["unread_assemblies"]))
        # A bought item still to be priced keeps the pack provisional too: its cost is a catalogue
        # match or a labelled allowance, not yet a fact.
        manifest["status"] = ("verified" if proved and manifest["complete"]
                              and not manifest["bought_in_unmatched"] else "provisional")
        if proved and not manifest["complete"]:
            manifest["assumptions"].append(
                f"the GA's identity is verified from its own title block, but the pack is "
                f"incomplete: {len(manifest['missing'])} made part(s) it references have no "
                f"drawing")
        if manifest.get("bought_in_unmatched"):
            manifest["assumptions"].append(
                "bought-in, no drawing needed, to be priced from the catalogue or as a labelled "
                "allowance: " + ", ".join(manifest["bought_in_unmatched"]))
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
    manifest["pdfs_read"] = _reads["n"]
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

_CACHE: Dict[str, Any] = {}


def folders_from_index(roots: Optional[List[Path]] = None) -> Tuple[List[FolderRow], str]:
    """The index as folder rows, read once per index file: Self-Running asks for every row."""
    sys.path.insert(0, str(HERE))
    import drawing_index as di
    cfg = di.settings()
    try:
        stamp = (str(cfg["path"]), cfg["path"].stat().st_mtime)
    except OSError:
        stamp = None
    if stamp and _CACHE.get("stamp") == stamp:
        return _CACHE["value"]
    idx = di.load(cfg["path"])
    if not idx:
        return [], f"no drawing index at {cfg['path']}; run src/drawing_index.py --build"
    out: List[FolderRow] = []
    for k, v in (idx.get("folders") or {}).items():
        p = Path(k)
        out.append((p, [(p / n, int(s), float(m)) for n, s, m in v.get("files") or []], di.is_archive(k)))
    fresh = di.is_fresh(idx, cfg["max_hours"])
    value = (out, f"drawing index built {di.summary(idx)['built_at']}" + ("" if fresh else " (STALE)"))
    if stamp:
        _CACHE.update(stamp=stamp, value=value)
    return value


def folders_for(drawing: str, live: bool = True
                ) -> Tuple[List[FolderRow], str, Optional[Callable[[str], List[FileRow]]]]:
    """The folders one drawing's pack can come from, from the lookup database (made from the
    index on first use if needed), with the folder around each candidate GA RE-LISTED NOW, so a
    pack is never chosen from a stale listing; and a lookup for shared-library parts."""
    sys.path.insert(0, str(HERE))
    import drawing_index as di
    cfg = di.settings()
    db = di.db_path(cfg["path"])
    stale_rule = db.exists() and di.db_meta(db).get("did_rule") != di.DID_RULE
    if not db.exists() or stale_rule:
        idx = di.load(cfg["path"])
        if not idx:
            return [], f"no drawing index at {cfg['path']}; run src/drawing_index.py --build", None
        print(f"[pack] making the lookup database from {cfg['path']} "
              f"({'its drawing numbers were read by an older rule' if stale_rule else 'once'})",
              file=sys.stderr, flush=True)
        di.build_db(idx, db)
    rows = di.db_rows_for(db, drawing)
    meta = di.db_meta(db)
    time_ok = (datetime.now().timestamp() - meta["built_at"]) <= cfg["max_hours"] * 3600
    source = f"lookup database built {datetime.fromtimestamp(meta['built_at']).isoformat(timespec='minutes')}" + \
        ("" if time_ok else " (STALE)")
    if live:
        holders = [(folder, a) for folder, files, a in rows
                   if any(_same(drawing_id(f[0].name), drawing) for f in files)]
        current = [f for f, a in holders if not a] or [f for f, _a in holders]
        rank = _default_area_rank()
        first = min((rank(f) for f in current), default=0)
        own = sorted({f for f in current if rank(f) == first}, key=lambda p: len(p.parts))
        relisted = []
        t0 = time.time()
        for ga_folder in own:
            top = ga_folder.parent
            if any(top == r or r in top.parents for r in relisted):
                continue
            now_rows = di.live_rows(top, depth=6)
            if now_rows is None:
                continue
            rows = [r for r in rows if not (r[0] == top or top in r[0].parents)] + now_rows
            relisted.append(top)
        if relisted:
            source += f"; {len(relisted)} folder(s) around the GA re-listed now in {round(time.time() - t0, 1)} s"
    return rows, source, (lambda did: di.db_lookup(db, did))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drawing", required=True)
    ap.add_argument("--client", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-live", action="store_true", help="use the index's listing only; do not re-list the GA's folder")
    ap.add_argument("--store", action="store_true",
                    help="keep the pack in Live Enquiry\\<client>\\<drawing> (src/pack_store.py) when it may be priced")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(HERE))
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):                         # --json output stays pure JSON
        try:
            import config  # noqa: F401  (loads .env)
        except Exception:                                                # noqa: BLE001
            pass
        folders, source, lookup = folders_for(args.drawing, live=not args.no_live)
        m = resolve(args.drawing, folders, args.client, lookup=lookup)
        m["source"] = source
        if args.store and m["price_ok"]:
            import pack_store as ps
            kept = ps.store(m, args.client)
            m["stored"] = kept
            m["stored_files"] = ps.stored_files(kept, m)
    if args.json:
        print(json.dumps(m, indent=1))
        return 0 if m["price_ok"] else 2
    print(f"{m['drawing']}  {m['status'].upper()}  ({source}; {m.get('pdfs_read', 0)} drawing PDF(s) read)")
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
    if m.get("identity"):
        print(f"  GA identity {m['identity']}; drawings "
              f"{'complete' if m.get('complete') else ('NOT PROVED COMPLETE: the parts list was not read' if not m.get('references_read') and not m.get('missing') else 'INCOMPLETE')}"
              + (f"; parts list read from sheet(s) {', '.join(m['sheets_read'])}" if m.get("sheets_read") else "")
              + (f"; {len(m['bought_in_unmatched'])} bought-in item(s) to price"
                 if m.get("bought_in_unmatched") else ""))
    for x in m.get("assigned_by_text") or []:
        print(f"  by text {Path(x['path']).name} is {x['drawing']}")
    for x in m.get("unassigned_files") or []:
        print(f"  UNASSIGNED  {x['path']}  ({x['why']})")
    if m.get("other_drawings_in_folders"):
        _o = sorted({x['drawing'] for x in m['other_drawings_in_folders']})
        print(f"  other drawings in the pack's folders, not called for and not included: "
              f"{', '.join(_o[:12])}{' ...' if len(_o) > 12 else ''}")
    for sheet, called in sorted((m.get("sheet_references") or {}).items()):
        print(f"  sheet   {sheet} calls for {len(called)}: {', '.join(called[:10])}{' ...' if len(called) > 10 else ''}")
    for x in m["members"]:
        if len(x.get("parents") or []) > 1:
            print(f"  shared  {x['drawing']} is called for by {', '.join(x['parents'])}")
    for k in ("missing", "bought_in_unmatched", "unreferenced", "library", "conflicts", "assumptions"):
        if m.get(k):
            print(f"  {k}: " + "; ".join(m[k]))
    if m["question"]:
        print(f"  ASK: {m['question']}")
    if m.get("stored"):
        print(f"  kept: {m['stored']['state']} -> {m['stored']['folder']}")
    return 0 if m["price_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
