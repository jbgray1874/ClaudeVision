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
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _where_settings_live() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        import config                                              # noqa: WPS433
        return config.dot_env_path()
    except Exception:                                              # noqa: BLE001
        return str(Path(__file__).resolve().parents[2] / ".env")


# ── OCR ─────────────────────────────────────────────────────────────────────────────

def _tesseract(image_path: str, *, psm: str = "6", whitelist: str = "") -> str:
    cmd = ["tesseract", image_path, "-", "--psm", psm]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"tesseract could not be run: {exc}") from exc
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
        if target.read_bytes() == payload:
            return None
    except OSError:
        pass
    for n in range(2, 100):
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        if not candidate.exists():
            return candidate
        try:
            if candidate.read_bytes() == payload:
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
        payload = out.tobytes()
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
    seen, out = set(), []
    resolved_out = _resolved(out_dir)
    cutoff = time.time() - (since_days * 86400) if since_days and since_days > 0 else 0.0
    for pdf in folder_listing(source_dir, recurse=recurse,
                              skip={out_dir.name, UNSORTED}):
        if pdf.suffix.lower() != ".pdf":
            continue
        key = _resolved(pdf)
        if key in seen:
            continue
        seen.add(key)
        if _resolved(pdf.parent) == resolved_out:
            continue
        try:
            if cutoff and pdf.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        out.append(pdf)
    return sorted(out, key=lambda p: p.name.lower())


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
        force: bool = False, since_days: int = 0,
        recurse: bool = False) -> Dict[str, Any]:
    """One day's run over a folder of scans."""
    prepare_out(out_dir)
    done = _ledger(out_dir)
    results, skipped = [], []
    for pdf in scans_to_read(source_dir, out_dir, since_days=since_days, recurse=recurse):
        mark = _fingerprint(pdf)
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
        if (not force and isinstance(record, dict) and record.get("mark") == mark
                and all((out_dir / name).exists() for name in record.get("files") or [])):
            skipped.append(pdf.name)
            continue
        try:
            result = split_pdf(pdf, out_dir, dry_run=dry_run)
            results.append(result)
        except Exception as exc:                                     # noqa: BLE001
            # ONE BAD SCAN DOES NOT COST THE DAY. A corrupt or password-protected PDF is
            # reported and the rest of the folder is still split.
            results.append({"source": pdf.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not dry_run:
            done[key] = {"mark": mark,
                         "files": [n["file"] for n in result["notes"] if n["file"]]}
    if not dry_run:
        (out_dir / LEDGER).write_text(json.dumps(done, indent=1), encoding="utf-8")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help="Folder the scanner writes into")
    ap.add_argument("--since", type=int, default=0, metavar="DAYS",
                    help="Only scans modified in the last DAYS days. The scan folder holds "
                         "months of them, so the first run is the long one; after it, a "
                         "day's work is a handful of files.")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="Folder to write one PDF per delivery note into")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read and report, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="Re-split scans this has already done")
    ap.add_argument("--recurse", action="store_true",
                    help="Also read scans in subfolders of the source folder")
    a = ap.parse_args()

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
        every = scans_to_read(source, out, recurse=a.recurse)
        chosen = scans_to_read(source, out, since_days=a.since, recurse=a.recurse)
    except RuntimeError as exc:
        # The folder is there and cannot be listed — a permissions problem, or a share that
        # answers Test-Path and refuses enumeration. Said out loud, because the alternative
        # is reporting somebody's day of post as an empty folder.
        print(f"  !! {exc}")
        return 2

    print(f"  {len(every)} PDF(s) in the folder"
          + (f", {len(chosen)} modified in the last {a.since} day(s)" if a.since else "")
          + (" — nothing to do" if not chosen else ""))
    if every and not chosen and a.since:
        print(f"     (run without --since, or with a larger number, to reach the rest)")

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

    report = run(source, out, dry_run=a.dry_run, force=a.force, since_days=a.since,
                 recurse=a.recurse)
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
    print(f"{notes} delivery note(s), {unsorted} page(s) to {UNSORTED}"
          + (" [dry run, nothing written]" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
