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

# ── A UNC PATH, NOT A DRIVE LETTER ──────────────────────────────────────────────────
#
# K: is a MAPPED DRIVE, and a mapping belongs to a logged-on session. A scheduled task, a
# Windows service and the SDI Intelligence backend all run without one, so "K:\IT\..." is
# simply not there for them — the job runs, finds no folder, creates one on the local disk
# and writes the day's delivery notes somewhere nobody will ever look. It exits 0 while doing
# it, which is the whole problem.
#
# The same share by its UNC name is reachable from all of them, and from Explorer, and means
# the same thing in a config file on any machine.
DEFAULT_OUT = r"\\sdi-dc01\shareddata$\IT\DeliveryNotesOutput"


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


def run(source_dir: Path, out_dir: Path, *, dry_run: bool = False,
        force: bool = False) -> Dict[str, Any]:
    """One day's run over a folder of scans."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done = _ledger(out_dir)
    results, skipped = [], []
    for pdf in sorted(source_dir.glob("*.pdf")) + sorted(source_dir.glob("*.PDF")):
        mark = _fingerprint(pdf)
        record = done.get(pdf.name) or {}
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
            done[pdf.name] = {"mark": mark,
                              "files": [n["file"] for n in result["notes"] if n["file"]]}
    if not dry_run:
        (out_dir / LEDGER).write_text(json.dumps(done, indent=1), encoding="utf-8")
    return {"when": datetime.now().isoformat(timespec="seconds"),
            "source": str(source_dir), "out": str(out_dir),
            "results": results, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="Folder the scanner writes into")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="Folder to write one PDF per delivery note into")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read and report, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="Re-split scans this has already done")
    a = ap.parse_args()

    report = run(Path(a.source), Path(a.out), dry_run=a.dry_run, force=a.force)
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
