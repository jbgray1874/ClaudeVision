"""Why a folder under an allowed root could not be listed, in words a person can act on.

THE PICKER SAID "FOLDER NOT FOUND" FOR A FOLDER THAT EXISTS. 27 Sep 2026: an estimator opened
the drawing picker, clicked the Live Enquiry root and read "Cannot read this folder — Folder
not found". The folder was on the share the whole time; the VPN was down, so the service's
stat of \\\\sdi-dc01\\... failed and Path.is_dir() said False. The message named a folder and
blamed it, when the thing that had gone was the network between this machine and the share.

Three different situations produced that one sentence, and they send a person to three
different places:

  * the ROOT itself cannot be reached      — the VPN, the share, or the account the service
                                             runs as; nothing under it will list either
  * an ancestor inside the root is missing — the folder was moved or renamed on the share
  * only the leaf is missing               — the same, one level down

This is a pure function so the picker's wording can be driven in a test without booting the
service. It changes no behaviour except the sentence in the 404. Paths are split on either
separator by hand: the service runs on Windows and the tests run wherever they run, and a
UNC path must read the same in both.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional

_SEPS = ("\\", "/")


def _parts(p: str) -> List[str]:
    """Path components, keeping a UNC's ``\\\\server\\share`` as one leading component."""
    s = str(p or "").replace("/", "\\").rstrip("\\")
    unc = s.startswith("\\\\")
    body = s[2:] if unc else s
    parts = [x for x in body.split("\\") if x != ""]
    if unc and len(parts) >= 2:
        parts = ["\\\\" + parts[0] + "\\" + parts[1]] + parts[2:]
    elif unc and parts:
        parts = ["\\\\" + parts[0]]
    return parts


def _join(parts: List[str]) -> str:
    return "\\".join(parts)


def _norm(p: str) -> str:
    return _join(_parts(p)).lower()


def root_of(target: str, roots: Iterable[str]) -> Optional[str]:
    """The configured root this path sits under, as configured, or None."""
    t = _norm(target)
    for root in roots:
        r = _norm(root)
        if t == r or t.startswith(r + "\\"):
            return str(root)
    return None


def folder_missing_detail(target: str, roots: Iterable[str],
                          isdir=os.path.isdir) -> str:
    """The 404 detail for a folder inside an allowed root that did not list.

    `isdir` is injectable so the three situations can be driven without a share.
    """
    root = root_of(target, roots)
    if root is None:
        return f"Folder not found: {target}"
    if not isdir(root):
        _unc = str(root).startswith(_SEPS[0] * 2) or str(root).startswith("//")
        return (f"The share root {root} is not reachable from this service right now, so "
                f"nothing under it can be listed. "
                + ("Check the VPN and that the share is up, and that the account the service "
                   "runs as can see it." if _unc else
                   "Check the drive or folder is present on this machine."))
    # The root answers; find the highest missing folder between the root and the target.
    t_parts = _parts(target)
    r_len = len(_parts(root))
    missing_at = len(t_parts)
    for depth in range(r_len + 1, len(t_parts) + 1):
        if not isdir(_join(t_parts[:depth])):
            missing_at = depth
            break
    if missing_at >= len(t_parts):
        return (f"Folder not found: {target}. The folder above it is there, so this one "
                f"was moved, renamed or has not been created yet.")
    return (f"Folder not found: {target}. The share answers, but "
            f"{t_parts[missing_at - 1]} under {_join(t_parts[:missing_at - 1])} is missing — "
            f"the folder was moved or renamed on the share.")
