"""Where a resolved drawing pack is kept: Live Enquiry\\<client>\\<drawing>, re-used if unchanged (JG, 9 Nov 2026).

    K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\<client>\\<drawing>          the first set
    ...\\Live Enquiry\\<client>\\<drawing> v2, v3 ...                                    a changed set

Every entry point (the estimating page, AI Estimate Self-Running, the tracker pricer) saves its
pack here through store(). The pack's files are compared with the latest set already saved for
that client and drawing, by name and fingerprint:

  re-extracted  THE RULE SINCE 15 NOV 2026 (JG: "we need to re extract"): every run copies the
              pack from W: again. A saved extract is never trusted as it stands. The same pack
              is copied over its saved copy in the same folder (a missing file comes back); a
              pack that differs goes whole into a new version folder, as "changed" below.
  unchanged   only with fresh=False: the saved set is used as it is, after every file of it has
              been found in the folder (one that is absent is copied in: "restored")
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
          now: Optional[datetime] = None, fresh: bool = True) -> Dict[str, Any]:
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
        # A FOLDER A PERSON MADE IS NEVER SUPERSEDED (JG, 10 Nov 2026): one with no manifest of
        # ours that differs from the design pack is the estimator's pack; it is used as it is
        # and nothing is filed beside it (12674-01-GA v2 held a lone DXF beside the full pack).
        if any(diff.values()) and not (last / MANIFEST).exists() \
                and any(p.is_file() for p in last.iterdir()):
            return {"state": "kept by hand", "folder": str(last), "version": last_n,
                    "changes": diff}
        if fresh and not any(diff.values()):
            # EVERY RUN TAKES THE PACK FROM W: AGAIN (JG, 15 Nov 2026: "no, we need to re
            # extract. we know the drawing extracts we did were rubbish"). A pack saved on
            # 10 Nov without its top-level drawing was handed to a run on 15 Nov as it stood.
            # A saved extract is no longer trusted: each file discovery found now is copied
            # over the saved copy of it, into the same folder, so Live Enquiry\<client>\<drawing>
            # holds the pack as it is on W: today. A pack that differs from the saved one is
            # copied whole into a new version folder, further down, so the earlier set is never
            # overwritten. A file in the folder that is not in today's pack is left where it is,
            # named in the manifest, and not handed to the run. A pack a person made (no
            # manifest of ours, and different) is left alone, above.
            for f in files:
                shutil.copy2(Path(f["path"]), last / Path(f["path"]).name)
            sys.path.insert(0, str(HERE))
            from pack_resolver import DRAWING_EXT
            extra = sorted(p.name for p in last.iterdir() if p.is_file()
                           and p.suffix.lower() in DRAWING_EXT and p.name.lower() not in wanted)
            result = {"state": "re-extracted", "folder": str(last), "version": last_n,
                      "changes": diff, "copied": len(files)}
            if extra:
                result["not_in_todays_pack"] = extra
            _write(last, manifest, result, now)
            return result
        if not any(diff.values()):
            # UNCHANGED IS WHAT IS IN THE FOLDER, NOT WHAT ITS MANIFEST SAYS (15 Nov 2026).
            # 12736-00-01's saved pack listed the top-level assembly PDF and the file was not
            # there. The set was called unchanged on the manifest's word, the run was handed a
            # path with nothing at it, and the estimate was made without the GA. Every file of
            # the pack is now looked for where it is saved; one that is absent is copied in
            # again from where discovery found it, and that is said. If it cannot be copied the
            # error goes up and the row is held.
            absent = [f for f in files if not (last / Path(f["path"]).name).is_file()]
            for f in absent:
                shutil.copy2(Path(f["path"]), last / Path(f["path"]).name)
            result = {"state": "restored" if absent else "unchanged", "folder": str(last),
                      "version": last_n, "changes": diff}
            if absent:
                result["restored"] = sorted(Path(f["path"]).name for f in absent)
            if absent or not (last / MANIFEST).exists():
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
    if result.get("state") == "kept by hand":
        # A PACK A PERSON MADE IS READ AS IT STANDS: the drawing files that are in it, not the
        # names of the design pack's files, which may not be there.
        sys.path.insert(0, str(HERE))
        from pack_resolver import DRAWING_EXT
        try:
            return [str(p) for p in sorted(folder.iterdir())
                    if p.is_file() and p.suffix.lower() in DRAWING_EXT]
        except OSError:
            return []
    return [str(folder / Path(f["path"]).name) for f in _files_of(manifest)]


def not_there(paths: Any) -> List[str]:
    """The names of the files a run would be handed that are not where they are said to be."""
    return [Path(str(p)).name for p in paths if not Path(str(p)).is_file()]


def top_level_absent(manifest: Dict[str, Any], paths: Any) -> str:
    """'' when the pack's own top-level drawing is among the files a run is handed; else its
    name. The top-level drawing is the member the pack is named for; its PDF is the sheet
    every other drawing hangs from, so an estimate without it is not an estimate of the job."""
    want = str(manifest.get("drawing") or "").strip().lower()
    top = next((m for m in manifest.get("members") or []
                if str(m.get("drawing") or "").strip().lower() == want), None)
    pdf = next((f for f in (top or {}).get("files") or []
                if str(f.get("format") or Path(f["path"]).suffix.lstrip(".")).lower() == "pdf"), None)
    if not want or pdf is None:
        return ""
    names = {Path(str(p)).name.lower() for p in paths if Path(str(p)).is_file()}
    name = Path(pdf["path"]).name
    if name.lower() in names or any(n.endswith(".pdf") and n.startswith(want) for n in names):
        return ""
    return name
