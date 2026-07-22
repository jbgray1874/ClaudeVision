#!/usr/bin/env python3
"""
SOLIDWORKS discovery probe  —  READ-ONLY, no data written, no file saved.

WHAT THIS IS
------------
A one-off *discovery* tool. Before we build the production connector
(src/source_connectors/solidworks.py, see docs/solidworks_integration_design.md),
we need to know a simple factual thing: for SDI's own drawings, WHICH of the
capabilities the design note promises are actually populated in the files?

The design note lists what each SolidWorks surface *can* yield (material, gauge,
flat-pattern cut length, bend count, holes, surface area, weldment cut list,
BOM). Whether a given field is *present* depends on how each model was built and
saved. This probe opens a batch of real drawings read-only and reports, per file
and as a batch coverage matrix, exactly what it could read and what was absent —
so Phase 1/2 scope is decided on evidence, not assumption.

It uses the FULL SolidWorks API over COM (win32com) — the seat the trial licence
unlocks (clock: Aug 5). No Document Manager key is required for this route. The
full API is what can *compute* geometry (surface area, flat pattern, holes), so
the probe can measure the ceiling of what's achievable, not just stored metadata.

SAFETY
------
- Opens every document with ReadOnly + Silent flags.
- Never calls Save / SaveAs / EditRebuild-and-save. Documents are closed after read.
- If a mass-property or flat-pattern read forces a rebuild, that happens in memory
  only and is discarded on close — nothing is written back to the file.
- Wrap every extraction in try/except: one unreadable field never aborts the file,
  one unreadable file never aborts the batch. Absent == honestly reported as null,
  never guessed. (NO MOCKING — a field we cannot read is reported missing.)

USAGE  (on the Windows box, in the ClaudeVision venv)
-----
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe tools\\solidworks\\sw_discovery_probe.py ^
        --path "C:\\path\\to\\drawings" ^
        --out  "C:\\ClaudeVision\\sw_probe_report.json"

  --path      a folder (recursed) or a single .SLDPRT/.SLDASM/.SLDDRW file.
              Repeat --path to probe several roots.
  --out       where to write the JSON report (default: sw_probe_report.json in CWD).
  --limit     stop after N models (handy for a quick first look).
  --visible   run SolidWorks visibly (default: hidden). Visible can be more robust
              on some installs if a document dialog would otherwise block.
  --no-mass   skip mass properties (surface area / mass / volume). Mass props force
              a rebuild and are the slowest step — skip for a fast metadata-only pass.

REQUIREMENTS
------------
    pip install pywin32
  A SolidWorks seat licensed on this machine (trial is fine). The COM ProgID
  "SldWorks.Application" must resolve — it does once SW has been run once.

This file is Windows-only and intentionally NOT imported by the pipeline; it lives
under tools/ so the cross-platform src/ tree stays importable everywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional


# ── SolidWorks API enum values (swconst) we rely on ─────────────────────────
# Hard-coded so the probe doesn't depend on a typelib-generated constants module.
SW_DOC_PART = 1          # swDocPART
SW_DOC_ASSEMBLY = 2      # swDocASSEMBLY
SW_DOC_DRAWING = 3       # swDocDRAWING

# OpenDoc6 options (bit flags) — Silent(1) + ReadOnly(2) = 3
SW_OPEN_SILENT = 1       # swOpenDocOptions_Silent
SW_OPEN_READONLY = 2     # swOpenDocOptions_ReadOnly
SW_OPEN_FLAGS = SW_OPEN_SILENT | SW_OPEN_READONLY

_EXT_TO_DOCTYPE = {
    ".sldprt": SW_DOC_PART,
    ".sldasm": SW_DOC_ASSEMBLY,
    ".slddrw": SW_DOC_DRAWING,
}


def _log(msg: str) -> None:
    print(msg, flush=True)


# ── COM connection ──────────────────────────────────────────────────────────
def connect_solidworks(visible: bool):
    """Dispatch (or attach to) the SolidWorks application object.

    Returns the ISldWorks COM object, or raises with a readable message if the
    seat/ProgID isn't available — the trial licence must be active for this to work.
    """
    try:
        import win32com.client  # pywin32
    except ImportError as e:  # pragma: no cover - Windows-only dependency
        raise RuntimeError(
            "pywin32 is not installed. Run:  pip install pywin32"
        ) from e

    try:
        sw = win32com.client.Dispatch("SldWorks.Application")
    except Exception as e:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "Could not create the 'SldWorks.Application' COM object. "
            "Is SolidWorks installed and has it been run at least once on this "
            "machine? Is the trial licence still active (clock: Aug 5)?"
        ) from e

    try:
        sw.Visible = bool(visible)
    except Exception:
        pass  # non-fatal — some configs disallow toggling Visible
    # Suppress modal dialogs so a batch never blocks on a popup.
    try:
        sw.CommandInProgress = True
    except Exception:
        pass
    return sw


# ── file discovery ──────────────────────────────────────────────────────────
def gather_models(paths: List[str], limit: Optional[int]) -> List[str]:
    """Expand --path roots into a de-duplicated list of model files (parts +
    assemblies; drawings are skipped — a .SLDDRW carries no geometry of its own)."""
    found: List[str] = []
    seen = set()
    for root in paths:
        if os.path.isfile(root):
            candidates = [root]
        else:
            candidates = []
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    candidates.append(os.path.join(dirpath, f))
        for c in candidates:
            ext = os.path.splitext(c)[1].lower()
            if ext in (".sldprt", ".sldasm"):
                key = os.path.normcase(os.path.abspath(c))
                if key not in seen:
                    seen.add(key)
                    found.append(c)
    found.sort()
    if limit is not None:
        found = found[:limit]
    return found


# ── per-field extractors (each self-contained + exception-safe) ─────────────
def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def read_custom_properties(model, config_name: str) -> Dict[str, str]:
    """Custom + configuration-specific properties (material, finish, part no,
    description, weight, ...). Returns {name: resolved_value}."""
    out: Dict[str, str] = {}
    for cfg in ("", config_name):  # "" = file-level custom props
        cpm = _safe(lambda: model.Extension.CustomPropertyManager(cfg))
        if cpm is None:
            continue
        names = _safe(lambda: cpm.GetNames)
        # GetNames is a property returning a VARIANT array in most bindings.
        names_list = names if isinstance(names, (list, tuple)) else _safe(lambda: cpm.GetNames())
        if not names_list:
            continue
        for name in names_list:
            # Get6 resolves references (e.g. "SW-Mass") to their evaluated value.
            val = None
            got = _safe(lambda: cpm.Get6(name, False, "", "", False, False))
            if isinstance(got, (list, tuple)) and len(got) >= 2:
                val = got[1] or got[0]
            if val:
                out[str(name)] = str(val)
    return out


def read_material(model, config_name: str) -> Optional[str]:
    """Applied material name (from the model / config), never inferred."""
    def _try_a():
        res = model.GetMaterialPropertyName2(config_name, "")
        # some bindings return (database, name); take the name
        if isinstance(res, (list, tuple)):
            return res[-1] or None
        return res or None
    name = _safe(_try_a)
    if not name:
        name = _safe(lambda: model.MaterialIdName)
    if name and str(name).strip() and str(name).strip() not in ("<none>",):
        return str(name).strip()
    return None


def read_mass_properties(model) -> Dict[str, Any]:
    """Surface area (m²), mass (kg), volume (m³), bounding box (m).

    Forces an in-memory rebuild of the mass model; nothing is saved. This is the
    step that unlocks powder/area pricing, so it's worth the cost — but --no-mass
    skips it for a fast metadata-only pass."""
    out: Dict[str, Any] = {
        "surface_area_m2": None, "mass_kg": None, "volume_m3": None, "bbox_m": None,
    }
    mp = _safe(lambda: model.Extension.CreateMassProperty())
    if mp is None:
        return out
    out["surface_area_m2"] = _safe(lambda: round(float(mp.SurfaceArea), 6))
    out["mass_kg"] = _safe(lambda: round(float(mp.Mass), 6))
    out["volume_m3"] = _safe(lambda: round(float(mp.Volume), 9))
    # Bounding box: OverrideCenterOfMass off; GetMassProperties returns a flat array
    # whose layout is documented; we instead read the axis-aligned box if exposed.
    box = _safe(lambda: mp.GetMassProperties2(1))  # accuracy flag; may be unsupported
    if isinstance(box, (list, tuple)) and len(box) >= 6:
        out["bbox_m"] = [round(float(v), 6) for v in box[:6]]
    return out


def _iter_features(model):
    """Yield top-level features via the feature-tree linked list."""
    feat = _safe(lambda: model.FirstFeature())
    guard = 0
    while feat is not None and guard < 100000:
        yield feat
        feat = _safe(lambda: feat.GetNextFeature())
        guard += 1


def read_sheetmetal_and_bends(model) -> Dict[str, Any]:
    """Bend count + sheet-metal presence, discovered from feature types.

    A genuine bend count = number of bend features (EdgeBend / SketchBend / OneBend)
    plus flat-pattern presence. Exact flat-pattern cut length needs the flat-pattern
    body length and is reported as 'flat_pattern_present' here; the production
    connector will read the length off the flat-pattern configuration."""
    out: Dict[str, Any] = {
        "is_sheet_metal": False, "bend_count": 0, "flat_pattern_present": False,
    }
    bend_types = {"EdgeBend", "SketchBend", "OneBend", "SMBaseFlange", "SheetMetal"}
    for feat in _iter_features(model):
        tname = _safe(lambda: feat.GetTypeName2()) or _safe(lambda: feat.GetTypeName())
        if not tname:
            continue
        if tname in ("SheetMetal", "SMBaseFlange", "SMBaseFlangePattern"):
            out["is_sheet_metal"] = True
        if tname in ("EdgeBend", "SketchBend", "OneBend"):
            out["bend_count"] += 1
        if tname in ("FlatPattern",):
            out["flat_pattern_present"] = True
    return out


def read_hole_signal(model) -> Dict[str, Any]:
    """Hole-related feature signal — honestly a SIGNAL, not a full enumeration.

    A true per-diameter hole count needs face/edge geometry analysis (the production
    full-API connector does this). Here we count Hole-Wizard and simple hole/cut
    features so the batch report shows whether the models even carry recognisable
    hole features — the input to deciding if Phase 2 (computed holes) is worth it."""
    out = {"hole_wizard_features": 0, "cut_features": 0, "note": "signal only — not a per-diameter count"}
    for feat in _iter_features(model):
        tname = _safe(lambda: feat.GetTypeName2()) or _safe(lambda: feat.GetTypeName())
        if not tname:
            continue
        if tname in ("HoleWzd", "HoleSeries", "AdvHoleWzd"):
            out["hole_wizard_features"] += 1
        if tname in ("Cut", "CutExtrude", "ICE"):  # ICE = extruded cut
            out["cut_features"] += 1
    return out


def read_weldment_cutlist(model) -> List[Dict[str, Any]]:
    """Weldment cut-list folders → per-member profile / length / quantity.

    This is the single biggest Phase-1 win (fixes the noisy GA tube-length rollup),
    so the probe reads it directly: find CutListFolder features and pull their
    cut-list custom properties (LENGTH, QUANTITY, Description/PROFILE)."""
    rows: List[Dict[str, Any]] = []
    for feat in _iter_features(model):
        tname = _safe(lambda: feat.GetTypeName2()) or _safe(lambda: feat.GetTypeName())
        if tname not in ("CutListFolder", "SubWeldFolder", "WeldmentCutListFeature"):
            continue
        body_folder = _safe(lambda: feat.GetSpecificFeature2())
        cpm = _safe(lambda: body_folder.CustomPropertyManager) if body_folder else None
        props: Dict[str, str] = {}
        if cpm is not None:
            names = _safe(lambda: cpm.GetNames())
            for name in (names or []):
                got = _safe(lambda: cpm.Get6(name, False, "", "", False, False))
                if isinstance(got, (list, tuple)) and len(got) >= 2:
                    props[str(name)] = str(got[1] or got[0])
        rows.append({
            "folder": _safe(lambda: feat.Name),
            "length": props.get("LENGTH") or props.get("Length"),
            "quantity": props.get("QUANTITY") or props.get("Quantity"),
            "description": props.get("Description") or props.get("PROFILE") or props.get("Material"),
            "all_props": props,
        })
    return rows


def read_configurations(model) -> List[str]:
    names = _safe(lambda: model.GetConfigurationNames())
    return list(names) if names else []


def read_assembly_components(model) -> List[Dict[str, Any]]:
    """Top-level assembly components → the seed of a genuine BOM (part + qty)."""
    comps = _safe(lambda: model.GetComponents(True))  # True = top-level only
    out: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for c in (comps or []):
        path = _safe(lambda: c.GetPathName())
        if not path:
            continue
        counts[path] = counts.get(path, 0) + 1
    for path, qty in counts.items():
        out.append({"path": path, "part_number": os.path.splitext(os.path.basename(path))[0], "quantity": qty})
    return out


# ── one model ───────────────────────────────────────────────────────────────
def probe_model(sw, path: str, do_mass: bool) -> Dict[str, Any]:
    ext = os.path.splitext(path)[1].lower()
    doctype = _EXT_TO_DOCTYPE.get(ext, SW_DOC_PART)
    record: Dict[str, Any] = {
        "path": path,
        "part_number": os.path.splitext(os.path.basename(path))[0],
        "doc_type": {SW_DOC_PART: "part", SW_DOC_ASSEMBLY: "assembly"}.get(doctype, "part"),
        "opened": False,
        "errors": [],
    }

    errors = 0
    warnings = 0
    # OpenDoc6(FileName, Type, Options, Configuration, Errors, Warnings)
    model = _safe(lambda: sw.OpenDoc6(path, doctype, SW_OPEN_FLAGS, "", errors, warnings))
    if model is None:
        # Fall back to the ActiveDoc if OpenDoc6's out-params confused the binding.
        model = _safe(lambda: sw.ActiveDoc)
    if model is None:
        record["errors"].append("OpenDoc6 returned no model (open failed or licence inactive)")
        return record

    record["opened"] = True
    try:
        configs = read_configurations(model)
        active_cfg = _safe(lambda: model.ConfigurationManager.ActiveConfiguration.Name) or ""
        record["configurations"] = configs
        record["active_configuration"] = active_cfg
        record["material"] = read_material(model, active_cfg)
        record["custom_properties"] = read_custom_properties(model, active_cfg)
        record["sheet_metal"] = read_sheetmetal_and_bends(model)
        record["holes"] = read_hole_signal(model)
        record["weldment_cut_list"] = read_weldment_cutlist(model)
        if record["doc_type"] == "assembly":
            record["components"] = read_assembly_components(model)
        if do_mass:
            record["mass_properties"] = read_mass_properties(model)
        else:
            record["mass_properties"] = {"skipped": True}
    except Exception as e:
        record["errors"].append(f"extraction error: {e!r}")
    finally:
        # Close WITHOUT saving — read-only guarantee.
        title = _safe(lambda: model.GetTitle())
        if title:
            _safe(lambda: sw.CloseDoc(title))
    return record


# ── batch coverage summary ──────────────────────────────────────────────────
def summarise(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Batch coverage matrix — for how many models was each capability populated?
    This is the actual deliverable of the probe: evidence for Phase 1/2 scoping."""
    opened = [r for r in records if r.get("opened")]
    n = len(opened)

    def _pct(count: int) -> str:
        return f"{count}/{n}" + (f" ({round(100*count/n)}%)" if n else "")

    have_material = sum(1 for r in opened if r.get("material"))
    have_props = sum(1 for r in opened if r.get("custom_properties"))
    have_sheet = sum(1 for r in opened if (r.get("sheet_metal") or {}).get("is_sheet_metal"))
    have_bends = sum(1 for r in opened if (r.get("sheet_metal") or {}).get("bend_count"))
    have_flat = sum(1 for r in opened if (r.get("sheet_metal") or {}).get("flat_pattern_present"))
    have_holes = sum(1 for r in opened if (r.get("holes") or {}).get("hole_wizard_features"))
    have_cutlist = sum(1 for r in opened if r.get("weldment_cut_list"))
    have_area = sum(1 for r in opened if (r.get("mass_properties") or {}).get("surface_area_m2") is not None)
    have_mass = sum(1 for r in opened if (r.get("mass_properties") or {}).get("mass_kg") is not None)

    return {
        "models_found": len(records),
        "models_opened": n,
        "models_failed": len(records) - n,
        "coverage": {
            "material_name":          _pct(have_material),
            "custom_properties":      _pct(have_props),
            "sheet_metal_detected":   _pct(have_sheet),
            "bend_count_present":     _pct(have_bends),
            "flat_pattern_present":   _pct(have_flat),
            "hole_wizard_features":   _pct(have_holes),
            "weldment_cut_list":      _pct(have_cutlist),
            "surface_area_m2":        _pct(have_area),
            "mass_kg":                _pct(have_mass),
        },
        "reading": (
            "Each cell = how many opened models carried that datum. High material / "
            "cut-list / area coverage => Phase 1 (DocMgr metadata + cut lists) and the "
            "area-pricing win are worth building now. Low flat-pattern/hole coverage in "
            "saved files => those need the full-API compute path (Phase 2)."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only SolidWorks discovery probe.")
    ap.add_argument("--path", action="append", default=[], required=True,
                    help="Folder (recursed) or a single model file. Repeatable.")
    ap.add_argument("--out", default="sw_probe_report.json", help="Output JSON path.")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N models.")
    ap.add_argument("--visible", action="store_true", help="Run SolidWorks visibly.")
    ap.add_argument("--no-mass", action="store_true", help="Skip mass properties (faster).")
    args = ap.parse_args(argv)

    models = gather_models(args.path, args.limit)
    if not models:
        _log("No .SLDPRT/.SLDASM files found under the given --path root(s).")
        return 2
    _log(f"Discovered {len(models)} model file(s). Connecting to SolidWorks ...")

    try:
        sw = connect_solidworks(visible=args.visible)
    except RuntimeError as e:
        _log(f"[FATAL] {e}")
        return 3

    records: List[Dict[str, Any]] = []
    for i, path in enumerate(models, 1):
        _log(f"[{i}/{len(models)}] {path}")
        try:
            records.append(probe_model(sw, path, do_mass=not args.no_mass))
        except Exception:
            _log(traceback.format_exc())
            records.append({"path": path, "opened": False, "errors": ["probe crashed — see traceback"]})

    report = {
        "tool": "sw_discovery_probe",
        "read_only": True,
        "summary": summarise(records),
        "records": records,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    _log("")
    _log("── Batch coverage ──")
    for k, v in report["summary"]["coverage"].items():
        _log(f"  {k:<24} {v}")
    _log("")
    _log(f"Full report written to: {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
