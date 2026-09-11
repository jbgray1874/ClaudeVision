"""Is this machine actually able to run the engine? Checked from requirements.txt, at startup.

THE RUN THIS EXISTS BECAUSE OF. On a box whose environment had lost two packages, launching the
engine produced, in this order: a four-line warning that every catalogue and history price was
missing (pyodbc), a timing table reporting that the first phase "STARTED AND NEVER FINISHED",
and then a traceback ending

    RuntimeError: pdfplumber is not installed.

raised from inside page extraction, after the scan had already begun. Three separate symptoms of
one fact — two required packages were absent — and not one of them said so plainly or named the
command that fixes it. requirements.txt had listed both as core-required all along. The file
declared the contract; nothing enforced it.

So this reads requirements.txt and checks it. Two properties matter more than the checking:

  DERIVED, NOT DUPLICATED. The list of required packages is parsed from requirements.txt itself,
  under its own "Core pipeline (required)" heading. A second hand-written list in here would
  drift from the first, and a dependency added to one and not the other is precisely the kind of
  silent gap this module is about.

  THE DISTRIBUTION IS NOT THE MODULE. `pip install PyMuPDF` gives you `import fitz`;
  python-dotenv gives `dotenv`; Pillow gives `PIL`. That mapping cannot be derived from the
  name, so it is written out explicitly here and a test asserts it covers every required line in
  requirements.txt — adding a dependency without saying how to import it fails the suite rather
  than silently going unchecked.

Platform markers are honoured: pywin32 is required on Windows and irrelevant elsewhere, so a
Linux CI run is not told it is missing a package it must not have.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

# The heading in requirements.txt that opens the required block, and the one that closes it.
# Matched on the words rather than a line number so reformatting the file does not silently
# empty this check.
_REQUIRED_HEADING = re.compile(r"core pipeline \(required\)", re.I)
_OPTIONAL_HEADING = re.compile(r"optional / feature-specific", re.I)

# DISTRIBUTION NAME -> the module you actually import. Not derivable from the name, so stated.
# A required distribution missing from here is a test failure, not a silent pass.
IMPORT_NAME: Dict[str, str] = {
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "pyodbc": "pyodbc",
    "ezdxf": "ezdxf",
    "shapely": "shapely",
    "pdfplumber": "pdfplumber",
    "PyMuPDF": "fitz",
    "pandas": "pandas",
    "python-dotenv": "dotenv",
    "requests": "requests",
    "Pillow": "PIL",
    "openai": "openai",
    "pywin32": "win32com",
}

# WHAT BREAKS WITHOUT IT, keyed by the MODULE name (the thing imported), not the
# distribution. In the words of the failure it actually produces. A preflight that
# says "pdfplumber is missing" is better than a traceback; one that says what stops working is
# better still, because it tells whoever reads it whether they can proceed at all.
CONSEQUENCE: Dict[str, str] = {
    "pdfplumber": "no PDF text at all — every page reads as empty and the scan dies inside "
                  "page extraction",
    # KEYED BY MODULE, consistently — the lookup is by module name, so an entry filed under the
    # DISTRIBUTION ("PyMuPDF") was never found and that package's consequence went unstated.
    # Caught by this module's own test rather than in use.
    "fitz": "no PDF rendering or page images — the vision BOM reader has nothing to look at",
    "pyodbc": "SDILive/UDEF unreachable: every catalogue and history price is MISSING, not "
              "zero, and the unit cost is costed from fallbacks only",
    "openpyxl": "the estimate workbook cannot be written or read back, so there are no "
                "calculated totals and no money-bearing record",
    "ezdxf": "no DXF geometry — flat patterns, blanks and bend lines are all unavailable",
    "shapely": "no net-area or nesting geometry",
    "pandas": "tabular handling unavailable across several readers",
    "dotenv": "configuration in .env is not loaded, so credentials and flags fall back to "
              "defaults without saying so",
    "requests": "no web or LLM price lookups",
    "PIL": "no image handling — logos and page rasters fail",
    "openai": "the VISION BOM reader cannot run, so every BOM is read by one reader instead "
              "of two and the drawing's own parts list may go unread",
    "xlrd": "legacy .xls manual estimate sheets cannot be read for comparison",
    "win32com": "SolidWorks native extraction is unavailable (Windows only)",
}


# FATAL vs DEGRADING, AND THE LIST IS EVIDENCE-BASED. Stopping the run for every missing
# required package would be its own overreach: a box without `openai` reads every BOM with one
# reader instead of two, which is worse than two and far better than nothing, and refusing to
# run at all would turn a degraded estimate into no estimate. So only packages whose absence
# provably raises on the core scan path are fatal. Today that is pdfplumber — extract_with_
# pdfplumber raises RuntimeError and the scan dies inside page extraction, which is exactly the
# failure that prompted this module. A package joins this set when a failure proves it belongs,
# not when it looks important.
FATAL = {"pdfplumber"}


def _platform_applies(marker: str) -> bool:
    """Honour a PEP 508 marker we actually use. Only sys_platform is in requirements.txt, and
    guessing at a marker language we do not use would be worse than not supporting it."""
    marker = (marker or "").strip()
    if not marker:
        return True
    match = re.match(r"sys_platform\s*(==|!=)\s*['\"]([^'\"]+)['\"]", marker)
    if not match:
        return True                  # an unrecognised marker is not grounds to skip a check
    operator, value = match.group(1), match.group(2)
    return (sys.platform == value) if operator == "==" else (sys.platform != value)


def required_distributions(path: Path = REQUIREMENTS) -> List[str]:
    """Every distribution requirements.txt marks as core-required on THIS platform."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:                                                    # noqa: BLE001
        return []
    out: List[str] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            if _REQUIRED_HEADING.search(line):
                inside = True
            elif _OPTIONAL_HEADING.search(line):
                inside = False
            continue
        if not inside or not line:
            continue
        # strip a trailing inline comment, then split off any marker
        spec = line.split("#", 1)[0].strip()
        if not spec:
            continue
        name, _, marker = spec.partition(";")
        name = re.split(r"[<>=!~\[]", name.strip(), 1)[0].strip()
        if name and _platform_applies(marker):
            out.append(name)
    return out


def check(path: Path = REQUIREMENTS) -> Dict[str, Any]:
    """{ok, missing:[{distribution, module, consequence}], unmapped:[...], checked:[...]}"""
    required = required_distributions(path)
    missing: List[Dict[str, str]] = []
    unmapped: List[str] = []
    checked: List[str] = []
    for dist in required:
        module = IMPORT_NAME.get(dist)
        if not module:
            # NAMED, NOT SKIPPED. An unmapped requirement is unchecked, and an unchecked
            # requirement reads exactly like a satisfied one.
            unmapped.append(dist)
            continue
        checked.append(dist)
        try:
            importlib.import_module(module)
        except Exception:                                                # noqa: BLE001
            missing.append({"distribution": dist, "module": module,
                            "consequence": CONSEQUENCE.get(module, "")})
    fatal = [m for m in missing if m["distribution"] in FATAL]
    degrading = [m for m in missing if m["distribution"] not in FATAL]
    return {
        # can the engine run at all?
        "can_run": not fatal,
        # is the environment complete? A degraded run is a legitimate run and a reduced one.
        "ok": not missing and not unmapped,
        "fatal": fatal, "degrading": degrading, "missing": missing,
        "unmapped": unmapped, "checked": checked,
        "requirements": str(path),
    }


def describe_environment(result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What to stamp onto the saved record: which declared packages this run did NOT have.

    Same principle as money_provenance. An estimate produced on a box without pyodbc is costed
    from fallbacks and is a perfectly legitimate diagnostic — what must never happen is somebody
    reading that record later and taking its figures for catalogue prices. A warning on a console
    nobody kept is not a record; the record has to say it itself.
    """
    result = result if result is not None else check()
    return {
        "schema": "environment.v1",
        "complete": bool(result["ok"]),
        "missing": [{"package": m["distribution"], "consequence": m["consequence"]}
                    for m in result["missing"]],
        "unverified": list(result["unmapped"]),
        "why_it_matters": ("every figure this run produced was computed without the packages "
                          "listed above. Their consequences are stated so a reader does not "
                          "have to infer what was degraded."
                          if result["missing"] else
                          "every declared package was present"),
    }


def report(result: Optional[Dict[str, Any]] = None, log=print) -> bool:
    """Print the verdict. Returns True when the engine can run, False when it cannot.

    A degraded environment returns True and says what it lost: the run is worth having and the
    loss has to be declared. A fatal one returns False BEFORE the scan starts, rather than
    dying part-way through it with a bare RuntimeError from inside page extraction.
    """
    result = result if result is not None else check()
    if result["ok"]:
        log(f"   [preflight] {len(result['checked'])} required package(s) present")
        return True

    def _install_line(items):
        names = " ".join(i["distribution"] for i in items)
        # THE INTERPRETER, NAMED. On the box this module was written for, the packages were
        # installed and the run still failed: `.venv\Scripts\python.exe -c "import pdfplumber,
        # pyodbc, win32com.client"` printed ok while `python src\main.py` raised "pdfplumber is
        # not installed". Two Pythons, and nothing on screen said which one was running — so
        # "the packages are installed" and "the packages are installed where this run can see
        # them" were indistinguishable. `pip install` alone repeats the mistake; the executable
        # that is actually short of them is the one to install into.
        log(f"     This run is using:   {sys.executable}")
        log(f"     Install into THAT interpreter:")
        log(f"         \"{sys.executable}\" -m pip install {names}")
        log(f"     Or everything declared:")
        log(f"         \"{sys.executable}\" -m pip install -r {result['requirements']}")
        log(f"     If that path is not the venv you expected, the run was launched with the "
            f"wrong Python.")

    if result["fatal"]:
        log("")
        log("   " + "=" * 72)
        log("   THIS MACHINE CANNOT RUN THE ENGINE — a required package is missing.")
        log("   " + "=" * 72)
        for item in result["fatal"]:
            log(f"     MISSING  {item['distribution']}  (import {item['module']})")
            if item["consequence"]:
                log(f"              without it: {item['consequence']}")
        _install_line(result["fatal"] + result["degrading"])
        log("")
        log("   Stopping BEFORE the scan rather than part-way through it. The previous")
        log("   behaviour was a traceback from inside page extraction, after sixteen files")
        log("   had been found and one had started.")
        log("   " + "=" * 72)
        log("")
        return False

    log("")
    log("   " + "-" * 72)
    log("   THIS RUN IS DEGRADED — declared packages are missing. It will complete, and")
    log("   what it could not do is recorded on the estimate itself.")
    for item in result["degrading"]:
        log(f"     MISSING  {item['distribution']}  (import {item['module']})")
        if item["consequence"]:
            log(f"              without it: {item['consequence']}")
    for dist in result["unmapped"]:
        log(f"     UNCHECKED  {dist} — requirements.txt requires it and "
            f"dependency_preflight has no import name for it, so it was NOT verified")
    if result["degrading"]:
        _install_line(result["degrading"])
    log("   " + "-" * 72)
    log("")
    return True


__all__ = ["REQUIREMENTS", "IMPORT_NAME", "CONSEQUENCE", "FATAL",
           "required_distributions", "check", "report", "describe_environment"]
