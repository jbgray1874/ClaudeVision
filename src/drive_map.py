"""A mapped drive letter as its network path, so W:\\ works where the letter does not exist (JG, 9 Nov 2026).

A drive letter belongs to one logon. An administrator PowerShell, a scheduled task and a service
do not see the letters mapped in the user's own session, so "W:\\Design\\..." reads as missing
there, and the drawing index found nothing on its first build. A path that starts with a letter
is therefore translated to its UNC form before it is read:

  1. SDI_DRIVE_MAP, the service's own setting: "K=\\\\server\\share;W=\\\\server\\share2". Unset,
     it is this business's two: K (shared data) and W (the CAD share, \\\\sdi-dc01\\CAD).
  2. Otherwise, on Windows, the user's own saved mapping (HKCU\\Network\\<letter>, which an
     administrator window of the same user can read even where the letter itself is missing).
  3. Otherwise the path is left as it was.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Optional

DEFAULT = r"K=\\sdi-dc01\shareddata$\Shared;W=\\sdi-dc01\CAD"
_LETTER = re.compile(r"^([A-Za-z]):[\\/]?(.*)$", re.S)


def parse(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in str(raw or "").split(";"):
        if "=" not in pair:
            continue
        letter, unc = pair.split("=", 1)
        letter, unc = letter.strip().rstrip(":").upper(), unc.strip().rstrip("\\/")
        if len(letter) == 1 and letter.isalpha() and unc:
            out[letter] = unc
    return out


def _saved_mapping(letter: str) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Network\\{letter}") as k:
            val, _ = winreg.QueryValueEx(k, "RemotePath")
        return str(val).rstrip("\\/") or None
    except OSError:
        return None


def to_unc(path: str, env: Optional[Dict[str, str]] = None) -> str:
    """The UNC form of a drive-letter path, or the path unchanged."""
    m = _LETTER.match(str(path or ""))
    if not m:
        return str(path or "")
    letter, rest = m.group(1).upper(), m.group(2)
    e = env if env is not None else os.environ
    raw = e.get("SDI_DRIVE_MAP")
    base = parse(DEFAULT if raw is None else raw).get(letter) or _saved_mapping(letter)
    if not base:
        return str(path)
    return base + ("\\" + rest.replace("/", "\\").lstrip("\\") if rest else "")
