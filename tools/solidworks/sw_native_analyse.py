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
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import pythoncom
import win32com.client
from win32com.client import VARIANT
from win32com.client import gencache

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
    material: str = ""
    thickness_mm: Optional[float] = None
    mass_kg: Optional[float] = None
    bbox_mm: Optional[Tuple[float, float, float]] = None
    ops_hint: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    feature_types: List[str] = field(default_factory=list)  # diagnostic: raw type names seen


class SolidWorksSession:
    def __init__(self, visible: bool = False):
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

    def open(self, path: str):
        path = os.path.abspath(path) if not path.startswith("\\\\") else path
        ext = os.path.splitext(path)[1].lower()
        doctype = DOCTYPE.get(ext)
        if doctype is None:
            raise ValueError(f"Unsupported extension: {ext}")
        errs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warns = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = self.sw.OpenDoc6(path, doctype, OPEN_OPTS, "", errs, warns)
        if doc is None:
            raise RuntimeError(
                f"OpenDoc6 failed: {path}  errs={errs.value} warns={warns.value}"
            )
        _t = _safe_str(_get0(doc, "GetTitle"))
        if _t:
            self._open_titles.append(_t)
        return doc, doctype

    def close_all(self):
        for title in reversed(self._open_titles):
            try:
                self.sw.CloseDoc(title)
            except Exception:
                pass
        self._open_titles.clear()

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


# Cut-list property names SolidWorks generates for sheet-metal bodies. Spellings vary by
# version/template, so each datum is tried against several candidates.
_CUTLIST_KEYS = {
    "flat_length": ("Bounding Box Length", "Sheet Metal Bounding Box Length",
                    "Bounding Box Length@@@", "SW-Bounding Box Length"),
    "flat_width": ("Bounding Box Width", "Sheet Metal Bounding Box Width",
                   "Bounding Box Width@@@", "SW-Bounding Box Width"),
    "thickness": ("Sheet Metal Thickness", "Thickness", "SW-Sheet Metal Thickness"),
    "bend_radius": ("Bend Radius", "Default Bend Radius", "SW-Bend Radius"),
    "cut_length": ("Cut Length", "Perimeter", "SW-Cut Length"),
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
        # Get2/Get are the simple string-returning forms; Get5/Get4 use byref out-params
        # which are awkward under this binding, so they are last resorts.
        for meth in ("Get2", "Get"):
            try:
                v = getattr(cpm, meth)(name)
                if isinstance(v, (list, tuple)):
                    v = next((x for x in v if isinstance(x, str) and x.strip()), None)
                if v not in (None, ""):
                    return _safe_str(v)
            except Exception:
                continue
        return None

    _hits = 0
    for key, candidates in _CUTLIST_KEYS.items():
        for cand in candidates:
            raw = _get_prop(cand)
            val = _num_mm(raw)
            if val is not None:
                out[key] = val
                _hits += 1
                break
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


def sheet_metal_signals(doc) -> RouteSignals:
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
    sig.material = _prop(props, "Material", "Material Description", "Material Spec",
                         "Spec", "Grade") or _applied
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
        sig.flat_length_mm = _cut_props.get("flat_length")
        sig.flat_width_mm = _cut_props.get("flat_width")
        sig.bend_radius_mm = _cut_props.get("bend_radius")
        sig.cut_length_mm = _cut_props.get("cut_length")
        if _cut_props.get("thickness"):
            sig.thickness_mm = _cut_props["thickness"]

    # Last-resort thickness for a sheet part: the smallest bounding-box dimension of an
    # UNFORMED blank is its thickness. Only used when the part has no bends and no cut-list
    # thickness, and it is recorded as inferred so it is never mistaken for a model value.
    if sig.is_sheet_metal and sig.thickness_mm is None and sig.bbox_mm:
        try:
            _mn = min(float(x) for x in sig.bbox_mm if x)
            if 0.4 <= _mn <= 12.0 and not sig.bend_count:
                sig.thickness_mm = round(_mn, 3)
                sig.notes.append(f"thickness inferred from bbox min ({_mn:.2f}mm) — no cut-list value")
        except Exception:
            pass

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
    return sig


def assembly_bom(doc) -> List[BomLine]:
    """FULL multi-level BOM, qty aggregated by the part's document identity (not instance
    name). GetComponents(False) returns every component at every level; GetModelDoc2 is
    interface-returning so the component is wrapped IComponent2 and its model IModelDoc2
    (else the title falls back to the instance name '...-3' and material/path are lost)."""
    counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
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
                }
            counts[key]["qty"] += 1.0
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
            )
        )
    lines.sort(key=lambda x: x.part_number.lower())
    return lines


def drawing_bom_tables(doc) -> List[BomLine]:
    """Extract BOM table annotations from a drawing. Best-effort: the table API varies by
    SW version — VERIFY on one known .slddrw (e.g. 12120's GA) before trusting it."""
    lines: List[BomLine] = []
    visited = 0
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
                                headers.append(_safe_str(t.Text2(0, col)).lower())
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
                                pn = _safe_str(t.Text2(r, idx_pn))
                                if not pn:
                                    continue
                                qty = 1.0
                                if idx_qty is not None:
                                    try:
                                        qty = float(_safe_str(t.Text2(r, idx_qty)).replace(",", ""))
                                    except Exception:
                                        qty = 1.0
                                desc = _safe_str(t.Text2(r, idx_desc)) if idx_desc is not None else ""
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
        elif doctype == SW_DRW:
            result["bom"] = [asdict(b) for b in drawing_bom_tables(doc)]
        elif doctype == SW_PART:
            sig = sheet_metal_signals(doc)
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
ARCHIVE_FOLDER_TOKENS = ("archive", "old versions", "superseded", "obsolete",
                         "wip", "do not use", "backup", "previous")


def find_sw_files(root: str, skip_archive: bool = True) -> List[str]:
    exts = {".sldprt", ".sldasm", ".slddrw"}
    found = []
    for dirpath, dirs, files in os.walk(root):
        if skip_archive:
            # Prune archive/superseded subfolders so os.walk does not descend into them.
            dirs[:] = [d for d in dirs
                       if not any(tok in d.lower() for tok in ARCHIVE_FOLDER_TOKENS)]
            if any(tok in dirpath.lower() for tok in ARCHIVE_FOLDER_TOKENS):
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python sw_native_analyse.py <file_or_folder> [--out <json path>]")
        sys.exit(2)
    argv = list(sys.argv[1:])
    out_override = None
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 >= len(argv):
            print("ERROR: --out needs a path")
            sys.exit(2)
        out_override = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print("Usage: python sw_native_analyse.py <file_or_folder> [--out <json path>]")
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
        print(f"No SolidWorks files under: {target}")
        print("Note: a job's *-Technical folder is often 2D only (DXF/PDF). The native "
              "models live elsewhere under the job root — point me at that folder.")
        sys.exit(1)
    session = SolidWorksSession(visible=False)
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
    finally:
        session.shutdown()
    out_json = out_override or os.path.join(
        target if os.path.isdir(target) else os.path.dirname(target),
        "_sw_native_extract.json",
    )
    try:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
    except OSError as _e_write:
        # The models often live on a read-only CAD share. Losing a completed analysis
        # (minutes of SolidWorks document opens) to a write permission error is not
        # acceptable — fall back to the current working directory and say where it went.
        _fallback = os.path.join(os.getcwd(), "_sw_native_extract.json")
        print(f"\nWARNING: could not write to {out_json} ({_e_write})")
        with open(_fallback, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        out_json = _fallback
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
