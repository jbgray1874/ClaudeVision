"""
source_connectors/solidworks.py — normalise the SolidWorks native extract into the
shapes the estimator/reconcile consume. This is Layer 0 (highest reliability) of the
source waterfall: for SDI's own designs the native model is ground truth for BOM
structure + quantities + material; DXF stays authoritative for flat geometry (holes,
cut length) and PDF for free-text notes.

Input: the JSON written by tools/solidworks/sw_native_analyse.py (`_sw_native_extract.json`),
a list of per-file records: {path, title, doctype (1 part/2 asm/3 drw), custom_properties,
bbox_mm, bom:[...], route_signals:{...}|null, errors}.

This module does NOT open SolidWorks. It reads the extract JSON (optionally triggering
the analyser as a subprocess on a machine that has SW). Pure field-mapping — no per-job
or per-part logic — so it scales to any job the analyser can read.

Public surface:
    load_native_extract(json_path)                 -> list[dict]  (raw records)
    normalize_native_extract(records)              -> NativeJob   (bom + part_signals + meta)
    native_extract_for_job(folder=..., json=...,
                           run=False, analyser=...) -> NativeJob | None
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE_NAME = "solidworks_api"
RELIABILITY = 1.0
EXTRACT_FILENAME = "_sw_native_extract.json"

# Doc types (mirror the analyser).
SW_PART, SW_ASM, SW_DRW = 1, 2, 3

# Assembly description/title tokens that indicate a WELDED assembly (not bolt-together).
# The native model does not always flag weld intent structurally, so — like the engine's
# existing _ASSEMBLY_WELD_PHRASES — we read it from the name/description. Weld-bead feature
# detection on assemblies is a planned refinement; until then a match is a FLAGGED
# candidate, never a silent assertion.
_WELD_NAME_TOKENS = ("weld assy", "weld assembly", "welded", "weldment", "wa0", "wa1", "-wa", "sa0")


def _clean_pn(name: str) -> str:
    """Normalise a part number for matching. The analyser already strips SolidWorks
    instance suffixes (it emits clean document titles), so we do NOT strip here — that
    would wrongly turn '12120-01-103' into '12120-01'. Just trim/upper-safe compare."""
    return str(name or "").strip()


@dataclass
class NativePart:
    part_number: str
    material: str = ""
    is_sheet_metal: bool = False
    bend_count: int = 0
    hole_count_est: int = 0
    flat_pattern: bool = False
    has_weldment: bool = False
    bbox_mm: Optional[List[float]] = None
    doctype: int = SW_PART
    source: str = SOURCE_NAME
    reliability: float = RELIABILITY


@dataclass
class NativeBomRow:
    part_number: str
    quantity: float = 1.0
    material: str = ""
    is_assembly: bool = False
    weld_candidate: bool = False
    source: str = SOURCE_NAME
    reliability: float = RELIABILITY
    flags: List[str] = field(default_factory=list)


@dataclass
class NativeJob:
    bom: List[NativeBomRow] = field(default_factory=list)          # top-assembly flattened BOM
    part_signals: Dict[str, NativePart] = field(default_factory=dict)  # by part number
    meta: Dict[str, Any] = field(default_factory=dict)
    found: bool = False

    def material_for(self, part_number: str) -> str:
        p = self.part_signals.get(_clean_pn(part_number))
        return p.material if p else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "meta": self.meta,
            "bom": [vars(r) for r in self.bom],
            "part_signals": {k: vars(v) for k, v in self.part_signals.items()},
        }


# ── loading ──────────────────────────────────────────────────────────────────
def load_native_extract(json_path: str | Path) -> List[Dict[str, Any]]:
    jp = Path(json_path)
    if not jp.exists():
        return []
    try:
        data = json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _is_weld_candidate(title: str, description: str) -> bool:
    blob = f"{title} {description}".lower()
    return any(tok in blob for tok in _WELD_NAME_TOKENS)


def _pick_top_assembly(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The job's top assembly = the assembly record with the largest (full-depth) BOM.
    Generic — no reliance on a '-GA' naming convention, though that usually wins anyway."""
    asms = [r for r in records if r.get("doctype") == SW_ASM and r.get("bom")]
    if not asms:
        return None
    return max(asms, key=lambda r: len(r.get("bom") or []))


# ── normalisation ────────────────────────────────────────────────────────────
def normalize_native_extract(records: List[Dict[str, Any]]) -> NativeJob:
    job = NativeJob()
    if not records:
        return job
    job.found = True

    # Per-part signals from every part record's route_signals (material + geometry).
    doctype_by_pn: Dict[str, int] = {}
    for r in records:
        pn = _clean_pn(r.get("title") or "")
        if not pn:
            continue
        doctype_by_pn[pn] = int(r.get("doctype") or SW_PART)
        rs = r.get("route_signals")
        if not isinstance(rs, dict):
            continue
        job.part_signals[pn] = NativePart(
            part_number=pn,
            material=str(rs.get("material") or ""),
            is_sheet_metal=bool(rs.get("is_sheet_metal")),
            bend_count=int(rs.get("bend_count") or 0),
            hole_count_est=int(rs.get("hole_count_est") or 0),
            flat_pattern=bool(rs.get("flat_pattern_present")),
            has_weldment=bool(rs.get("has_weldment")),
            bbox_mm=rs.get("bbox_mm"),
            doctype=int(r.get("doctype") or SW_PART),
        )

    # BOM = the top assembly's full-depth component list, quantities already rolled up.
    top = _pick_top_assembly(records)
    if top:
        job.meta["top_assembly"] = top.get("title")
        # Descriptions per part (for weld-candidate + display), from part records.
        desc_by_pn = {
            _clean_pn(r.get("title") or ""): _first_line_desc(r)
            for r in records
        }
        for line in (top.get("bom") or []):
            pn = _clean_pn(line.get("part_number") or "")
            if not pn:
                continue
            dt = doctype_by_pn.get(pn, SW_PART)
            is_asm = dt == SW_ASM
            desc = desc_by_pn.get(pn, "")
            weld = is_asm and _is_weld_candidate(pn, desc)
            # Material: prefer the part's own applied material (BOM lines carry none).
            mat = job.material_for(pn) or str(line.get("material") or "")
            row = NativeBomRow(
                part_number=pn,
                quantity=float(line.get("quantity") or 1.0),
                material=mat,
                is_assembly=is_asm,
                weld_candidate=weld,
            )
            if weld:
                row.flags.append("weld-assembly candidate (from name) — confirm weld/dress")
            job.bom.append(row)

    job.meta["counts"] = {
        "records": len(records),
        "parts_with_signals": len(job.part_signals),
        "bom_rows": len(job.bom),
        "weld_candidates": sum(1 for r in job.bom if r.weld_candidate),
        "material_coverage": sum(1 for p in job.part_signals.values() if p.material),
    }
    return job


def _first_line_desc(record: Dict[str, Any]) -> str:
    bom = record.get("bom") or []
    if bom and isinstance(bom[0], dict):
        return str(bom[0].get("description") or "")
    return ""


# ── job entry point ──────────────────────────────────────────────────────────
def native_extract_for_job(
    *,
    folder: Optional[str | Path] = None,
    json_path: Optional[str | Path] = None,
    run: bool = False,
    analyser: Optional[str | Path] = None,
    python_exe: Optional[str] = None,
) -> Optional[NativeJob]:
    """Resolve + normalise the native extract for a job.

    - json_path given            -> read it.
    - folder given               -> read <folder>/_sw_native_extract.json; if absent and
                                     run=True, invoke the analyser (needs SolidWorks) then read.
    Returns a NativeJob (found=False if nothing native is available — the caller then
    falls back cleanly to the PDF/DXF path)."""
    jp: Optional[Path] = Path(json_path) if json_path else None
    if jp is None and folder is not None:
        jp = Path(folder) / EXTRACT_FILENAME

    if jp is not None and not jp.exists() and run and folder is not None:
        _run_analyser(folder, analyser=analyser, python_exe=python_exe)

    records = load_native_extract(jp) if jp else []
    job = normalize_native_extract(records)
    job.meta.setdefault("extract_path", str(jp) if jp else None)
    return job


def _run_analyser(folder: str | Path, analyser: Optional[str | Path] = None,
                  python_exe: Optional[str] = None) -> None:
    """Invoke sw_native_analyse.py on a folder (Windows + SolidWorks only). Best-effort:
    failures leave no JSON and the caller falls back to PDF/DXF."""
    if analyser is None:
        analyser = Path(__file__).resolve().parents[2] / "tools" / "solidworks" / "sw_native_analyse.py"
    exe = python_exe or os.environ.get("SDI_PYTHON_EXE") or "python"
    try:
        subprocess.run([exe, str(analyser), str(folder)], check=False, timeout=1800)
    except Exception:
        pass


# ── reconcile helper (native -> part_estimates), mirrors the dual-path reconcile ──
def apply_native_to_part_estimates(summary: Dict[str, Any], job: NativeJob) -> Dict[str, int]:
    """Fold native truth into estimate_summary.part_estimates, non-destructively:
      - MATERIAL: set from the native model where a part currently has none/inferred
        (native is reliability 1.0 — the model's own applied material).
      - QUANTITY: correct bought-in/fastener quantities from the native BOM roll-up.
      - WELD: flag weld-candidate assemblies for the weld/dress route.
    Returns {'material_set','qty_corrected','weld_flagged'}. Geometry (holes/cut length)
    is deliberately NOT overwritten here — DXF stays authoritative for that.
    NOTE: wiring the CALL of this into file_scan is a separate, reviewed step; this keeps
    the mapping isolated and testable first."""
    out = {"material_set": 0, "qty_corrected": 0, "weld_flagged": 0}
    if not job or not job.found:
        return out
    es = summary.get("estimate_summary") or {}
    parts = es.get("part_estimates")
    if not isinstance(parts, list):
        return out

    qty_by_pn = {_clean_pn(r.part_number): r.quantity for r in job.bom}
    weld_pns = {_clean_pn(r.part_number) for r in job.bom if r.weld_candidate}

    for p in parts:
        pn = _clean_pn(str(p.get("part_number") or ""))
        if not pn:
            continue
        nat = job.part_signals.get(pn)
        # Material: native wins where the engine has nothing solid.
        if nat and nat.material and not str(p.get("normalized_material") or "").strip():
            p["normalized_material"] = nat.material
            p.setdefault("review_flags", []).append(
                f"Material '{nat.material}' from SolidWorks model")
            out["material_set"] += 1
        # Quantity: native BOM roll-up corrects fastener/bought-in counts.
        q = qty_by_pn.get(pn)
        if q is not None and int(q) > 0 and p.get("quantity") != int(q):
            _old = p.get("quantity")
            p["quantity"] = int(q)
            p.setdefault("review_flags", []).append(
                f"Quantity {_old} -> {int(q)} from SolidWorks BOM")
            out["qty_corrected"] += 1
        # Weld candidate → flag for the weld/dress route.
        if pn in weld_pns:
            p.setdefault("review_flags", []).append(
                "SolidWorks: welded sub-assembly — confirm weld/dress route")
            out["weld_flagged"] += 1

    return out
