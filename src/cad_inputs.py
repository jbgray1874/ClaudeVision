"""
cad_inputs.py — what CAD was in the job folder, and what the engine did with each file.

WHY THIS EXISTS. The engine reads .pdf, .dxf and the three SolidWorks document types, and
silently ignores everything else. A customer sending DWG flat patterns therefore gets an
estimate built from the PDF alone — with transcribed blanks and inferred cut lengths —
while the measured geometry sat unread in the same folder. Nothing in the output said so,
because nothing was looking.

Two jobs, both about the same question:

  CONVERT   DWG is DXF's binary sibling. Turned into DXF it feeds the reader we already
            have, so a DWG flat pattern stops being a measured outline we throw away.

            TWO BACKENDS, BECAUSE THE FIRST ONE CAN BE UNREACHABLE. The ODA File Converter
            is free, batch and offline — and it has to be downloaded from a host that this
            network blocks, browser and winget alike, so on the machine that needs it the
            answer to "install the converter" was "you cannot". A capability that depends on
            a vendor's website being reachable is not a capability.

            SolidWorks is the second backend and it was here all along: the runner must have
            a licensed interactive seat anyway, because Excel and SOLIDWORKS are driven over
            COM on a real desktop. A machine that can estimate can convert. It is slower per
            file and it needs the seat, which is why ODA stays first when present.

  DECLARE   Everything else — STEP, IGES, Parasolid, STL — is named in the output as present
            and unread. Not parsed: those formats carry geometry and no part numbers, no
            quantities, no material, and a STEP of a folded part has no flat pattern in it.
            But an estimator deciding whether to trust a number deserves to know a file they
            supplied was never opened.

Nothing here parses geometry. It answers "what was in the folder, and what happened to it".
"""
from __future__ import annotations

import os
import re
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
# Windows and macOS leave these in every folder they touch. They are not customer
# input and listing them as "unrecognised" trains a reader to skim past the section
# where a real unread file would appear.
_IGNORED_NAMES = ("~$", ".~", "_sw_native_extract", "thumbs.db", "desktop.ini",
                  ".ds_store")


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

    # The same filename can exist in two places under one job folder. Reporting only the
    # name makes two copies look like one file listed twice, which reads as a bug in the
    # listing rather than as what it is — a duplicate that may or may not be identical.
    _files = [p for p in sorted(folder.rglob("*")) if p.is_file() and not _is_noise(p)]
    _seen: Dict[str, int] = {}
    for p in _files:
        _seen[p.name] = _seen.get(p.name, 0) + 1

    def _label(p: Path) -> str:
        if _seen.get(p.name, 0) < 2:
            return p.name
        try:
            return str(p.relative_to(folder))
        except ValueError:
            return str(p)

    for path in _files:
        ext = path.suffix.lower()
        if path.resolve() in made:
            out["converted"].append(_label(path))
        elif ext in READ_NATIVELY:
            out["read"].append(_label(path))
        elif ext in READ_BY_SOLIDWORKS:
            out["solidworks"].append(_label(path))
        elif ext in KNOWN_UNREAD or ext in CONVERTIBLE:
            out["unread"].append(_label(path))
        elif ext in (".xlsx", ".xls", ".docx", ".msg", ".eml", ".txt", ".csv", ".zip"):
            continue                      # correspondence and workbooks, not CAD
        else:
            out["unknown"].append(_label(path))
    return {"schema": SCHEMA, "folder": str(folder), "present": True, **out}


# ── WHAT AN UNOPENED DWG APPEARS TO BE ───────────────────────────────────────────────

# A general-arrangement sheet says so in its name. Whole words, because "GA" inside a part
# code is not a statement about the drawing.
_GA_MARKERS = ("GA", "GENERAL ARRANGEMENT", "ASSY", "ASSEMBLY", "LAYOUT", "ELEVATION")
_GA_RE = re.compile(r"(?<![A-Z0-9])(?:%s)(?![A-Z0-9])"
                    % "|".join(m.replace(" ", r"\s+") for m in _GA_MARKERS))


def dwg_class(path: Any) -> str:
    """What a DWG appears to be, from its name alone: "flat", "general_arrangement", "unknown".

    THE COST OF A MISSING CONVERTER IS NOT THE SAME FOR EVERY DWG, AND THE FLAG SAID IT WAS.
    "4 DWG unread" reads as four missing measurements and sends somebody hunting an installer.
    On 11650-04 it was two general arrangements of a job we had already read as PDF plus two
    sheets the content gate declined — the expected value of converting them was nothing, and
    I spent an afternoon on a converter before checking that.

    THE TWO CLASSES ARE WORTH ENTIRELY DIFFERENT AMOUNTS.

      A FLAT PATTERN is the strongest input this engine can be handed short of a model: it
      converts to a DXF and lands as measured geometry at rank 80 — blank, cut length, pierce
      count, bend lines. On a pack with no SolidWorks models it is the difference between
      costing a part and sizing it from drawing text.

      A GENERAL ARRANGEMENT is worth approximately nothing. It converts to a DXF of viewports,
      dimensions and title-block text — the same content as the PDF of the same sheet, which
      is already read. Possibly worth less than nothing, if a viewport rectangle is taken for
      a blank.

    READ THROUGH THE CONVENTION THAT ALREADY SUPPLIES MATERIAL AND GAUGE, not a second idea of
    what a filename means. `11650-04-01A_2MM PETG_REVG` names a gauge and a material because
    the drawing office names flats that way — the same reading that now stands beside the title
    block as evidence. A name that carries both IS the convention's statement that this is the
    stock a part is cut from.

    THE GA MARKER IS CHECKED FIRST. A sheet that says GA has said so deliberately; where a name
    somehow carries both, the explicit word beats the inferred pair.

    Never raises, and answers "unknown" rather than guessing — a pack that names nothing by any
    convention is a fact about the pack, not a class to invent.
    """
    try:
        stem = Path(path).stem.upper().replace("_", " ").replace("-", " ")
        if _GA_RE.search(stem):
            return "general_arrangement"
        from drawing_job_merge import material_from_dxf_filename, thickness_mm_from_dxf_filename
        p = Path(path)
        if material_from_dxf_filename(p) and thickness_mm_from_dxf_filename(p) is not None:
            return "flat"
    except Exception:
        return "unknown"
    return "unknown"


def classify_dwgs(names: Sequence[Any]) -> Dict[str, List[str]]:
    """The same names, grouped by what each appears to be. Empty groups are omitted so a
    caller can print only what is there."""
    out: Dict[str, List[str]] = {}
    for n in names or ():
        out.setdefault(dwg_class(n), []).append(str(n))
    return {k: v for k, v in out.items() if v}


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


def convert_dwgs_with_solidworks(
    dwgs: Sequence[Path],
    out_dir: Path,
    *,
    export: Optional[Callable[[Path, Path], bool]] = None,
) -> Dict[str, Any]:
    """DWG -> DXF through the SolidWorks seat the runner already has.

    `export` exists so this can be driven without SolidWorks installed: the conversion is one
    COM call per file, and a function that can only be tested on a machine with a particular
    CAD package is a function nobody tests. Production passes nothing and gets the real one.

    NEVER RAISES. A seat that is busy, absent or refusing costs the DWGs, not the estimate --
    the job still runs from the PDFs exactly as it does today, and the output says why.

    ONE DOCUMENT AT A TIME, CLOSED AFTER. This runs on somebody's actual desktop, beside the
    estimate that is using the same seat. Leaving drawings open would put a modal dialog in
    front of the next COM call the engine makes, which is the kind of failure that gets
    blamed on the estimate rather than on this.
    """
    out: Dict[str, Any] = {"converted": [], "converted_paths": [], "reason": "", "files": []}
    dwgs = [Path(p) for p in dwgs]
    if not dwgs:
        return out
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        out["reason"] = f"could not create the conversion output folder: {exc}"
        return out

    _export = export or _solidworks_dxf_export
    failed: List[str] = []
    session_lost = ""
    for dwg in dwgs:
        target = out_dir / (dwg.stem + ".dxf")
        record: Dict[str, Any] = {"dwg": dwg.name, "backend": "solidworks",
                                  "converted": False, "dxf": None, "reason": ""}
        if session_lost:
            record["reason"] = f"not attempted — {session_lost}"
            out["files"].append(record)
            continue
        try:
            ok = bool(_export(dwg, target))
        except Exception as exc:                # noqa: BLE001 -- a CAD seat may fail any way
            failed.append(f"{dwg.name} ({type(exc).__name__}: {exc})")
            record["reason"] = f"{type(exc).__name__}: {exc}"
            out["files"].append(record)
            # A FAULTED COM SERVER DOES NOT RECOVER BY BEING ASKED AGAIN. 11650-04 reported
            # the identical RPC failure four times because the session died on the first file
            # and the other three were calls into a corpse -- four alarming lines describing
            # one event. And this is the estimate's OWN SolidWorks session: continuing to
            # hammer it is how a converter takes down the run it was meant to help.
            if _is_com_fault(exc):
                session_lost = ("the SolidWorks COM session faulted on "
                                f"{dwg.name} ({exc}) and was not asked again")
            continue
        if ok and target.is_file():
            out["converted"].append(target.name)
            out["converted_paths"].append(str(target))
            record.update(converted=True, dxf=target.name)
        else:
            failed.append(dwg.name)
            record["reason"] = ("SolidWorks reported success but wrote no DXF" if ok
                                else "SolidWorks would not open it")
        out["files"].append(record)

    if session_lost:
        out["reason"] = (
            f"the ODA File Converter was not found, and {session_lost}. A COM fault here is "
            f"usually SolidWorks not running, running as a different user, or busy with a "
            f"modal dialog — check the SolidWorks window on the runner. The estimate is "
            f"unaffected; these DWGs were not read.")
    elif not out["converted"]:
        out["reason"] = (
            f"the ODA File Converter was not found, and SolidWorks could not convert the "
            f"{len(dwgs)} DWG file(s) either"
            + (f" ({'; '.join(failed[:3])})" if failed else "")
            + ". Nothing has read them — if any are part flat patterns, those parts are "
              "being sized from drawing text instead.")
    elif failed:
        out["reason"] = (f"SolidWorks converted {len(out['converted'])} of {len(dwgs)} DWG "
                         f"file(s); {len(failed)} would not open: {', '.join(failed[:3])}")
    return out


# COM faults, as opposed to a file SolidWorks simply would not open. -2147023170 is
# RPC_S_CALL_FAILED: the server went away mid-call, which means the session is gone and the
# next file will fail the same way for a reason that has nothing to do with it.
_COM_FAULT_CODES = (-2147023170, -2147417848, -2147023174, -2146959355)


# ── WHY THE SEAT COULD NOT BE ATTACHED TO, AS A FACT RATHER THAN A SHRUG ────────────
#
# "SolidWorks is either not running, or is running in a different logon session from this
# runner. Both look identical from here."
#
# That sentence is true of GetActiveObject and useless to the person reading it. James, on a
# paid seat that was open at the time: "we can't be having these issues with SolidWorks. the
# company is paying for this subscription. it needs to work." He is right, and the engine's
# part of it is that it stopped looking at the exact point where looking is cheap.
#
# The two cases are NOT identical from here — they are only identical to COM. Windows will say
# whether SLDWORKS.exe is running, under which user, and in which logon session, and this
# process knows its own. Comparing them turns an unactionable error into one instruction.
#
# STDLIB ONLY. psutil is not a dependency of this engine and adding one to print a better
# error message is the wrong trade; tasklist has carried session and user since XP.

def this_process() -> Dict[str, Any]:
    """Our own logon session and user, for comparison with SolidWorks'."""
    out: Dict[str, Any] = {"session": None, "user": None}
    try:
        import ctypes
        _sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(_sid)):
            out["session"] = int(_sid.value)
    except Exception:                                      # noqa: BLE001
        pass
    out["user"] = os.environ.get("USERNAME") or ""
    return out


def solidworks_processes() -> Optional[List[Dict[str, str]]]:
    """Every SLDWORKS.exe on this machine with its user and session.

    None means WE COULD NOT LOOK, which must never be reported as "none running" — that is the
    same inference-printed-as-observation this whole function exists to stop.
    """
    try:
        raw = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=20, check=False).stdout
    except Exception:                                      # noqa: BLE001
        return None
    if not raw or "SLDWORKS" not in raw.upper():
        # tasklist prints an INFO line when a filter matches nothing; that is a real answer.
        return [] if raw else None
    import csv, io
    out: List[Dict[str, str]] = []
    try:
        for row in csv.reader(io.StringIO(raw)):
            # Image Name, PID, Session Name, Session#, Mem, Status, User Name, ...
            if len(row) < 7 or not row[0].upper().startswith("SLDWORKS"):
                continue
            out.append({"pid": row[1].strip(), "session": row[3].strip(),
                        "user": (row[6].split("\\")[-1] or "").strip()})
    except Exception:                                      # noqa: BLE001
        return None
    return out


def attach_failure_reason(procs: Optional[List[Dict[str, str]]],
                          me: Dict[str, Any],
                          elevated: Optional[bool]) -> str:
    """One sentence naming the actual cause, and what to do about it.

    Ordered by what the reader can act on soonest, and every branch ends in an instruction.
    A diagnosis with no next step is the message this replaces.
    """
    if elevated:
        # Checked first: an elevated runner cannot see an ordinary SolidWorks however plainly
        # it is on screen, and no amount of process detail changes the answer.
        return ("This runner is ELEVATED and SolidWorks almost certainly is not: an "
                "administrator process cannot see an ordinary one in the Running Object "
                "Table. Start the runner from a NORMAL PowerShell, or install it as the "
                "scheduled task (tools\\start\\install-runner-task.ps1), which runs "
                "unelevated in your own desktop session.")
    if procs is None:
        return ("SolidWorks is either not running, or is running in a different logon session "
                "from this runner, and this process could not query the machine to find out "
                "which.")
    if not procs:
        return ("SLDWORKS.exe is NOT RUNNING on this machine — nothing was there to attach "
                "to. Open SolidWorks in this desktop session and re-run.")

    _my_session = me.get("session")
    _my_user = str(me.get("user") or "")
    _same = [p for p in procs
             if str(p.get("session") or "") == str(_my_session)
             and p.get("user", "").lower() == _my_user.lower()]
    if _same:
        # Same user, same session, unelevated runner, and still invisible. The only remaining
        # ROT partition is integrity level, so SolidWorks is the elevated one.
        return (f"SolidWorks IS running as {_my_user} in your own session "
                f"(session {_my_session}, PID {_same[0].get('pid')}) and is still not visible, "
                f"which leaves one cause: it was started AS ADMINISTRATOR and this runner was "
                f"not. Close SolidWorks and reopen it normally — not 'Run as administrator'.")
    _where = "; ".join(f"PID {p.get('pid')} as {p.get('user') or '?'} in session "
                       f"{p.get('session') or '?'}" for p in procs[:3])
    return (f"SolidWorks IS running on this machine but not where this runner can reach it: "
            f"{_where}. This runner is {_my_user or '?'} in session {_my_session}. The Running "
            f"Object Table is per logon session, so these cannot see each other. Start the "
            f"runner in the session that owns SolidWorks — the scheduled task from "
            f"tools\\start\\install-runner-task.ps1 does this; a Windows service or NSSM "
            f"never can, because session 0 has no desktop.")


def _is_com_fault(exc: Exception) -> bool:
    args = getattr(exc, "args", ()) or ()
    code = args[0] if args and isinstance(args[0], int) else None
    return code in _COM_FAULT_CODES or "remote procedure call" in str(exc).lower()


def _solidworks_dxf_export(dwg: Path, dxf: Path) -> bool:
    """The real COM call. Windows, pywin32 and a licensed seat, or ImportError/RuntimeError.

    A DWG opens as a DRAWING document (swDocDRAWING = 3) and saves straight back out as DXF.
    The import wizard is what makes this fiddly: shown, it blocks on a desktop nobody is
    watching, and the toggle that suppresses it is version-dependent. Every toggle below is
    attempted and none is required -- a SolidWorks that does not recognise one raises, and a
    conversion that then blocks is caught by the caller as a failure for that file rather
    than a hang for the run.
    """
    import pythoncom                                       # noqa: F401 -- Windows only
    import win32com.client                                 # noqa: F401

    SW_DRW = 3
    OPEN_SILENT_READONLY = 1 | 2

    # NO USER-PREFERENCE TOGGLES. There were two here, 226 and 227, guessed at as the
    # swUserPreferenceToggle_e entries that suppress the DXF/DWG import mapping dialog, and
    # wrapped in try/except on the assumption that a wrong id would raise cleanly.
    #
    # IT DOES NOT RAISE. It faults the COM server: every one of 11650-04's four DWGs came
    # back -2147023170, RPC_S_CALL_FAILED, identically — the session died on the first call
    # and the remaining three were made into a corpse. Worse, that is the SAME SolidWorks
    # session the estimate itself drives, so a guess in a converter could take out the run
    # that was using it.
    #
    # A constant nobody has verified is not a guess with a safety net. It is an instruction
    # to a program that will do what it is told.
    # ATTACH, NEVER LAUNCH. Dispatch() returns a running SolidWorks if one is registered and
    # STARTS ONE if not -- hidden, unlicensed-prompt-prone, and a second seat competing with
    # the estimate for the same desktop. GetActiveObject only ever attaches, so "SolidWorks
    # is not running" comes back as that sentence instead of as a mysterious new process.
    #
    # AND NOT RESTARTED AUTOMATICALLY AFTER A FAULT. Bringing SolidWorks back up is a large
    # side effect on a machine whose whole job is one interactive seat, and the estimate may
    # be mid-COM-call on it. A converter that reboots the tool the run depends on is a worse
    # failure than four unread drawings.
    pythoncom.CoInitialize()
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception as exc:                               # noqa: BLE001
        # WHAT WE KNOW IS THAT WE CANNOT SEE IT, WHICH IS NOT THE SAME AS IT NOT BEING THERE.
        #
        # This said "SolidWorks is not running on this machine" and sent somebody to start an
        # application that was already open, twice. GetActiveObject looks in the Running
        # Object Table, and the ROT is scoped per LOGON SESSION and per INTEGRITY LEVEL — so a
        # runner launched from an elevated PowerShell cannot see a SolidWorks running as the
        # ordinary user, however plainly it is on the screen in front of you. Same machine,
        # same desktop, two tables.
        #
        # MK_E_UNAVAILABLE (0x800401E3 / -2147221021) is exactly that answer and nothing more:
        # not in the table I am allowed to read. Reporting it as a fact about the machine is
        # the same defect this codebase keeps naming — an inference printed as an observation
        # — and here it cost real time on a machine that had a licensed seat open all along.
        _elevated = None
        try:
            import ctypes
            _elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:                                  # noqa: BLE001
            pass
        raise RuntimeError(
            "No SolidWorks seat could be attached to, so there is nothing to convert with. "
            "This does not mean SolidWorks is closed — it means this process could not find "
            f"it in the Running Object Table it is allowed to read. "
            f"{attach_failure_reason(solidworks_processes(), this_process(), _elevated)} "
            f"({exc})")
    errs = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warns = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = sw.OpenDoc6(str(dwg), SW_DRW, OPEN_SILENT_READONLY, "", errs, warns)
    if doc is None:
        raise RuntimeError(f"OpenDoc6 refused it (errs={errs.value} warns={warns.value})")
    title = None
    try:
        title = doc.GetTitle()
        return bool(doc.SaveAs(str(dxf)))
    finally:
        # CLOSED WHATEVER HAPPENED. An open drawing left on that desktop is a modal dialog
        # in front of the next estimate.
        try:
            if title:
                sw.CloseDoc(title)
        except Exception:                                  # noqa: BLE001
            pass


def convert_dwgs(
    folder: Path,
    out_dir: Optional[Path] = None,
    *,
    converter: Optional[str] = None,
    runner: Optional[Callable[[List[str]], int]] = None,
    solidworks: Any = None,
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
    _all_dwgs = [p for p in sorted(folder.rglob("*"))
                 if p.is_file() and p.suffix.lower() in CONVERTIBLE and not _is_noise(p)]

    # ── A GENERAL ARRANGEMENT IS NOT WORTH A COM CALL ──────────────────────────────────
    #
    # dwg_class has been able to tell a flat pattern from a GA since it was written, and its
    # own docstring says a GA "is worth approximately nothing… possibly worth less than
    # nothing, if a viewport rectangle is taken for a blank". It was wired to REPORTING only.
    # Every DWG in the folder was still opened.
    #
    # WHAT THAT COST ON 12552. The pack's only DWG is 12552-00-GA — the general arrangement,
    # the same sheet as the PDF the engine had already read. Converting it was worth nothing,
    # it faulted the COM server (-2147023170, RPC_S_CALL_FAILED), and SolidWorks went down
    # with a crash dialog — taking with it the seat the NATIVE MODEL EXTRACT needs. On a pack
    # with no DXFs, that extract is the only measured geometry there is. The engine spent the
    # seat on the file it had already decided was worthless, and lost the one that mattered.
    #
    # ORDERING WOULD NOT HAVE SAVED IT EITHER. Running the extract first only moves which
    # operation is holding the session when the GA faults it. Not opening the file is the
    # fix; there was never a reason to.
    #
    # SKIPPED, NOT FAILED. It is named in the output as a GA that was deliberately not
    # converted, because "not read" and "not worth reading" are different facts and an
    # estimator chasing unread geometry deserves to know which this is.
    _skipped_ga = [p for p in _all_dwgs if dwg_class(p) == "general_arrangement"]
    dwgs = [p for p in _all_dwgs if p not in _skipped_ga]

    # PER FILE, NOT PER RUN. "converted 2 of 4" is a number an estimator cannot act on: it
    # does not say WHICH two, whether the other two failed or were 3D, or whether the ones
    # that converted were then used. A DWG that silently contributes nothing looks exactly
    # like one that was never there, which is the whole failure this module exists to end.
    result: Dict[str, Any] = {"schema": SCHEMA, "found": [p.name for p in _all_dwgs],
                              "converted": [], "converted_paths": [], "reason": "",
                              "backend": "", "files": [],
                              "skipped_general_arrangement": [p.name for p in _skipped_ga]}
    if _skipped_ga:
        # THE SHAPE THE REST OF THIS LIST USES — dwg / backend / converted / dxf / reason.
        # A second record shape in one list is how a consumer ends up printing "None -> None"
        # for half the rows, which is exactly what the first version of this did.
        result["files"].extend(
            {"dwg": p.name, "backend": "", "converted": False, "dxf": None,
             "reason": "not attempted — a general arrangement, not a flat pattern. The same "
                       "content as the PDF of this sheet, which was read. Converting it adds "
                       "nothing and costs a CAD seat the model extract needs."}
            for p in _skipped_ga)
    if not dwgs:
        return result

    exe = converter or find_converter()
    if not exe and runner is None and solidworks is not False:
        # SECOND BACKEND, TRIED BEFORE GIVING UP. Reported with its own basis so a reader can
        # tell which tool produced these DXFs -- they are not identical in fidelity, and a
        # geometry question six months from now deserves to know which one drew the outline.
        _sw = convert_dwgs_with_solidworks(dwgs, out_dir or (folder / "_dxf_from_dwg"),
                                           export=solidworks)
        result["backend"] = "solidworks"
        result["converted"] = _sw["converted"]
        result["converted_paths"] = _sw["converted_paths"]
        result["reason"] = _sw["reason"]
        result["files"] = result["files"] + _sw["files"]
        return result
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
    result["backend"] = "oda"
    # ODA converts a FOLDER, so the per-file account is reconstructed by stem — the only
    # thing it tells us. A DWG with no DXF of its own name did not convert, whatever the
    # exit code said.
    _by_stem = {p.stem.upper(): p for p in produced}
    result["files"] = result["files"] + [
        {"dwg": d.name, "backend": "oda",
         "converted": d.stem.upper() in _by_stem,
         "dxf": (_by_stem[d.stem.upper()].name if d.stem.upper() in _by_stem else None),
         "reason": ("" if d.stem.upper() in _by_stem
                    else "the converter produced no DXF for this file — it may be a 3D DWG, "
                         "which holds no flat pattern")}
        for d in dwgs]
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
