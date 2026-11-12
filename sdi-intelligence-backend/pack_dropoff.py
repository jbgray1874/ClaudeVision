"""EVERY NEW JOB'S DRAWING PACK IS ALSO KEPT IN THE DROP-OFF FOLDER (JG, 12 Nov 2026).

"For every new job we also need to save the drawing pack to C:\\ClaudeVision\\chatgptdropoff.
We should auto create a client name folder where none exists at the time of creation of the
job, then a folder below that with the job number / name identifier and all the drawings.
Same as at K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry."

So, when a job is queued, the drawings just staged for it are copied to

    <drop-off>\\<client>\\<drawing number>\\

exactly the files the estimate will read, with the pack manifest when there is one.

WHAT IT NEVER DOES. It never deletes or moves anything: a file of the same name is replaced
by the job's current copy, and a file from an earlier run that is no longer in the pack stays
where it is. It never stops a job: a drop-off that cannot be written is said once in the
service log and the estimate runs. It never creates the drop-off folder itself, so a machine
with no such folder (the server) keeps none.

The folder is <checkout>\\chatgptdropoff unless SDI_PACK_DROPOFF_DIR names another;
SDI_PACK_DROPOFF_DIR=off switches it off. Client folders under it are git-ignored: drawings
are customer data and are never committed.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_OFF = {"off", "0", "no", "false", "none"}
# The service's own notes in a staged folder (CONCEPT_DOCUMENT.json, ENQUIRY_BRIEF.txt): not
# drawings. The pack manifest is lower-case and is kept.
_STAGE_NOTE = re.compile(r"[A-Z][A-Z_]+\.json|ENQUIRY_BRIEF\.txt")


def root(repo_root: Path) -> Optional[Path]:
    """Where packs are dropped, or None when there is nowhere (or it is switched off)."""
    raw = str(os.getenv("SDI_PACK_DROPOFF_DIR", "")).strip()
    if raw.lower() in _OFF:
        return None
    folder = Path(raw) if raw else Path(repo_root) / "chatgptdropoff"
    return folder if folder.is_dir() else None


def save(staged_folder: Any, client: str, drawing: str, repo_root: Path,
         safe: Callable[[Any], str] = str) -> Dict[str, Any]:
    """Copy the staged pack to <drop-off>\\<client>\\<drawing>. Says what it did; never raises."""
    out: Dict[str, Any] = {"saved": False, "folder": "", "files": [], "why": ""}
    try:
        base = root(repo_root)
        if base is None:
            out["why"] = "no drop-off folder on this machine"
            return out
        _client, _drawing = safe(client).strip(), safe(drawing).strip()
        if not _client or not _drawing:
            out["why"] = "no client or drawing number to name the folder"
            return out
        src = Path(str(staged_folder))
        dest = base / _client / _drawing
        if dest.resolve() == src.resolve():
            out["why"] = "the job is staged in the drop-off folder already"
            return out
        files: List[Path] = sorted(p for p in src.iterdir()
                                   if p.is_file() and not _STAGE_NOTE.fullmatch(p.name))
        if not files:
            out["why"] = "nothing was staged"
            return out
        dest.mkdir(parents=True, exist_ok=True)      # the client folder is made when missing
        for p in files:
            shutil.copy2(p, dest / p.name)
        out.update(saved=True, folder=str(dest), files=[p.name for p in files])
    except Exception as exc:                                             # noqa: BLE001
        out["why"] = f"{type(exc).__name__}: {exc}"
    return out
