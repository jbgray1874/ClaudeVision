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


def _cast(obj, iface: str):
    """CastTo an object to a named SW interface (IModelDoc2, IFeature, IPartDoc, ...) so
    its methods are early-bound and callable with (). Requires the typelib module loaded
    (EnsureModule). Returns the cast object, or the original if the cast is unavailable."""
    if obj is None:
        return None
    try:
        return win32com.client.CastTo(obj, iface)
    except Exception:
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
    has_weldment: bool = False
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
    for _mk in ("CreateMassProperty2", "CreateMassProperty"):
        try:
            ext = doc.Extension
            mp = _call_or_prop(ext, _mk)
            if mp is None:
                continue
            mass = _call_or_prop(mp, "Mass")
            mass = float(mass) if mass is not None else 0.0
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


def sheet_metal_signals(doc) -> RouteSignals:
    """Feature walk for sheet-metal / hole / weldment hints on a part doc."""
    sig = RouteSignals(part_number=_safe_str(_get0(doc, "GetTitle")))
    # Cast to IModelDoc2 so FirstFeature()/GetNextFeature() are real methods (late binding
    # returns 'Member not found'). Requires the typelib loaded via EnsureModule.
    mdoc = doc
    try:
        mdoc = win32com.client.CastTo(doc, "IModelDoc2")
        sig.notes.append(f"cast_IModelDoc2_type={type(mdoc).__name__}")
    except Exception as e:
        sig.notes.append(f"cast_IModelDoc2_err={type(e).__name__}:{e}")
    feat = None
    try:
        feat = mdoc.FirstFeature()
    except Exception as e:
        sig.notes.append(f"FirstFeature: {e!r}")
        # Try FeatureManager / count-based traversal as a fallback.
        try:
            n = int(mdoc.GetFeatureCount())
            sig.notes.append(f"GetFeatureCount={n}")
            feat = mdoc.FeatureByPositionReverse(0) if n else None
        except Exception as e2:
            sig.notes.append(f"FeatureByPosition_err={type(e2).__name__}:{e2}")
            feat = _get0(doc, "FirstFeature")  # last-resort late-bound property form
    sig.notes.append("first_feature=" + ("obj" if feat is not None else "None"))
    try:
        bend_count = 0
        hole_like = 0
        visited = 0
        while feat is not None and visited < 100000:
            visited += 1
            feat = _cast(feat, "IFeature")
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
            if "sheetmetal" in t or "sheet metal" in t:
                sig.is_sheet_metal = True
            if "bend" in t:  # EdgeBend / SketchBend / OneBend / SketchedBend
                bend_count += 1
                sig.is_sheet_metal = True
            if "hole" in t or "holewizard" in t or "holeseries" in t:
                hole_like += 1
            if "weldment" in t or "structuralmember" in t or "weldmentcutlist" in t:
                sig.has_weldment = True
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
    sig.material = (
        props.get("Material")
        or props.get("MATERIAL")
        or props.get("Material Description")
        or _applied
        or ""
    )
    for k, v in props.items():
        if "thick" in k.lower() and v:
            try:
                sig.thickness_mm = float(
                    "".join(ch for ch in v.replace(",", ".") if ch.isdigit() or ch == ".")
                )
            except Exception:
                pass
    sig.bbox_mm = get_bbox_mm(doc, SW_PART)
    sig.mass_kg = get_mass_kg(doc)

    # Route hints (rules-first — align with the estimator's op names). These are HINTS,
    # honestly flagged: powder in particular is a default assumption to confirm from notes.
    if sig.is_sheet_metal or sig.bend_count:
        sig.ops_hint += ["laser_cutting", "folding"]
    if sig.hole_count_est:
        sig.ops_hint.append("hole_machining")
    if sig.has_weldment:
        sig.ops_hint += ["welding", "dress_welds"]
    mat_u = sig.material.upper()
    if any(x in mat_u for x in ("MS", "MILD", "STEEL", "CRS", "ZINTEC")):
        sig.ops_hint.append("powder_coating")  # DEFAULT ASSUMPTION — confirm from drawing notes
    sig.ops_hint = sorted(set(sig.ops_hint))
    return sig


def assembly_bom(doc) -> List[BomLine]:
    """Top-level component counts (qty = instance count of same doc + config). For a full
    multi-level BOM, recurse GetChildren — a next-step improvement."""
    counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    try:
        comps = doc.GetComponents(True)  # True = top level only
    except Exception:
        comps = None
    if not comps:
        return []
    for c in comps:
        try:
            _sup = _get0(c, "GetSuppression2")
            try:
                if _sup is not None and int(_sup) == 0:  # swComponentSuppressed
                    continue
            except Exception:
                pass
            name2 = _safe_str(_get0(c, "Name2"))
            config = _safe_str(_get0(c, "ReferencedConfiguration"))
            model = _get0(c, "GetModelDoc2")
            title = name2.split("/")[0]
            path = ""
            props: Dict[str, str] = {}
            material = ""
            if model is not None:
                title = _safe_str(_get0(model, "GetTitle")) or title
                path = _safe_str(_get0(model, "GetPathName"))
                props = get_custom_properties(model)
                material = (
                    props.get("Material")
                    or props.get("MATERIAL")
                    or props.get("Description")
                    or ""
                )
            key = (path or title, config)
            if key not in counts:
                counts[key] = {
                    "part_number": title,
                    "description": props.get("Description") or props.get("DESCRIPTION") or "",
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
                        description=props.get("Description", ""),
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
        print("Usage: python sw_native_analyse.py <file_or_folder>")
        sys.exit(2)
    target = sys.argv[1]
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
                          f"weldment={rs.get('has_weldment')} mass_kg={rs.get('mass_kg')} "
                          f"bbox={rs.get('bbox_mm')}")
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
    out_json = os.path.join(
        target if os.path.isdir(target) else os.path.dirname(target),
        "_sw_native_extract.json",
    )
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
