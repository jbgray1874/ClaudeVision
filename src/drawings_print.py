#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""drawings_print.py — one printable PDF of the drawings behind an estimate.

AN ESTIMATE IS CHECKED AGAINST THE DRAWINGS, AND THE DRAWINGS WERE THE ONE THING THE PAGE
COULD NOT HAND OVER.

An estimator reviewing a sheet wants the pack in front of them — on paper, or at least in one
window — and until now that meant opening the job folder on the share and printing twelve files
one at a time. Reviewing is what the whole parallel run depends on, and every step that makes it
more tedious shows up in the adoption register as a job that never came back.

So this collects the drawings for a job into a SINGLE PDF, in a stable order, with a bookmark
per source file so a forty-page pack can be navigated rather than scrolled.

WHAT IT REFUSES TO DO QUIETLY. A pack is rarely all PDFs — there are DXFs, DWGs and SolidWorks
models in it too, and none of those is a printable page. Dropping them silently would hand an
estimator eight sheets of a twelve-drawing pack with nothing to say four were missing, and they
would review what they were given. So anything that cannot be printed is named on a cover page,
and the cover page appears only when there is something to say.

Run:
    python src/drawings_print.py --out merged.pdf --json PATH [PATH ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Printable here means "has pages". Everything else in a pack is geometry or a model.
PRINTABLE = (".pdf",)
# Named separately from "anything else" so the cover page can say WHY a file was left out —
# "not a printable drawing" is a different message from "we did not recognise this".
KNOWN_UNPRINTABLE = (".dxf", ".dwg", ".sldprt", ".sldasm", ".step", ".stp", ".iges", ".igs")

# THINGS THE ENGINE WROTE, WHICH WERE NEVER PART OF THE PACK.
#
# `_sw_native_extract.json` is the SOLIDWORKS extract the engine itself produces and drops beside
# the drawings. It was being listed under the red NOT PRINTED heading, beneath a sentence reading
# "these are part of the job and are not in this print" — which is untrue of it twice over: it is
# not part of the job and it is not a drawing. A warning that cries wolf about a file nobody was
# ever going to print is how the whole list stops being read, and the list exists to catch the one
# case that matters: a real drawing missing from the paper.
ENGINE_ARTIFACTS = ("_sw_native_extract.json",)


class PrintInputError(ValueError):
    """Something the estimator can fix, phrased for them. The backend turns it into a 400."""


def _ensure_engine_on_path() -> None:
    """APPENDED, never prepended — see parity_run for why. Two modules are called `config`."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.append(here)


def collect(paths: List[str]) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    """Expand what the page sent into printable files and a reason for each that is not.

    Folders are walked, because the Drawings panel holds a job FOLDER as often as it holds
    files, and "print the drawings" means the pack either way.

    Order is deliberate and stable: sorted by path, so the same job prints the same way twice.
    A pack whose page order changed between printings would be worse than useless for checking
    one estimate against another.
    """
    printable: List[Path] = []
    skipped: List[Tuple[Path, str]] = []
    seen = set()

    def consider(p: Path) -> None:
        key = str(p).lower()
        if key in seen:
            return
        seen.add(key)
        if p.name.lower() in ENGINE_ARTIFACTS:      # never part of the pack; not a gap in it
            return
        suffix = p.suffix.lower()
        if suffix in PRINTABLE:
            printable.append(p)
        elif suffix in KNOWN_UNPRINTABLE:
            skipped.append((p, "not a printable drawing — geometry or a model"))
        else:
            skipped.append((p, f"not printed — '{suffix or 'no extension'}' is not a drawing"))

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file():
                    consider(child)
        elif p.is_file():
            consider(p)
        else:
            skipped.append((p, "not found on this machine"))

    printable.sort(key=lambda x: str(x).lower())
    skipped.sort(key=lambda x: str(x[0]).lower())
    return printable, skipped


def _cover(doc: Any, job: Optional[str], printed: List[Path],
           skipped: List[Tuple[Path, str]]) -> None:
    """A contents page, inserted ONLY when something could not be printed.

    A clean all-PDF pack prints exactly the drawings and nothing else, because an extra sheet
    on every print is an annoyance that gets the feature turned off. When files ARE missing
    from the print, the estimator has to be told on the paper itself — a warning on a screen
    they have already walked away from is no warning at all.
    """
    import fitz

    page = doc.new_page(0, width=595, height=842)          # A4 portrait
    y = 60

    def line(text: str, size: int = 10, colour=(0, 0, 0), gap: int = 14) -> None:
        nonlocal y
        page.insert_text((56, y), text, fontsize=size, color=colour,
                         fontname="helv")
        y += gap

    line(f"Drawings for {job}" if job else "Drawings", size=16, gap=26)
    n = len(printed)
    line(f"{n} drawing{'' if n == 1 else 's'} {'follows' if n == 1 else 'follow'} this page.",
         gap=22)

    for p in printed:
        line(f"    {p.name}", size=9, gap=12)

    # A SKIPPED FILE WHOSE DRAWING IS ON THE PAPER ANYWAY IS NOT A GAP.
    #
    # A pack routinely carries the same GA as both a PDF and a DWG. Listing the DWG in red under
    # "part of the job and not in this print" says the reviewer is missing a drawing they are in
    # fact holding — it was printed, from the PDF beside it. Only a stem with NO printed
    # counterpart is a real hole in the paper, and separating the two is what keeps the red list
    # worth reading.
    printed_stems = {p.stem.lower() for p in printed}
    covered = [(p, w) for p, w in skipped if p.stem.lower() in printed_stems]
    missing = [(p, w) for p, w in skipped if p.stem.lower() not in printed_stems]

    if missing:
        y += 14
        line(f"NOT PRINTED — {len(missing)} file{'' if len(missing) == 1 else 's'}",
             size=11, colour=(0.7, 0.1, 0.1), gap=18)
        line("These are part of the job and are not in this print. They are listed so the pack",
             size=9, colour=(0.35, 0.35, 0.35), gap=11)
        line("is not reviewed as if it were complete.",
             size=9, colour=(0.35, 0.35, 0.35), gap=18)
        for p, why in missing:
            line(f"    {p.name}  —  {why}", size=9, colour=(0.35, 0.35, 0.35), gap=12)

    if covered:
        y += 14
        line(f"ALSO IN THE PACK — {len(covered)} file{'' if len(covered) == 1 else 's'}, "
             f"already on the paper", size=10, colour=(0.35, 0.35, 0.35), gap=16)
        line("The same drawing was printed from its PDF. Nothing is missing here.",
             size=9, colour=(0.45, 0.45, 0.45), gap=16)
        for p, _why in covered:
            line(f"    {p.name}  —  printed from {p.stem}.PDF",
                 size=9, colour=(0.45, 0.45, 0.45), gap=12)


def build(paths: List[str], out_path: str | Path,
          job: Optional[str] = None) -> Dict[str, Any]:
    """Merge the printable drawings into one PDF at out_path and describe what happened."""
    _ensure_engine_on_path()
    try:
        import fitz                                                  # PyMuPDF
    except ImportError as exc:                                       # pragma: no cover
        raise PrintInputError(
            "PyMuPDF is not installed on this machine, so drawings cannot be merged "
            "(pip install pymupdf).") from exc

    printable, skipped = collect(paths)
    if not printable:
        # Say which it was, because "nothing to print" over a folder of twelve DXFs is a very
        # different situation from "nothing to print" over an empty list.
        if skipped:
            raise PrintInputError(
                f"None of the {len(skipped)} file(s) can be printed — a pack of models and "
                f"geometry has no printable pages. Only PDFs can be printed.")
        raise PrintInputError("No drawings were given to print.")

    merged = fitz.open()
    toc = []
    try:
        for src_path in printable:
            try:
                with fitz.open(str(src_path)) as src:
                    if src.page_count == 0:
                        skipped.append((src_path, "the PDF has no pages"))
                        continue
                    # Page 1 of this file within the merged document, for the bookmark.
                    toc.append([1, src_path.name, merged.page_count + 1])
                    merged.insert_pdf(src)
            except Exception as exc:                                 # noqa: BLE001
                # A corrupt or password-protected PDF must not lose the other eleven.
                skipped.append((src_path, f"could not be opened ({type(exc).__name__})"))

        printed = [p for p in printable
                   if p not in {s[0] for s in skipped}]
        if not printed:
            raise PrintInputError(
                "Every PDF in the pack failed to open — see the job folder.")

        if skipped:
            _cover(merged, job, printed, skipped)
            # The cover took page 1, so every bookmark moves down by one.
            toc = [[lvl, title, page + 1] for lvl, title, page in toc]
            # Name the bookmark for what the sheet actually says. When every skipped file's
            # drawing was printed from its PDF twin there is no gap, and a bookmark promising
            # "what is not printed" would send a reviewer looking for a problem that is not there.
            _stems = {p.stem.lower() for p in printed}
            _gap = any(p.stem.lower() not in _stems for p, _ in skipped)
            toc.insert(0, [1, "Contents — and what is not printed" if _gap else "Contents", 1])

        merged.set_toc(toc)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        merged.save(str(out), garbage=3, deflate=True)
    finally:
        merged.close()

    return {
        "pdf": str(out),
        "printed": [str(p) for p in printed],
        "printed_count": len(printed),
        "pages": _page_count(out),
        "skipped": [{"path": str(p), "reason": why} for p, why in skipped],
        "skipped_count": len(skipped),
        "cover_page": bool(skipped),
    }


def _page_count(path: Path) -> Optional[int]:
    try:
        import fitz
        with fitz.open(str(path)) as d:
            return d.page_count
    except Exception:                                                # noqa: BLE001
        return None


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Merge a job's drawings into one printable PDF.")
    ap.add_argument("paths", nargs="+", help="Drawing files and/or job folders")
    ap.add_argument("--out", required=True, help="Where to write the merged PDF")
    ap.add_argument("--job", help="Job name for the cover page, when there is one")
    ap.add_argument("--json", action="store_true",
                    help="Emit the result as a single JSON line on stdout (for the backend)")
    a = ap.parse_args()

    try:
        res = build(a.paths, a.out, job=a.job)
    except PrintInputError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

    if a.json:
        print(json.dumps(res))
    else:
        print(f"  {res['printed_count']} drawing(s), {res['pages']} page(s) -> {res['pdf']}")
        for s in res["skipped"]:
            print(f"  NOT PRINTED  {Path(s['path']).name}  —  {s['reason']}")


if __name__ == "__main__":
    main()
