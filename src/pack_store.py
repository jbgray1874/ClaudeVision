"""Where a resolved drawing pack is kept: Live Enquiry\\<client>\\<drawing>, re-used if unchanged (JG, 9 Nov 2026).

    K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\<client>\\<drawing>          the first set
    ...\\Live Enquiry\\<client>\\<drawing> v2, v3 ...                                    a changed set

Every entry point (the estimating page, AI Estimate Self-Running, the tracker pricer) saves its
pack here through store(). The pack's files are compared with the latest set already saved for
that client and drawing, by name and fingerprint:

  unchanged   the saved set is used as it is; nothing is copied
  new         the first set: the folder is made and filled
  changed     a NEW folder beside the old one ("<drawing> v2"), with what was added, removed or
              changed listed in its manifest. The earlier set is never overwritten, so a decision
              taken on it stays traceable, and the change flags it for review.

A folder filled before this existed (by hand, or by the old collector) has no manifest; its files
are fingerprinted where they lie, so an identical set is still "unchanged".

The root is SDI_PACK_STORE, else AI_ENQUIRY_DEST (the Self-Running collector's setting), else the
Live Enquiry folder above, always read through its UNC path.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
MANIFEST = "pack_manifest.json"
DEFAULT_ROOT = r"K:\Estimating\Completed\AI Estimating\Live Enquiry"


def store_root(env: Optional[Dict[str, str]] = None) -> Path:
    e = env if env is not None else os.environ
    sys.path.insert(0, str(HERE))
    from drive_map import to_unc
    return Path(to_unc(e.get("SDI_PACK_STORE") or e.get("AI_ENQUIRY_DEST") or DEFAULT_ROOT, e))


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip()).strip(". ") or "unnamed"


def _files_of(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for m in manifest.get("members") or []:
        for f in m.get("files") or []:
            key = Path(f["path"]).name.lower()
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def _versions(base: Path) -> List[Tuple[int, Path]]:
    found = []
    if base.is_dir():
        found.append((1, base))
    try:
        for p in base.parent.iterdir():
            m = re.fullmatch(re.escape(base.name) + r" v(\d+)", p.name)
            if m and p.is_dir():
                found.append((int(m.group(1)), p))
    except OSError:
        pass
    return sorted(found)


def _saved_prints(folder: Path) -> Dict[str, str]:
    """name -> fingerprint of a saved set: from its manifest, or measured where none was written."""
    try:
        saved = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        return {Path(f["path"]).name.lower(): f["fingerprint"] for f in _files_of(saved)}
    except (OSError, ValueError, KeyError):
        pass
    sys.path.insert(0, str(HERE))
    from pack_resolver import fingerprint, DRAWING_EXT
    out = {}
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in DRAWING_EXT:
                st = p.stat()
                out[p.name.lower()] = fingerprint(p, st.st_size, st.st_mtime)
    except OSError:
        pass
    return out


def compare(wanted: Dict[str, str], saved: Dict[str, str]) -> Dict[str, List[str]]:
    return {"added": sorted(set(wanted) - set(saved)), "removed": sorted(set(saved) - set(wanted)),
            "changed": sorted(k for k in set(wanted) & set(saved) if wanted[k] != saved[k])}


def store(manifest: Dict[str, Any], client: str, root: Optional[Path] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Save the pack (or find it already saved). Returns where, which version and what changed;
    the same facts are written into the manifest beside the files."""
    root = root or store_root()
    now = now or datetime.now()
    drawing = manifest.get("drawing") or "pack"
    base = root / _safe(client or manifest.get("client") or "Unknown client") / _safe(drawing)
    files = _files_of(manifest)
    wanted = {Path(f["path"]).name.lower(): f["fingerprint"] for f in files}
    versions = _versions(base)
    if versions:
        last_n, last = versions[-1]
        diff = compare(wanted, _saved_prints(last))
        if not any(diff.values()):
            result = {"state": "unchanged", "folder": str(last), "version": last_n, "changes": diff}
            if not (last / MANIFEST).exists():
                _write(last, manifest, result, now)
            return result
        target = base.parent / f"{base.name} v{last_n + 1}"
        state, number = "changed", last_n + 1
    else:
        target, state, number, diff = base, "new", 1, compare(wanted, {})
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        src = Path(f["path"])
        dst = target / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    result = {"state": state, "folder": str(target), "version": number, "changes": diff,
              "previous": str(versions[-1][1]) if versions else None}
    _write(target, manifest, result, now)
    return result


def _write(folder: Path, manifest: Dict[str, Any], result: Dict[str, Any], now: datetime) -> None:
    out = dict(manifest, stored=dict(result, at=now.isoformat(timespec="seconds")))
    (folder / MANIFEST).write_text(json.dumps(out, indent=1), encoding="utf-8")


def stored_files(result: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    """The saved copies of the pack's files, which is what a run is given to read."""
    folder = Path(result["folder"])
    return [str(folder / Path(f["path"]).name) for f in _files_of(manifest)]
