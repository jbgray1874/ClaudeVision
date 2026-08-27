r"""
sw_native_analyse.py
Analyse .sldprt / .sldasm / .slddrw for BOM + route signals via SolidWorks COM.

Provenance: refined from an assessment + draft provided by SDI (which itself built on
the existing sw_read scripts on \\sdi-dc01\CAD). This supersedes sw_discovery_probe.py
for real extraction: the probe answered "can we open it + coverage matrix"; this answers
"BOM + routes" — component quantities, sheet-metal/weld/hole feature signals mapped to
the estimator's own operation names, and (best-effort) drawing BOM tables.

Accuracy order by source (feed the estimator in this precedence):
  .sldasm  -> part numbers + qty + material + config      (BOM: strongest)
  .sldprt  -> material, thickness, mass, sheet-metal feats (routes: strongest)
  .slddrw  -> released BOM tables + notes (WELD/POWDER/fold callouts)
  .dxf     -> flat-pattern cut length / holes / fold lines (our existing path)
  .pdf     -> free-text notes / Path C bought-in hardware  (our existing dual-path)
  .iges    -> geometry only; NEVER a BOM source, last resort

Reconciliation intent (NOT done here — this is the extractor):
  native qty+material  ∪  DXF geometry  ∪  PDF notes  ->  one job JSON for the estimator.
  Qty from assembly/drawing BOM beats PDF guesses; geometry metrics from DXF beat PDF.

Read-only + non-destructive: opens Silent+ReadOnly, closes every doc it opened, never
Quit()s SolidWorks (a designer may have it open). Logs are English only.

Usage (on a PC with SolidWorks + access to the CAD share):
  python sw_native_analyse.py "\\sdi-dc01\CAD\Design\...\12120 - ...\<folder with .SLDPRT>"
  python sw_native_analyse.py "D:\path\to\file.sldasm"
Writes _sw_native_extract.json next to the target.

NOTE: point it at a folder that actually holds .SLDPRT/.SLDASM. The job's *-Technical
folder is often 2D only (DXF/PDF) — the native models live elsewhere under the job root.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# COM IMPORTED LAZILY. Everything in this file that decides something — which folders are
# the live design, whether a cut-list zero is a value, how a table cell is read — is pure
# Python, and requiring pywin32 to import it meant none of it could be tested anywhere but a
# Windows box with SolidWorks. The regression suite skipped those fixtures silently, which is
# indistinguishable from passing them. The session class imports COM when it is constructed.
try:
    import pythoncom
    import win32com.client
    from win32com.client import VARIANT
    from win32com.client import gencache
    _COM_AVAILABLE = True
except ImportError as _com_exc:          # not Windows, or pywin32 absent
    pythoncom = win32com = VARIANT = gencache = None       # type: ignore
    _COM_AVAILABLE = False
    _COM_IMPORT_ERROR = str(_com_exc)

# SolidWorks doc types
SW_PART = 1
SW_ASM = 2
SW_DRW = 3
DOCTYPE = {
    ".sldprt": SW_PART,
    ".sldasm": SW_ASM,
    ".slddrw": SW_DRW,
}
# OpenDoc6 options: silent (1) + read-only (2).
OPEN_OPTS = 1 | 2

# SldWorks type library GUID (stable across versions); major version is per SW release
# (SW2026 = 34, from the makepy output 83A33D31-...x0x34x0). EnsureModule loads the
# wrappers so CastTo can give early-bound interface access.
SW_TYPELIB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SW_TYPELIB_MAJOR = 34

# The version of the DATA this analyser writes into the extract. Bump it whenever the extract
# gains a field the estimate depends on (v3 added material provenance + the weldment tube
# section). The consumer re-runs the analyser when an extract's stamped version is behind this,
# so a CODE improvement reaches an OLD job automatically — the models never changed, but what we
# read out of them did, and a freshness check that only looks at file dates would reuse a stale
# extract for ever. Kept in step with source_connectors.solidworks._MIN_EXTRACT_SCHEMA_VERSION.
EXTRACT_SCHEMA_VERSION = 3

# Opt-in (--flatten): flatten formed parts in memory to MEASURE the developed blank when
# the cut-list property route yields nothing usable. Off by default because it rebuilds
# every affected model. Read-only either way — the bend state is restored and the document
# closed without saving.
ALLOW_FLATTEN = True

# SW sheet-metal feature type names that each add a bend line (lower-cased). SMBaseFlange
# (flat base) and UnFold/Fold (model flatten/refold ops) are intentionally excluded.
_BEND_FEATURE_TYPES = {
    "edgeflange", "sketchbend", "edgebend", "onebend", "hem",
    "miterflange", "jog", "sweptflange", "crossbreak",
}


_SW_MOD = None


def _sw_mod():
    """The generated gen_py module for the SolidWorks typelib (from makepy/EnsureModule).
    Its interface classes call methods by DISPID, which reaches interface-returning methods
    (FirstFeature, CreateMassProperty) that late-binding's name table does NOT expose."""
    global _SW_MOD
    if _SW_MOD is None:
        _SW_MOD = False
        for _maj in (SW_TYPELIB_MAJOR, 34, 33, 32, 31, 30, 29, 28):
            try:
                m = gencache.GetModuleForTypelib(SW_TYPELIB_GUID, 0, _maj, 0)
                if m is not None:
                    _SW_MOD = m
                    break
            except Exception:
                continue
    return _SW_MOD or None


def _wrap(obj, iface: str):
    """Wrap a raw SW dispatch with the generated interface class (IModelDoc2, IFeature,
    IModelDocExtension, ...) so its methods resolve by DISPID. Returns the wrapped object,
    or the original if the module/class is unavailable."""
    if obj is None:
        return None
    mod = _sw_mod()
    if mod is None:
        return obj
    cls = getattr(mod, iface, None)
    if cls is None:
        return obj
    # The generated class calls _oleobj_.InvokeTypes(DISPID,...) — it needs the RAW
    # PyIDispatch, not the late-bound CDispatch (else '<unknown>.InvokeTypes').
    raw = getattr(obj, "_oleobj_", obj)
    for _candidate in (raw, obj):
        try:
            w = cls(_candidate)
            # sanity: the wrapper must expose InvokeTypes on its _oleobj_
            if getattr(w, "_oleobj_", None) is not None:
                return w
        except Exception:
            continue
    return obj


@dataclass
class BomLine:
    part_number: str
    description: str = ""
    qty: float = 1.0
    config: str = ""
    material: str = ""
    thickness_mm: Optional[float] = None
    file_path: str = ""
    source: str = ""  # assembly_tree | drawing_bom | part_props
    custom_props: Dict[str, str] = field(default_factory=dict)
    # WHOSE CHILD IS THIS. GetComponents(False) returns every component at every level and
    # the BOM aggregates them by document identity, so the tree arrives FLATTENED: the
    # engine learns that 12422-24's assembly contains 05M and never learns that 05M hangs
    # off 102. Everything downstream that has to decide who owns an operation — which
    # assembly a powder event belongs to, which parent carries a child's material — is then
    # reconstructing a hierarchy that the model already knew.
    #
    # Empty means a DIRECT child of the assembly being analysed. Additive: the aggregated
    # `bom` list is unchanged, so no existing reader moves.
    parent_part_number: str = ""
    # 1 part, 2 assembly, 3 drawing — swDocumentTypes_e, as the analyser already reports for
    # the documents it opens. An assembly node must never take material of its own, and
    # knowing that from the model beats inferring it from the word "ASSEMBLY" in a
    # description.
    doc_type: Optional[int] = None


@dataclass
class RouteSignals:
    part_number: str
    is_sheet_metal: bool = False
    bend_count: int = 0
    hole_count_est: int = 0
    flat_pattern_present: bool = False
    has_weldment: bool = False
    # ── Flat pattern, from the SolidWorks cut-list (the estimating prize) ──────────
    # SolidWorks auto-generates cut-list properties on sheet-metal bodies: the FLAT
    # blank length/width, the material thickness and the bend radius. This is exactly
    # what a PDF cannot supply (see docs/Estimating_from_PDFs_vs_CAD) — blank size for
    # material and nesting, thickness for gauge pricing, and a real bend radius.
    flat_length_mm: Optional[float] = None
    flat_width_mm: Optional[float] = None
    bend_radius_mm: Optional[float] = None
    cut_length_mm: Optional[float] = None
    # Set when the solid is demonstrably formed (its smallest bounding-box dimension is
    # far greater than the sheet thickness) but no bend feature was counted. A Base Flange
    # built from a multi-segment sketch bakes its bends in and exposes no bend feature, so
    # feature-counting alone under-reports. Flagged, never silently assumed.
    formed_but_no_bend_features: bool = False
    # True when the feature tree shows imported geometry with no modelled fabrication
    # features (an 'MBimport' body and nothing we would make). That is a supplier-supplied
    # model — a bought-in component, not something SDI fabricates — so it must take no
    # fabrication route. Catches fasteners, PEM inserts, standoffs, connectors.
    likely_bought_in: bool = False
    # ── further cut-list data (present on SDI's sheet-metal cut lists) ────────────
    # Cut length is published split: outer profile + inner cut-outs. Laser time needs the
    # sum, and the split is itself useful (a part that is mostly cut-outs runs differently
    # from one that is mostly profile). Bend COUNT from the cut list resolves parts whose
    # bends are baked into a base flange and cannot be counted from the feature tree.
    cut_length_outer_mm: Optional[float] = None
    cut_length_inner_mm: Optional[float] = None
    cut_out_count: Optional[int] = None
    blank_area_mm2: Optional[float] = None
    bend_allowance_mm: Optional[float] = None
    bend_count_cutlist: Optional[int] = None
    surface_treatment: str = ""
    sheet_gauge: str = ""
    # A tube/hollow-section profile {a, b, t, profile_form, length_mm} read from a WELDMENT
    # cut list — the frame members a sheet-metal read never sees. None on a non-section part.
    section_profile: Optional[Dict[str, Any]] = None
    material: str = ""
    # Where `material` came from: "custom_property" (the designer typed a spec) or
    # "applied_library" (the model's appearance/simulation template, often a default). The
    # waterfall ranks an applied-library material below the drawing's own callout, so an
    # explicit MDF on the drawing is not overruled by a birch-ply appearance on the model.
    material_source: str = ""
    thickness_mm: Optional[float] = None
    mass_kg: Optional[float] = None
    bbox_mm: Optional[Tuple[float, float, float]] = None
    ops_hint: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    feature_types: List[str] = field(default_factory=list)  # diagnostic: raw type names seen


class SolidWorksSession:
    def __init__(self, visible: bool = False):
        if not _COM_AVAILABLE:
            raise RuntimeError(
                f"SolidWorks COM is not available in this Python ({_COM_IMPORT_ERROR}). "
                f"This analyser must run on Windows with pywin32 and SolidWorks installed.")
        pythoncom.CoInitialize()
        # EARLY binding via EnsureDispatch: generates the SolidWorks typelib so no-arg
        # methods like FirstFeature()/GetNextFeature()/GetTypeName2() resolve as real
        # methods. Late-binding Dispatch could not find FirstFeature ('Member not found')
        # — the classic reason SolidWorks automation needs makepy/early binding. Fall back
        # to late Dispatch if typelib generation is unavailable.
        # Load the SolidWorks typelib module by GUID (generated once by makepy). This makes
        # CastTo(obj, "IModelDoc2"/"IFeature"/...) available — the standard SW pattern. We
        # do NOT EnsureDispatch the ProgID (SW's Application object refuses to drive makepy).
        self.early_bound = False
        for _maj in (SW_TYPELIB_MAJOR, 34, 33, 32, 31, 30, 29, 28):
            try:
                gencache.EnsureModule(SW_TYPELIB_GUID, 0, _maj, 0)
                self.early_bound = True
                break
            except Exception:
                continue
        self.sw = win32com.client.Dispatch("SldWorks.Application")
        print(f"[binding] typelib_loaded={self.early_bound} "
              f"(CastTo {'available' if self.early_bound else 'UNAVAILABLE — run makepy on sldworks.tlb'})",
              flush=True)
        self.sw.Visible = visible
        self._open_titles: List[str] = []
        # Documents that were ALREADY open when this run started. We read them; we never
        # close them. Closing a designer's open document is the one irreversible thing this
        # tool could do, and it would take their unsaved work with it.
        self._borrowed_titles: List[str] = []
        # KEPT FOR THE MANIFEST. close_all() clears the per-file list, so the
        # fact that a model was read out of somebody's open session survived
        # only as a console line — and that is the one caveat this extract
        # carries that a freshness fingerprint cannot see.
        self.borrowed_seen: List[str] = []
        # WHETHER THE DOCUMENT open() LAST RETURNED CAME OUT OF SOMEBODY'S SESSION.
        # Flattening is read-only in intent — it restores the bend state and closes without
        # saving — but on a BORROWED document that all happens inside the window a designer
        # is looking at: their part visibly unfolds and refolds, and the rebuild marks their
        # document dirty even though nothing of ours is written. On a document we opened,
        # nobody sees it and nobody is asked to save it on the way out.
        #
        # This is the same distinction close_all() already draws, for the same reason, and
        # it is why acquisition could be turned back on at all.
        self.last_open_borrowed: bool = False

    def open(self, path: str):
        path = os.path.abspath(path) if not path.startswith("\\\\") else path
        ext = os.path.splitext(path)[1].lower()
        doctype = DOCTYPE.get(ext)
        if doctype is None:
            raise ValueError(f"Unsupported extension: {ext}")
        self.last_open_borrowed = False
        errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warns = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        # OWNERSHIP. SolidWorks does not open a document twice: if a designer already has
        # this file open, OpenDoc6 hands back THEIR document, and closing it afterwards
        # closes their work — unsaved changes included. Ask what is already open BEFORE
        # opening anything, and close only what this process actually opened.
        # SHORT-CIRCUIT. Knowing a document is already open and then calling OpenDoc6
        # anyway is what still failed micro_usb_Wire_01 on v7: the assembly load already
        # holds the title, OpenDoc6 refuses with 65536, and the recovery path runs only
        # after the refusal. If we already know SolidWorks has it, take it — do not ask for
        # it a second time and then try to clean up the refusal.
        _trace: List[str] = []
        _existing = self._get_open_document(path, _trace)
        if _existing is not None:
            self._borrowed_titles.append(_safe_str(_get0(_existing, "GetTitle")) or path)
            self.last_open_borrowed = True
            print(f"[reused] {os.path.basename(path)} was already open "
                  f"({'; '.join(_trace)}) — read in place, not reopened")
            return _existing, doctype
        _already = False
        doc = self.sw.OpenDoc6(path, doctype, OPEN_OPTS, "", errs, warns)
        if doc is None:
            # 65536 is swFileWithSameTitleAlreadyOpen. On this job it is not a corrupt file:
            # opening the assemblies FIRST loads their components, so a component opened
            # again by path is refused because SolidWorks already holds a document of that
            # title. micro_usb_Wire_01 failed for exactly this reason and its data was simply
            # lost. The document is right there — take it rather than reporting a failure.
            if int(errs.value or 0) & 65536:
                _trace = []
                doc = self._get_open_document(path, _trace)
                if doc is not None:
                    print(f"[recovered] already-open document reused ({'; '.join(_trace)})")
                    self._borrowed_titles.append(_safe_str(_get0(doc, "GetTitle")) or path)
                    self.last_open_borrowed = True
                    return doc, doctype
                # Say what was tried. A bare "failed" told us nothing last time and cost a
                # whole run to learn no more than that.
                raise RuntimeError(
                    f"OpenDoc6 failed: {path}  errs={errs.value} warns={warns.value} "
                    f"(swFileWithSameTitleAlreadyOpen — a document of this title is open but "
                    f"could not be retrieved; tried: {'; '.join(_trace) or 'nothing'})"
                )
            raise RuntimeError(
                f"OpenDoc6 failed: {path}  errs={errs.value} warns={warns.value}"
            )
        _t = _safe_str(_get0(doc, "GetTitle"))
        self.last_open_borrowed = bool(_already)
        if _t and not _already:
            self._open_titles.append(_t)
        elif _already:
            self._borrowed_titles.append(_t or path)
        return doc, doctype

    def _get_open_document(self, path: str, trace: Optional[List[str]] = None):
        """The already-open document for this path, or None.

        FOUR ROUTES, because the first attempt at this used only the GetFirstDocument walk
        and recovered nothing on 12120 — and a silent None told us only that it had failed,
        not which step had. Each route records what it returned, so a failure is diagnosable
        from the log instead of guessed at:

          1. GetOpenDocumentByName — the documented lookup, and the one that should work.
             Omitting it was the mistake.
          2. GetDocuments() — the whole open-document array, including components loaded
             invisibly as part of an assembly, which is what these actually are.
          3. The GetFirstDocument/GetNext linked walk.
          4. Title match, as a last resort: a component pulled in by an assembly can report
             a title whose path does not resolve identically.
        """
        trace = trace if trace is not None else []
        _target = self._norm(path)
        _stem = os.path.splitext(os.path.basename(path))[0].lower()

        # 1. The documented call.
        for _name in ("GetOpenDocumentByName2", "GetOpenDocumentByName"):
            try:
                d = getattr(self.sw, _name)(path)
                if d is not None:
                    trace.append(f"{_name}: found")
                    return d
                trace.append(f"{_name}: None")
            except Exception as exc:
                trace.append(f"{_name}: raised {type(exc).__name__}")

        # 2. The full array of open documents.
        _by_title = None
        try:
            docs = self.sw.GetDocuments()
            _n = len(docs) if docs is not None else 0
            trace.append(f"GetDocuments: {_n} open")
            for d in (docs or []):
                try:
                    if self._norm(_safe_str(_get0(d, "GetPathName"))) == _target:
                        trace.append("GetDocuments: path match")
                        return d
                    _t = _safe_str(_get0(d, "GetTitle"))
                    if _by_title is None and _t and os.path.splitext(_t)[0].lower() == _stem:
                        _by_title = d
                except Exception:
                    continue
        except Exception as exc:
            trace.append(f"GetDocuments: raised {type(exc).__name__}")

        # 3. The linked walk.
        try:
            d = _get0(self.sw, "GetFirstDocument")
            seen = 0
            while d is not None and seen < 5000:
                seen += 1
                if self._norm(_safe_str(_get0(d, "GetPathName"))) == _target:
                    trace.append(f"GetFirstDocument walk: path match after {seen}")
                    return d
                _t = _safe_str(_get0(d, "GetTitle"))
                if _by_title is None and _t and os.path.splitext(_t)[0].lower() == _stem:
                    _by_title = d
                d = _get0(d, "GetNext")
            trace.append(f"GetFirstDocument walk: {seen} document(s), no path match")
        except Exception as exc:
            trace.append(f"GetFirstDocument walk: raised {type(exc).__name__}")

        # 4. Title, last.
        if _by_title is not None:
            trace.append("matched on title")
        return _by_title

    @staticmethod
    def _norm(path: str) -> str:
        if not path:
            return ""
        try:
            return os.path.normcase(path if str(path).startswith("\\\\")
                                    else os.path.abspath(path))
        except Exception:
            return os.path.normcase(str(path))

    def _is_already_open(self, path: str) -> bool:
        """Was this document open before we asked for it? Compared on the full path, since
        two files in different folders can share a title."""
        _target = self._norm(path)
        try:
            d = self.sw.GetFirstDocument2() if hasattr(self.sw, "GetFirstDocument2") \
                else _get0(self.sw, "GetFirstDocument")
        except Exception:
            d = None
        seen = 0
        while d is not None and seen < 5000:
            seen += 1
            try:
                _p = _safe_str(_get0(d, "GetPathName"))
                if _p and os.path.normcase(_p) == _target:
                    return True
                d = _get0(d, "GetNext")
            except Exception:
                break
        return False

    def close_all(self):
        """Close ONLY the documents this process opened. Anything that was already open when
        we arrived belongs to whoever opened it."""
        for title in reversed(self._open_titles):
            try:
                self.sw.CloseDoc(title)
            except Exception:
                pass
        self._open_titles.clear()
        if self._borrowed_titles:
            for _b in self._borrowed_titles:
                if _b not in self.borrowed_seen:
                    self.borrowed_seen.append(_b)
            print(f"[ownership] left {len(self._borrowed_titles)} document(s) open that "
                  f"were already open before this run: "
                  f"{', '.join(self._borrowed_titles[:5])}")
            self._borrowed_titles.clear()

    def shutdown(self):
        self.close_all()
        try:
            # Deliberately do NOT Quit()/ExitApp() — a designer may have SW open. We
            # only close the docs we opened. On a dedicated batch box you could ExitApp.
            pass
        finally:
            self.sw = None
            pythoncom.CoUninitialize()


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _clean_pn(name: str) -> str:
    """Strip the SolidWorks component instance suffix ('12120-01-02M-1' -> '12120-01-02M')
    so quantities aggregate by part identity, not by instance."""
    return re.sub(r"-\d+$", "", _safe_str(name)).strip()


def _prop(props: Dict[str, str], *aliases: str) -> str:
    """Case-insensitive property lookup by any of several alias names, tolerant of the
    naming variation between designers/templates (Material vs MATERIAL vs 'Material Spec').
    Generic — no per-job hardcoding: tries exact (case-folded) matches first, then a loose
    contains-match. This is what keeps property extraction repeatable across every job."""
    if not props:
        return ""
    low = {str(k).lower().strip(): v for k, v in props.items()}
    for a in aliases:
        v = low.get(a.lower().strip())
        if v:
            return _safe_str(v)
    for a in aliases:
        al = a.lower().strip()
        for k, v in low.items():
            if al in k and v:
                return _safe_str(v)
    return ""


# The material aliases a designer may type into a custom property, in priority order.
_MATERIAL_PROP_ALIASES = ("Material", "Material Description", "Material Spec", "Spec", "Grade")

# Hollow-section words a weldment cut-list member description carries. A frame's tube lives ONLY
# in the weldment cut list — the analyser reads the sheet-metal keys and never these, so the
# tube frame arrived at the estimate empty. Gated on a keyword so a plain part is not read as a
# tube. Matches document_builder._SECTION_HOLLOW_KW so both readers agree on what a section is.
_WELDMENT_SECTION_KW = ("TUBE", "RHS", "SHS", "CHS", "BOX", "HOLLOW", "SECTION",
                        "SQUARE", "RECTANGULAR")
_WELDMENT_PROFILE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)")


def parse_weldment_profile(description: str) -> Optional[Dict[str, Any]]:
    """A hollow-section profile (side_a × side_b × wall) from a weldment cut-list member's
    description — 'TUBE, SQUARE 30 X 30 X 2.6', 'RHS 60 X 40 X 3'.

    Pure: a description string in, a profile out, so it is proven in tests with no SolidWorks.
    The COM read that supplies the description and the member LENGTH needs a seat and is wired
    separately; this is the parse that turns what SolidWorks already knows into the {a, b, t,
    profile_form} the estimator's tube costing consumes.

    The three numbers are ordered so the smallest is the wall thickness; SHS when the two sides
    are equal, RHS otherwise. Gated on a hollow-section keyword AND a wall that is credibly less
    than half of each side, so a plain part ('BRACKET 30 X 30 X 3 PLATE') is not read as a tube.
    Returns None when no section can be read (an honest gap, never a guessed profile)."""
    text = str(description or "").upper()
    if not any(kw in text for kw in _WELDMENT_SECTION_KW):
        return None
    m = _WELDMENT_PROFILE_RE.search(text)
    if not m:
        return None
    try:
        dims = sorted(float(m.group(i)) for i in (1, 2, 3))
    except (TypeError, ValueError):
        return None
    wall, side_a, side_b = dims[0], dims[1], dims[2]
    if wall <= 0 or wall > 12 or side_a <= wall * 2 or side_b <= wall * 2:
        return None
    return {"a": side_a, "b": side_b, "t": wall,
            "profile_form": "SHS" if abs(side_a - side_b) < 1e-6 else "RHS"}


# The cut-list property names a weldment member publishes its size and length under. Read into
# _all_cutlist_props by the SAME COM enumeration that decides the cut-list KIND, so reading them
# needs no new SolidWorks call — the analyser already has them.
_WELDMENT_DESC_KEYS = ("Description", "Part Description", "Desc")
_WELDMENT_LENGTH_KEYS = ("LENGTH", "Length", "Total Length", "Cut Length", "Member Length")


def weldment_section_from_cutlist(all_props: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A tube section {a, b, t, profile_form, length_mm} from a weldment cut-list's OWN
    properties: the member Description carries the profile, LENGTH the cut length.

    Pure: a properties dict in, a section out, so it is proven in tests with no SolidWorks. The
    dict is exactly what the COM enumeration already reads into _all_cutlist_props to decide the
    cut-list kind, so this reads two names the analyser already holds — no new SolidWorks call.
    Returns None when no hollow-section description can be read (an honest gap, never a guessed
    tube). Carries review_section_profile so the estimate flags it for a human, like the drawing-
    text section path does — a cut-list read is strong but a frame's members deserve a check."""
    if not isinstance(all_props, dict) or not all_props:
        return None
    low = {str(k).strip().lower(): v for k, v in all_props.items()}
    desc = ""
    for k in _WELDMENT_DESC_KEYS:
        v = low.get(k.lower())
        if v:
            desc = str(v)
            break
    prof = parse_weldment_profile(desc)
    if not prof:
        return None
    section = dict(prof)
    for k in _WELDMENT_LENGTH_KEYS:
        v = low.get(k.lower())
        _len = _num_mm(v) if v not in (None, "") else None
        if _len and _len > 0:
            section["length_mm"] = _len
            break
    section["detection_path"] = "weldment_cut_list"
    section["source_text"] = desc[:60].strip()
    section["review_section_profile"] = True
    return section


def _material_and_source(props: Dict[str, str], applied: str) -> Tuple[str, str]:
    """The part's material AND where it came from — the split the waterfall needs.

    SolidWorks hands the same material back two ways, and they are not equal evidence. An
    EXPLICIT custom property is the spec the designer typed; it is what the part is bought to,
    so it stays the strongest model source. The library-APPLIED material is the appearance /
    simulation template the model happens to carry — frequently a default nobody revisited
    ("Plain Carbon Steel" on a part the drawing calls MDF, a birch-ply visual on an MDF panel)
    — so it must not overrule the drawing's own callout.

    Returns (material, "custom_property") when a custom property names it, (material,
    "applied_library") when only the applied material does, and ("", "") when the model names
    no material at all. Pure — props is a plain dict and applied a plain string — so this
    decision is verified in tests without a SolidWorks seat, even though the COM calls that
    fill props/applied upstream cannot be."""
    custom = _prop(props, *_MATERIAL_PROP_ALIASES)
    if custom:
        return custom, "custom_property"
    applied = _safe_str(applied)
    if applied:
        return applied, "applied_library"
    return "", ""


def _table_text(table, row: int, col: int) -> str:
    """One cell of a table annotation.

    ITableAnnotation exposes Text2(row, col, useCached) on some builds and Text(row, col) on
    others, and calling the wrong arity raises rather than returning nothing — which is how a
    released drawing BOM came back empty on every row instead of reporting it could not be
    read. Try each form; the first that answers wins."""
    # A LINKED cell — which is what a BOM table's cells are — can return an empty string
    # from Text2 while DisplayedText2 holds the resolved value. Treating the first
    # non-None answer as final therefore accepted "" and never asked the call that would
    # have answered. Keep going until something non-empty comes back.
    for _attempt in (lambda: table.DisplayedText2(row, col, 0),
                     lambda: table.DisplayedText2(row, col),
                     lambda: table.DisplayedText(row, col),
                     lambda: table.Text2(row, col, True),
                     lambda: table.Text2(row, col),
                     lambda: table.Text(row, col)):
        try:
            v = _attempt()
        except Exception:
            continue
        if v is None:
            continue
        _t = _safe_str(v).strip()
        if _t:
            return _t
    return ""


def _get0(obj, name):
    """Read a NO-ARGUMENT SolidWorks getter that late-binding pywin32 may expose as a
    method OR as a property. In this binding GetTitle/GetPathName/FirstFeature/
    GetNextFeature/GetTypeName2/GetModelDoc2/CreateMassProperty resolve as PROPERTIES
    (the value is returned directly), so calling them with () raises 'str object is not
    callable'. This returns the value whether it's a bound method or already the value.
    Arg-taking calls (GetComponents(True), GetBox(0), Text2(r,c)) are left as normal
    method calls — those resolve correctly."""
    try:
        attr = getattr(obj, name)
    except Exception:
        return None
    try:
        return attr() if callable(attr) else attr
    except Exception:
        return None


def get_custom_properties(doc) -> Dict[str, str]:
    """Resolved custom properties from the document manager (config = "" = file level)."""
    out: Dict[str, str] = {}
    try:
        cpm = doc.Extension.CustomPropertyManager("")
    except Exception:
        return out
    names = []
    try:
        # Some pywin32 builds expose GetNames as a method, some as a property.
        raw = cpm.GetNames
        names = list(raw() if callable(raw) else (raw or []))
    except Exception:
        try:
            names = list(cpm.GetNames() or [])
        except Exception:
            names = []
    for n in names:
        if not n:
            continue
        try:
            val = ""
            resolved = ""
            try:
                # Get5(name, useCached, val, resolvedVal, wasResolved) — by-ref out-params
                # must be VARIANT VT_BYREF holders (plain strings silently read nothing).
                v1 = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
                v2 = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
                v3 = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
                cpm.Get5(n, False, v1, v2, v3)
                val = _safe_str(v1.value)
                resolved = _safe_str(v2.value)
            except Exception:
                try:
                    ok, val, resolved = cpm.Get4(n, False, "", "")
                    val, resolved = _safe_str(val), _safe_str(resolved)
                except Exception:
                    continue
            out[n] = resolved or val
        except Exception:
            continue
    return out


def get_bbox_mm(doc, doctype: int) -> Optional[Tuple[float, float, float]]:
    try:
        if doctype == SW_PART:
            box = doc.GetPartBox(True)
        else:
            box = doc.GetBox(False)
        if not box or len(box) < 6:
            return None
        # SW returns metres in most installs.
        w = abs(box[3] - box[0]) * 1000.0
        h = abs(box[4] - box[1]) * 1000.0
        d = abs(box[5] - box[2]) * 1000.0
        return (round(w, 2), round(h, 2), round(d, 2))
    except Exception:
        return None


def flat_pattern_by_flatten(doc, folded_bbox: Optional[Tuple[float, float, float]],
                            thickness_mm: Optional[float],
                            notes: List[str]) -> Optional[Tuple[float, float]]:
    """Measure the DEVELOPED blank by flattening the part in memory, then measuring it.

    Why this exists: the cut-list property route is name-based, and SolidWorks uses the
    name 'Bounding Box Length' for both a sheet-metal flat pattern AND a weldment solid's
    box. On 12120-01-01M it returned the folded envelope (126.39x82.2) where the true
    blank is 132.39x88.2. Flattening and MEASURING cannot be fooled that way — a flattened
    body's bounding box is the blank, by construction.

    Read-only intent, same contract as the mass-property read: SetBendState changes the
    in-memory model only, the original state is restored, and the document is closed
    without saving. Nothing is written to any file.

    SELF-VERIFYING. The swSMBendState_e values differ across versions and we will not
    assert one from memory, so each candidate is tried and the RESULT is checked against
    geometry that only a real flatten can produce:
      1. the box must GROW in at least one axis (material is consumed round a bend), and
      2. its smallest axis must collapse to about the sheet thickness (a flat blank is
         one sheet thick, whereas the folded part stands proud).
    A candidate failing either test is discarded. If none pass, we return nothing rather
    than a number — an honest null beats a plausible fiction.
    """
    if not folded_bbox:
        return None
    part = _wrap(doc, "IPartDoc")
    if part is None:
        return None
    try:
        _orig = _get0(part, "GetBendState")
    except Exception:
        return None
    if _orig is None:
        return None

    _folded_sorted = sorted(folded_bbox, reverse=True)
    best: Optional[Tuple[float, float]] = None
    try:
        for _state in (2, 1, 3):          # candidate 'flattened' values, verified below
            if _state == _orig:
                continue
            try:
                part.SetBendState(_state)
                # ForceRebuild3 TAKES an argument (TopOnly). _get0 calls with none, so
                # the rebuild never happened and we measured the body BEFORE it was rebuilt
                # into its flattened state — silently, because the failure is swallowed.
                try:
                    doc.ForceRebuild3(False)
                except Exception:
                    try:
                        doc.EditRebuild3()
                    except Exception:
                        pass
            except Exception:
                continue
            box = get_bbox_mm(doc, SW_PART)
            if not box:
                continue
            _b = sorted(box, reverse=True)
            _grew = _b[0] > _folded_sorted[0] + 0.05 or _b[1] > _folded_sorted[1] + 0.05
            # A developed blank is exactly one sheet thick. Without a known thickness fall
            # back to "the third axis collapsed a long way", which a real flatten always does.
            if thickness_mm and thickness_mm > 0:
                _thin = abs(_b[2] - thickness_mm) <= max(0.2, thickness_mm * 0.25)
            else:
                _thin = _b[2] < _folded_sorted[2] * 0.5
            if _grew and _thin:
                best = (round(_b[0], 2), round(_b[1], 2))
                notes.append(
                    f"flat pattern MEASURED by flattening in memory: {best[0]}x{best[1]}mm "
                    f"(folded envelope was {_folded_sorted[0]:g}x{_folded_sorted[1]:g}mm; "
                    f"blank is one sheet thick at {_b[2]:g}mm) — bend state {_state}")
                break
            notes.append(
                f"flatten attempt (state {_state}) rejected: box "
                f"{_b[0]:g}x{_b[1]:g}x{_b[2]:g}mm "
                f"{'did not grow' if not _grew else 'is not one sheet thick'}")
    finally:
        try:
            part.SetBendState(_orig)
            try:
                doc.ForceRebuild3(False)
            except Exception:
                pass
        except Exception:
            notes.append("WARNING: could not restore the original bend state in memory "
                         "(document is closed without saving, so the file is unchanged)")
    return best


def get_mass_kg(doc) -> Optional[float]:
    # CreateMassProperty is interface-returning -> wrap IModelDocExtension so it resolves
    # by DISPID; the returned mass-property is wrapped IMassProperty for .Mass.
    ext = _wrap(_get0(doc, "Extension"), "IModelDocExtension")
    for _mk in ("CreateMassProperty2", "CreateMassProperty"):
        try:
            mp = getattr(ext, _mk)()
            mp = _wrap(mp, "IMassProperty")
            mass = float(_get0(mp, "Mass") or 0.0)
            if mass:
                return round(mass, 4)
        except Exception:
            continue
    # Fallback: the older array-returning forms. CreateMassProperty returned nothing on
    # every part of the first real job tested, leaving mass null across the board — and
    # mass is the whole basis of the by-weight costing path. GetMassProperties2 returns
    # [cx, cy, cz, volume, area, mass, ...] with mass in kg (document units are SI).
    for _src, _name in ((ext, "GetMassProperties2"), (ext, "GetMassProperties"),
                        (doc, "GetMassProperties2"), (doc, "GetMassProperties")):
        try:
            res = getattr(_src, _name)(0) if _name.endswith("2") else getattr(_src, _name)()
            if isinstance(res, (list, tuple)) and len(res) >= 6:
                mass = float(res[5] or 0.0)
                if mass:
                    return round(mass, 4)
        except Exception:
            continue
    return None


def _call_or_prop(obj, name):
    """Return obj.name whether it is a method (call it) or a property (value). Unlike
    _get0 this RAISES on error so callers can record why a call failed."""
    attr = getattr(obj, name)
    return attr() if callable(attr) else attr


# Densities used ONLY to resolve the units of the cut-list Mass value (kg vs grams) by
# order of magnitude. Nominal handbook figures; a few percent either way cannot change
# which of two readings a thousand-fold apart is the right one.
_DENSITY_KG_M3 = (
    ("STAINLESS", 8000.0), ("ALUMINI", 2700.0), ("ALUMINU", 2700.0),
    # Wrought alloy designations — a SolidWorks library material is named '6061 Alloy',
    # never 'aluminium', so the family token alone never matches it.
    ("6061", 2700.0), ("6082", 2700.0), ("5251", 2700.0), ("5052", 2700.0),
    ("5083", 2700.0), ("1050", 2700.0), ("1060", 2700.0), ("7075", 2700.0),
    ("BRASS", 8500.0), ("COPPER", 8960.0), ("ZINC", 7140.0),
    ("ACRYLIC", 1190.0), ("PMMA", 1190.0), ("ABS", 1040.0), ("NYLON", 1140.0),
    ("POLYCARB", 1200.0), ("PVC", 1400.0),
    ("MDF", 750.0), ("PLYWOOD", 600.0), ("TIMBER", 500.0),
    # Species names, for the same reason — a title block says OAK, not TIMBER.
    ("OAK", 700.0), ("BEECH", 720.0), ("BIRCH", 660.0), ("PINE", 500.0),
    ("SPRUCE", 450.0), ("BALSA", 160.0), ("PLY", 600.0),
    ("STEEL", 7850.0),          # last: 'STAINLESS STEEL' must match stainless first
)


def _density_kg_m3(material: str) -> Optional[float]:
    u = str(material or "").upper()
    if not u:
        return None
    for token, rho in _DENSITY_KG_M3:
        if token in u:
            return rho
    return None


def _num_mm(value) -> Optional[float]:
    """Parse a cut-list property value to millimetres.

    Cut-list values arrive as display strings ('79.00', '1.5mm', '79'). SolidWorks stores
    these already in the document's display units (mm on these models), so this does NOT
    convert — it only extracts the number. Returns None when nothing numeric is present,
    never a guess.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", s.replace(",", "."))
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    return v if v > 0 else None


def _num_count(value) -> Optional[int]:
    """A COUNT from the cut list, where ZERO is a real answer.

    _num_mm rejects non-positive values, which is right for a length: a blank cannot be 0mm
    long, so a zero there is a failed read. It is wrong for a count. 'Cut Outs = 0' says this
    part is a plain blank with one outer profile and one pierce, and dropping it to None
    turned that statement back into "nobody looked" — the exact confusion the resolver's
    explicit-zero handling exists to end, reintroduced one layer upstream."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", s.replace(",", "."))
    if not m:
        return None
    try:
        v = int(round(float(m.group(0))))
    except ValueError:
        return None
    return v if v >= 0 else None


# Cut-list property names SolidWorks generates for sheet-metal bodies. Spellings vary by
# version/template, so each datum is tried against several candidates.
# Property names confirmed present on SDI's own sheet-metal cut lists (12120 enumeration):
#   Bend Allowance, Bend Radius, Bends, Bounding Box Area, Bounding Box Area-Blank,
#   Bounding Box Length, Bounding Box Width, Cost-TotalCost, Cut Outs,
#   Cutting Length-Inner, Cutting Length-Outer, Description, MATERIAL, Mass, QUANTITY,
#   Sheet Metal Gauge, Sheet Metal Thickness, Surface Treatment
# We were reading four of eighteen. The cut length we had been guessing at ("Cut Length",
# "Perimeter") does not exist under those names — it is split Outer/Inner, which is better:
# outer is the profile, inner is the cut-outs, and laser time needs both. Bend COUNT is
# published too, which resolves parts whose bends are baked into a base flange and cannot
# be feature-counted. Alternative names are kept so other SolidWorks versions still match.
_CUTLIST_KEYS = {
    "flat_length": ("Bounding Box Length", "Sheet Metal Bounding Box Length",
                    "Bounding Box Length@@@", "SW-Bounding Box Length"),
    "flat_width": ("Bounding Box Width", "Sheet Metal Bounding Box Width",
                   "Bounding Box Width@@@", "SW-Bounding Box Width"),
    "thickness": ("Sheet Metal Thickness", "Thickness", "SW-Sheet Metal Thickness"),
    "bend_radius": ("Bend Radius", "Default Bend Radius", "SW-Bend Radius"),
    "cut_length_outer": ("Cutting Length-Outer", "Cut Length-Outer", "Cut Length",
                         "Perimeter", "SW-Cut Length"),
    "cut_length_inner": ("Cutting Length-Inner", "Cut Length-Inner"),
    "bend_count": ("Bends", "Bend Count", "Number of Bends"),
    "cut_out_count": ("Cut Outs", "Cutouts", "Cut Out Count"),
    "blank_area_mm2": ("Bounding Box Area-Blank", "Bounding Box Area"),
    "bend_allowance": ("Bend Allowance",),
    "mass_raw": ("Mass",),
}
# Text-valued cut-list properties — parsed as strings, never through the millimetre reader.
_CUTLIST_TEXT_KEYS = {
    "surface_treatment": ("Surface Treatment", "Finish"),
    "sheet_gauge": ("Sheet Metal Gauge", "Gauge"),
}


def _cutlist_properties(feat, notes: List[str]) -> Dict[str, Any]:
    """Read the cut-list custom properties hanging off a CutListFolder feature.

    This is where SolidWorks puts the flat-pattern bounding box and the sheet thickness —
    the two values a PDF can never supply. The property manager is reached differently
    across SolidWorks versions and binding modes, so several access forms are tried and
    whichever worked is recorded in notes. Returns {} when none succeed (honest null),
    never a fabricated value.
    """
    out: Dict[str, Any] = {}
    cpm = None
    for attr in ("CustomPropertyManager", "GetCustomPropertyManager"):
        try:
            cpm = _call_or_prop(feat, attr)
            if cpm is not None:
                break
        except Exception:
            continue
    if cpm is None:
        return out

    # Refresh the cut list so the auto-properties exist/are current. Read-only intent:
    # this updates in-memory derived data only and the document is closed without saving.
    try:
        bf = _get0(feat, "GetSpecificFeature2")
        if bf is not None:
            for m in ("UpdateCutList", "Update"):
                try:
                    _call_or_prop(bf, m)
                    break
                except Exception:
                    continue
    except Exception:
        pass

    def _get_prop(name: str) -> Optional[str]:
        """Read one cut-list property, tolerating every return shape these COM methods use.

        CRITICAL: Get/Get2/Get4/Get5 return the VALUE in [out] parameters and a STATUS CODE
        as the function result. Under this binding the out-params come back in a tuple with
        that status. Treating the bare result as the value read 1 (success) for every
        property and reported a 1.0mm flat blank on a 79mm part — a plausible-looking number
        that is entirely fictional. So: strings only, never a bare number.
        """
        for meth in ("Get5", "Get4", "Get3", "Get2", "Get"):
            fn = getattr(cpm, meth, None)
            if fn is None:
                continue
            for args in ((name, False), (name,)):
                try:
                    r = fn(*args)
                except Exception:
                    continue
                # Tuple/list => (status, ValOut, ResolvedValOut). The RESOLVED value is the
                # evaluated one (equations/links already applied), so prefer the last string.
                if isinstance(r, (list, tuple)):
                    strs = [x for x in r if isinstance(x, str) and x.strip()]
                    if strs:
                        return _safe_str(strs[-1])
                    continue
                if isinstance(r, str) and r.strip():
                    return _safe_str(r)
                # A bare int/float here is the status code, NOT the property value. Reject it.
        return None

    # ENUMERATE EVERYTHING FIRST — always, not only on failure. SolidWorks names the
    # property "Bounding Box Length" in BOTH a sheet-metal cut list (where it is the FLAT
    # PATTERN box) and a weldment cut list (where it is the SOLID's box). Asking for the
    # name blind cannot tell those apart, and that is precisely how 12120-01-01M returned
    # its folded envelope as a flat. The full name list distinguishes them — a sheet-metal
    # folder carries 'Sheet Metal Thickness'/'Bend Radius', a weldment folder carries
    # 'LENGTH'/'ANGLE1'/'Description' — so record it on every read and let the evidence
    # decide rather than the property name.
    _all_props: Dict[str, str] = {}
    try:
        _names = _get0(cpm, "GetNames")
        for _nm in (list(_names) if _names else []):
            _nm = str(_nm)
            _v = _get_prop(_nm)
            _all_props[_nm] = _v if _v is not None else ""
    except Exception:
        pass
    if _all_props:
        out["_all_cutlist_props"] = _all_props
        # Which KIND of cut list answered. Sheet-metal markers mean 'Bounding Box Length'
        # is the flat; their absence means it is the solid and must not be costed as a blank.
        _sm_markers = [k for k in _all_props
                       if "sheet metal" in k.lower() or "bend radius" in k.lower()
                       or "flat pattern" in k.lower()]
        out["_cutlist_kind"] = "sheet_metal" if _sm_markers else "unknown_or_weldment"
        notes.append(f"cutlist_kind={out['_cutlist_kind']} "
                     f"props={sorted(_all_props)}")

    _hits = 0
    _raw_seen: List[str] = []
    # COUNTS accept zero; LENGTHS do not. A blank cannot be 0mm long, so a zero there is a
    # failed read — but "Cut Outs = 0" and "Bends = 0" are statements about the part, and
    # parsing them with the length reader turned each into "nobody looked".
    _COUNT_KEYS = {"cut_out_count", "bend_count", "hole_count"}
    for key, candidates in _CUTLIST_KEYS.items():
        for cand in candidates:
            raw = _get_prop(cand)
            if raw is not None and len(_raw_seen) < 5:
                _raw_seen.append(f"{key}={raw!r}")
            val = _num_count(raw) if key in _COUNT_KEYS else _num_mm(raw)
            if val is not None:
                out[key] = val
                _hits += 1
                break
    # Record the RAW strings read. A previous version silently turned a COM status code
    # into a 1.0mm blank; showing the raw value makes that class of error visible instead
    # of it looking like a real measurement.
    # Text-valued properties (finish, gauge designation) — the mm reader would strip these
    # to a meaningless number ("Powder Coat" -> None, "16 GA" -> 16.0).
    for key, candidates in _CUTLIST_TEXT_KEYS.items():
        for cand in candidates:
            raw = _get_prop(cand)
            if raw and str(raw).strip():
                out[key] = str(raw).strip()
                break
    if _raw_seen:
        notes.append("cutlist_raw: " + "; ".join(_raw_seen))
    if _hits:
        notes.append(f"cutlist_props_read={_hits}")
    else:
        # Say so rather than silently returning nothing — this is the datum that decides
        # whether a job can clear the credibility gate.
        try:
            names = _get0(cpm, "GetNames")
            notes.append(f"cutlist_props_none; available={list(names)[:12] if names else None}")
        except Exception:
            notes.append("cutlist_props_none")
    return out


def infer_thickness_from_bbox(bbox_mm, is_sheet_metal: bool, bend_count: int = 0):
    """Thickness of an unformed blank, read off its own solid. None when it cannot be said.

    A plate's smallest bounding-box dimension IS its thickness. A folded part's is not — its
    envelope always stands taller than its material — so this applies only where nothing has
    been bent.

    A part with no sheet-metal feature has to earn it on shape. A flat plate is modelled as
    an extrude, not a flange, so excluding those excluded the parts that most need a
    thickness inferred; but a 10mm pin measuring 10 x 10 x 30 also has a small minimum and is
    not 10mm thick. Requiring the smallest dimension to be a small fraction of the next
    smallest is what separates a plate from a bar or a block.

    A module-level function so a test can drive it rather than re-implement it — a test that
    restates the rule proves only that the test agrees with itself.
    """
    try:
        dims = sorted(float(x) for x in (bbox_mm or []) if x)
    except (TypeError, ValueError):
        return None
    if len(dims) < 3 or bend_count:
        return None
    smallest = dims[0]
    if not (0.4 <= smallest <= 12.0):
        return None
    plate_shape = dims[1] > 0 and (smallest / dims[1]) <= 0.25
    if is_sheet_metal or plate_shape:
        return round(smallest, 3)
    return None


def sheet_metal_signals(doc, allow_flatten: Optional[bool] = None) -> RouteSignals:
    """Feature walk for sheet-metal / hole / weldment hints on a part doc."""
    sig = RouteSignals(part_number=_safe_str(_get0(doc, "GetTitle")))
    # Wrap with the generated IModelDoc2 class so FirstFeature() resolves by DISPID (late
    # binding returns 'Member not found' for interface-returning methods).
    mdoc = _wrap(doc, "IModelDoc2")
    sig.notes.append(f"mdoc_wrapped={type(mdoc).__name__}")
    feat = None
    try:
        feat = mdoc.FirstFeature()
    except Exception as e:
        sig.notes.append(f"FirstFeature: {e!r}")
        feat = _get0(doc, "FirstFeature")  # last-resort late-bound property form
    sig.notes.append("first_feature=" + ("obj" if feat is not None else "None"))
    _cut_props: Dict[str, Any] = {}
    try:
        bend_count = 0
        hole_like = 0
        visited = 0
        while feat is not None and visited < 100000:
            visited += 1
            feat = _wrap(feat, "IFeature")
            raw_t = ""
            try:
                raw_t = _safe_str(feat.GetTypeName2())
            except Exception:
                try:
                    raw_t = _safe_str(feat.GetTypeName())
                except Exception:
                    raw_t = _safe_str(_get0(feat, "Name"))
            t = raw_t.lower()
            if raw_t and len(sig.feature_types) < 120:
                sig.feature_types.append(raw_t)  # diagnostic: what types the walk sees
            if "sheetmetal" in t or "sheet metal" in t or t == "smbaseflange":
                sig.is_sheet_metal = True
            if t == "flatpattern":
                sig.flat_pattern_present = True
            # SW sheet-metal BEND features. Each EdgeFlange/SketchBend/etc adds a bend line;
            # SMBaseFlange is the flat base (NOT a bend); UnFold/Fold are model ops that
            # flatten/refold existing bends, so they are NOT counted to avoid double-count.
            if t in _BEND_FEATURE_TYPES or ("bend" in t and "unbend" not in t):
                bend_count += 1
                sig.is_sheet_metal = True
            # HoleWzd = hole-wizard FEATURE count (undercounts vs DXF pierce count — DXF
            # stays authoritative for total holes). Kept as a sheet-metal signal only.
            if t in ("holewzd", "holeseries", "advholewzd"):
                hole_like += 1
            if "weldment" in t or "structuralmember" in t or "weldmentcutlist" in t:
                sig.has_weldment = True
            # The cut-list folder carries the flat-pattern bounding box, sheet thickness
            # and bend radius — the values that let a sheet part be costed properly.
            if t in ("cutlistfolder", "subweldfolder", "solidbodyfolder") and not _cut_props:
                try:
                    _cut_props = _cutlist_properties(feat, sig.notes) or {}
                except Exception as _e_cl:
                    sig.notes.append(f"cutlist_err: {_e_cl!r}")
            try:
                feat = feat.GetNextFeature()
            except Exception:
                feat = _get0(feat, "GetNextFeature")
        sig.bend_count = bend_count
        sig.hole_count_est = hole_like
        sig.notes.append(f"features_visited={visited}")
    except Exception as e:
        sig.notes.append(f"feature_walk_error: {e!r}")

    props = get_custom_properties(doc)
    # Material: prefer a custom property, else the SW-APPLIED material (MaterialIdName is a
    # property like "db|name" — take the name). Fabricated parts usually carry the applied
    # material, NOT a custom prop. Prefer GetMaterialPropertyName2(config, out db) which
    # returns the NAME ("Plain Carbon Steel" etc.); MaterialIdName gave a bare id ('273').
    _applied = ""
    try:
        _db = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        _nm = _safe_str(doc.GetMaterialPropertyName2("", _db))
        if _nm and not _nm.isdigit():
            _applied = _nm
    except Exception as e:
        sig.notes.append(f"material_name_err: {e!r}")
    if not _applied:
        _mid = _safe_str(_get0(doc, "MaterialIdName"))
        _applied = _mid.split("|")[-1].strip() if "|" in _mid else _mid
    # Split the material from its provenance: a typed custom property is the spec (strongest),
    # the library-applied material is the appearance default (must not overrule the drawing).
    sig.material, sig.material_source = _material_and_source(props, _applied)
    _thk = _prop(props, "Thickness", "Sheet Thickness", "Gauge", "Material Thickness")
    if _thk:
        try:
            sig.thickness_mm = float(
                "".join(ch for ch in _thk.replace(",", ".") if ch.isdigit() or ch == ".")
            )
        except Exception:
            pass
    sig.bbox_mm = get_bbox_mm(doc, SW_PART)
    sig.mass_kg = get_mass_kg(doc)

    # ── Flat pattern + thickness from the cut list ────────────────────────────────
    # Cut-list thickness is the sheet-metal parameter itself, so it beats a custom
    # property or anything inferred from the bounding box.
    if _cut_props:
        # SANITY GATE. Unfolding a part can only make it BIGGER, never smaller: the flat
        # blank must be at least the largest face dimension of the folded solid. A read that
        # returned 1.0 x 1.0mm for a 79mm part (a COM status code mistaken for a value)
        # passed every downstream check and would have costed as a 1mm square of steel.
        # Reject anything geometrically impossible and say why, rather than carry a
        # plausible-looking fiction into a price.
        _fl = _cut_props.get("flat_length")
        _fw = _cut_props.get("flat_width")
        _bbox_max = 0.0
        try:
            _bbox_max = max(float(x) for x in (sig.bbox_mm or []) if x)
        except Exception:
            pass
        _read_tainted = False
        if _fl and _fw and _bbox_max:
            _flat_max = max(_fl, _fw)
            if _flat_max < _bbox_max * 0.95:
                sig.notes.append(
                    f"REJECTED cut-list flat {_fl}x{_fw}mm — smaller than the folded solid "
                    f"({_bbox_max:.1f}mm); a flat pattern cannot be smaller than the part")
                _fl = _fw = None
                # Every value in this dict came from the SAME property-manager read. If the
                # flat is geometrically impossible the read itself is wrong, so thickness and
                # bend radius from it cannot be trusted either — even when they happen to look
                # plausible. A status code of 1 read as "1.0mm thick" passes a thickness-vs-bbox
                # check on any formed part (01M: 1.0 < 21.5) and would silently misprice the
                # material. Discard the whole read and fall back to the labelled inference.
                _read_tainted = True
            else:
                # SECOND GATE — the one the first cannot see. A folded part's DEVELOPED blank
                # must be LARGER than the envelope it folds into: material is consumed going
                # round the bends. So if a part with bends reports a "flat" that matches its
                # own bounding box, we are not looking at a flat pattern at all — we are
                # looking at the FOLDED bounding box, which is a real number that is simply
                # the wrong one. PRECAUTIONARY, not observed: written believing 12120-01-01M
                # had failed this way, which fuller extraction disproved (its solid is
                # 79x64.5x21.5 against a 126.39x82.2 flat — a genuine developed blank). Kept
                # because the geometry it asserts is sound and the first gate passes a folded
                # box by construction (folded == bbox is never < 0.95 x bbox), so nothing
                # else would catch it. Costing a folded envelope UNDER-BUYS material.
                _has_bends = bool(sig.bend_count or sig.formed_but_no_bend_features)
                if _has_bends and sig.bbox_mm:
                    try:
                        _dims = [float(x) for x in sig.bbox_mm if x]
                        # Does EACH flat side coincide with SOME bounding-box dimension?
                        # Match against any axis, not the two largest — a folded part's
                        # height often exceeds its footprint width (01M is 126.39 x 82.2 x 90,
                        # the 90 being the upstand). Each dimension is consumed once.
                        if len(_dims) >= 2:
                            _avail, _same = list(_dims), True
                            for _f in (float(_fl), float(_fw)):
                                _hit = next((d for d in _avail
                                             if abs(_f - d) <= max(0.5, d * 0.01)), None)
                                if _hit is None:
                                    _same = False
                                    break
                                _avail.remove(_hit)
                            if _same:
                                sig.notes.append(
                                    f"REJECTED cut-list flat {_fl}x{_fw}mm — the part is FOLDED "
                                    f"({sig.bend_count or '?'} bend(s)) yet the reported flat "
                                    f"equals its folded bounding box "
                                    f"({'x'.join(f'{d:g}' for d in _dims)}mm). A developed blank must be "
                                    f"larger than the envelope it folds into, so this is the "
                                    f"FOLDED box, not a flat pattern — using it would under-buy "
                                    f"material. Flat pattern must come from the DXF or a "
                                    f"flat-pattern-specific property")
                                _fl = _fw = None
                                _read_tainted = True
                    except Exception:
                        pass
        sig.flat_length_mm = _fl
        sig.flat_width_mm = _fw
        sig.bend_radius_mm = None if _read_tainted else _cut_props.get("bend_radius")
        if not _read_tainted:
            # ── CUT LENGTH: outer profile + inner cut-outs ────────────────────────
            # The laser cuts both. Reporting only the outer under-states the time on any
            # part with holes or slots; 01M has three. Kept separately as well, since the
            # split is real information about how the part runs.
            _co = _cut_props.get("cut_length_outer")
            _ci = _cut_props.get("cut_length_inner")
            sig.cut_length_outer_mm = _co
            sig.cut_length_inner_mm = _ci
            if _co or _ci:
                sig.cut_length_mm = round((_co or 0.0) + (_ci or 0.0), 2)
                sig.notes.append(
                    f"cut length {sig.cut_length_mm}mm from the cut list "
                    f"(outer {_co or 0:g} + inner {_ci or 0:g}) — measured, not a perimeter floor")
            sig.blank_area_mm2 = _cut_props.get("blank_area_mm2")
            sig.bend_allowance_mm = _cut_props.get("bend_allowance")
            sig.surface_treatment = str(_cut_props.get("surface_treatment") or "")
            sig.sheet_gauge = str(_cut_props.get("sheet_gauge") or "")
            for _k, _attr in (("cut_out_count", "cut_out_count"),
                              ("bend_count", "bend_count_cutlist")):
                _v = _cut_props.get(_k)
                if _v is not None:
                    try:
                        setattr(sig, _attr, int(round(float(_v))))
                    except (TypeError, ValueError):
                        pass
            # ── BEND COUNT the feature tree cannot see ────────────────────────────
            # A Base Flange from a multi-segment sketch exposes no bend feature, so
            # feature-counting reports zero on a visibly folded part (02M, 06M, 08M). The
            # cut list publishes the real count. Take it when it beats what we counted, and
            # say where it came from — this replaces a flagged unknown with a fact.
            if sig.bend_count_cutlist and sig.bend_count_cutlist > sig.bend_count:
                sig.notes.append(
                    f"bend count {sig.bend_count} -> {sig.bend_count_cutlist} from the cut "
                    f"list ('Bends'); the feature tree cannot count bends baked into a "
                    f"base flange sketch")
                sig.bend_count = sig.bend_count_cutlist
        _thk = None if _read_tainted else _cut_props.get("thickness")
        if _read_tainted:
            sig.notes.append(
                "cut-list read discarded in full (flat failed the geometry check) — "
                "thickness/bend radius from the same read are not trusted")
        # Thickness must not exceed the solid's smallest dimension.
        if _thk and sig.bbox_mm:
            try:
                _bbox_min = min(float(x) for x in sig.bbox_mm if x)
                if _thk > _bbox_min * 1.05:
                    sig.notes.append(
                        f"REJECTED cut-list thickness {_thk}mm — exceeds the solid's smallest "
                        f"dimension ({_bbox_min:.2f}mm)")
                    _thk = None
            except Exception:
                pass
        if _thk:
            sig.thickness_mm = _thk

        # ── MASS from the cut list, with its UNITS resolved by geometry ────────────
        # GetMassProperties2 has never populated on these models, but the cut list
        # publishes 'Mass'. Its units follow the document (kg on some, grams on others)
        # and the value alone cannot say which — 0.12 and 122 are both plausible for a
        # small bracket. So predict the mass from geometry (blank area x thickness x
        # density) and accept whichever reading matches. If neither does, record the raw
        # value and leave mass unset: a mass that is wrong by 1000x would silently wreck
        # the material cost, and an honest null is recoverable where that is not.
        if not _read_tainted and sig.mass_kg is None:
            _mraw = _cut_props.get("mass_raw")
            _dens = _density_kg_m3(sig.material)
            _area = sig.blank_area_mm2 or (
                (sig.flat_length_mm or 0) * (sig.flat_width_mm or 0))
            if _mraw and _dens and _area and sig.thickness_mm:
                _pred = (_area / 1e6) * (sig.thickness_mm / 1000.0) * _dens   # kg
                _cands = [("kg", float(_mraw)), ("g", float(_mraw) / 1000.0)]
                _best = next((u_v for u_v in _cands
                              if _pred > 0 and 0.6 <= u_v[1] / _pred <= 1.6), None)
                if _best:
                    sig.mass_kg = round(_best[1], 5)
                    sig.notes.append(
                        f"mass {sig.mass_kg}kg from the cut list (raw {_mraw!r} read as "
                        f"{_best[0]}; geometry predicts {_pred:.4f}kg from "
                        f"{_area:.0f}mm2 x {sig.thickness_mm}mm x {_dens}kg/m3)")
                else:
                    sig.notes.append(
                        f"cut-list Mass {_mraw!r} NOT USED — matches neither kg nor grams "
                        f"against the {_pred:.4f}kg the geometry predicts; units "
                        f"unresolved, so mass is left unset rather than guessed")
            elif _mraw:
                sig.notes.append(
                    f"cut-list Mass {_mraw!r} present but its units cannot be checked "
                    f"(need material density, blank area and thickness) — left unset")

    # Last-resort thickness for a sheet part: the smallest bounding-box dimension of an
    # UNFORMED blank is its thickness. Only used when the part has no bends and no cut-list
    # thickness, and it is recorded as inferred so it is never mistaken for a model value.
    #
    # NOT ONLY FOR SHEET-METAL PARTS. This was gated on is_sheet_metal, which is true only
    # where the feature tree holds a sheet-metal feature. A flat plate is modelled as an
    # extrude, so it got no thickness here and no plate verdict downstream — and 12120's 04M
    # (60 x 34.04 x 1.5) kept being folded off the drawing text because nothing could say it
    # was flat. The parts that most need a thickness inferred were the ones excluded.
    #
    # For a part with no sheet-metal features the shape has to earn it: the smallest
    # dimension must be a small fraction of the next smallest, which is what makes something
    # a plate rather than a bar or a block. A 10mm pin measuring 10 x 10 x 30 has a small
    # minimum too, and is not 10mm "thick".
    if sig.thickness_mm is None and sig.bbox_mm and not sig.bend_count:
        _inferred = infer_thickness_from_bbox(sig.bbox_mm, sig.is_sheet_metal, sig.bend_count)
        if _inferred is not None:
            sig.thickness_mm = _inferred
            sig.notes.append(
                f"thickness inferred from bbox min ({_inferred:.2f}mm) — no cut-list value"
                + ("" if sig.is_sheet_metal else
                   "; part carries no sheet-metal feature, and its solid is plate-shaped"))

    # ── Formed-but-no-bend-features cross-check ───────────────────────────────────
    # A Base Flange built from a multi-segment sketch bakes its bends into that feature and
    # exposes no EdgeFlange/SketchBend, so counting bend features under-reports. If the solid
    # is demonstrably formed — its smallest bbox dimension is several times the sheet
    # thickness — say so, rather than silently reporting zero bends and dropping the fold.
    if sig.is_sheet_metal and not sig.bend_count and sig.bbox_mm and sig.thickness_mm:
        try:
            _mn = min(float(x) for x in sig.bbox_mm if x)
            if _mn > max(3.0 * float(sig.thickness_mm), float(sig.thickness_mm) + 3.0):
                sig.formed_but_no_bend_features = True
                sig.notes.append(
                    f"FORMED but no bend features counted: min bbox {_mn:.1f}mm vs thickness "
                    f"{sig.thickness_mm}mm — bends are likely baked into the base flange; "
                    f"fold time needs confirming")
        except Exception:
            pass

    # ── Flat pattern by MEASUREMENT, when the property route gave nothing usable ───
    # Reached when the part is formed but we have no blank — either the cut list was
    # silent, or its "flat" was rejected as the folded envelope. Flattening and measuring
    # cannot be fooled by a property name, so it is the authoritative fallback.
    #
    # ON BY DEFAULT FROM THE PIPELINE SINCE 2026-08-27, and the reason it was not is worth
    # keeping: "opt-in because it rebuilds each model in memory and costs time". True, and
    # the wrong trade. This fires ONLY on a formed sheet-metal part for which the cut list
    # gave no usable blank — which is precisely the case that makes the engine infer
    # geometry, and inferred geometry is its single largest source of inaccuracy. Paying
    # seconds of rebuild to stop guessing a blank size is not a close call.
    #
    # It never runs on a BORROWED document. See SolidWorksSession.last_open_borrowed.
    _may_flatten = ALLOW_FLATTEN if allow_flatten is None else allow_flatten
    if (_may_flatten and sig.is_sheet_metal
            and (sig.bend_count or sig.formed_but_no_bend_features)
            and not (sig.flat_length_mm and sig.flat_width_mm)):
        _fp = flat_pattern_by_flatten(doc, sig.bbox_mm, sig.thickness_mm, sig.notes)
        if _fp:
            sig.flat_length_mm, sig.flat_width_mm = _fp
            sig.flat_pattern_present = True

    # A part whose tree is imported geometry with no modelled fabrication features is a
    # supplier model (fastener, PEM, standoff, connector, display module) — we buy it, we
    # do not make it. Detect before assigning any route.
    _fab_feats = {"SHEETMETAL", "SMBASEFLANGE", "EDGEFLANGE", "FOLD", "UNFOLD", "FLATPATTERN",
                  "EXTRUSION", "CUT", "REVOLUTION", "REVCUT", "SWEEP", "SWEEPCUT", "LOFT",
                  "HOLEWZD", "WELDMENT", "STRUCTURALMEMBER"}
    _types_u = {str(t).upper() for t in (sig.feature_types or [])}
    if "MBIMPORT" in _types_u and not (_types_u & _fab_feats):
        sig.likely_bought_in = True

    # Route hints (rules-first — align with the estimator's op names). These are HINTS,
    # honestly flagged: powder in particular is a default assumption to confirm from notes.
    if sig.likely_bought_in:
        # Bought-in: no fabrication route at all. Handling/assembly is added by the
        # estimator, not asserted here.
        sig.notes.append("likely bought-in (imported body, no fabrication features)")
    else:
        # Sheet metal is CUT — but only FOLDED when the model actually has bends. Gating
        # 'folding' on is_sheet_metal alone put a fold operation on flat blanks: 12120-01-05M
        # is SheetMetal -> SMBaseFlange -> FlatPattern with no EdgeFlange/Fold at all, yet was
        # given a fold. An operation must follow evidence, never the material class.
        if sig.is_sheet_metal or sig.bend_count:
            sig.ops_hint.append("laser_cutting")
        # Fold when the model shows bends — either counted bend features, or a solid that
        # is demonstrably formed (bends baked into the base flange). Gating on counted
        # features alone would DROP the fold on those parts; gating on is_sheet_metal alone
        # ADDED a fold to flat blanks. Both are wrong; this follows the geometry.
        if sig.bend_count or sig.formed_but_no_bend_features:
            sig.ops_hint.append("folding")
        if sig.hole_count_est:
            sig.ops_hint.append("hole_machining")
        if sig.has_weldment:
            sig.ops_hint += ["welding", "dress_welds"]
        # Powder is a DEFAULT ASSUMPTION for FABRICATED steel — confirm from drawing notes.
        # It must not be applied to a steel bought-in: the Amphenol USB coupler, M4
        # thumbscrews, PEM inserts and the Lenovo display module all carry material 'Steel'
        # and were being given a powder-coat operation they will never see.
        mat_u = sig.material.upper()
        _is_steel = any(x in mat_u for x in ("MILD STEEL", "MILD_STEEL", "CR4", "STEEL",
                                             "CRS", "ZINTEC", "GALV"))
        if _is_steel and (sig.is_sheet_metal or sig.has_weldment):
            sig.ops_hint.append("powder_coating")
    sig.ops_hint = sorted(set(sig.ops_hint))
    # ── TUBE FRAME: read the section out of the weldment cut list the analyser already has ──
    # The cut-list read above enumerated every property name into _all_cutlist_props to decide
    # the cut-list KIND; a weldment folder carries the member Description ('TUBE 30 X 30 X 2.6')
    # and its LENGTH there. Extract the section from what is already in hand — no new SolidWorks
    # call — so a frame's tubes stop arriving at the estimate empty. None on a sheet part.
    try:
        if sig.section_profile is None and isinstance(_cut_props, dict):
            _all = _cut_props.get("_all_cutlist_props") or {}
            _sec = weldment_section_from_cutlist(_all)
            if _sec:
                sig.section_profile = _sec
                sig.ops_hint = sorted(set(sig.ops_hint) | {"welding", "dress_welds"})
                sig.notes.append(f"weldment_section={_sec.get('profile_form')} "
                                 f"{_sec.get('a')}x{_sec.get('b')}x{_sec.get('t')} "
                                 f"len={_sec.get('length_mm')}")
    except Exception as _e_sec:
        sig.notes.append(f"weldment_section_err: {_e_sec!r}")
    return sig


def assembly_bom(doc) -> List[BomLine]:
    """FULL multi-level BOM, qty aggregated by the part's document identity (not instance
    name). GetComponents(False) returns every component at every level; GetModelDoc2 is
    interface-returning so the component is wrapped IComponent2 and its model IModelDoc2
    (else the title falls back to the instance name '...-3' and material/path are lost)."""
    counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    # (parent, child, config) -> instance count, and the child's document type. Kept beside
    # the aggregated BOM rather than replacing it, so the flat list every current reader
    # consumes is byte-identical and only the hierarchy is new.
    _edges: Dict[Tuple[str, str, str], float] = {}
    _edge_meta: Dict[Tuple[str, str, str], Optional[int]] = {}
    # GetComponents is on IAssemblyDoc and is arg-taking, so it works on the raw late-bound
    # doc (that is how the top-level version worked). False = ALL levels (full flattened
    # tree); fall back to True (top level) if a build rejects False.
    comps = None
    for _topflag in (False, True):
        try:
            comps = doc.GetComponents(_topflag)
            if comps:
                break
        except Exception:
            try:
                comps = _wrap(doc, "IAssemblyDoc").GetComponents(_topflag)
                if comps:
                    break
            except Exception:
                comps = None
    if not comps:
        return []
    for c in comps:
        try:
            c = _wrap(c, "IComponent2")
            _sup = _get0(c, "GetSuppression2")
            try:
                if _sup is not None and int(_sup) == 0:  # swComponentSuppressed
                    continue
            except Exception:
                pass
            name2 = _safe_str(_get0(c, "Name2"))
            config = _safe_str(_get0(c, "ReferencedConfiguration"))
            model = None
            try:
                model = c.GetModelDoc2()
            except Exception:
                model = _get0(c, "GetModelDoc2")
            # LIGHTWEIGHT COMPONENTS. A large assembly opens components lightweight to save
            # memory, and a lightweight component has no IModelDoc2 — GetModelDoc2 returns
            # nothing. Everything read from the model then silently vanishes: the BOM line
            # keeps the instance name but loses its title, material, properties and path,
            # so the part looks unidentified rather than unresolved. Resolve it and retry.
            #
            # swComponentSuppressionState_e: 2 = swComponentFullyResolved,
            # 3 = swComponentResolved. Both lift a component out of lightweight; which one
            # a given SolidWorks build accepts varies, so try the fully-resolved state first
            # and fall back. The comment here previously named 3 as fully-resolved, which it
            # is not.
            #
            # The retry must go through _get0 exactly as the first attempt does. In this
            # late-binding, GetModelDoc2 resolves as a PROPERTY, so calling it with () raises
            # rather than returning the model — which is the very failure that sent us here.
            # Retrying with the calling convention that just failed can only fail again.
            if model is None:
                for _state in (2, 3):
                    try:
                        c.SetSuppression2(_state)
                    except Exception:
                        continue
                    try:
                        model = c.GetModelDoc2()
                    except Exception:
                        model = _get0(c, "GetModelDoc2")
                    if model is not None:
                        break
            model = _wrap(model, "IModelDoc2") if model is not None else None
            # Document identity. The component INSTANCE name carries the '-N' suffix
            # (strip it); the model's document TITLE is already the clean part number
            # (do NOT strip — '12120-01-103' must not lose its '-103').
            title = _clean_pn(name2.split("/")[-1])
            path = ""
            props: Dict[str, str] = {}
            material = ""
            if model is not None:
                _dt = _safe_str(_get0(model, "GetTitle"))
                if _dt:
                    title = os.path.splitext(_dt)[0].strip()
                path = _safe_str(_get0(model, "GetPathName"))
                props = get_custom_properties(model)
                material = _prop(props, "Material", "Material Description", "Material Spec", "Grade")
            # WHOSE CHILD IS THIS. IComponent2.GetParent returns the owning COMPONENT, or
            # nothing for a direct child of the assembly being analysed. Read through the
            # same wrap-and-clean path as the component itself so a sub-assembly's identity
            # matches the one it is given when IT is the child of something else — an edge
            # whose two ends spell the node differently is not an edge.
            parent_pn = ""
            try:
                _par = _get0(c, "GetParent")
                if _par is not None:
                    _par = _wrap(_par, "IComponent2")
                    _pm = None
                    try:
                        _pm = _par.GetModelDoc2()
                    except Exception:
                        _pm = _get0(_par, "GetModelDoc2")
                    _pt = _safe_str(_get0(_wrap(_pm, "IModelDoc2"), "GetTitle")) if _pm else ""
                    parent_pn = (os.path.splitext(_pt)[0].strip() if _pt
                                 else _clean_pn(_safe_str(_get0(_par, "Name2")).split("/")[-1]))
            except Exception:
                parent_pn = ""
            _dtype = None
            if model is not None:
                try:
                    _dtype = int(_get0(model, "GetType"))
                except Exception:
                    _dtype = None

            key = (title, config)
            if key not in counts:
                counts[key] = {
                    "part_number": title,
                    "description": _prop(props, "Description", "Part Description", "Desc"),
                    "qty": 0.0,
                    "config": config,
                    "material": material,
                    "file_path": path,
                    "custom_props": props,
                    "parent_part_number": parent_pn,
                    "doc_type": _dtype,
                }
            counts[key]["qty"] += 1.0
            # ONE INSTANCE PER EDGE, counted where it hangs. The aggregated line above keeps
            # the flattened total every existing reader expects; this is what the hierarchy
            # is actually built from, and an assembly used twice under different parents has
            # two edges rather than one line with a doubled quantity and no owner.
            _edges.setdefault((parent_pn, title, config), 0.0)
            _edges[(parent_pn, title, config)] += 1.0
            _edge_meta[(parent_pn, title, config)] = _dtype
        except Exception:
            continue
    lines = []
    for v in counts.values():
        lines.append(
            BomLine(
                part_number=v["part_number"],
                description=v["description"],
                qty=v["qty"],
                config=v["config"],
                material=v["material"],
                file_path=v["file_path"],
                source="assembly_tree",
                custom_props=v["custom_props"],
                parent_part_number=v.get("parent_part_number") or "",
                doc_type=v.get("doc_type"),
            )
        )
    lines.sort(key=lambda x: x.part_number.lower())
    _ASSEMBLY_EDGES[id(doc)] = [
        {"parent": p, "child": ch, "config": cfg, "qty": q,
         "child_doc_type": _edge_meta.get((p, ch, cfg))}
        for (p, ch, cfg), q in sorted(_edges.items())
    ]
    return lines


# assembly_bom's signature is fixed by its callers, so the edges it discovers are handed
# over here rather than returned. Keyed on the document object so two assemblies analysed in
# one session cannot collect each other's tree.
_ASSEMBLY_EDGES: Dict[int, List[Dict[str, Any]]] = {}


def assembly_edges(doc) -> List[Dict[str, Any]]:
    """The parent->child edges found by the last assembly_bom(doc) for this document."""
    return _ASSEMBLY_EDGES.get(id(doc), [])


def _collect_from_table(t, lines: List[BomLine]) -> None:
    """Read one table annotation's rows into BomLines. Shared by both discovery paths so
    they cannot drift apart in what they accept."""
    try:
        rows = int(t.RowCount)
        cols = int(t.ColumnCount)
    except Exception:
        return
    headers = []
    for col in range(cols):
        try:
            headers.append(_table_text(t, 0, col).lower())
        except Exception:
            headers.append("")
    idx_pn = next((i for i, h in enumerate(headers)
                   if "part" in h or "item" in h or h == "no"), 0)
    idx_qty = next((i for i, h in enumerate(headers)
                    if "qty" in h or "qnty" in h or "quantity" in h), None)
    idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), None)
    for r in range(1, rows):
        try:
            pn = _table_text(t, r, idx_pn)
            if not pn:
                continue
            qty = 1.0
            if idx_qty is not None:
                try:
                    qty = float(_table_text(t, r, idx_qty).replace(",", ""))
                except Exception:
                    qty = 1.0
            desc = _table_text(t, r, idx_desc) if idx_desc is not None else ""
            lines.append(BomLine(part_number=pn, description=desc, qty=qty,
                                 source="drawing_bom"))
        except Exception:
            continue


def drawing_bom_tables(doc) -> List[BomLine]:
    """Extract BOM table annotations from a drawing. Best-effort: the table API varies by
    SW version — VERIFY on one known .slddrw (e.g. 12120's GA) before trusting it."""
    lines: List[BomLine] = []
    visited = 0

    def _tables_everywhere():
        """Every table annotation on the drawing, not just those hanging off the views of
        the ACTIVE SHEET.

        GetFirstView/GetNextView walks one sheet, and on these drawings the BOM is not
        there — both .SLDDRW records came back with zero rows and zero errors, which reads
        as "this drawing has no BOM" rather than "we looked in one place". Three sources
        are collected: the document's own table annotations, every view returned by
        GetViews() across all sheets, and the per-sheet walk as a fallback.
        """
        out = []
        for _name in ("GetTableAnnotations", "GetTableAnnotationCount"):
            if _name == "GetTableAnnotations":
                try:
                    for t in (_get0(doc, "GetTableAnnotations") or []):
                        out.append(t)
                except Exception:
                    pass
        # GetViews() returns an array per sheet — [[sheet1 views], [sheet2 views], ...] —
        # so every sheet's tables are reachable, not only the active one.
        try:
            sheets = doc.GetViews()
            for _sheet in (sheets or []):
                for _v in (_sheet or []):
                    try:
                        for t in (_get0(_v, "GetTableAnnotations") or []):
                            out.append(t)
                    except Exception:
                        continue
        except Exception:
            pass
        return out

    try:
        for t in _tables_everywhere():
            try:
                _tt = _get0(t, "Type")
                # swTableAnnotationType_e: 3 = swTableAnnotation_BillOfMaterials. Where the
                # type is readable, take BOM tables only — a revision block and a general
                # note table have rows and columns too, and reading them as a BOM invents
                # part numbers out of revision letters.
                if _tt is not None and int(_tt) not in (3,):
                    continue
            except Exception:
                pass
            _collect_from_table(t, lines)
        if lines:
            lines.sort(key=lambda x: x.part_number.lower())
            return lines
    except Exception:
        pass

    try:
        v = _get0(doc, "GetFirstView")
        while v is not None and visited < 50:
            visited += 1
            tables = _get0(v, "GetTableAnnotations")
            if tables:
                for t in tables:
                    try:
                        rows = int(t.RowCount)
                        cols = int(t.ColumnCount)
                        headers = []
                        for col in range(cols):
                            try:
                                headers.append(_table_text(t, 0, col).lower())
                            except Exception:
                                headers.append("")
                        idx_pn = next(
                            (i for i, h in enumerate(headers) if "part" in h or "item" in h or "no" == h),
                            0,
                        )
                        idx_qty = next(
                            (i for i, h in enumerate(headers) if "qty" in h or "qnty" in h or "quantity" in h),
                            None,
                        )
                        idx_desc = next(
                            (i for i, h in enumerate(headers) if "desc" in h),
                            None,
                        )
                        for r in range(1, rows):
                            try:
                                pn = _table_text(t, r, idx_pn)
                                if not pn:
                                    continue
                                qty = 1.0
                                if idx_qty is not None:
                                    try:
                                        qty = float(_table_text(t, r, idx_qty).replace(",", ""))
                                    except Exception:
                                        qty = 1.0
                                desc = _table_text(t, r, idx_desc) if idx_desc is not None else ""
                                lines.append(
                                    BomLine(part_number=pn, description=desc, qty=qty, source="drawing_bom")
                                )
                            except Exception:
                                continue
                    except Exception:
                        continue
            v = _get0(v, "GetNextView")
    except Exception:
        pass
    return lines


def analyse_file(session: SolidWorksSession, path: str) -> Dict[str, Any]:
    doc, doctype = session.open(path)
    result: Dict[str, Any] = {
        "path": path,
        "title": "",
        "doctype": doctype,
        "custom_properties": {},
        "bbox_mm": None,
        "bom": [],
        "route_signals": None,
        "errors": [],
    }
    result["title"] = _safe_str(_get0(doc, "GetTitle"))
    try:
        result["custom_properties"] = get_custom_properties(doc)
    except Exception as e:
        result["errors"].append(f"props: {e}")
    try:
        result["bbox_mm"] = get_bbox_mm(doc, doctype)
    except Exception as e:
        result["errors"].append(f"bbox: {e}")
    try:
        if doctype == SW_ASM:
            result["bom"] = [asdict(b) for b in assembly_bom(doc)]
            # THE TREE, BESIDE THE FLATTENED LIST. Every SLDASM reports its own edges, so
            # 101's and 102's children are known even though the GA's BOM lists them all at
            # one level. This is what lets an operation be owned by the assembly it actually
            # belongs to instead of by whichever node the flattening happened to leave it
            # nearest.
            result["assembly_edges"] = assembly_edges(doc)
            result["assembly_part_number"] = (
                os.path.splitext(result.get("title") or "")[0].strip())
        elif doctype == SW_DRW:
            result["bom"] = [asdict(b) for b in drawing_bom_tables(doc)]
        elif doctype == SW_PART:
            # NEVER FLATTEN SOMEBODY ELSE'S OPEN DOCUMENT. Read-only in intent is not
            # the same as invisible: on a borrowed document the part visibly unfolds and
            # refolds in front of the designer, and the rebuild dirties their file. On a
            # document this process opened, neither happens.
            sig = sheet_metal_signals(
                doc, allow_flatten=ALLOW_FLATTEN and not session.last_open_borrowed)
            sig.part_number = result["title"] or sig.part_number
            result["route_signals"] = asdict(sig)
            props = result["custom_properties"]
            result["bom"] = [
                asdict(
                    BomLine(
                        part_number=result["title"],
                        description=_prop(props, "Description", "Part Description", "Desc"),
                        qty=1.0,
                        material=sig.material,
                        thickness_mm=sig.thickness_mm,
                        file_path=path,
                        source="part_props",
                        custom_props=props,
                    )
                )
            ]
    except Exception as e:
        result["errors"].append(f"bom_or_route: {e}")
    return result


# Folder-name tokens that mark superseded/scratch content to skip (case-insensitive).
# Archived models are often the OLD/broken revision (or half-built test assemblies) and
# would pollute or stall a batch — the "ignore archived drawings" rule, at ingest.
# Kept as a name for compatibility, but discovery no longer has its own rule: it uses
# _is_excluded_dir, the same whole-word test as the fingerprint. Two lists meant discovery
# and the manifest could disagree about what the extract covers — a "previous/" folder read
# by one and omitted by the other — which is the same silent-divergence bug as "folder"
# matching "old", just from the opposite direction.
# Folders whose contents are not the live design: superseded models that would otherwise
# make a drawing-only job look as though native evidence had been ignored.
#
# MATCHED AS WHOLE WORDS. Substring matching excluded "CAD Folder", because "folder"
# contains "old" — and the consequence is not a missed folder but a silent one: the analyser
# read those files while the manifest omitted them, so any later change to them was
# invisible to the freshness check. Discovery and fingerprinting must also use the SAME rule,
# or the two disagree about what the extract covers.
# "previous" and "prev" come from the discovery rule this replaced. Unifying two lists must
# not quietly WIDEN what gets read: every token either list had is kept.
_EXCLUDED_DIR_TOKENS = ("archive", "archived", "obsolete", "superseded", "old", "backup",
                        "bak", "dnu", "scrap", "wip", "temp", "tmp",
                        "previous", "prev")
_EXCLUDED_DIR_PHRASES = ("do not use", "not for manufacture")


def _is_excluded_dir(name: str) -> bool:
    n = str(name or "").strip().lower()
    if n.startswith(".") or n.startswith("~"):
        return True
    if any(ph in n for ph in _EXCLUDED_DIR_PHRASES):
        return True
    # Split on anything that is not a letter or digit, so "Old Revs", "_BAK", "rev-old" all
    # match while "Folder" and "Boldon" do not.
    return any(w in _EXCLUDED_DIR_TOKENS for w in re.split(r"[^a-z0-9]+", n) if w)


ARCHIVE_FOLDER_TOKENS = _EXCLUDED_DIR_TOKENS


def find_sw_files(root: str, skip_archive: bool = True) -> List[str]:
    """The models under `root` this analyser will open.

    THE EXCLUSION IS RELATIVE TO THE ROOT, AND WAS ABSOLUTE. `Path(dirpath).parts` names every
    ancestor of the walked directory — including the components of the folder the operator
    typed on the command line. Because `dirs[:]` already prunes archive folders BELOW the
    root, that test could never fire on a descendant: its only reachable effect was to refuse
    the target itself. Point this tool at a job that happens to live under a folder called WIP
    — which is exactly where live models sit — and every file was skipped, the tool printed
    "No SolidWorks files under", exited 1, and wrote no extract.

    Meanwhile the CONSUMER counts the same folder with `p.relative_to(root).parts[:-1]`, finds
    the models, and raises native_models_not_read. Two halves of one system giving opposite
    answers about the same directory, with the half that could clear the blocker refusing to
    run. The consumer's rule is the correct one and this is now the same rule, which is what
    native_files_state's own comment has always demanded.
    """
    exts = {".sldprt", ".sldasm", ".slddrw"}
    root_path = Path(root)
    found = []
    for dirpath, dirs, files in os.walk(root):
        if skip_archive:
            # Prune archive/superseded subfolders so os.walk does not descend into them.
            # ONE RULE, shared with the fingerprint and the consumer — see _is_excluded_dir.
            dirs[:] = [d for d in dirs if not _is_excluded_dir(d)]
            try:
                _rel = Path(dirpath).relative_to(root_path).parts
            except ValueError:                      # pragma: no cover — os.walk stays inside
                _rel = ()
            if any(_is_excluded_dir(part) for part in _rel):
                continue
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                if f.startswith("~$"):
                    continue
                # Also skip files whose NAME flags an old/test copy.
                low = f.lower()
                if skip_archive and (" old version" in low or "(old)" in low or " test." in low):
                    continue
                found.append(os.path.join(dirpath, f))
    return sorted(found)


def explain_no_files(root: str) -> str:
    """Why a folder that has models yielded none, in words an operator can act on.

    "No SolidWorks files under: K:\\..." is true and useless: it does not distinguish a folder
    with no models from a folder whose models were every one of them excluded, and those need
    opposite responses. This walks again with the exclusions OFF and reports the difference,
    naming the folders that did the excluding — because the answer is nearly always one
    directory name.
    """
    everything = find_sw_files(root, skip_archive=False)
    if not everything:
        return ("There are no .SLDPRT/.SLDASM/.SLDDRW files anywhere under that folder. A "
                "job's *-Technical folder is often 2D only (DXF/PDF) — the native models "
                "usually live elsewhere under the job root.")
    kept = set(find_sw_files(root, skip_archive=True))
    dropped = [p for p in everything if p not in kept]
    if not dropped:                                  # pragma: no cover — caller checked
        return ""
    blamed = sorted({part for p in dropped
                     for part in Path(p).relative_to(Path(root)).parts[:-1]
                     if _is_excluded_dir(part)})
    lines = [f"{len(dropped)} of {len(everything)} model file(s) were EXCLUDED, which is why "
             f"nothing was analysed."]
    if blamed:
        lines.append(f"  Excluded by folder name: {', '.join(blamed)}")
        lines.append(f"  A folder is skipped when its name contains any of: "
                     f"{', '.join(_EXCLUDED_DIR_TOKENS)}.")
        lines.append("  If those really are the live models, move them out of that folder or "
                     "point me directly at the subfolder that holds them.")
    else:
        lines.append("  Excluded by FILE name (' old version', '(old)', ' test.').")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python sw_native_analyse.py <file_or_folder> [--out <json path>] [--no-flatten]")
        sys.exit(2)
    argv = list(sys.argv[1:])
    global ALLOW_FLATTEN
    # --flatten is kept and does nothing new; it is in scripts and in people's notes, and a
    # flag that starts erroring is a worse answer than a flag that agrees with the default.
    if "--flatten" in argv:
        argv.remove("--flatten")
    if "--no-flatten" in argv:
        ALLOW_FLATTEN = False
        argv.remove("--no-flatten")
        print("[flatten] OFF — a formed part with no usable cut-list blank will report NO "
              "flat pattern rather than being measured. Its blank will be inferred downstream.",
              flush=True)
    else:
        print("[flatten] ON — formed parts with no usable cut-list blank are flattened IN "
              "MEMORY and measured. The model is restored and closed WITHOUT SAVING, and a "
              "document already open in somebody's session is never flattened.", flush=True)
    out_override = None
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            print("ERROR: --out needs a path")
            sys.exit(2)
        out_override = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print("Usage: python sw_native_analyse.py <file_or_folder> [--out <json path>] [--no-flatten]")
        sys.exit(2)
    target = argv[0]

    # Fail LOUDLY on an unreachable target. Without this the run fell through to
    # "treat it as a single file" -> "Unsupported extension:" -> then tried to write the
    # report to the PARENT directory and died with a confusing FileNotFoundError. A path
    # we cannot see is a setup problem, and it should say so.
    if not os.path.exists(target):
        print(f"ERROR: path not found or not accessible:\n  {target}")
        print("\nCommon causes:")
        print("  - UNC path to a hidden/admin share (\\\\host\\name$\\...): the process may have")
        print("    no session to it. Try the MAPPED DRIVE instead, e.g. K:\\Estimating\\...")
        print("  - running from an ELEVATED PowerShell: an admin shell does not inherit the")
        print("    network credentials that mapped the drive. Use a normal shell.")
        print("  - a typo or a trailing space in the folder name (check with Test-Path).")
        sys.exit(2)

    paths = find_sw_files(target) if os.path.isdir(target) else [target]
    if not paths:
        print(f"No SolidWorks files ANALYSED under: {target}")
        # WHICH KIND OF NOTHING. An empty folder and a folder whose every model was excluded
        # need opposite responses, and the old message could not tell them apart — so an
        # operator whose models sat one directory name away from being read was told to go
        # and look for models somewhere else.
        print(explain_no_files(target))
        sys.exit(1)
    session = SolidWorksSession(visible=False)
    # Before the first document is opened, so a mid-run save is detectable.
    _fp_before = _fingerprint_native_files(target)
    all_results = []
    try:
        for p in paths:
            print(f"\n=== {p} ===", flush=True)
            try:
                r = analyse_file(session, p)
                all_results.append(r)
                print(f"Title: {r.get('title')}  type={r.get('doctype')}")
                print(f"Props: {len(r.get('custom_properties') or {})}")
                print(f"BOM lines: {len(r.get('bom') or [])}")
                rs = r.get("route_signals")
                if rs:
                    print(f"  material={rs.get('material')!r} sheet_metal={rs.get('is_sheet_metal')} "
                          f"bends={rs.get('bend_count')} holes={rs.get('hole_count_est')} "
                          f"flat={rs.get('flat_pattern_present')} weldment={rs.get('has_weldment')} "
                          f"mass_kg={rs.get('mass_kg')} bbox={rs.get('bbox_mm')}")
                    # The costing-critical line: flat blank + gauge. Printed separately so a
                    # missing value is obvious at a glance rather than buried in the JSON.
                    print(f"  FLAT: {rs.get('flat_length_mm')} x {rs.get('flat_width_mm')} mm"
                          f"  thickness={rs.get('thickness_mm')}mm"
                          f"  bend_r={rs.get('bend_radius_mm')}"
                          f"  cut_len={rs.get('cut_length_mm')}"
                          f"{'  [FORMED - bends not feature-counted]' if rs.get('formed_but_no_bend_features') else ''}"
                          f"{'  [BOUGHT-IN]' if rs.get('likely_bought_in') else ''}")
                    print(f"  ops_hint={rs.get('ops_hint')}  feat_types={rs.get('feature_types')[:12]}")
                    if rs.get("notes"):
                        print(f"  notes={rs.get('notes')}")
                if r.get("errors"):
                    print(f"Errors: {r['errors']}")
            except Exception as e:
                print(f"FAILED: {e}")
                all_results.append({"path": p, "errors": [str(e)]})
            finally:
                session.close_all()
        # Captured while the session is still alive. shutdown() clears session.sw, so
        # reading the version afterwards recorded an empty string on every extract.
        _sw_version = _sw_version_string(session)
    finally:
        session.shutdown()
    out_json = out_override or os.path.join(
        target if os.path.isdir(target) else os.path.dirname(target),
        "_sw_native_extract.json",
    )

    # THE MANIFEST. Without it the consumer cannot tell whether this extract still describes
    # the files on disk, and its freshness check silently degrades to comparing file
    # timestamps — which a copy, a restore or a `touch` defeats, and which cannot see a model
    # that has been deleted or renamed at all.
    #
    # COVERAGE travels with it. Per-file failures are caught and written as error-only
    # records, and the process still exits zero, so an extraction where every file failed
    # produced a non-empty list that read downstream as a successful read.
    # FINGERPRINT AFTER, COMPARED WITH BEFORE. Taken only at the end, the manifest describes
    # the files as they are NOW while the results describe them as they were when each was
    # opened. A model saved by a designer while a long batch is running produces an extract
    # that claims to match the current file and does not. Two readings that differ means the
    # design moved under us and the run cannot be trusted as a snapshot of anything.
    _fp_after = _fingerprint_native_files(target)
    _fp_changed = bool(_fp_before) and bool(_fp_after) and _fp_before != _fp_after
    if _fp_changed:
        print("\nWARNING: the model files CHANGED DURING this extraction. The results "
              "describe the files as they were when each was opened, which is no longer "
              "what is on disk. This extract is marked invalid — re-run it.")

    _errors = [{"path": r.get("path"), "errors": r.get("errors")}
               for r in all_results if isinstance(r, dict) and r.get("errors")]
    _ok = [r for r in all_results
           if isinstance(r, dict) and not r.get("errors") and r.get("title")]
    payload = {
        "schema": f"sw_native_extract.v{EXTRACT_SCHEMA_VERSION}",
        "schema_version": EXTRACT_SCHEMA_VERSION,
        "_manifest": {
            "schema_version": EXTRACT_SCHEMA_VERSION,
            "native_files_fingerprint": _fp_after,
            "fingerprint_before": _fp_before,
            # True when the files moved under us mid-run. The consumer must not treat this
            # extract as a valid snapshot of anything.
            "changed_during_extraction": _fp_changed,
            # The FOLDER, for both file and folder targets — this is what the consumer
            # fingerprints, and recording a file path here made every single-file extract
            # read as stale immediately.
            "generated_from": _fingerprint_scope(target),
            "solidworks_version": _sw_version,
            "extractor_schema": f"sw_native_extract.v{EXTRACT_SCHEMA_VERSION}",
            # READ OUT OF SOMEBODY'S OPEN SESSION. A borrowed document is read in the state
            # the designer has it in, which may include unsaved changes — so the extract can
            # describe a model that is not what is on disk, and the fingerprint cannot see
            # that: it hashes the FILE. This is the whole residual risk of running the
            # analyser automatically now that it no longer closes anyone's work, so it
            # travels with the extract instead of scrolling past in a console.
            "read_from_open_documents": list(getattr(session, "borrowed_seen", []) or []),
            "files_seen": len(all_results),
            "files_read": len(_ok),
            "files_failed": len(_errors),
            "errors": _errors[:200],
        },
        "records": all_results,
    }

    def _write(path: str) -> None:
        """Atomic: a half-written extract read by the pipeline is worse than none, because it
        parses to fewer records rather than failing."""
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)

    try:
        _write(out_json)
    except OSError as _e_write:
        # The models often live on a read-only CAD share. Losing a completed analysis
        # (minutes of SolidWorks document opens) to a write permission error is not
        # acceptable — fall back to the current working directory and say where it went.
        _fallback = os.path.join(os.getcwd(), "_sw_native_extract.json")
        print(f"\nWARNING: could not write to {out_json} ({_e_write})")
        _write(_fallback)
        out_json = _fallback
    # The LAST line is the produced path, so a caller can read it back rather than assuming
    # where the file went — which is wrong whenever the fallback above fires.
    print(f"\nWrote {out_json}")
    print(f"EXTRACT_PATH={out_json}")
    if _errors:
        print(f"COVERAGE: {len(_ok)} of {len(all_results)} file(s) read, "
              f"{len(_errors)} failed")

    # ── THE EXIT CODE IS THE ONLY THING A SCRIPT READS ──────────────────────────────
    # Every per-file failure is caught, recorded and written, and the process then exited
    # ZERO — so an extraction in which SolidWorks opened nothing at all reported success to
    # its caller, wrote a well-formed extract full of error-only records, and left "did the
    # analyser work?" answerable only by a human reading scrollback. The manifest has always
    # carried files_read; nothing that runs this tool was ever told.
    #
    # A PARTIAL RUN STILL EXITS ZERO. Some files failing is normal — a model open in a
    # designer's session, a corrupt fixture — and the extract is worth having: the consumer
    # already weighs coverage and blocks when the failures touch the priced assembly. Only a
    # run that read NOTHING is a failed run, and that is the one this now says out loud.
    if all_results and not _ok:
        print(f"\nERROR: {len(all_results)} file(s) were opened and NONE could be read. The "
              f"extract written above contains no usable model data.")
        print("  Common causes: SolidWorks could not start or attach; every model is open in "
              "another session; the files are a newer SolidWorks version than this machine.")
        print("  The estimate will treat this as models-present-but-unread, which is correct "
              "— but do not read the written file as a successful extraction.")
        sys.exit(1)
    if _fp_changed:
        # Already printed as a warning above, and it is also a failed run: the extract does
        # not describe the files on disk, so nothing downstream may treat it as a snapshot.
        sys.exit(1)


def _fingerprint_scope(target: str) -> str:
    """The folder a fingerprint covers. A file target is analysed on its own but fingerprinted
    over its whole folder, and `generated_from` used to record the FILE — so the consumer
    treated a file path as a directory, computed an empty fingerprint, and marked a
    freshly-written extract stale on the spot. Both now record the same folder."""
    return target if os.path.isdir(target) else os.path.dirname(os.path.abspath(target))


def _fingerprint_native_files(target: str) -> str:
    """Same basis and same exclusions as the consumer's native_files_state, so the two can be
    compared at all."""
    import hashlib
    exts = (".sldprt", ".sldasm", ".slddrw")
    found = []
    try:
        root = _fingerprint_scope(target)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d)]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts and not fn.startswith("~$"):
                    try:
                        st = os.stat(os.path.join(dirpath, fn))
                    except OSError:
                        continue
                    found.append((fn.lower(), st.st_size, int(st.st_mtime)))
    except Exception:
        return ""
    if not found:
        return ""
    found.sort()
    basis = "|".join(f"{n}:{s}:{m}" for n, s, m in found)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _sw_version_string(session: Any) -> str:
    try:
        return _safe_str(_get0(session.sw, "RevisionNumber"))
    except Exception:
        return ""


if __name__ == "__main__":
    main()
