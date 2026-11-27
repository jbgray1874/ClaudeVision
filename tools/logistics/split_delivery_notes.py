"""Split a day's scanned delivery notes into one PDF per note, named for the note.

    python split_delivery_notes.py --source "K:\\Logistics\\Scans\\Inbox"
                                   --out    "K:\\Logistics\\Scans\\SplitScan"

James Gray, 21 September 2026: "We get a number of these each day and we want to have a
process that runs once a day and splits each delivery note out to a new folder
K:\\Logistics\\Scans\\SplitScan with a delivery note number as the file name and client name
if we can find it."

    30022230 Tesco.pdf
    30022337 Boots.pdf
    30022283 Marks & Spencer.pdf
    _Unsorted\\scan21092026 p1.pdf

── THE THREE THINGS THIS IS CAREFUL ABOUT ──────────────────────────────────────────────────

IT NEVER INVENTS A NAME. A page that is not one of SDI's delivery notes goes to _Unsorted
under the scan it came from and the page it was — one of the four files sent is a GB Lift
Trucks LOLER examination report, upside down, and a splitter that assumes every page is a
note would have filed somebody's forklift inspection as a delivery to Tesco. A misnamed file
is worse than an unfiled one because nobody opens a delivery note they have already filed.

IT DOES NOT TOUCH THE SOURCE. The scans stay where the scanner put them. What stops the same
note being split again tomorrow is a small record of what has already been done, keyed on the
source file's name, size and modified time — so a re-scanned file with the same name IS
processed again, and an untouched one is not.

IT IS SAFE TO RUN TWICE. Same inputs, same outputs, nothing duplicated and nothing
overwritten with a different note: a name that already exists and holds a DIFFERENT note gets
a numbered suffix rather than clobbering what is there.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_note_reader import REGIONS, group_into_notes, read_page  # noqa: E402

# The scanner's own resolution is whatever it is; this is what the PAGE is rendered at before
# OCR. 200 is enough for 8pt type and keeps a 40-page batch to a few minutes.
RENDER_DPI = 200
# Each region is enlarged before OCR. Tesseract is markedly better on larger glyphs and the
# crops are small, so this is cheap: it is most of the difference between 4 numbers out of 11
# and 11 out of 11.
REGION_SCALE = 2

UNSORTED = "_Unsorted"
LEDGER = ".splitscan-done.json"
LOGS = "_logs"
# The job's own notes, kept in the ledger beside the per-scan records: how far it has got.
META = "_meta"
# One run at a time: the service, the page's button and an old laptop task share one ledger.
LOCK = ".splitscan.lock"
# What the service last saw, rewritten every check - the answer to "is it running?".
STATUS = "service-status.txt"
# Where a job with no record of a complete run starts, unless --since / --from reach further.
FIRST_RUN_DAYS = 7
# More than this to read in one run is not a day's post or a missed fortnight - it is the
# back catalogue, or the scope is wrong. The run refuses and says so (--no-limit to override).
MAX_TO_READ = 100
# Each run re-checks a day before the point the last complete run reached. Costs a ledger
# lookup per scan; covers a clock that is a few minutes out, or a copy that lands late.
OVERLAP = 86400
# A lock not touched for this long belongs to a run that died (the machine went off).
LOCK_STALE = 30 * 60
# In service mode, a scan still being written is left for the next check, and a scan that
# failed is tried again hourly rather than OCR'd every few minutes.
SETTLE = 3 * 60
RETRY_AFTER = 60 * 60

# ── THE FOLDERS COME FROM CONFIG, AND THERE IS NO GUESS BEHIND THEM ─────────────────
#
# James Gray: "config needs to be in config files. not json files lying around and being
# copied manually around." So both folders are `SDI_SCAN_SOURCE_DIR` / `SDI_SCAN_SPLIT_DIR`
# in the project's one .env, read through the project's one config module.
#
# UNSET IS AN ANSWER AND A GUESS IS NOT. This file used to carry
# \\sdi-dc01\shareddata$\Logistics\Scans as a default, reasoned from two true facts: the
# estimating share IS \\sdi-dc01\shareddata$, and the drive in Explorer reads
# K:\Logistics\Scans. The conclusion was wrong, and the job CREATED that tree rather than
# refusing it — after which the folder existed, `Test-Path` answered True, and the diagnosis
# went to `Path.glob`, to enumeration and to permissions, because the last thing anybody
# suspects is a folder the code made for itself.
#
# AND A UNC PATH, NOT A DRIVE LETTER. K: is a mapping, and a mapping belongs to a logged-on
# session. A scheduled task, a Windows service and the backend each run without one — and an
# elevated shell is a different session again, which is why K: is in Explorer and absent from
# an Administrator prompt. Under a task, "K:\..." is not there at all: the job would create a
# folder of that name on the local disk, file the day into it, and exit 0.
def _configured(name: str) -> str:
    """One setting, read through the project's config so .env is the only place it lives."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        import config                                              # noqa: WPS433
        return str(getattr(config, name, "") or "").strip()
    except Exception:                                              # noqa: BLE001
        # Runnable with nothing else installed: the shell still answers.
        return os.getenv("SDI_" + name, "").strip()


DEFAULT_SOURCE = _configured("SCAN_SOURCE_DIR")
DEFAULT_OUT = _configured("SCAN_SPLIT_DIR")


def from_cutoff(text: str) -> Optional[float]:
    """`--from 2026-10-01` as a timestamp: local midnight at the start of that day."""
    if not text:
        return None
    return datetime.strptime(text.strip(), "%Y-%m-%d").timestamp()


def _where_settings_live() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        import config                                              # noqa: WPS433
        return config.dot_env_path()
    except Exception:                                              # noqa: BLE001
        return str(Path(__file__).resolve().parents[2] / ".env")


# ── OCR ─────────────────────────────────────────────────────────────────────────────

class NoOCR(RuntimeError):
    """Tesseract could not be run at all.

    ITS OWN TYPE BECAUSE IT IS NOT A BAD SCAN. One corrupt PDF must not cost the day, so
    `run()` catches per file and carries on — which turned a missing binary into 947
    identical error lines and an exit code of 0. A tool that is not installed is a fact about
    the machine, true before the first page is read and true after the last, and it stops the
    run rather than being reported 947 times.
    """


def find_tesseract(explicit: Optional[str] = None) -> Optional[str]:
    """Locate tesseract, or None. In order: an explicit path, config, PATH, install roots.

    THE INSTALLER DOES NOT PUT IT ON PATH. UB-Mannheim's package lands in
    `C:\\Program Files\\Tesseract-OCR` and leaves PATH alone, so `winget install` completes,
    reports success, and `tesseract` is still "not recognized" — and a PATH edit needs a new
    shell before it takes, which makes the same command work or fail depending on which
    window it is typed in. Looking in the usual places costs nothing and ends all of that.

    Same shape as `cad_inputs.find_converter` for the ODA converter, deliberately: two ways
    of finding an external tool is two places to fix when one of them stops working.
    """
    if explicit and Path(explicit).is_file():
        return str(explicit)
    configured = _configured("TESSERACT_PATH")
    if configured and Path(configured).is_file():
        return str(configured)
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return found
    for candidate in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                      r"C:\Users\%s\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
                      % os.getenv("USERNAME", ""),
                      "/usr/bin/tesseract", "/usr/local/bin/tesseract",
                      "/opt/homebrew/bin/tesseract"):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _tesseract(image_path: str, *, psm: str = "6", whitelist: str = "") -> str:
    exe = find_tesseract()
    if not exe:
        raise NoOCR("tesseract is not installed, or cannot be found")
    cmd = [exe, image_path, "-", "--psm", psm]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    try:
        # TESSERACT WRITES UTF-8; `text=True` ALONE DECODES IN THE LOCALE CODEPAGE. On the
        # logistics machine that is cp1252, which has no character at 0x9d — the last byte
        # of a curly quote — so the reader thread died with a traceback, the page's text was
        # lost, and three real delivery notes were filed as "not a delivery note". Named
        # encoding, and a byte it still cannot place becomes U+FFFD rather than nothing.
        done = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NoOCR(f"tesseract could not be run ({exe}): {exc}") from exc
    return done.stdout or ""


# Per-region OCR settings. The number is read with a digits-only charset, which is the single
# biggest accuracy win here — it cannot return a letter where a digit belongs.
_REGION_OCR = {
    "values": {"psm": "6", "whitelist": "0123456789/"},
    "invoice": {"psm": "6", "whitelist": ""},
    "footer": {"psm": "7", "whitelist": ""},
    "whole": {"psm": "4", "whitelist": ""},
}


def page_reader(page_image, tmp_dir: Path):
    """An `ocr(region)` for one rendered page, cached so each region is read once."""
    from PIL import Image                                          # noqa: WPS433

    cache: Dict[str, str] = {}

    def ocr(region: str) -> str:
        if region in cache:
            return cache[region]
        left, top, right, bottom = REGIONS[region]
        width, height = page_image.size
        box = (int(width * left), int(height * top),
               int(width * right), int(height * bottom))
        crop = page_image.crop(box)
        if REGION_SCALE != 1:
            crop = crop.resize((crop.width * REGION_SCALE, crop.height * REGION_SCALE),
                               Image.LANCZOS)
        path = tmp_dir / f"{region}.png"
        crop.save(path)
        settings = _REGION_OCR.get(region, {"psm": "6", "whitelist": ""})
        cache[region] = _tesseract(str(path), **settings)
        return cache[region]

    return ocr


def read_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """Read every page of one scan. Returns a list of `read_page` results.

    A PAGE THAT READS AS NOTHING IS TRIED UPSIDE DOWN. The forklift report in the sample is
    at 180 degrees, and a delivery note in the same tray would be too. Only pages that failed
    are rotated, so the cost falls on the pages that were going to be a problem anyway.
    """
    import pymupdf                                                  # noqa: WPS433
    from PIL import Image                                           # noqa: WPS433

    out: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        document = pymupdf.open(str(pdf_path))
        for page in document:
            pix = page.get_pixmap(dpi=RENDER_DPI)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            found = read_page(page_reader(image, tmp_dir))
            if not found["is_note"]:
                turned = read_page(page_reader(image.rotate(180, expand=True), tmp_dir))
                if turned["is_note"]:
                    turned["rotated"] = 180
                    found = turned
            out.append(found)
        document.close()
    return out


# ── naming ──────────────────────────────────────────────────────────────────────────

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text: Any) -> str:
    """A Windows-safe filename fragment. Trailing dots and spaces are illegal too."""
    out = _ILLEGAL.sub(" ", str(text or ""))
    out = " ".join(out.split())
    return out.rstrip(" .")


def note_filename(note: Dict[str, Any], fallback: str) -> str:
    """`30022230 Tesco.pdf`, or the number alone when no client could be read."""
    number = safe_name(note.get("number") or "")
    client = safe_name(note.get("client") or "")
    if number and client:
        return f"{number} {client}.pdf"
    if number:
        return f"{number}.pdf"
    return f"{safe_name(fallback)}.pdf"


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


_PDF_ID = re.compile(rb"/ID\s*\[[^\]]*\]")


def _same_pdf(a: bytes, b: bytes) -> bool:
    """The same pages, ignoring the file's /ID - which used to be new on every save.

    ── "IDENTICAL CONTENT" NEVER WAS ────────────────────────────────────────────────
    A page carved twice from the same scan came out with a different /ID each time, so the
    check below never found a match: a scan read a second time put "scan p3 (2).pdf" into
    _Unsorted beside the first. Notes with a number were safe (matched by number first);
    pages without one were not. New files are saved without a fresh ID, and files already on
    the share (which have one) are compared with it taken out."""
    return a == b or _PDF_ID.sub(b"", a) == _PDF_ID.sub(b"", b)


def _unique(target: Path, payload: bytes) -> Optional[Path]:
    """Where to write, or None when this exact note is already filed there.

    IDENTICAL CONTENT IS NOT A CLASH. Re-running the day is the ordinary case and must not
    produce "30022230 Tesco (2).pdf". A file of the same name holding something DIFFERENT is
    a real clash — two notes numbered the same, or a re-scan that read differently — and it
    gets a suffix rather than quietly replacing what is there.
    """
    if not target.exists():
        return target
    try:
        if _same_pdf(target.read_bytes(), payload):
            return None
    except OSError:
        pass
    for n in range(2, 100):
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        if not candidate.exists():
            return candidate
        try:
            if _same_pdf(candidate.read_bytes(), payload):
                return None
        except OSError:
            continue
    return target.with_name(f"{target.stem} ({_fingerprint(target)}){target.suffix}")


# ── the run ─────────────────────────────────────────────────────────────────────────

def split_pdf(pdf_path: Path, out_dir: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    """Split one scan. Returns what was written and what could not be identified."""
    import pymupdf                                                  # noqa: WPS433

    pages = read_pdf(pdf_path)
    notes, unsorted = group_into_notes(pages)
    written: List[Dict[str, Any]] = []
    source = pymupdf.open(str(pdf_path))

    def _carve(indexes, target: Path) -> Optional[Path]:
        out = pymupdf.open()
        for i in indexes:
            out.insert_pdf(source, from_page=i, to_page=i)
        payload = out.tobytes(no_new_id=True)          # the same page, the same bytes
        out.close()
        where = _unique(target, payload)
        if where is None:
            return None
        if not dry_run:
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_bytes(payload)
        return where

    for n, note in enumerate(notes, start=1):
        name = note_filename(note, f"{pdf_path.stem} note {n}")
        existing = already_filed(out_dir, note.get("number"))
        if existing is not None:
            written.append({
                "file": existing.name, "written": False, "path": str(existing),
                "number": note.get("number"), "client": note.get("client"),
                "account": note.get("account"), "pages": [i + 1 for i in note["pages"]],
                "already": True,
            })
            continue
        where = _carve(note["pages"], out_dir / name)
        written.append({
            "file": name, "written": bool(where), "path": str(where or ""),
            "number": note.get("number"), "client": note.get("client"),
            "account": note.get("account"), "pages": [i + 1 for i in note["pages"]],
            "already": False,
        })

    for index in unsorted:
        name = f"{safe_name(pdf_path.stem)} p{index + 1}.pdf"
        _carve([index], out_dir / UNSORTED / name)

    source.close()
    return {"source": pdf_path.name, "pages": len(pages),
            "notes": written, "unsorted": [i + 1 for i in unsorted]}


def _ledger_key(pdf: Path, source_dir: Path) -> str:
    try:
        return pdf.relative_to(source_dir).as_posix()
    except ValueError:
        return pdf.name


def _save_ledger(out_dir: Path, done: Dict[str, Any]) -> None:
    """Written after EVERY scan, not once at the end: the task has a two-hour limit, and a
    run stopped at 1h59 used to forget everything it had done and start again tomorrow."""
    tmp = out_dir / (LEDGER + ".tmp")
    tmp.write_text(json.dumps(done, indent=1), encoding="utf-8")
    os.replace(tmp, out_dir / LEDGER)


def _names_in(folder: Path) -> Optional[set]:
    """Every file name in the output folder, lower-cased, from ONE listing - rather than a
    round trip to the share for every note of every scan in scope. None if it can't be
    listed, and the caller then asks file by file."""
    try:
        return {n.lower() for n in os.listdir(folder)}
    except OSError:
        return None


def is_done(record: Any, mark: str, out_dir: Path, names: Optional[set] = None) -> bool:
    """Split already, unchanged since, and every note it produced still on the share.
    A scan whose last attempt FAILED is never done, however long ago that was."""
    if not isinstance(record, dict) or record.get("mark") != mark or record.get("failed"):
        return False
    files = record.get("files") or []
    if names is not None:
        return all(f.lower() in names for f in files)
    return all((out_dir / f).exists() for f in files)


def _ledger(out_dir: Path) -> Dict[str, Any]:
    try:
        data = json.loads((out_dir / LEDGER).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def already_filed(out_dir: Path, number: Any) -> Optional[Path]:
    """The file this note is already in, or None.

    ── THE OUTPUT FOLDER IS THE LEDGER ─────────────────────────────────────────────
    #
    James Gray, 21 September 2026: "We can run as often as we want but how do we make sure it
    doesn't re generate the same individual invoices again over and over?"

    ASKED OF THE FOLDER, NOT OF A RECORD ABOUT THE FOLDER. A note is already done when a file
    for it is sitting there — which is the same question a person answers by looking, and it
    cannot drift from what is actually on the share.

    A separate record of "what I have done" can, and every way it goes wrong is silent:
    somebody deletes a file and it never comes back; somebody restores the folder from backup
    and everything is filed twice; the record is on a share that was offline at 06:30. The
    folder is the one thing that cannot be wrong about its own contents.

    Matched on the NUMBER, not the whole filename, so a note re-scanned on a day when the
    client line reads differently is still recognised as the same note.
    """
    number = safe_name(number)
    if not number:
        return None
    for candidate in (out_dir.glob(f"{number}.pdf"), out_dir.glob(f"{number} *.pdf")):
        for found in candidate:
            return found
    return None


def _resolved(path: Path) -> str:
    """A comparable absolute form, falling back to the path as given.

    `Path.resolve()` goes to the filesystem, and on a UNC share it can fail where the path is
    perfectly good. Falling back keeps the folder-exclusion check working instead of throwing
    inside a listing.
    """
    try:
        return str(path.resolve()).rstrip("\\/").lower()
    except OSError:
        return str(path).rstrip("\\/").lower()


def folder_listing(folder: Path, *, recurse: bool = False,
                   skip: Optional[set] = None) -> List[Path]:
    """Every FILE in the folder, listed once, with the listing error surfaced if there is one.

    ── LISTED, NOT GLOBBED ─────────────────────────────────────────────────────────

    `source_dir.glob("*.pdf")` returns nothing on a folder that cannot be enumerated, nothing
    on a folder of subfolders, and nothing on a folder that does not exist — three quite
    different situations that all read as "the folder is empty" from the caller's side. The
    first live run against the real share printed `0 PDF(s) in the folder` for a folder that
    Explorer shows 948 items in.

    `iterdir` raises when it cannot list, which is what we want: a permissions problem should
    say so rather than be reported as an empty day's post.

    It also settles the case question for good. "*.pdf" and "*.PDF" are the SAME files on
    Windows and separate patterns on Linux, so globbing both and adding the lists reads every
    scan twice on the machine this actually runs on. One listing, one suffix comparison, one
    entry per file, on both.
    """
    skip = {s.lower() for s in (skip or set())}
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise RuntimeError(f"cannot list {folder}: {exc}") from exc

    files: List[Path] = []
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:                                              # a dead reparse point
            continue
        if not is_dir:
            files.append(entry)
            continue
        if recurse and entry.name.lower() not in skip:
            files.extend(folder_listing(entry, recurse=True, skip=skip))
    return files


def folder_census(folder: Path, *, recurse: bool = False) -> Dict[str, Any]:
    """What is in the folder — for the run that found no scans and has to say why.

    A day with no post, a share nobody can list, and a folder of date-named subfolders are
    the same line of output unless the job says what it saw.
    """
    census: Dict[str, Any] = {"files": 0, "pdfs": 0, "folders": 0,
                              "suffixes": {}, "sample": [], "error": None}
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        census["error"] = f"{type(exc).__name__}: {exc}"
        return census
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            census["folders"] += 1
        else:
            census["files"] += 1
            suffix = entry.suffix.lower() or "(none)"
            census["suffixes"][suffix] = census["suffixes"].get(suffix, 0) + 1
            if suffix == ".pdf":
                census["pdfs"] += 1
        if len(census["sample"]) < 5:
            census["sample"].append(entry.name + ("\\" if is_dir else ""))
    return census


def scans_to_read(source_dir: Path, out_dir: Path, *, since_days: int = 0,
                  recurse: bool = False) -> List[Path]:
    """The PDFs in the scan folder that are this run's business.

    ── THE OUTPUT FOLDER LIVES INSIDE THE INPUT FOLDER ──────────────────────────────

    K:\\Logistics\\Scans\\SplitScan is a child of K:\\Logistics\\Scans, so everything this
    job writes lands inside the folder it reads. Nothing but this exclusion stands between
    the job and eating its own output for ever — every note re-split into a note of one page,
    named after itself, on every run. It is excluded by name as well as by path, so the guard
    survives `--recurse`.
    """
    # ── ONE ROUND TRIP PER FOLDER, NOT PER FILE ──────────────────────────────────────
    #
    # This used to `resolve()` every file: 947 calls to the server per listing, and the
    # front door listed three times over — some 3,000 round trips before a page was read.
    # Idle share, a second or two; busy share, a run that prints its two paths and sits
    # there. Nothing in a listing needs the file resolved: the same file cannot be listed
    # twice by one `iterdir`, so the case-fold on the path as given is the dedupe, and the
    # output-folder check is on the PARENT, of which a non-recursive run has exactly one.
    seen, out, parents = set(), [], {}
    resolved_out = _resolved(out_dir)
    for pdf in folder_listing(source_dir, recurse=recurse,
                              skip={out_dir.name, UNSORTED}):
        if pdf.suffix.lower() != ".pdf":
            continue
        key = str(pdf).lower()
        if key in seen:
            continue
        seen.add(key)
        parent = str(pdf.parent)
        if parent not in parents:
            parents[parent] = _resolved(pdf.parent)
        if parents[parent] == resolved_out:
            continue
        out.append(pdf)
    return recent(sorted(out, key=lambda p: p.name.lower()), since_days=since_days)


def recent(pdfs: List[Path], *, since_days: int = 0,
           from_ts: Optional[float] = None) -> List[Path]:
    """The scans in scope: modified on or after the start date when there is one, else
    inside the rolling window, else every one of them.

    ── A ROLLING WINDOW LOSES SCANS; A START DATE DOES NOT ─────────────────────────

    BARDON DELIVERY NOTES 7-10-2026 was saved at 07:18 on a Thursday and never split.
    The task ran `--since 1`, a window of 24 hours counted back from WHEN IT RAN, on a
    laptop where it runs at logon - and Friday's run started after 07:18, so the file was
    already too old for it and had been too new for Thursday's. Nothing failed and
    nothing was said. With a start date, a scan stays in scope until the ledger records it
    done, however late, seldom or interrupted the runs are.
    """
    if from_ts is not None:
        cutoff = from_ts
    elif since_days and since_days > 0:
        cutoff = time.time() - (since_days * 86400)
    else:
        return list(pdfs)
    kept = []
    for pdf in pdfs:
        try:
            if pdf.stat().st_mtime >= cutoff:
                kept.append(pdf)
        except OSError:
            continue
    return kept


def _arrived(st: os.stat_result) -> float:
    """When a scan reached the folder: when the scanner last wrote it.

    ── NOT THE CREATED TIME ────────────────────────────────────────────────────────
    This briefly took the later of modified and (Windows) created, so that a scan copied in
    with an old date would still count. On the real share it made the WHOLE back catalogue
    "new": a folder copied or migrated to another location gets a fresh created time on
    every file, so 995 scans going back to 2024 all read as arriving recently, and the first
    run set about OCR-ing every one of them (13 October 2026). The modified time is what the
    scanner sets and what a copy keeps."""
    return st.st_mtime


def arrival(path: Path) -> float:
    return _arrived(path.stat())


def _record(ledger: Dict[str, Any], pdf: Path, source_dir: Path) -> Any:
    return ledger.get(_ledger_key(pdf, source_dir)) or ledger.get(pdf.name)


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def scope_start(ledger: Dict[str, Any], every: List[Path], source_dir: Path,
                asked: Optional[float] = None,
                asked_as: str = "the date asked for") -> Tuple[float, str]:
    """Where this run starts looking: (timestamp, why), WORKED OUT FROM THE JOB'S OWN RECORD.

    ── NOTHING TO SET, AND NOTHING THAT CAN BE SET WRONG ─────────────────────────────

    James Gray, 13 October 2026: "I don't have time to manually do re runs because of a bug /
    mis timing" - and of a start date in .env: "looks like a hard coded hack". It was. So:

      * After a run that dealt with every scan in scope, the ledger records when that run
        STARTED. The next run looks at everything that arrived since then, less a day. A
        machine off for a fortnight just has a longer next run; nothing ages out.
      * With no such record yet (a first run), the last FIRST_RUN_DAYS days - or further back
        if --since / --from asks. NOT "from the earliest scan the ledger knows": that reached
        the whole back catalogue on the real share (see `_arrived`), and a first run that
        might OCR two years of post is not a safe default.

    A scan that FAILED is in scope whatever its age, until it splits (see `in_scope`).

    `asked` (--since / --from) can only move the start EARLIER - to take on older scans by
    hand. It can never narrow a run: that is how BARDON DELIVERY NOTES 7-10-2026 was missed.
    """
    meta = ledger.get(META) if isinstance(ledger.get(META), dict) else {}
    covered = meta.get("covered_to")
    if isinstance(covered, (int, float)):
        start, why = covered - OVERLAP, f"the last complete run, {_when(covered)}, less a day"
    else:
        start = time.time() - FIRST_RUN_DAYS * 86400
        why = f"no complete run on record yet, so the last {FIRST_RUN_DAYS} days"
    if asked is not None and asked < start:
        return asked, f"{asked_as}, further back than the job's own record"
    return start, why


def in_scope(every: List[Path], start: float, ledger: Dict[str, Any], source_dir: Path, *,
             settle: float = 0) -> Tuple[List[Path], List[Tuple[Path, float]]]:
    """(scans to deal with, scans left for next time because they are still being written).

    In scope: arrived at or after `start`, or recorded as failing - however old."""
    now = time.time()
    chosen: List[Path] = []
    waiting: List[Tuple[Path, float]] = []
    for pdf in every:
        record = _record(ledger, pdf, source_dir)
        failing = isinstance(record, dict) and record.get("failed")
        try:
            st = pdf.stat()
        except OSError:
            continue
        came = _arrived(st)
        if came < start and not failing:
            continue
        if settle and now - st.st_mtime < settle:
            waiting.append((pdf, came))
            continue
        chosen.append(pdf)
    return chosen, waiting


class Busy(RuntimeError):
    """Another run holds the lock."""


@contextlib.contextmanager
def run_lock(out_dir: Path):
    """One run at a time over one ledger.

    The service checks every few minutes, the page has a button, and the laptop's old task
    may still fire: two runs at once would OCR the same scan twice and each write the ledger
    over the other. The lock is a file in the output folder, created only if absent (atomic on
    the share), refreshed before every scan, and treated as abandoned once it has not been
    touched for LOCK_STALE - so a run killed with the machine does not block the next for
    ever."""
    path = out_dir / LOCK
    me = f"{socket.gethostname()} (pid {os.getpid()}), started {datetime.now():%Y-%m-%d %H:%M}"
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
                holder = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue                                           # released meanwhile
            if age < LOCK_STALE:
                raise Busy(holder or "another run")
            try:
                path.unlink()                                      # abandoned
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(me)
        try:
            yield path
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        return
    raise Busy("another run")


def _beat(out_dir: Path) -> None:
    try:
        os.utime(out_dir / LOCK)
    except OSError:
        pass


def prepare_out(out_dir: Path) -> None:
    """Make the output folder — and never the tree above it.

    ── THE JOB MANUFACTURED ITS OWN SOURCE FOLDER ───────────────────────────────────

    `out_dir.mkdir(parents=True)` on `\\\\sdi-dc01\\shareddata$\\Logistics\\Scans\\SplitScan`
    created `Logistics`, then `Scans`, then `SplitScan`, on a share where none of them
    existed — because the guessed UNC was not what `K:` points at. The next run then found
    the source folder present (it had just been made), empty, and reported a quiet day.

    `Test-Path` said True. `source.exists()` passed. The front-door guard added for exactly
    this could not fire, because **the job had already answered its own question**.

    So: this creates the output folder, and refuses when the folder above it is absent. A
    path with a typo in it is then refused rather than built, which is the whole point of
    checking a path at all.
    """
    if out_dir.is_dir():
        return
    if not out_dir.parent.is_dir():
        raise RuntimeError(
            f"the folder above the output folder does not exist: {out_dir.parent} — "
            "refusing to create it, because a wrong path would then be built rather "
            "than refused")
    out_dir.mkdir(exist_ok=True)


def run(source_dir: Path, out_dir: Path, *, dry_run: bool = False,
        force: bool = False, since_days: int = 0, recurse: bool = False,
        pdfs: Optional[List[Path]] = None, progress=None,
        from_ts: Optional[float] = None, covers: Optional[float] = None,
        retry_after: float = 0) -> Dict[str, Any]:
    """One day's run over a folder of scans.

    `pdfs` is the listing when the caller already has one — the front door lists the folder
    to say what it found, and listing a share of 947 files again to read the same answer is
    the sort of thing that is free on a laptop and minutes on a busy server.

    `progress(text)` is called before each scan is read. OCR is a minute or two for a day's
    post and silent while it works, and a run that prints its count line and then nothing
    for ninety seconds is indistinguishable from one that has hung — which is what the
    person watching it concluded, twice.

    `covers`: everything that arrived before this moment is dealt with once the run gets
    through `pdfs` - recorded in the ledger as how far the job has got (see `scope_start`).
    Defaults to when the run started. Not recorded if any scan could not even be looked at.

    `retry_after` (seconds): a scan whose last attempt failed is left alone until then.
    """
    started = time.time()
    prepare_out(out_dir)
    done = _ledger(out_dir)
    names = _names_in(out_dir)
    results, skipped = [], []
    if pdfs is None:
        every = scans_to_read(source_dir, out_dir, recurse=recurse)
        asked = from_ts if from_ts is not None else (
            started - since_days * 86400 if since_days and since_days > 0 else None)
        start, _ = scope_start(done, every, source_dir, asked)
        pdfs, _waiting = in_scope(every, start, done, source_dir)
    complete = True
    for n, pdf in enumerate(pdfs, start=1):
        # A scan caught half-written by the scanner is no loss: when it finishes, its size
        # and time change, so does this mark, and the next run reads it again in full.
        try:
            mark = _fingerprint(pdf)
        except OSError as exc:
            results.append({"source": pdf.name, "error": f"{type(exc).__name__}: {exc}"})
            complete = False
            continue
        # Keyed on the path within the scan folder, not the bare name: with --recurse two
        # date folders can each hold a "scan001.pdf" and one would otherwise mask the other.
        # Old ledgers are keyed on the name alone, so that is still honoured.
        key = _ledger_key(pdf, source_dir)
        record = done.get(key) or done.get(pdf.name) or {}
        # ── SKIPPING IS A SPEED DECISION, AND IT CHECKS ITS OWN WORK ────────────────
        #
        # Re-OCRing a forty-page batch that has not changed is minutes of nothing, so a scan
        # whose fingerprint matches is skipped — but ONLY while every note it produced is
        # still on the share. Delete one and the next run puts it back, because the claim
        # "I did this already" is verified against the folder rather than believed.
        if not force and is_done(record, mark, out_dir, names):
            skipped.append(pdf.name)
            continue
        if (retry_after and isinstance(record, dict) and record.get("failed")
                and record.get("mark") == mark
                and time.time() - float(record.get("last_failed_ts") or 0) < retry_after):
            continue                                   # failing; its next attempt is due later
        if progress:
            progress(f"  reading {pdf.name} ({n} of {len(pdfs)}) ...")
        _beat(out_dir)
        try:
            result = split_pdf(pdf, out_dir, dry_run=dry_run)
            results.append(result)
        except NoOCR:
            # NOT A BAD SCAN — A MACHINE WITH NO OCR ON IT. Catching this per file turned a
            # missing binary into 947 identical error lines and an exit code of 0. It is
            # true before the first page and true after the last, so it stops the run.
            raise
        except Exception as exc:                                     # noqa: BLE001
            # ONE BAD SCAN DOES NOT COST THE DAY. A corrupt or password-protected PDF is
            # reported and the rest of the folder is still split.
            #
            # AND IT IS NOT FORGOTTEN. It is recorded as failing - never as done - so every
            # run tries it again and says so, until it splits or somebody deals with it.
            failed = (record.get("failed", 0) if isinstance(record, dict)
                      and record.get("mark") == mark else 0) + 1
            first = (record.get("first_failed") if isinstance(record, dict)
                     and record.get("failed") else None) or datetime.now().isoformat(timespec="minutes")
            error = f"{type(exc).__name__}: {exc}"
            results.append({"source": pdf.name, "error": error, "failed": failed,
                            "first_failed": first})
            if not dry_run:
                done[key] = {"mark": mark, "failed": failed, "error": error[:300],
                             "first_failed": first, "last_failed_ts": time.time()}
                _save_ledger(out_dir, done)
            continue
        if not dry_run:
            done[key] = {"mark": mark,
                         "files": [n["file"] for n in result["notes"] if n["file"]],
                         "when": datetime.now().isoformat(timespec="minutes")}
            _save_ledger(out_dir, done)
            if names is not None:
                names.update(n["file"].lower() for n in result["notes"] if n["file"])
    if not dry_run:
        if complete:
            reached = started if covers is None else covers
            meta = done.get(META) if isinstance(done.get(META), dict) else {}
            done[META] = {**meta, "covered_to": reached, "covered_to_text": _when(reached)}
        _save_ledger(out_dir, done)
    return {"when": datetime.now().isoformat(timespec="seconds"),
            "source": str(source_dir), "out": str(out_dir),
            "results": results, "skipped": skipped}


def _how_to_find_the_share(path: Path) -> None:
    """How to get the real UNC name of a drive letter, and why the obvious answers lie.

    `net use` lists nothing for a drive mapped by Group Policy or a logon script, which is
    how most of them are made — so "no entries in the list" does not mean the drive is not
    mapped. An elevated shell is a different logon session and cannot see the mapping at
    all. Both are easy to read as "the drive is not really there", and it is.
    """
    text = str(path)
    if re.match(r"^[A-Za-z]:", text):
        letter = text[0].upper()
        print("     That is a mapped drive. If this is an elevated (Administrator) shell,")
        print("     the drive belongs to your ordinary logon session and is not visible")
        print("     here — the same reason a scheduled task cannot see it.")
    else:
        letter = "K"
        print("     If this UNC path was a guess, it is the wrong one. Get the real name")
        print("     from the drive letter itself, in a NORMAL (not Administrator) shell:")
    print(f"       (Get-PSDrive {letter}).DisplayRoot")
    print(f"       Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='{letter}:'\" "
          "| Select-Object ProviderName")
    print("     `net use` shows nothing for a drive mapped by Group Policy or a logon")
    print("     script, so an empty list there does not mean the drive is not mapped.")


class _Tee(io.TextIOBase):
    """Everything printed goes to the screen (or the task's nowhere) AND into the day's log."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
            except Exception:                                      # noqa: BLE001
                pass
        return len(text)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:                                      # noqa: BLE001
                pass


def _write_log(out: Optional[str], text: str, code: int) -> None:
    """THE DAILY RUN USED TO SAY NOTHING ANYWHERE. A scheduled task's output goes nowhere,
    so "why was this scan not split?" had no answer short of re-running it. Each run now
    appends what it said to SplitScan\\_logs\\splitscan-YYYY-MM-DD.log."""
    if not out or not Path(out).is_dir():
        return
    try:
        logs = Path(out) / LOGS
        logs.mkdir(exist_ok=True)
        stamp = datetime.now()
        with open(logs / f"splitscan-{stamp:%Y-%m-%d}.log", "a", encoding="utf-8") as f:
            f.write(f"==== {stamp:%Y-%m-%d %H:%M:%S}  exit {code}  {' '.join(sys.argv[1:])}\n")
            f.write(text if text.endswith("\n") else text + "\n")
    except OSError as exc:
        print(f"  (could not write the log: {exc})", file=sys.stderr)


def main() -> int:
    """Runs the job and keeps a copy of everything it says in the day's log."""
    a = _args()
    if a.watch:
        return watch(a)
    code, _ = _logged(a)
    return code


def _logged(a, *, keep=None) -> Tuple[int, str]:
    """One pass, with what it said kept in the day's log - always, or when `keep(text)`."""
    captured, real = io.StringIO(), sys.stdout
    sys.stdout = _Tee(real, captured)
    code = 2
    try:
        code = _main(a)
    finally:
        sys.stdout = real
        text = captured.getvalue()
        if keep is None or keep(text):
            _write_log(a.out, text, code)
    return code, text


def _write_status(out: str, text: str) -> None:
    if not out or not Path(out).is_dir():
        return
    try:
        logs = Path(out) / LOGS
        logs.mkdir(exist_ok=True)
        tmp = logs / (STATUS + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, logs / STATUS)
    except OSError:
        pass


def watch(a) -> int:
    """THE SERVICE: check the scan folder every `--watch` minutes, for ever.

    James Gray, 13 October 2026: "can we have this running on the server instead? then it's
    always up as a windows service." A daily task on a laptop runs when the laptop is on and
    somebody is logged on; this runs on SDI-App01 under NSSM, restarts with the machine, and
    files a scan a few minutes after it lands.

    A quiet check (nothing new) is not written to the day's log - 288 of them a day would
    bury the ones that matter - but every check rewrites `_logs\\service-status.txt`, so
    "is it running?" is answered by the time on that file. A check that read something, or
    has something to say ("!!"), goes in the day's log as before. A problem that persists
    (the share down overnight) is logged once an hour, not every check.

    Nothing short of the service being stopped ends this: a missing share, a missing
    tesseract or a crash in one check is said, and the next check tries again.
    """
    every = max(1.0, float(a.watch)) * 60
    print(f"  splitscan service: checking every {a.watch:g} minute(s); "
          f"source {a.source}, out {a.out}", flush=True)
    last_logged, last_logged_at = "", 0.0
    while True:
        began = datetime.now()
        # Said BEFORE the check as well as after: a check that is filing a backlog can take
        # a while, and "is it running?" should not wait for it to finish.
        _write_status(a.out, f"Checking now: started {began:%Y-%m-%d %H:%M:%S} on "
                             f"{socket.gethostname()}\n")
        try:
            code, text = _logged(a, keep=lambda s: False)
        except KeyboardInterrupt:
            raise
        except Exception as exc:                                   # noqa: BLE001
            code, text = 2, f"  !! the check failed: {type(exc).__name__}: {exc}\n"
        said = [line for line in text.splitlines() if line.strip()]
        worth = any("reading " in line or "!!" in line or "written" in line for line in said)
        trouble = "\n".join(line for line in said if "!!" in line)
        if worth and (trouble != last_logged or time.time() - last_logged_at > 3600
                      or any("reading " in line for line in said)):
            _write_log(a.out, text, code)
            last_logged, last_logged_at = trouble, time.time()
        nxt = began.timestamp() + every
        _write_status(a.out, (
            f"Last check: {began:%Y-%m-%d %H:%M:%S} on {socket.gethostname()}"
            f" (exit {code})\nNext check: about {_when(nxt)}\n\n" + "\n".join(said[-25:])
            + "\n"))
        time.sleep(max(5.0, nxt - time.time()))


def _args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help="Folder the scanner writes into")
    ap.add_argument("--since", type=int, default=0, metavar="DAYS",
                    help="Also take on scans from the last DAYS days. The job keeps its own "
                         "record of how far it has got, so this is only needed to reach "
                         "further back; it can never make a run look at less.")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="Folder to write one PDF per delivery note into")
    ap.add_argument("--from", dest="from_date", default="", metavar="YYYY-MM-DD",
                    help="Also take on scans from this date on (by hand, once). Like "
                         "--since, it can only reach further back.")
    ap.add_argument("--no-limit", action="store_true",
                    help=f"Read however many scans are in scope. Without it a run with more "
                         f"than {MAX_TO_READ} to read refuses: that is the back catalogue, "
                         "or a scope that is wrong, and either is a decision for a person.")
    ap.add_argument("--watch", type=float, default=0, metavar="MINUTES",
                    help="Run as a service: check every MINUTES minutes until stopped.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read and report, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="Re-split scans this has already done")
    ap.add_argument("--recurse", action="store_true",
                    help="Also read scans in subfolders of the source folder")
    return ap.parse_args(argv)


def _main(a=None) -> int:
    if a is None:
        a = _args()
    try:
        from_ts = from_cutoff(a.from_date)
    except ValueError:
        print(f"  !! --from must be a date written YYYY-MM-DD, not {a.from_date!r}")
        return 2

    # ── NOBODY HAS SAID WHERE THE SCANS ARE ─────────────────────────────────────────
    #
    # This is what a guessed default used to hide. "I do not know" is a better answer than
    # a plausible folder, because the plausible folder gets created and then believed.
    for flag, setting, value in (("--source", "SDI_SCAN_SOURCE_DIR", a.source),
                                 ("--out", "SDI_SCAN_SPLIT_DIR", a.out)):
        if value:
            continue
        print(f"  !! no {flag} folder, and {setting} is not set.")
        print(f"     Put it in {_where_settings_live()} as")
        print(f"       {setting}=\\\\server\\share\\Logistics\\Scans"
              + ("\\SplitScan" if flag == "--out" else ""))
        print("     as a UNC path, not a drive letter: a scheduled task and the backend")
        print("     each run without a logon session, so a mapped drive is not there for")
        print("     them — and an elevated shell cannot see one either.")
        _how_to_find_the_share(Path("K:"))
        return 2

    source, out = Path(a.source), Path(a.out)

    # ── SAY WHERE YOU LOOKED, AND REFUSE IF IT IS NOT THERE ─────────────────────────
    #
    # The first live run printed "0 delivery note(s)" and exited 0. Nothing was wrong with
    # the reading — nothing had been READ, because `Path.glob` on a folder that does not
    # exist returns no files and no error. This is the exact failure this file has comments
    # about elsewhere and did not guard at its own front door: a job that runs, reports
    # success and does nothing.
    #
    # A share can be missing for ordinary reasons — a typo, a VPN down, a scheduled task with
    # no drive mapping, permissions. All of them look identical from inside the loop, and all
    # of them are obvious the moment the path is printed.
    print(f"  source: {source}")
    print(f"  out   : {out}")
    if not source.exists():
        print("  !! that folder does not exist, or this session cannot reach it.")
        _how_to_find_the_share(source)
        # ── A MAPPED DRIVE DOES NOT CROSS THE ELEVATION BOUNDARY ────────────────────
        #
        # An elevated shell is a DIFFERENT LOGON SESSION from the desktop, and a mapped
        # drive belongs to the session that mapped it. So `K:` is there in Explorer, there
        # in an ordinary PowerShell, and simply absent in "Administrator: Windows
        # PowerShell" — where this reports a folder that plainly exists as missing.
        #
        # Exactly the same reason a scheduled task cannot see it, which is why the default
        # is a UNC path. Said here because the symptom looks like a typo and is not.
        return 2
    if not source.is_dir():
        print(f"  !! that is a file, not a folder.")
        return 2

    # ── AND REFUSE TO BUILD THE PATH YOU WERE ASKED TO CHECK ────────────────────────
    #
    # This is what went wrong last time: the output folder was made with its parents, so a
    # guessed UNC that pointed at nothing became a real, empty folder tree on the share —
    # and the next run found its source present and reported a quiet day. See `prepare_out`.
    if not out.is_dir() and not out.parent.is_dir():
        print(f"  !! the folder above the output folder does not exist: {out.parent}")
        print("     Refusing to create it. A path with a typo in it would otherwise be")
        print("     built rather than refused, and the next run would find it and report")
        print("     an empty day's post.")
        _how_to_find_the_share(out)
        return 2

    try:
        # Listed ONCE. What is in scope is a filter on the listing, not a second listing.
        every = scans_to_read(source, out, recurse=a.recurse)
    except RuntimeError as exc:
        # The folder is there and cannot be listed — a permissions problem, or a share that
        # answers Test-Path and refuses enumeration. Said out loud, because the alternative
        # is reporting somebody's day of post as an empty folder.
        print(f"  !! {exc}")
        return 2

    # ── WHAT IS IN SCOPE COMES FROM THE JOB'S OWN RECORD, NOT FROM THE CLOCK ─────────
    #
    # See `scope_start`. --since / --from can only reach further back.
    started = time.time()
    ledger = _ledger(out) if out.is_dir() else {}
    asked = from_ts if from_ts is not None else (
        started - a.since * 86400 if a.since and a.since > 0 else None)
    asked_as = (f"from {a.from_date}, as asked" if from_ts is not None else
                f"the last {a.since} day(s), as asked")
    start, why = scope_start(ledger, every, source, asked, asked_as)
    chosen, waiting = in_scope(every, start, ledger, source,
                               settle=SETTLE if a.watch else 0)
    # Everything that arrived before the earliest scan still being written is dealt with.
    covers = min([started] + [came for _, came in waiting])

    # How many of those are already split, from the ledger and ONE listing of the output
    # folder - so "nothing new" and "nothing in scope" are different sentences.
    names = _names_in(out) if out.is_dir() else None
    already = 0
    for pdf in chosen:
        try:
            key = _ledger_key(pdf, source)
            if is_done(ledger.get(key) or ledger.get(pdf.name), _fingerprint(pdf), out, names):
                already += 1
        except OSError:
            pass
    print(f"  {len(every)} PDF(s) in the folder, {len(chosen)} in scope (arrived since "
          f"{_when(start)}: {why}; or still failing)"
          + (" — nothing to do" if not chosen else
             f": {already} already split, {len(chosen) - already} to read"))
    if waiting:
        print(f"  {len(waiting)} still being written, left for the next check: "
              + ", ".join(p.name for p, _ in waiting))

    # ── A FLOOD IS A DECISION, NOT A RUN ─────────────────────────────────────────────
    #
    # 13 October 2026: a scope bug put all 995 scans in the folder in scope, and the run set
    # about OCR-ing two years of post into SplitScan. Nothing stopped it but a person reading
    # the console. A day's post is a handful; a missed fortnight is a few dozen.
    to_read = len(chosen) - already
    if to_read > MAX_TO_READ and not a.no_limit and not a.dry_run:
        print(f"  !! {to_read} scans to read is more than {MAX_TO_READ}: that is the back "
              "catalogue, or a scope that is wrong. Nothing was read.")
        print("     Check the line above. To file them anyway, run once by hand with "
              "--no-limit.")
        return 2

    # ── NO PDFs IS A FINDING, NOT A RESULT ──────────────────────────────────────────
    #
    # The real share reported "0 PDF(s) in the folder" for a folder Explorer shows 948 items
    # in. There is no way to tell from that line whether the day was quiet, the scans are one
    # level down in date folders, or the listing came back empty — so say which.
    if not every:
        census = folder_census(source, recurse=a.recurse)
        if census["error"]:
            print(f"     the folder could not be listed: {census['error']}")
        elif not census["files"] and census["folders"] == 1 and out.parent == source:
            # THE SHARE THIS JOB BUILT FOR ITSELF. An empty scan folder whose only content
            # is our own output folder is not a quiet day — it is a path that was created
            # rather than found, and the scanner has never written a thing into it.
            print(f"     — and that folder is {out.name}, this job's own output folder.")
            print("     An empty scan folder holding nothing but our own output is a path")
            print("     that was CREATED rather than found. The scanner has never written")
            print("     here. This is not the share you are looking at in Explorer.")
            _how_to_find_the_share(source)
        elif not census["files"] and not census["folders"]:
            print("     the folder listed as completely empty.")
        else:
            kinds = ", ".join(f"{n} {s}" for s, n in
                              sorted(census["suffixes"].items(), key=lambda kv: -kv[1])[:6])
            print(f"     it holds {census['files']} file(s) and "
                  f"{census['folders']} folder(s)" + (f": {kinds}" if kinds else ""))
            if census["sample"]:
                print(f"     first few: {', '.join(census['sample'])}")
            if census["folders"] and not a.recurse:
                print("     the scans may be in subfolders — try again with --recurse")

    # ── CHECKED BEFORE A SINGLE PAGE IS RENDERED ────────────────────────────────────
    #
    # The scans have no text layer at all, so without OCR there is nothing to do — and
    # finding that out per file produced one error line per scan and an exit code of 0.
    if chosen and not find_tesseract():
        print("  !! tesseract is not installed on this machine, or cannot be found.")
        print("     The scans are photographs of paper with no text layer, so nothing can")
        print("     be read without it. Install it:")
        print("       winget install UB-Mannheim.TesseractOCR")
        print("     Then open a NEW shell: the installer adds it to PATH, and a PATH change")
        print("     does not reach a window that was already open — which makes the same")
        print("     command work or fail depending on which one you type it in.")
        print("     It is also looked for in the usual install folders, so a PATH that was")
        print("     never updated is not fatal. If it is somewhere else, put it in")
        print(f"     {_where_settings_live()} as")
        print(r"       SDI_TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe")
        return 2

    try:
        # A dry run writes nothing, so it does not need the lock and does not hold up a real one.
        guard = contextlib.nullcontext() if a.dry_run else run_lock(out)
        with guard:
            report = run(source, out, dry_run=a.dry_run, force=a.force, recurse=a.recurse,
                         pdfs=chosen, covers=covers,
                         retry_after=RETRY_AFTER if a.watch else 0,
                         progress=lambda text: print(text, flush=True))
    except Busy as exc:
        # Not a failure: somebody else's run is doing this work right now.
        print(f"  another run is already splitting ({exc}); this one did nothing and the "
              "other will file what is in scope")
        return 0
    except NoOCR as exc:
        # Reachable if it vanishes mid-run (an update, a share going away). Once, not 947
        # times, and not with an exit code that says the day went fine.
        print(f"  !! {exc}")
        return 2
    notes = unsorted = 0
    for result in report["results"]:
        if result.get("error"):
            print(f"  !! {result['source']}: {result['error']}")
            continue
        for note in result["notes"]:
            notes += 1
            where = "written" if note["written"] else "already filed"
            if note.get("already"):
                where = f"already filed as {note['file']}"
            print(f"  {note['file']}  ({where}, page(s) "
                  f"{', '.join(str(p) for p in note['pages'])} of {result['source']})")
        for page in result["unsorted"]:
            unsorted += 1
            print(f"  {UNSORTED}: {result['source']} page {page} — not a delivery note")
    if report["skipped"]:
        print(f"  {len(report['skipped'])} scan(s) already done, skipped")
    failing = [r for r in report["results"] if r.get("error")]
    if failing:
        print(f"  !! NEEDS ATTENTION: {len(failing)} scan(s) could not be split. They stay in "
              "scope and are tried again every run until they split:")
        for r in failing:
            since = f", failing since {r['first_failed']}" if r.get("failed", 0) > 1 else ""
            print(f"     {r['source']} (attempt {r.get('failed', 1)}{since}): {r['error']}")
    print(f"{notes} delivery note(s), {unsorted} page(s) to {UNSORTED}"
          + (" [dry run, nothing written]" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
