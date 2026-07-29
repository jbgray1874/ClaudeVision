"""
cad_inputs.py — what CAD was in the job folder, and what the engine did with each file.

WHY THIS EXISTS. The engine reads .pdf, .dxf and the three SolidWorks document types, and
silently ignores everything else. A customer sending DWG flat patterns therefore gets an
estimate built from the PDF alone — with transcribed blanks and inferred cut lengths —
while the measured geometry sat unread in the same folder. Nothing in the output said so,
because nothing was looking.

Two jobs, both about the same question:

  CONVERT   DWG is DXF's binary sibling. The ODA File Converter turns it into DXF offline,
            in bulk, for free, and the result feeds the reader we already have. A DWG flat
            pattern is a measured outline we were throwing away.

  DECLARE   Everything else — STEP, IGES, Parasolid, STL — is named in the output as present
            and unread. Not parsed: those formats carry geometry and no part numbers, no
            quantities, no material, and a STEP of a folded part has no flat pattern in it.
            But an estimator deciding whether to trust a number deserves to know a file they
            supplied was never opened.

Nothing here parses geometry. It answers "what was in the folder, and what happened to it".
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

SCHEMA = "cad_inputs.v1"

# Read directly by the engine today.
READ_NATIVELY = {".pdf", ".dxf"}
READ_BY_SOLIDWORKS = {".sldprt", ".sldasm", ".slddrw"}

# Convertible into something we read. DWG is the whole list, and the only one worth it: it
# is the same geometry as a DXF in a different container.
CONVERTIBLE = {".dwg"}

# Present in fabrication folders, carrying geometry and nothing an estimate needs. Named so a
# reader knows they were seen and skipped, rather than missed.
KNOWN_UNREAD = {".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".sat", ".stl", ".3dm"}

# Working copies, backups and the analyser's own output are not customer inputs.
_IGNORED_NAMES = ("~$", ".~", "_sw_native_extract")


def _is_noise(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(".") or any(tok in name for tok in _IGNORED_NAMES)


def inventory(folder: Path, *, converted: Optional[Sequence[Path]] = None) -> Dict[str, Any]:
    """Every CAD file in the folder, grouped by what the engine does with it.

    `converted` names files produced by conversion, so a DXF we made from a DWG is not
    reported as if the customer supplied it.
    """
    folder = Path(folder)
    made = {Path(p).resolve() for p in (converted or [])}
    out: Dict[str, List[str]] = {"read": [], "solidworks": [], "converted": [],
                                 "unread": [], "unknown": []}
    if not folder.is_dir():
        return {"schema": SCHEMA, "folder": str(folder), "present": False, **out}

    for path in sorted(folder.rglob("*")):
        if not path.is_file() or _is_noise(path):
            continue
        ext = path.suffix.lower()
        if path.resolve() in made:
            out["converted"].append(path.name)
        elif ext in READ_NATIVELY:
            out["read"].append(path.name)
        elif ext in READ_BY_SOLIDWORKS:
            out["solidworks"].append(path.name)
        elif ext in KNOWN_UNREAD or ext in CONVERTIBLE:
            out["unread"].append(path.name)
        elif ext in (".xlsx", ".xls", ".docx", ".msg", ".eml", ".txt", ".csv", ".zip"):
            continue                      # correspondence and workbooks, not CAD
        else:
            out["unknown"].append(path.name)
    return {"schema": SCHEMA, "folder": str(folder), "present": True, **out}


# ── DWG -> DXF ───────────────────────────────────────────────────────────────────────
# The ODA File Converter is a free standalone tool. It is called rather than linked, so a
# missing installation degrades to "not converted, and here is why" instead of an exception.
_ODA_ARGS = ("ACAD2018", "DXF", "0", "1")     # output version, format, recurse, audit


def find_converter(explicit: Optional[str] = None) -> Optional[str]:
    """Locate the ODA File Converter, or None. Checked in order: an explicit path, config,
    the PATH, then the usual install roots."""
    if explicit and Path(explicit).is_file():
        return str(explicit)
    try:
        import config
        cfg = getattr(config, "DWG_CONVERTER_PATH", None)
        if cfg and Path(cfg).is_file():
            return str(cfg)
    except Exception:
        pass
    found = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
    if found:
        return found
    for root in (r"C:\Program Files\ODA", r"C:\Program Files (x86)\ODA"):
        base = Path(root)
        if not base.is_dir():
            continue
        for exe in sorted(base.glob("*/ODAFileConverter.exe")):
            return str(exe)
    return None


def convert_dwgs(
    folder: Path,
    out_dir: Optional[Path] = None,
    *,
    converter: Optional[str] = None,
    runner: Optional[Callable[[List[str]], int]] = None,
) -> Dict[str, Any]:
    """Convert every DWG in `folder` to DXF, returning what was produced and what was not.

    `runner` exists so this can be driven without the executable present: the conversion is
    an external process, and a function that can only be tested on a machine with a
    particular program installed is a function nobody tests.

    Never raises into the run. A conversion that cannot happen is reported, not thrown — the
    job still estimates from the PDF, exactly as it does today, and the output says why the
    DWGs were not used.
    """
    folder = Path(folder)
    dwgs = [p for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix.lower() in CONVERTIBLE and not _is_noise(p)]
    result: Dict[str, Any] = {"schema": SCHEMA, "found": [p.name for p in dwgs],
                              "converted": [], "converted_paths": [], "reason": ""}
    if not dwgs:
        return result

    exe = converter or find_converter()
    if not exe and runner is None:
        # NOT "these flat patterns". A job folder's DWGs are whatever the customer sent, and
        # they are not all part flats — a GA sheet is the DWG equivalent of the PDF, and
        # 12120's only DWG is exactly that. Promising measured blanks from files nobody has
        # opened is the same over-claim the engine exists to stop.
        result["reason"] = (
            f"{len(dwgs)} DWG file(s) found and not converted: the ODA File Converter was not "
            f"located. It is a free standalone download; set config.DWG_CONVERTER_PATH to its "
            f"executable, or put it on PATH. Until then nothing has read them — if any are "
            f"part flat patterns, those parts are being sized from drawing text instead.")
        return result

    out_dir = Path(out_dir or (folder / "_dxf_from_dwg"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["reason"] = f"could not create the conversion output folder: {exc}"
        return result

    cmd = [str(exe), str(folder), str(out_dir), *_ODA_ARGS, "*.DWG"]
    try:
        code = runner(cmd) if runner else subprocess.call(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    except Exception as exc:                 # a broken converter must not stop the estimate
        result["reason"] = f"the DWG converter failed to run ({exc}); the DWGs were not used."
        return result

    produced = [p for p in sorted(out_dir.rglob("*.dxf")) if p.is_file()]
    result["converted"] = [p.name for p in produced]
    result["converted_paths"] = [str(p) for p in produced]
    if not produced:
        result["reason"] = (
            f"the DWG converter ran (exit {code}) but produced no DXF. The files may be "
            f"3D DWGs, which hold no flat pattern, or a version the converter cannot read.")
    elif len(produced) < len(dwgs):
        result["reason"] = (f"{len(dwgs) - len(produced)} of {len(dwgs)} DWG file(s) produced "
                            f"no DXF and were not used.")
    return result


if __name__ == "__main__":
    # Verify a DWG setup without running a job.
    #
    #     python src\cad_inputs.py "K:\...\12120-01-GA- DIGITAL TICKETING BRACKET"
    #
    # Prints what is in the folder, whether the converter was found, what it produced, and
    # whether each converted file would be accepted as a part flat pattern. A setup you
    # cannot check is not a setup: the failure mode this guards against is a converter that
    # runs, writes files nobody reads, and leaves the estimate exactly as it was.
    import sys

    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: python cad_inputs.py <job folder> [--no-convert]")
        raise SystemExit(2)

    _folder = Path(" ".join(a for a in sys.argv[1:] if not a.startswith("--")).strip('"'))
    if not _folder.is_dir():
        print(f"Not a folder: {_folder}")
        raise SystemExit(2)

    _exe = find_converter()
    print(f"\nODA File Converter : {_exe or 'NOT FOUND'}")
    if not _exe:
        print("   Install the free ODA File Converter, or set config.DWG_CONVERTER_PATH to "
              "its executable.")

    _conv: Dict[str, Any] = {"converted_paths": []}
    if "--no-convert" not in sys.argv:
        _conv = convert_dwgs(_folder)
        if _conv.get("found"):
            print(f"\nDWG found          : {len(_conv['found'])}")
            for _n in _conv["found"][:12]:
                print(f"   {_n}")
            print(f"DWG converted      : {len(_conv.get('converted') or [])}")
        if _conv.get("reason"):
            print(f"\n   {_conv['reason']}")

    _inv = inventory(_folder, converted=[Path(p) for p in _conv.get("converted_paths") or []])
    for _key, _label in (("read", "read directly"), ("solidworks", "read by SolidWorks"),
                         ("converted", "converted from DWG"), ("unread", "PRESENT, NOT READ"),
                         ("unknown", "unrecognised")):
        _items = _inv.get(_key) or []
        if _items:
            print(f"\n{_label} ({len(_items)}):")
            for _n in _items[:15]:
                print(f"   {_n}")

    # The step that decides whether a conversion was worth anything: a converted file still
    # has to look like a part's flat pattern, or nothing will measure it.
    if _conv.get("converted_paths"):
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from drawing_job_merge import is_flat_part_dxf
            print("\nwould be used as a part flat pattern:")
            for _p in _conv["converted_paths"]:
                _ok = is_flat_part_dxf(Path(_p))
                print(f"   {'YES' if _ok else 'no '}  {Path(_p).name}"
                      + ("" if _ok else "   (GA sheet, or no part number in the filename)"))
        except ImportError:
            pass
    print()
