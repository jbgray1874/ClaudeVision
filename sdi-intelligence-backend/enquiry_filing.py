"""An email's drawings, saved into Live Enquiry so they can be estimated.

"if we receive an email with a pdf / pdf's in the email app SDI private
assistant I want to be able to save that down to the file system and then go
to the other app, open up the estimate and run an estimate" - James Gray,
30 October 2026.

Its own module, with no FastAPI and no mailbox in it, so the rules below can
be tested on bytes and a temporary folder.

── WHERE ───────────────────────────────────────────────────────────────────
<Live Enquiry>\\<client>\\<job or enquiry number>\\ - the two levels the
estimating browser treats as a job (it offers "start" two folders down), so
the folder this writes is one the phone and the desk can run straight away.
Both names are typed by a person and cleaned HERE, because the page can be
bypassed: Windows refuses some characters outright and silently drops a
trailing dot, and ".." must never be a folder name.

── WHAT ────────────────────────────────────────────────────────────────────
Files the engine runs from: staging's DRAWING_SUFFIXES. A logo, a signature
image or a spreadsheet in the same email is listed as not saved, with the
reason, rather than swept into the pack - staging would skip it there anyway,
with a note nobody on a phone would see.

── NEVER OVERWRITES ────────────────────────────────────────────────────────
A file of the same name and the same bytes is already there and is left
alone. The same name with different bytes is a revision, and is saved beside
it as "name (2).pdf", never over it: the estimate that was run from the first
one still has to be explainable. Every write is exclusive ("xb"), so there is
no moment between looking and writing in which a file could be replaced.
"""
import os
import re
from pathlib import Path

# The same tuple as staging.DRAWING_SUFFIXES; a test holds them together.
# Not imported, because staging reads the service's configuration as it loads
# and this must load wherever the private assistant does.
DRAWINGS = (".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp")

# Windows' reserved characters and control characters - estimate_routes'
# _UNSAFE, the rule every other job folder on the share is named by.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Refused(Exception):
    """A reason to show the person, not a fault."""


def segment(text) -> str:
    """A typed name, made fit to be one folder."""
    cleaned = _UNSAFE.sub("-", str(text or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(". ")
    return cleaned[:120]


def file_name(name) -> str:
    """A sender's file name, reduced to a name - the same as the private
    assistant's own _file_name, for the same reason: it came from outside."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(name or "")).strip()
    cleaned = cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip(" .")
    cleaned = re.sub(r'[<>:"|?*]', "_", cleaned)
    return cleaned[:160] or "attachment"


# Where the estimating app looks for packs: the same setting and default as
# estimating_job_tools.LIVE_ENQUIRY_ROOT and public_surface.ENQUIRY_DEFAULT, held
# together by a test. Not imported from there: those travel with push-to-server
# and this travels with Deploy-AMCRM, and a module the private assistant needs
# must not depend on a file the other deploy copies.
LIVE_ENQUIRY_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                        r"\AI Estimating\Live Enquiry")


def live_enquiry_root() -> Path:
    return Path((os.getenv("SDI_LIVE_ENQUIRY_ROOT", "") or LIVE_ENQUIRY_DEFAULT).strip())


def file_for_estimating(root, client, reference, files) -> dict:
    """Save `files` - [(name, bytes)] - under root\\client\\reference.

    Returns what was saved, what was not and why, and the pack's name as the
    estimating app knows it ("Client/Job")."""
    c, r = segment(client), segment(reference)
    if not c or not r:
        raise Refused("Give it a client and a job or enquiry number - they are the two "
                      "folders the drawings are filed under.")
    base = Path(root)
    if not base.is_dir():
        raise Refused(f"Live Enquiry cannot be reached from the server ({base}).")
    folder = base / c / r
    folder.mkdir(parents=True, exist_ok=True)
    # Belt and braces after cleaning: the folder made must be inside the root.
    if base.resolve() not in folder.resolve().parents:
        raise Refused("That client or job name does not make a folder inside Live Enquiry.")

    saved, skipped = [], []
    for name, content in files:
        clean = file_name(name)
        suffix = Path(clean).suffix.lower()
        if suffix not in DRAWINGS:
            skipped.append({"name": clean, "why": "not a drawing the estimate reads"})
            continue
        target = folder / clean
        for n in range(2, 100):
            try:
                with open(target, "xb") as out:          # exclusive: never over a file
                    out.write(content)
                saved.append(target.name)
                break
            except FileExistsError:
                if target.is_file() and target.read_bytes() == content:
                    skipped.append({"name": target.name, "why": "already in the folder"})
                    break
                target = folder / f"{Path(clean).stem} ({n}){suffix}"
        else:
            skipped.append({"name": clean, "why": "ninety-eight versions of it are there already"})
    return {"client": c, "reference": r, "relative": f"{c}/{r}",
            "folder_path": str(folder), "saved": saved, "skipped": skipped}
