"""staging.py — the drawings an estimate was actually run on, gathered into one folder.

WHAT WAS SELECTED AND WHAT WAS PRICED WERE NOT THE SAME THING, AND NOTHING SAID SO.

The page let an estimator pick three drawings out of a folder of twelve. Those picks were used
for exactly one purpose — working out their common parent — and then discarded: the runner was
handed the FOLDER and ran `main.py --job <folder>`, which reads everything in it. Three
selected, twelve priced, and no line anywhere admitting the difference.

The same defect stopped two sources ever being combined. Drawings imported from a Document
Manager extract live on the DM output share; drawings picked from the estimating share live
under K:. Two parents, so the run was refused outright — "those drawings come from 2 different
job folders" — even though the page had merged them into one perfectly good list.

So the list is now STAGED: every file on it is copied into one folder per client and job, and
that folder is what the engine is pointed at. Selection means selection, two sources merge into
one pack, and the folder is a durable record of exactly which drawings produced a number — which
is the thing you want six weeks later when somebody asks.

THE FOLDER IS REPLACED ON A RE-RUN, NOT ADDED TO. A second run of the same job must not inherit
a drawing that was removed from the list, or the estimate silently prices a pack the estimator
did not choose. So the folder is emptied first. Deleting on a live share is the most dangerous
thing this service does, and _clear_folder below refuses to touch anything that is not directly
inside the staging root.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import config

# What the engine can actually read. Copying a .docx into the pack would not break anything, but
# it would sit in the folder implying it was considered, and the folder is meant to be the
# record of what was priced.
#
# .slddrw belongs here with .sldprt and .sldasm: the engine's own _NATIVE_EXTS counts all three
# as native model files, so leaving it out made a job with a SolidWorks drawing look like one
# without.
DRAWING_SUFFIXES = (".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp")

# A RENDER IS A DRAWING ONLY WHEN SOMEBODY SAYS IT IS. Customer packs arrive as images as
# well as PDFs — two renders of an M&S collection bin started this — and the engine reads
# them (file_scan wraps one image as a one-page PDF). But a job folder on the share also
# holds site photos, logo files and screenshots, and sweeping those into a pack because a
# FOLDER was chosen would cost a vision read per holiday snap and file them as parts of the
# job. So an image is staged when it was SELECTED BY NAME, and skipped with a note when it
# merely lived in a chosen folder — "selection means selection", the rule this module
# already applies to everything else.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

# NOT A DRAWING, AND IT MUST TRAVEL WITH THE JOB ANYWAY.
#
# The SolidWorks connector is self-gating on `_sw_native_extract.json` being in the job folder.
# Staging pointed the engine at a folder that did not contain it, so LAYER 0 — the strongest
# source in the building, carrying modelled material, gauge, flat blank and full-depth BOM
# quantities — simply stopped applying. And it stopped SILENTLY: with no models in the staged
# folder either, `native_present_but_unread` could not fire, so the job read as a genuinely
# drawings-only one. That is exactly the failure the invariant layer exists to prevent, and
# staging reintroduced it.
#
# So the extract follows the job. It is fetched from the selection's own folders even when the
# estimator picked individual drawings and never selected the JSON — it describes the job, not
# any one drawing.
SIDECAR_NAMES = ("_sw_native_extract.json",)

# The three extensions the engine counts as a native model. Kept here rather than imported
# because this service does not import the engine, and they must not drift: source_connectors
# .solidworks._NATIVE_EXTS is the other copy and a fixture compares the two.
NATIVE_SUFFIXES = (".sldprt", ".sldasm", ".slddrw")

# THE ADDRESS OF THE MODELS, WRITTEN INTO THE PACK WHEN THE MODELS THEMSELVES STAY PUT.
# Read by source_connectors.solidworks, which analyses those folders in place and writes the
# extract into the job folder. The name is shared with the engine and must not drift.
MODEL_SOURCES_FILENAME = "_sdi_model_sources.json"

# Pathological-input guards. A pack is tens of files and tens of megabytes; anything wildly past
# that is somebody having pointed at the wrong folder, and the copy should refuse rather than
# spend ten minutes filling a share.
MAX_FILES = int(os.getenv("SDI_STAGING_MAX_FILES", "400"))
MAX_BYTES = int(os.getenv("SDI_STAGING_MAX_MB", "750")) * 1024 * 1024


class StagingError(Exception):
    """Something the estimator can see and fix. The route turns it into a 400."""


def staging_root() -> Path:
    return Path(getattr(config, "STAGING_ROOT", "") or "")


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _is_inside(child: Path, parent: Path) -> bool:
    """True only if `child` really sits under `parent`.

    Compared on normalised, case-folded strings with a separator appended, so that a sibling
    named like the parent with a suffix — ...\\SDIIntelligenceAISheetOLD next to
    ...\\SDIIntelligenceAISheet — cannot pass a naive startswith and become deletable.
    """
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def job_folder_for(client: str, drawing: str) -> Path:
    """One folder per client and job — the same shape as the output side, so an estimator
    looking for the inputs of a job finds them where they would look for its outputs."""
    root = staging_root()
    if not str(root):
        raise StagingError(
            "No staging folder is configured. Set SDI_STAGING_ROOT to the folder the "
            "estimating inputs should be gathered into.")
    if not client or not drawing:
        raise StagingError("A client and a drawing number are needed to stage the drawings.")
    return root / client / drawing


def _clear_folder(folder: Path) -> int:
    """Empty a staged job folder. THIS IS THE DELETE, AND IT IS FENCED FOUR WAYS.

    A re-run must not inherit a drawing that has since been removed from the list, so the
    folder is replaced rather than added to. That means deleting files on a live share, from a
    path partly derived from user input, which is the most dangerous thing in this service.

    So: the folder must be configured, must resolve to somewhere genuinely inside the staging
    root, must not BE the root, and must already exist. Anything else raises rather than
    guesses. Nothing here walks upward and nothing follows a link out.
    """
    root = staging_root()
    if not str(root):
        raise StagingError("No staging folder is configured.")

    resolved = Path(os.path.realpath(str(folder)))
    root_resolved = Path(os.path.realpath(str(root)))

    if not _is_inside(resolved, root_resolved):
        raise StagingError(
            f"Refusing to clear {folder}: it is not inside the staging folder {root}.")
    if _norm(resolved) == _norm(root_resolved):
        raise StagingError(
            f"Refusing to clear {folder}: that is the staging root itself, not one job's folder.")
    if not resolved.is_dir():
        return 0

    removed = 0
    for entry in sorted(resolved.iterdir()):
        # Re-check every child. A symlink or junction planted in the folder could otherwise
        # carry a delete somewhere else entirely.
        target = Path(os.path.realpath(str(entry)))
        if not _is_inside(target, root_resolved):
            raise StagingError(
                f"Refusing to remove {entry.name}: it points outside the staging folder.")
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    return removed


def _expand(paths: Iterable[str]) -> Tuple[List[Path], List[Tuple[str, str]]]:
    """The page's list, turned into the actual files to copy.

    Folders are walked, because the Drawings panel holds a job folder as often as it holds
    files. Order is by full path so the same list stages identically twice.
    """
    found: List[Path] = []
    skipped: List[Tuple[str, str]] = []
    seen: set = set()

    def consider(p: Path, *, explicit: bool = False) -> None:
        # A LOCK FILE IS NOT A MODEL. SolidWorks and Office write "~$<name>" beside a document
        # that is open, and it carries the document's own extension — so "~$12349-02-69-GA
        # .SLDASM" passed the suffix test and was staged as a drawing. Six of them reached one
        # pack. They are a few bytes of who-has-it-open, they make the model count wrong, and
        # handing one to the analyser asks SolidWorks to open a file that is not a document.
        # Their presence says somebody had those models open when the pack was picked, which
        # is worth saying rather than silently copying.
        if p.name.startswith("~$") or p.name.startswith("~"):
            skipped.append((str(p), "a SolidWorks/Office lock file, not a drawing — it means "
                                    "someone had that document open"))
            return
        suffix = p.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            # Selected by name: a render the engine reads. Found in a chosen folder: a photo
            # until somebody says otherwise — see IMAGE_SUFFIXES above.
            if not explicit:
                skipped.append((str(p), "an image in a chosen folder — a render is staged "
                                        "only when selected by name, so a job folder's "
                                        "photos do not become parts of the job"))
                return
        elif suffix not in DRAWING_SUFFIXES:
            skipped.append((str(p), f"not a drawing file ({p.suffix or 'no extension'})"))
            return
        key = p.name.lower()
        if key in seen:
            # SAME NAME WINS ONCE, and the later one wins — the rule the page already applies
            # when a Document Manager copy lands on top of a share copy.
            found[:] = [f for f in found if f.name.lower() != key]
        seen.add(key)
        found.append(p)

    for raw in paths:
        p = Path(str(raw))
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file():
                    consider(child)
        elif p.is_file():
            consider(p, explicit=True)
        else:
            skipped.append((str(p), "not found on this machine"))

    # Drop any sidecar that was picked up as a "file" — it is handled separately, and
    # reporting it as an unrecognised extension reads as though it were ignored.
    skipped = [(pth, why) for pth, why in skipped
               if Path(pth).name.lower() not in {n.lower() for n in SIDECAR_NAMES}]
    return found, skipped


def _sidecars_for(paths: Iterable[str]) -> List[Path]:
    """The job-level files that must travel with the drawings, found from the selection.

    A selected folder is searched; selected files are searched for beside themselves. The
    estimator never has to know the extract exists, which is the point — they select drawings.
    """
    folders: List[Path] = []
    for raw in paths:
        p = Path(str(raw))
        if p.is_dir():
            folders.append(p)
        elif p.is_file():
            folders.append(p.parent)

    out: List[Path] = []
    seen: set = set()
    for folder in folders:
        for name in SIDECAR_NAMES:
            # ONE LEVEL UP, DIRECT HIT ONLY. A job routinely keeps its drawings and its models
            # in sibling folders — 12349-02\PDF and 12349-02\Models — and the analyser writes
            # the extract beside the MODELS. Searching only downward from the drawings folder
            # therefore never finds it, and the run reads as a job with no models at all.
            # Upward is one level and an exact filename: no rglob of a parent, which on an
            # estimating share could be the whole client.
            for cand in (folder / name, folder.parent / name, *sorted(folder.rglob(name))):
                try:
                    if cand.is_file() and str(cand).lower() not in seen:
                        seen.add(str(cand).lower())
                        out.append(cand)
                except OSError:
                    continue
    return out


def _native_models_beside(paths: Iterable[str]) -> List[Path]:
    """SolidWorks models sitting with the selection that were not part of it.

    ASKED ONLY WHEN THE ANSWER MATTERS — when the pack arrives with neither an extract nor a
    model — because it is the difference between the two things "no SOLIDWORKS extract" can
    mean. A job that has no models is a fact about the job. A job whose models are one click
    away in the folder the drawings came from is a selection that switched off the strongest
    source in the building, and nothing anywhere said so.
    """
    folders: List[Path] = []
    for raw in paths:
        p = Path(str(raw))
        folders.append(p if p.is_dir() else p.parent)

    out: List[Path] = []
    seen: set = set()
    for folder in folders:
        try:
            children = sorted(folder.rglob("*"))
        except OSError:
            continue
        for cand in children:
            try:
                if not cand.is_file() or cand.suffix.lower() not in NATIVE_SUFFIXES:
                    continue
            except OSError:
                continue
            if _is_excluded_path(cand, folder):
                continue
            key = _norm(cand)
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def _is_excluded_path(path: Path, root: Path) -> bool:
    """An archive, a backup or a ~lock file is not the live design.

    Same rule the analyser applies when it decides what to read, so the count reported here is
    the count of models a run could actually use.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    for part in rel.parts[:-1]:
        n = part.strip().lower()
        if n.startswith(".") or n.startswith("~"):
            return True
        if any(tok in re.split(r"[^a-z0-9]+", n) for tok in _EXCLUDED_DIR_TOKENS):
            return True
        if any(ph in n for ph in _EXCLUDED_DIR_PHRASES):
            return True
    return path.name.startswith("~$") or path.name.startswith("~")


# MUST MATCH source_connectors.solidworks — the consumer's exclusion list and this one answer
# the same question on two sides of a copy, and a fixture compares them token for token.
_EXCLUDED_DIR_TOKENS = ("archive", "archived", "obsolete", "superseded", "old", "backup",
                        "bak", "dnu", "scrap", "wip", "temp", "tmp",
                        "previous", "prev")
_EXCLUDED_DIR_PHRASES = ("do not use", "not for manufacture")


def stage(paths: Iterable[str], *, client: str, drawing: str) -> Dict[str, Any]:
    """Copy the chosen drawings into this job's staging folder and describe what happened.

    Returns the folder to point the engine at, plus what was copied and what was not, so the
    run log can say it rather than leaving the estimator to compare two folders by eye.
    """
    folder = job_folder_for(client, drawing)
    files, skipped = _expand(paths)
    if not files:
        detail = "; ".join(f"{Path(p).name}: {why}" for p, why in skipped[:4])
        raise StagingError(
            "None of the selected items is a drawing the engine can read."
            + (f" ({detail})" if detail else ""))

    if len(files) > MAX_FILES:
        raise StagingError(
            f"{len(files)} drawings selected, which is past the {MAX_FILES} limit — this is "
            f"usually a folder chosen a level too high. Narrow the selection.")
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    if total > MAX_BYTES:
        raise StagingError(
            f"The selected drawings total {total // (1024 * 1024)} MB, past the "
            f"{MAX_BYTES // (1024 * 1024)} MB limit. Narrow the selection.")

    folder.mkdir(parents=True, exist_ok=True)

    # THE EXTRACT THE LAST RUN PAID FOR. Reading a pack of models takes SolidWorks the better
    # part of half an hour, and a re-run of the same pack was throwing that away every time:
    # the folder is emptied before the copy, which deleted an extract generated INTO it by the
    # previous run, and the engine then had no choice but to generate it again.
    #
    # Keeping it is safe because it is not trusted on sight. The extract carries a fingerprint
    # of the models it was taken from, and the engine re-checks that against the models in the
    # pack before using it: a changed, added or deleted model regenerates it, an unchanged one
    # is read in seconds. That check is what makes this a saving rather than a stale answer.
    #
    # A fresh extract travelling WITH the selection always wins — it is a statement about the
    # models made by whoever ran it, and this is only ever a cached one.
    _previous_extract: Optional[bytes] = None
    for _name in SIDECAR_NAMES:
        try:
            _previous_extract = (folder / _name).read_bytes()
        except OSError:
            continue
        break

    replaced = _clear_folder(folder)

    copied: List[str] = []
    for f in files:
        dest = folder / f.name
        shutil.copy2(str(f), str(dest))
        copied.append(f.name)

    # The job-level sidecars, after the drawings so a copy failure on one cannot cost the pack.
    sidecars: List[str] = []
    for sc in _sidecars_for(paths):
        try:
            shutil.copy2(str(sc), str(folder / sc.name))
            sidecars.append(sc.name)
        except OSError:
            skipped.append((str(sc), "could not be copied"))

    carried_forward = False
    if not sidecars and _previous_extract is not None:
        try:
            (folder / SIDECAR_NAMES[0]).write_bytes(_previous_extract)
            carried_forward = True
        except OSError:
            pass

    # NEITHER AN EXTRACT NOR A MODEL REACHED THE PACK. Say whether that is because the job has
    # none, or because they were beside the drawings and not selected. Three runs of 12349-02
    # were costed drawings-only and the log's only word on it was "no SOLIDWORKS extract found",
    # which is true of both and actionable in only one of them.
    native_staged = [n for n in copied if Path(n).suffix.lower() in NATIVE_SUFFIXES]
    unselected: List[Path] = []
    if not sidecars and not carried_forward and not native_staged:
        unselected = _native_models_beside(paths)

    # AND THEN POINT THE ENGINE AT THEM, WHERE THEY LIVE.
    #
    # Telling the estimator to select the models as well would work and is the wrong answer:
    # a model copied out of its folder loses the references that resolve its components, the
    # copy is tens of megabytes over a share on every re-run, and it asks somebody to know
    # which files the costing engine happens to need. None of that is their job.
    #
    # So the pack carries the ADDRESS of the models rather than the models. The runner has
    # SOLIDWORKS; with this it analyses them in place, writes the extract into the job folder,
    # and Layer 0 applies without anybody copying a JSON around by hand.
    if unselected:
        _sources = sorted({str(p.parent) for p in unselected})
        (folder / MODEL_SOURCES_FILENAME).write_text(
            json.dumps({"models_folders": _sources,
                        "model_count": len(unselected),
                        "note": "Written by staging: the drawings were selected out of these "
                                "folders and the SolidWorks models are still in them. Analyse "
                                "them in place — do not copy models into a staged pack."},
                       indent=2),
            encoding="utf-8")

    return {
        "folder": str(folder),
        "copied": copied,
        "copied_count": len(copied),
        "sidecars": sidecars,
        "sidecars_count": len(sidecars),
        "extract_carried_forward": carried_forward,
        "native_staged": native_staged,
        "native_unselected_count": len(unselected),
        "native_unselected_folders": sorted({str(p.parent) for p in unselected})[:3],
        "replaced_count": replaced,
        "skipped": [{"path": p, "reason": why} for p, why in skipped],
        "skipped_count": len(skipped),
        "bytes": total,
    }
