#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""printable_converters.py — turn anything a person could print into a PDF.

PRINT SHOULD MEAN PRINT.

`drawings_print` merged PDFs and named everything else on a cover page. That is honest but thin:
a job folder holds a finishing spec, a customer's notes, a site photo, a cut list and a flat
pattern, and an estimator reviewing an estimate wants all of it. Being told five of six files
were "not a drawing" is not the same as being handed the pack.

So each format that a person could send to a printer gets a converter here, and `drawings_print`
merges whatever comes back. The registry is the whole design: one place that says what we can
turn into paper, one contract, and formats added one at a time without touching the merge.

THREE OUTCOMES, AND THEY MEAN DIFFERENT THINGS.

  a PDF path           it converted; merge it
  ConversionUnavailable this MACHINE cannot do it — Word is not installed, ezdxf is missing.
                        Nothing is wrong with the file. Says so, names what is missing.
  ConversionFailed      this FILE could not be converted — corrupt, password-protected, empty.

The distinction matters on the cover. "Word is not installed on this machine" tells somebody how
to fix it. "could not be converted" about the same file tells them to look at the file. Collapsing
the two produces a message that helps with neither.

WHERE THIS RUNS, WHICH DECIDES WHAT WORKS.

Office conversion drives Word and Excel through COM, and COM needs an interactive desktop —
the same constraint that makes the estimate runner a Scheduled Task rather than a Windows
Service. On the laptop, where the runner logs on interactively, it works. On SDI-APP01, where
the portal is an NSSM service in session 0, it will not, and it must degrade to a line on the
cover rather than an exception. Every converter here is guarded for exactly that.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

__all__ = [
    "ConversionUnavailable", "ConversionFailed", "converter_for",
    "CONVERTIBLE_SUFFIXES", "describe_suffix", "convert",
]


class ConversionUnavailable(RuntimeError):
    """This machine cannot convert this kind of file. The file is fine."""


class ConversionFailed(RuntimeError):
    """This particular file could not be converted."""


# ── plain text ────────────────────────────────────────────────────────────────

# A4 at 72 dpi, with a margin wide enough to survive a stapler.
_PAGE_W, _PAGE_H = 595, 842
_MARGIN = 56
_LEADING = 13
_FONT_SIZE = 9.5
# Enough of a very long file to be useful without printing a log all afternoon. A file that hits
# this says so on its last page rather than stopping silently.
_MAX_TEXT_LINES = 2000


def _text_to_pdf(src: Path, out: Path) -> Path:
    """Lay a text file out as pages. No dependency beyond PyMuPDF, which is already required."""
    try:
        import pymupdf                                              # noqa: F401
    except ImportError as exc:
        raise ConversionUnavailable("PyMuPDF is not installed on this machine") from exc
    import pymupdf

    try:
        raw = src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ConversionFailed(f"could not be read ({type(exc).__name__})") from exc

    lines: List[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        # Wrap rather than clip. A CSV row running off the right edge is a row nobody can check.
        while len(line) > 110:
            lines.append(line[:110])
            line = line[110:]
        lines.append(line)
    truncated = len(lines) > _MAX_TEXT_LINES
    if truncated:
        lines = lines[:_MAX_TEXT_LINES]

    doc = pymupdf.open()
    per_page = int((_PAGE_H - 2 * _MARGIN) // _LEADING)
    try:
        for start in range(0, max(len(lines), 1), per_page):
            page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
            y = _MARGIN
            if start == 0:
                page.insert_text((_MARGIN, y), src.name, fontsize=11, fontname="hebo")
                y += 22
            for text in lines[start:start + per_page]:
                page.insert_text((_MARGIN, y), text, fontsize=_FONT_SIZE, fontname="cour")
                y += _LEADING
        if truncated:
            page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
            page.insert_text((_MARGIN, _MARGIN),
                             f"{src.name} continues past {_MAX_TEXT_LINES} lines and was cut "
                             f"off here.", fontsize=10, fontname="hebo")
        doc.save(str(out))
    finally:
        doc.close()
    return out


# ── images ────────────────────────────────────────────────────────────────────

def _image_to_pdf(src: Path, out: Path) -> Path:
    """One image, one page, fitted to A4 with its aspect kept and its filename beneath it."""
    try:
        import pymupdf
    except ImportError as exc:
        raise ConversionUnavailable("PyMuPDF is not installed on this machine") from exc

    try:
        img = pymupdf.open(str(src))
        pdf_bytes = img.convert_to_pdf()
        img.close()
    except Exception as exc:                                        # noqa: BLE001
        raise ConversionFailed(f"could not be read as an image ({type(exc).__name__})") from exc

    doc = pymupdf.open("pdf", pdf_bytes)
    try:
        doc.save(str(out))
    finally:
        doc.close()
    return out


# ── DXF and DWG ───────────────────────────────────────────────────────────────

def _dxf_to_pdf(src: Path, out: Path) -> Path:
    """Render a DXF as a page, using ezdxf's own PyMuPDF backend.

    Both libraries are already required by the engine, so a flat pattern reaches the paper with
    no new dependency. Fit to the page rather than to scale: an A4 sheet at 1:1 shows a corner of
    a display panel, and a reviewer wants to see the whole part.
    """
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext, layout, pymupdf as backend_mod
    except ImportError as exc:
        raise ConversionUnavailable(
            "ezdxf's drawing add-on is not available on this machine — DXF pages need "
            "ezdxf 1.1 or newer") from exc

    try:
        doc = ezdxf.readfile(str(src))
    except Exception as exc:                                        # noqa: BLE001
        raise ConversionFailed(f"is not a readable DXF ({type(exc).__name__})") from exc

    try:
        msp = doc.modelspace()
        backend = backend_mod.PyMuPdfBackend()
        # PAPER IS WHITE. MODEL SPACE IS BLACK.
        #
        # RenderContext honours the DXF's own background, and a CAD model space is black with
        # light entities on it — which is right on a screen and wrong on every printer. The
        # page came out a solid dark sheet with pale lines: unreadable under strip lighting,
        # and it would empty a toner cartridge across a pack of eleven drawings.
        #
        # BLACK on WHITE rather than merely inverting: a DXF carries entity colours by layer,
        # and a set of mid-greys and yellows that read fine on black are close to invisible on
        # white. A drawing sent to a printer is a line drawing, so every line is drawn in ink.
        _cfg = None
        try:
            from ezdxf.addons.drawing.config import (BackgroundPolicy, ColorPolicy,
                                                     Configuration)
            _cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                                 color_policy=ColorPolicy.BLACK)
        except Exception:                                       # noqa: BLE001
            _cfg = None                 # older ezdxf: render as before rather than not at all
        _frontend = (Frontend(RenderContext(doc), backend, config=_cfg) if _cfg is not None
                     else Frontend(RenderContext(doc), backend))
        _frontend.draw_layout(msp, finalize=True)
        page = layout.Page(0, 0, layout.Units.mm, layout.Margins.all(10))
        Path(out).write_bytes(backend.get_pdf_bytes(page))
    except Exception as exc:                                        # noqa: BLE001
        raise ConversionFailed(f"could not be rendered ({type(exc).__name__})") from exc
    return out


def _dwg_to_pdf(src: Path, out: Path) -> Path:
    """DWG via the ODA File Converter, then down the DXF path.

    ODA is free, offline and needs no SOLIDWORKS seat — which is the point of it. The engine
    already knows where it is, and this reads the same setting so one install serves both.
    """
    try:
        import config                                               # the engine's config
        exe = getattr(config, "DWG_CONVERTER_PATH", None)
    except Exception:                                               # noqa: BLE001
        exe = None
    if not exe or not Path(exe).exists():
        raise ConversionUnavailable(
            "DWG needs the ODA File Converter, which is not configured on this machine "
            "(set SDI_DWG_CONVERTER in .env)")

    workdir = Path(out).parent / f"_dwg_{src.stem}"
    indir, outdir = workdir / "in", workdir / "out"
    indir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        (indir / src.name).write_bytes(src.read_bytes())
        # ODA's CLI: in, out, output version, output type, recurse, audit
        subprocess.run([str(exe), str(indir), str(outdir), "ACAD2018", "DXF", "0", "1"],
                       check=False, capture_output=True, timeout=180)
    except Exception as exc:                                        # noqa: BLE001
        raise ConversionFailed(f"the DWG converter did not run ({type(exc).__name__})") from exc

    produced = sorted(outdir.glob("*.dxf")) + sorted(outdir.glob("*.DXF"))
    if not produced:
        raise ConversionFailed("the DWG converter produced no DXF")
    return _dxf_to_pdf(produced[0], out)


# ── Office ────────────────────────────────────────────────────────────────────

_OFFICE_APPS = {
    ".doc": "Word", ".docx": "Word", ".rtf": "Word", ".odt": "Word",
    ".xls": "Excel", ".xlsx": "Excel", ".xlsm": "Excel", ".ods": "Excel",
    ".ppt": "PowerPoint", ".pptx": "PowerPoint", ".odp": "PowerPoint",
}


def _office_to_pdf_inprocess(src: Path, out: Path) -> Path:
    """Export through the Office application itself, which is the only faithful renderer.

    WHY COM AND NOT A LIBRARY. No Python library renders .docx the way Word does, and an
    estimator comparing a spec against a drawing needs the document as its author saw it, not an
    approximation of it. Office is already on the machine that runs estimates, and the engine
    already drives Excel through COM to read the workbook.

    WHAT THAT COSTS. COM needs an interactive desktop. On SDI-APP01, where the portal runs as a
    service in session 0, this raises ConversionUnavailable and the file is named on the cover —
    which is the honest outcome, and the same one as before this module existed.
    """
    app_name = _OFFICE_APPS.get(src.suffix.lower())
    if app_name is None:
        raise ConversionUnavailable(f"no Office application handles '{src.suffix}'")
    if sys.platform != "win32":
        raise ConversionUnavailable(
            f"{app_name} conversion needs Windows — this is {sys.platform}")
    try:
        import pythoncom                                            # noqa: F401
        import win32com.client                                      # noqa: F401
    except ImportError as exc:
        raise ConversionUnavailable(
            "pywin32 is not installed, so Office documents cannot be converted") from exc

    import pythoncom
    import win32com.client

    wd_pdf, xl_pdf, pp_pdf = 17, 0, 2                               # Office export-format codes
    pythoncom.CoInitialize()
    app = None
    try:
        before = _office_pids()
        try:
            app = win32com.client.DispatchEx(f"{app_name}.Application")
        except Exception as exc:                                    # noqa: BLE001
            raise ConversionUnavailable(
                f"{app_name} could not be started on this machine — it may not be installed, "
                f"or this process has no interactive desktop") from exc
        # RECORD WHAT WE STARTED, so a timeout kills that and nothing else. COM returns no handle
        # on the process, so the only way to know is what appeared between these two lines.
        try:
            started = _office_pids() - before
            if len(started) == 1:
                _pid_file(out).write_text(str(started.pop()), encoding="utf-8")
        except Exception:                                           # noqa: BLE001
            pass                        # no marker means the timeout kills nothing. Correct.
        try:
            app.Visible = False
        except Exception:                                           # noqa: BLE001
            pass                        # Excel refuses this in some versions; harmless either way
        try:
            if app_name == "Word":
                doc = app.Documents.Open(str(src), ReadOnly=True)
                try:
                    doc.SaveAs(str(out), FileFormat=wd_pdf)
                finally:
                    doc.Close(False)
            elif app_name == "Excel":
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(str(src), ReadOnly=True, UpdateLinks=0)
                try:
                    wb.ExportAsFixedFormat(xl_pdf, str(out))
                finally:
                    wb.Close(False)
            else:
                pres = app.Presentations.Open(str(src), WithWindow=False, ReadOnly=True)
                try:
                    pres.SaveAs(str(out), pp_pdf)
                finally:
                    pres.Close()
        except Exception as exc:                                    # noqa: BLE001
            raise ConversionFailed(
                f"{app_name} could not export it ({type(exc).__name__})") from exc
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:                                       # noqa: BLE001
                pass
        pythoncom.CoUninitialize()

    if not Path(out).exists():
        raise ConversionFailed(f"{app_name} reported success but wrote no file")
    return out


# How long one document gets before we conclude Office is not coming back. A big spreadsheet can
# legitimately take a while; a modal dialog takes forever. This is the line between them.
OFFICE_TIMEOUT_SECONDS = 90


# OFFICE CONVERSION IS OFF UNLESS SOMEBODY ASKS FOR IT.
#
# It is the only converter that drives another application. Everything else here is a library
# call that either works or raises; Office opens Word or Excel, which can show a dialog, wait on a
# file lock, or sit in Protected View — none of which this process can see or answer.
#
# It hung the first real print, and the second. Defaulting it OFF means Print is reliable for the
# formats that cannot hang — drawings, text, images — and the fragile path is one somebody chose.
# Set SDI_PRINT_OFFICE=1 to turn it on.
OFFICE_ENABLED = os.getenv("SDI_PRINT_OFFICE", "").strip().lower() in {"1", "true", "yes", "on"}


def _office_to_pdf(src: Path, out: Path) -> Path:
    """Run the Office conversion in a CHILD PROCESS, with a timeout.

    THIS IS NOT DEFENSIVE PROGRAMMING, IT IS THE FIRST THING THAT HAPPENED. The first pack printed
    with Office conversion enabled hung on the estimating page — spreadsheets in the file list,
    Excel opened through COM, and something in it raised a dialog nobody could see. A COM call
    waiting on a modal dialog blocks UNINTERRUPTIBLY: no timeout, no KeyboardInterrupt, no way to
    give up. The print never returned.

    In-process there is no fix for that. `subprocess` can be killed; a blocked COM call cannot.
    So the conversion runs in a child, the parent waits `OFFICE_TIMEOUT_SECONDS`, and a child that
    has not finished is killed and reported as a file that could not be converted. One spreadsheet
    that upsets Excel then costs one line on the cover instead of the whole pack.

    The child is this module, run as a script — see `main()` at the bottom.
    """
    app_name = _OFFICE_APPS.get(src.suffix.lower())
    if app_name is None:
        raise ConversionUnavailable(f"no Office application handles '{src.suffix}'")
    if not OFFICE_ENABLED:
        raise ConversionUnavailable(
            f"{app_name} documents are not printed by default — converting them opens {app_name} "
            f"itself, which can stall on a dialog nobody can see. Set SDI_PRINT_OFFICE=1 to "
            f"include them.")
    if sys.platform != "win32":
        raise ConversionUnavailable(
            f"{app_name} conversion needs Windows — this is {sys.platform}")

    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--office", str(src), str(out)],
            capture_output=True, text=True, timeout=OFFICE_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        _kill_stray_office(out)
        raise ConversionFailed(
            f"{app_name} did not respond within {OFFICE_TIMEOUT_SECONDS}s — it may have opened a "
            f"dialog. The file was left out rather than holding up the print.") from None

    if proc.returncode == 0 and Path(out).exists():
        return Path(out)
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    last = detail[-1] if detail else f"exit code {proc.returncode}"
    # The child prints one marker line so the parent can keep the two meanings apart.
    if last.startswith("UNAVAILABLE:"):
        raise ConversionUnavailable(last[len("UNAVAILABLE:"):].strip())
    raise ConversionFailed(last[:200] if last else f"{app_name} produced no file")


def _pid_file(out: Path) -> Path:
    """Where the child records the Office process it started, so only that one is ever killed."""
    return Path(out).with_suffix(".office-pid")


def _kill_stray_office(out: Path) -> None:
    """Kill ONLY the Office process this conversion started.

    THE FIRST VERSION OF THIS KILLED EVERY EXCEL, WORD AND POWERPOINT ON THE MACHINE, on the
    reasoning that "nobody is working in Excel while a print is running". That was wrong the first
    time it ran: it closed a Word document that had been open since the previous afternoon and a
    PowerPoint deck, neither of anything to do with the print. An assumption about how somebody
    uses their own laptop is not a safety mechanism.

    So the child records the process id it created — snapshot before, diff after, since COM hands
    back no handle — and only that id is killed. If the file is absent, or the id has already
    gone, NOTHING is killed. A stray Office process that hangs the next conversion is a far
    smaller problem than shutting a document somebody is working in.
    """
    if sys.platform != "win32":
        return
    marker = _pid_file(out)
    try:
        pid = int(marker.read_text(encoding="utf-8").strip())
    except Exception:                                               # noqa: BLE001
        return                          # nothing recorded — kill nothing, deliberately
    finally:
        try:
            marker.unlink()
        except OSError:
            pass
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20)
    except Exception:                                               # noqa: BLE001
        pass


def _office_pids() -> set:
    """Process ids of the Office applications currently running, for the before/after diff."""
    if sys.platform != "win32":
        return set()
    found = set()
    for image in ("EXCEL.EXE", "WINWORD.EXE", "POWERPNT.EXE"):
        try:
            res = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV",
                                  "/NH"], capture_output=True, text=True, timeout=20)
        except Exception:                                           # noqa: BLE001
            continue
        for line in (res.stdout or "").splitlines():
            parts = [p.strip('" ') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                found.add(int(parts[1]))
    return found


# ── the registry ──────────────────────────────────────────────────────────────

# suffix -> (what it is, in words for the cover page, converter)
_REGISTRY: Dict[str, Tuple[str, Callable[[Path, Path], Path]]] = {}


def _register(suffixes: Tuple[str, ...], what: str,
              fn: Callable[[Path, Path], Path]) -> None:
    for s in suffixes:
        _REGISTRY[s] = (what, fn)


_register((".txt", ".csv", ".log", ".md", ".ini", ".cfg"), "a text file", _text_to_pdf)
_register((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"),
          "an image", _image_to_pdf)
_register((".dxf",), "a DXF drawing", _dxf_to_pdf)
_register((".dwg",), "a DWG drawing", _dwg_to_pdf)
_register((".doc", ".docx", ".rtf", ".odt"), "a Word document", _office_to_pdf)
_register((".xls", ".xlsx", ".xlsm", ".ods"), "a spreadsheet", _office_to_pdf)
_register((".ppt", ".pptx", ".odp"), "a presentation", _office_to_pdf)

CONVERTIBLE_SUFFIXES = frozenset(_REGISTRY)


def converter_for(suffix: str) -> Optional[Callable[[Path, Path], Path]]:
    entry = _REGISTRY.get(str(suffix or "").lower())
    return entry[1] if entry else None


def describe_suffix(suffix: str) -> Optional[str]:
    """What this kind of file is, in words a cover page can use."""
    entry = _REGISTRY.get(str(suffix or "").lower())
    return entry[0] if entry else None


def convert(src: Path, out: Path) -> Path:
    """Convert `src` to a PDF at `out`. Raises ConversionUnavailable / ConversionFailed."""
    fn = converter_for(Path(src).suffix)
    if fn is None:
        raise ConversionUnavailable(f"nothing here converts '{Path(src).suffix}'")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return fn(Path(src), Path(out))


def _office_child_main(argv: List[str]) -> int:
    """The child process the Office dispatcher spawns. One document, then exit.

    It prints a single marker line on failure so the parent can keep ConversionUnavailable and
    ConversionFailed apart across a process boundary — an exception type does not survive one, and
    the difference between "Word is not installed" and "this file is corrupt" is the whole value
    of the cover line.
    """
    src, out = Path(argv[0]), Path(argv[1])
    try:
        _office_to_pdf_inprocess(src, out)
    except ConversionUnavailable as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    except ConversionFailed as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:                                        # noqa: BLE001
        print(f"could not be converted ({type(exc).__name__})", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":                                          # pragma: no cover
    if len(sys.argv) >= 4 and sys.argv[1] == "--office":
        raise SystemExit(_office_child_main(sys.argv[2:4]))
    print(__doc__)
    raise SystemExit(0)
