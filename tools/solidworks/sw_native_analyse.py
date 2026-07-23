"""
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


class SolidWorksSession:
    def __init__(self, visible: bool = False):
        pythoncom.CoInitialize()
        self.sw = win32com.client.Dispatch("SldWorks.Application")
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
        try:
            self._open_titles.append(doc.GetTitle())
        except Exception:
            pass
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
    try:
        mp = doc.Extension.CreateMassProperty()
        if mp is None:
            return None
        mass = float(mp.Mass)  # kg
        return round(mass, 4) if mass else None
    except Exception:
        return None


def sheet_metal_signals(doc) -> RouteSignals:
    """Feature walk for sheet-metal / hole / weldment hints on a part doc."""
    sig = RouteSignals(part_number=_safe_str(getattr(doc, "GetTitle", lambda: "")()))
    try:
        feat = doc.FirstFeature()
        bend_count = 0
        hole_like = 0
        guard = 0
        while feat is not None and guard < 100000:
            guard += 1
            try:
                t = (feat.GetTypeName2() or feat.Name or "").lower()
                name = (feat.Name or "").lower()
                if "sheetmetal" in t or "sheetmetal" in name:
                    sig.is_sheet_metal = True
                if "bend" in t or t in ("bend", "sketchedbend"):
                    bend_count += 1
                    sig.is_sheet_metal = True
                if "hole" in t or "cut" in t or "holewizard" in t:
                    hole_like += 1
                if "weldment" in t or "structuralmember" in t:
                    sig.has_weldment = True
            except Exception:
                pass
            try:
                feat = feat.GetNextFeature()
            except Exception:
                break
        sig.bend_count = bend_count
        sig.hole_count_est = hole_like
    except Exception as e:
        sig.notes.append(f"feature_walk_error: {e}")

    props = get_custom_properties(doc)
    sig.material = (
        props.get("Material")
        or props.get("MATERIAL")
        or props.get("Material Description")
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
            try:
                if int(c.GetSuppression2()) == 0:  # swComponentSuppressed
                    continue
            except Exception:
                pass
            name2 = _safe_str(getattr(c, "Name2", None) or "")
            config = ""
            try:
                config = _safe_str(c.ReferencedConfiguration)
            except Exception:
                pass
            model = None
            try:
                model = c.GetModelDoc2()
            except Exception:
                model = None
            title = name2.split("/")[0]
            path = ""
            props: Dict[str, str] = {}
            material = ""
            if model is not None:
                try:
                    title = _safe_str(model.GetTitle()) or title
                except Exception:
                    pass
                try:
                    path = _safe_str(model.GetPathName())
                except Exception:
                    pass
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
        v = doc.GetFirstView()
        while v is not None and visited < 50:
            visited += 1
            try:
                tables = v.GetTableAnnotations()
            except Exception:
                tables = None
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
            try:
                v = v.GetNextView()
            except Exception:
                break
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
    try:
        result["title"] = _safe_str(doc.GetTitle())
    except Exception:
        pass
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


def find_sw_files(root: str) -> List[str]:
    exts = {".sldprt", ".sldasm", ".slddrw"}
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                if f.startswith("~$"):
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
                if r.get("route_signals"):
                    print(f"Routes: {r['route_signals'].get('ops_hint')}")
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
